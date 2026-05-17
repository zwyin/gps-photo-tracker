# GPS Photo Tracker 完整执行流程 (v0.11.0)

## 一、启动 & 初始化（全自动）

1. 应用启动 → PySide6 GUI 创建
2. 主窗口初始化：左侧控制面板 + 右侧结果面板
3. 加载历史路径、恢复分隔栏状态
4. 状态栏显示"就绪"

---

## 二、用户设置阶段（人工）

1. **选择目录**
   - GPS 轨迹目录（GPX/KML/TCX）
   - 照片目录（JPEG）
   - 输出目录（仅 COPY 模式需要）

2. **参数配置**（可选）
   - 孤立窗口：300s / 中间窗口：3600s / 上下文窗口：300s
   - 最大 GPS 距离：200m
   - 时间偏移 / 并发数 / 覆盖已有GPS / 保留目录结构
   - **自动调参（Auto-tune）**：根据实际数据智能推荐参数

3. **模式选择**
   - PREVIEW（预览，不写文件）
   - COPY（复制到输出目录并写 GPS）
   - OVERWRITE（直接修改原文件，需二次确认）

---

## 三、自动处理流水线

### Phase 1：扫描（自动）

| 步骤 | 自动 | 说明 |
|------|------|------|
| 解析 GPS 轨迹 | ✅ | 解析 GPX/KML/TCX → GPXSegment + TrackPoint |
| 扫描照片 | ✅ | 读取 JPEG → 提取 EXIF 时间戳 → 检查已有 GPS |

### Phase 2：GPS 匹配（自动）

#### 2.1 参数总览

| 参数 | 默认值 | 范围 | 作用 |
|------|--------|------|------|
| `time_offset` | 0s | -3600~3600 | 照片时间校正：adjusted = photo.timestamp + offset |
| `context_window` | 300s | 60~1800 | 判定"中间"vs"孤立"：前后邻居照片的时间间距上限 |
| `middle_time_window` | 3600s | 600~7200 | 中间照片：前后 GPS 点的最大时间差 |
| `max_gps_distance` | 200m | 50~1000 | 中间照片插值：前后 GPS 点的最大地理距离 |
| `isolated_window` | 300s | 60~3600 | 孤立照片：最近 GPS 点的最大时间差 |
| `match_isolated` | True | bool | 是否允许匹配孤立照片（头部/尾部/中间孤立均适用，关闭则全部拒绝） |

#### 2.2 匹配流程图

```
对每张照片（按拍摄时间排序）:
│
├─ Step 0: 预处理
│   adjusted_time = photo.timestamp + time_offset
│
├─ Step 1: 查找 GPS 覆盖段
│   遍历所有 GPXSegment，找最近的轨迹段
│   ├─ 精确匹配：seg.start ≤ adjusted_time ≤ seg.end → 进入 Step 2
│   ├─ 容差匹配（修复后）：adjusted_time 在某段的 isolated_window 范围内
│   │   → 进入 Step 2，会被判定为孤立（头部/尾部孤立）
│   └─ 均不在范围内 → ❌ NO_GPS_COVERAGE
│   ⚠️ 当前缺陷：只做精确匹配，头部和尾部照片被直接拒绝
│      而中间孤立（时间在段内但邻居间距大）能正常进入孤立匹配 → 三种场景不一致
│
├─ Step 2: 判定照片类型（中间 vs 孤立）
│   is_middle = (
│       前一张照片存在 AND 后一张照片存在 AND
│       (本照片 - 前一张) ≤ context_window AND
│       (后一张 - 本照片) ≤ context_window
│   )
│   即：前后都有邻居照片且间距足够近 → 中间
│       否则 → 孤立
│
├─ Step 3: 在覆盖段内查找前后 GPS 轨迹点
│   prev_point = 最后一个 timestamp < adjusted_time 的点
│   next_point = 第一个 timestamp > adjusted_time 的点
│   ├─ 两个都没有 → ❌ NO_TRACK_POINTS
│   └─ 至少有一个 → 继续
│
├─ Step 4: 按类型分流匹配
│   │
│   ├── 【中间 + 前后两点都有】→ 尝试插值
│   │   │
│   │   ├─ 两点距离 > max_gps_distance?
│   │   │   └─ ❌ GPS_DISTANCE（轨迹点跳跃太远）
│   │   │
│   │   ├─ 两点时间差 > middle_time_window?
│   │   │   └─ ❌ TIME_DIFF（轨迹点间隔太长）
│   │   │
│   │   └─ ✅ 线性插值
│   │       ratio = (adjusted_time - prev.timestamp) / (next.timestamp - prev.timestamp)
│   │       lat = prev.lat + ratio × (next.lat - prev.lat)
│   │       lon = prev.lon + ratio × (next.lon - prev.lon)
│   │       alt = prev.alt + ratio × (next.alt - prev.alt)  (None 视为 0，双 None 则结果 None)
│   │       method = "interpolated"（差值）
│   │
│   ├── 【中间 + 只有一个点】→ 最近点
│   │   │
│   │   ├─ 该点时间差 > middle_time_window?
│   │   │   └─ ❌ TIME_DIFF
│   │   │
│   │   └─ ✅ 取该点坐标
│   │       method = "nearest"（就近）
│   │
│   └── 【孤立】→ 孤立匹配（头/尾/中间孤立统一处理）
│       │
│       ├─ match_isolated = False?
│       │   └─ ❌ ISOLATED_DISABLED（不允许匹配孤立照片）
│       │
│       ├─ 选择最近点（两点都有则取时间差小的）
│       │
│       ├─ 时间差 > isolated_window?
│       │   └─ ❌ TIME_DIFF
│       │
│       └─ ✅ 取最近点坐标
│           method = "nearest"（就近）
```

