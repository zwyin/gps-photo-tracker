# GPS Photo Tracker - 测试数据策略

**版本：** v1.0
**日期：** 2026-05-05

---

## 1. 现有测试数据清单

### 1.1 数据源位置

所有测试数据在原项目 `/Users/zhiweiyin/repo_ds1600/gps-photo-tracker/test-data/`。

| 目录 | 内容 | 规模 | 用途 |
|------|------|------|------|
| `test-data/safe_test_data/` | 1 GPX + 3 JPG | ~42MB | 安全的小批量快速验证 |
| `test-data/gps_data/` | 3 GPX 文件 | ~1.4MB | GPS 轨迹数据 |
| `test-data/input/` | 179 JPG (DSCXXXXX) | ~2.2GB | 小批量照片（0217 单日） |
| `test-data/test_data_batch/` | 完整批量数据 | ~64GB | 大批量测试 + 对比报告 |
| `test-data/manual_test/` | 手动测试数据 | ~7.9GB | 人工验证用 |

### 1.2 批量测试数据详情 (test_data_batch)

```
test_data_batch/
├── gps_data/                  # 36 个 GPX 文件（0207-0221，15 天）
├── input/                     # 1,832 张原始照片
├── output/                    # 3,141 个已处理文件
├── v3_test_1309.json          # V3 算法测试结果（1,309 张有效对比）
├── v3_test_report.json        # V3 详细报告
├── v7.1_automated_test_report.json  # v7.1 自动化测试结果
├── test_report_by_date.json   # 按日期分类结果
├── phototracker_1309.json     # PhotoTracker 对比基准
└── phototracker_coverage.json # PhotoTracker 覆盖率分析
```

### 1.3 安全测试数据 (safe_test_data)

最小可用的验证集：

```
safe_test_data/
├── 20260217户外步行.gpx
├── DSC02258.JPG
├── DSC02264.JPG
└── DSC02270.JPG
```

---

## 2. 测试数据使用原则

### 2.1 核心原则：只读原始数据

> **原始测试数据永远不能被修改。**

- 原项目 `test-data/` 目录的数据是基准参照，不能写入、不能覆盖
- 每次测试前，将需要的数据**复制到新工程的独立工作目录**
- 复制后的数据可以自由操作，但需要能随时从原始数据恢复

### 2.2 工作目录结构

```
gps-photo-tracker-claude/
├── test-data/                    # 原始数据（只读，从原项目复制）
│   ├── gps_data/                 # GPX 轨迹文件
│   ├── safe_test_data/           # 最小测试集
│   └── small_batch/              # 小批量测试集（179 张）
├── test-work/                    # 测试工作区（可写入）
│   ├── output_safe/              # safe_test_data 的输出
│   ├── output_small/             # small_batch 的输出
│   └── output_batch/             # batch 测试的输出
└── tests/                        # 测试代码
```

### 2.3 测试流程

```
1. 从 test-data/ 复制数据到 test-work/
2. 运行测试，输出写入 test-work/output_xxx/
3. 对比 test-work/output_xxx/ 和原始 test-data/ 的基准
4. 清理 test-work/（或保留供分析）
```

---

## 3. 测试分层

### 3.1 第一层：单元测试（快速反馈）

- **数据**：用 conftest.py 里的 mock 数据，不依赖真实文件
- **覆盖**：匹配算法、EXIF 读写、GPX/KML/TCX 解析、坐标转换、并发处理、断点续传、参数推荐、方向变换、报告生成
- **速度**：< 2 分钟（328 个测试）
- **运行时机**：每次改代码
- **覆盖率要求**：新模块 ≥ 85%，Service 层 ≥ 80%，整体 ≥ 75%（当前 86.69%）

### 3.2 第二层：集成测试（真实数据，小批量）

- **数据**：safe_test_data（1 GPX + 3 JPG）
- **覆盖**：完整流程（扫描 → 解析 → 匹配 → 写入 → 验证）
- **速度**：< 30 秒
- **运行时机**：功能完成后

### 3.3 第三层：批量测试（真实数据，大批量）

- **数据**：small_batch（179 张 + 3 GPX）
- **覆盖**：成功率、性能、边界 case
- **验证**：匹配成功率 ≥ 80%，GPS 写入 100%
- **速度**：< 2 分钟
- **运行时机**：版本发布前

### 3.4 第四层：全量回归测试（可选）

- **数据**：test_data_batch（1832 张 + 36 GPX）
- **覆盖**：完整回归验证
- **验证**：成功率 ≥ 83%（对标 v7.2.0），GPS 精度对比
- **速度**：~10 分钟
- **运行时机**：重大版本发布前

---

## 4. v0.8.0 新增模块测试清单

| 模块 | 测试文件 | 测试数 | 覆盖率 |
|------|----------|--------|--------|
| `core/checkpoint.py` | `test_checkpoint.py` | 7 | 97% |
| `core/concurrency.py` | `test_concurrency.py` | 8 | 65% (mock) |
| `core/param_tuner.py` | `test_param_tuner.py` | 9 | 90% |
| `core/kml_parser.py` | `test_kml_parser.py` | 7 | 90% |
| `core/tcx_parser.py` | `test_tcx_parser.py` | 7 | 92% |
| `core/track_parser.py` | `test_track_parser.py` | 5 | 91% |
| `core/report_builder.py` | `test_report_builder.py` | 7 | 99% |
| `core/orientation.py` | `test_orientation.py` | 9 | 89% |
| `service/tagging_service.py` | `test_service.py` | 53 | 81% |

**总计：328 个测试，整体覆盖率 86.69%**

---

## 5. 基准指标（来自 v7.2.0 实测）

| 指标 | 基准值 | 数据集 |
|------|--------|--------|
| 匹配成功率 | 83.1% (1,523/1,832) | 1832 张 + 36 GPX |
| GPS 写入成功率 | 100% (1,523/1,523) | 同上 |
| 处理速度 | 305 张/分钟 | 同上 |
| GPS 版本 | 2.3.0.0 | mdls 验证 |
| 海拔精度 | 0.01m | *100/100 格式 |

**重写的最低要求：所有指标不低于基准值。**

---

## 6. 测试数据准备清单

重写开始前需要执行：

- [ ] 将 safe_test_data 复制到新工程
- [ ] 将 gps_data/ (3 个 GPX) 复制到新工程
- [ ] 将 input/27960217/ (179 张 JPG) 复制到新工程
- [ ] 将 test_data_batch/gps_data/ (36 个 GPX) 复制到新工程
- [ ] 保留 test_data_batch/ 下的 JSON 报告作为对比基准
- [ ] 创建 test-work/ 目录
- [ ] 编写测试数据复制脚本（从原项目自动同步）
