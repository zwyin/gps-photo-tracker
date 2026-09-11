# 相机时钟自动校正（Camera Clock Auto-Correction）设计

日期：2026-09-11 ｜ 任务 #12（第三梯队增强）｜ 分支：feat/clock-autocorrect

## 1. 问题

相机时钟与 GPS 记录仪时钟存在偏差 δ 时（时区错置、分钟级失准、夏令时），
照片 EXIF 时间系统性偏移，导致：

- 照片落在轨迹时间覆盖之外 → `no_gps_coverage` / `time_diff` 批量失败；
- 或更危险的情形：照片仍落入轨迹覆盖内，被匹配到**错误位置**（静默错误）。

现状：用户只能肉眼对比照片时间与轨迹时间范围，手动试 `time_offset`。

## 2. 方案对比（brainstorming 结论）

### 方案 A：已知地标反推

用户指定一张已知地标照片的真实位置 → 在轨迹上反推该位置对应的时间 → 
δ = 照片 EXIF 时间 − 反推时间。

- 优点：单张照片即可精确恢复 δ，对"静默错误"情形（方案 B 的盲区）有效。
- 缺点：需要人工挑选地标 + 知道真实坐标；单点估计无交叉验证；
  无法批量自动化；对没有地标照片的批次无解。

### 方案 B：批量扫描 offset 分布（选定）

对候选 offset 全量扫描，以"照片落入轨迹覆盖数"为目标函数，找尖峰。

- 优点：全自动、零人工先验、可交叉验证（N 张照片投票）、可量化置信度。
- 缺点：只能检测"覆盖外"信号；照片全在长轨迹覆盖内时不可检测（见 §4 限制）。

**选 B 的理由**：通用性（无地标依赖）+ 可自动给出置信度 + 方案 A 的场景
（静默错误）方案 B 同样无解时才需要，可留给未来作为 B 失败后的人工兜底入口。

## 3. 关键设计发现（修正任务书假设）

任务书原设想："收集匹配成功对的 photo_time vs track_time 差值，尖峰即 δ"。

**经代码分析（gps_matcher.py）该假设不成立**：匹配器纯按时间锚定——
相机偏差 δ 时，照片（EXIF 时间 t+δ）被匹配到轨迹上 t+δ 处的点，
`time_diff = |point.ts − (t+δ)|` 仍是采样间隔内的噪声（≈ 半个采样周期），
**不携带 δ 信息**。成功匹配对的差值直方图无论 δ 多大都聚集在 0 附近。

**真正可检测的信号**是覆盖率函数：

```
coverage(offset) = #{照片 : photo.timestamp + offset ∈ 某轨迹段 [start, end]}
```

δ 使照片时间分布整体平移，coverage(offset) 在 offset = −δ 处出现尖峰。
这是经典的**区间最大重叠问题**：照片 j 被段 i 覆盖 ⟺ offset ∈ [start_i−t_j, end_i−t_j]。
O(N·M log NM) 事件扫描即可精确求出所有局部最优，无需离散采样。

## 4. 算法（core/clock_correction.py）

```python
@dataclass(frozen=True)
class ClockCorrection:
    offset_s: int          # 建议的 MatcherConfig.time_offset 新值（总量，非增量）
    support: int           # 该 offset 下落入轨迹覆盖的照片数
    total: int             # 参与判定的照片数（有时间戳且非 skipped）
    confidence: float      # support / total
    gain: int              # 相对当前 offset 新挽回的照片数
    plateau_start_s: float # 达到该覆盖水平的 offset 区间（诊断用）
    plateau_end_s: float

def detect_offset(
    results: list[MatchResult],
    segments: list[GPXSegment],
    *,
    tolerance_s: float = 30.0,   # 小于此幅度的校正视为噪声，不建议
    min_support: int = 3,        # 尖峰最少支持票数
    current_offset_s: int = 0,   # 生成 results 时已应用的 offset
) -> ClockCorrection | None
```

步骤：

1. **参与照片**：`photo.timestamp is not None` 且 `method != "skipped"`
   （skipped = 已有 GPS 不参与匹配，与 offset 无关）。时间统一加 `current_offset_s`。
2. **事件扫描**：每 (照片, 段) 生成区间 `[start−t, end−t]`，扫描得
   coverage 恒定的候选区间序列（含照片覆盖位掩码）。
3. **守卫条件**（全部满足才返回建议，否则 None——宁缺勿错）：
   - **净增益**：`coverage(建议) > coverage(当前)`（有照片被实际挽回）；
   - **不伤害**：当前已覆盖的照片在建议 offset 下必须仍然覆盖
     （不允许牺牲已成功的照片去换失败照片——午餐照片等误报被此条拦截）；
   - `support ≥ min_support`（足够的投票数）；
   - `|建议 offset| ≥ tolerance_s`（亚容差校正视为噪声）。
4. **取值**：满足守卫的最大覆盖区间（可能为平台），建议值 = 平台**中心**
   round((lo+hi)/2)。中心而非最近零点：平台中心是最坏情况误差最小的选择
   （maximin slack）；当拍摄时段被轨迹起止紧紧夹住时（典型徒步场景）
   平台退化为窄带，中心精确恢复 δ。
5. **置信度** = support / total（任务书语义：尖峰票数 / 总数）。

### 限制（诚实声明）

- **静默错误不可检测**：相机偏差 δ 但照片仍全部落在（更长的）轨迹覆盖内时，
  coverage(当前) 已 100%，无失败信号 → 返回 None。此情形只有方案 A
  （地标反推）能解，留作未来人工入口。
- 平台很宽时（轨迹远长于拍摄时段），δ 不完全可辨识，中心值为最坏误差
  最小的估计，非精确 δ。
- 混合场景（偏差前/后都有轨迹外真实照片）可能被"不伤害"守卫拒绝 →
  保守 None，用户仍可手动设 offset。

## 5. 集成

- **CLI**：`--suggest-clock-offset` 旗标。preview 后运行检测，stdout 打印
  `clock-offset-suggest: ...` 行（供脚本解析），不自动应用、不写 EXIF。
  建议以 `--time-offset <值>` 重跑应用。
- **GUI**：右栏结果区顶部横幅（默认隐藏）。匹配完成（含失败，即
  review_ready 路径）后检测；命中则显示
  "检测到相机时钟偏差 X 秒（置信度 Y%，基于 N 张，可挽回 M 张）［应用校正并重新匹配］"。
  点击 = 写回 offset spin + 自动重跑 Step① 预览。无头测试只测逻辑
  （detect_offset 与 GUI 的建议计算/应用回调），不测视觉。

## 6. 测试（tests/unit/test_clock_correction.py）

合成场景（conftest 的 utc/make_segment/make_photo 工厂）：

- 经典偏差：track 10:00–12:00，12 张照片真实 10:05–11:55、相机 +1h →
  建议恰为 −3600s，confidence 1.0，gain 6；
- 健康相机：全落在覆盖内 → None；
- 静默错误（长轨迹全覆盖）：→ None（限制场景）；
- 午餐照片保护：轨迹内 6 张健康 + 轨迹后 3 张聚集 → None（不伤害守卫）；
- 票数不足：2 张偏离 < min_support=3 → None（min_support=2 时可命中）；
- 亚容差噪声：建议幅度 < tolerance_s → None；
- current_offset_s 非零基线：results 已带 +600s 校正 → 建议为替换总量；
- 边界：空输入 / 无时间戳照片 / method="skipped" 排除。