#### 2.3 失败原因汇总

| 失败原因 | 含义 | 影响参数 |
|----------|------|----------|
| `NO_GPS_COVERAGE` | 照片时间不在任何 GPS 轨迹段范围内（含头部排除问题） | `time_offset` |
| `NO_TRACK_POINTS` | 轨迹段内没有 GPS 点 | — |
| `GPS_DISTANCE` | 前后 GPS 点距离超过阈值（插值不可靠） | `max_gps_distance` |
| `TIME_DIFF` | 时间差超过对应窗口阈值 | `middle_time_window` / `isolated_window` |
| `ISOLATED_DISABLED` | 孤立照片且 `match_isolated` 关闭 | `match_isolated` |

#### 2.4 自动调参逻辑（Auto-tune）

根据 GPS 轨迹的实际数据特征推荐参数：

| 参数 | 自动调参规则 |
|------|-------------|
| `isolated_window` | 3 × 平均 GPS 采样间隔（最小 300s） |
| `middle_time_window` | 10 × 平均 GPS 采样间隔（最小 3600s） |
| `context_window` | 2 × 平均 GPS 采样间隔（最小 300s） |
| `max_gps_distance` | 中位速度 <3m/s → 200m，<8m/s → 400m，其他 → 500m |

### Phase 3：写入（自动，COPY/OVERWRITE 模式）

- COPY：复制照片到输出目录 → 写 EXIF GPS
- OVERWRITE：直接修改原文件 EXIF GPS
- 多线程并发写入，带进度条和校验

---

## 四、人工干预：Review 对话框（仅失败照片）

**触发条件**：匹配失败的照片存在时弹出

**每张照片可选操作**：

| 选项 | 说明 |
|------|------|
| 待定（默认） | 暂不处理 |
| 跳过 | 不修改该照片 |
| 手动选 GPS | 打开 GPS 轨迹可视化选点器 |
| 输入坐标 | 手动输入经纬度 |
| 跟随上一个 | 取上一张匹配成功照片的 GPS |
| 跟随下一个 | 取下一张匹配成功照片的 GPS |

**批量操作**：多选 → 批量应用 / "应用所有建议"一键处理

**完成后**：更新结果列表，颜色标注 review 指定的条目

---

## 五、数据流总览

```
用户输入（目录+参数）
    ↓
GPS轨迹 → TrackParser → GPXSegment[]
照片目录 → EXIF读取 → PhotoInfo[]
    ↓
GPSMatcher 自动匹配 → MatchResult[]
    ↓
 ┌─ 成功 → 直接进入结果列表
 └─ 失败 → Review 对话框（人工干预）→ 更新 MatchResult
    ↓
EXIFWriter 写入 GPS（COPY/OVERWRITE 模式）
    ↓
完成，状态栏汇总
```

---

## 六、错误处理（自动）

- 文件不可读 → 跳过 + 日志
- 处理异常 → 错误对话框 + 继续剩余
- 用户取消 → CancellationToken 优雅停止
- 崩溃 → 写 crash log

---

## 自动 vs 人工 总览

### 全自动（无需用户干预）
- 应用启动和 GUI 初始化
- GPS 轨迹文件解析和扫描
- 照片文件扫描和 EXIF 读取
- GPS 坐标匹配算法
- 进度跟踪和 UI 更新
- EXIF 写入和校验
- 错误处理和日志

### 需要人工决策
- 目录选择
- 参数配置（可选自动调参）
- 模式选择（PREVIEW/COPY/OVERWRITE）
- Review 对话框中对失败照片的处理
- 手动 GPS 坐标指定或轨迹选点
- 跟随上/下导航决策
- 批量操作选择
- 取消操作
