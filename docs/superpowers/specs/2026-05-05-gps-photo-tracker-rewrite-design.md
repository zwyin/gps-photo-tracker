# GPS Photo Tracker 重写设计规格

**日期：** 2026-05-05
**状态：** 待审阅
**技术栈：** Python 3.11+ / PySide6 / piexif / gpxpy / Pillow

---

## 1. 项目概述

批量处理本地/网络磁盘上的照片，根据 GPX 轨迹文件给照片写入 GPS EXIF 标签。桌面应用（PySide6），跨平台（macOS/Windows/Linux），可打包分发。

与 travel_photo_assistant 关系：独立开发，架构保留可集成性（Service 层提供干净 Python API）。

---

## 2. 架构

四层解耦，每层独立可测：

```
┌─────────────────────────────────────┐
│  GUI Layer (PySide6)                │  用户交互
├─────────────────────────────────────┤
│  Service Layer                      │  业务编排
│  GPSTaggingService                  │  (可被外部 import)
├──────────┬──────────┬───────────────┤
│ GPXParser│EXIFWriter│  GPSMatcher   │  核心算法层
│          │          │ (interpolated)│
├──────────┴──────────┴───────────────┤
│  FileIO Layer                       │  文件系统抽象
│  (local, network+retry)             │
└─────────────────────────────────────┘
```

**依赖规则：** GUI → Service → Core → FileIO。禁止跨层调用（GUI 不能直接调 Core）。每层只依赖下一层。

---

## 3. 数据结构

所有跨模块数据用 dataclass 定义，放在 `core/models.py`。禁止用裸 dict 传递数据。

```python
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime

@dataclass
class TrackPoint:
    timestamp: float        # UTC 时间戳，内部比较统一用这个
    latitude: float
    longitude: float
    altitude: float         # 统一用 altitude（不是 elevation）

@dataclass
class GPXSegment:
    filename: str
    start: float
    end: float
    points: list[TrackPoint]

@dataclass
class GPSInfo:
    latitude: float
    longitude: float
    altitude: float

@dataclass
class PhotoInfo:
    path: Path
    filename: str
    datetime: datetime      # 拍摄时间
    has_gps: bool
    existing_gps: GPSInfo | None = None

@dataclass
class MatchResult:
    photo: PhotoInfo
    success: bool
    gps: GPSInfo | None = None
    method: str | None = None       # "interpolated" | "nearest"
    time_diff: float | None = None  # 秒
    reject_reason: str | None = None

@dataclass
class BatchResult:
    total: int
    matched: int
    skipped: int
    failed: int
    success_rate: float
    results: list[MatchResult]
    reject_groups: dict[str, list[str]]  # 按原因分组的拒绝列表

@dataclass
class MatcherConfig:
    isolated_window: int = 300       # 孤立照片时间窗口（秒）
    middle_time_window: int = 3600   # 中间照片时间窗口（秒）
    context_window: int = 300        # 上下文窗口（秒）
    max_gps_distance: int = 200      # GPS 距离阈值（米）
    match_tail: bool = True          # 是否匹配首尾孤立照片
    time_offset: int = 0             # 照片时间偏移（秒）
```

---

## 4. 核心层设计

### 4.1 GPXParser

职责：解析 GPX 文件，输出 `list[GPXSegment]`。

- 用 gpxpy 解析
- 按 track > segment 分组，每个 segment 输出一个 GPXSegment
- 时间用 UTC 时间戳（`utc_time.timestamp()`），不在内部用本地时间戳
- altitude 键名统一（不是 elevation）

### 4.2 GPSMatcher

职责：输入照片列表 + GPX 分段，输出 `list[MatchResult]`。

**匹配流程（每张照片）：**

```
1. 找到照片时间所在的 GPXSegment（segment.start <= photo_time <= segment.end）
   → 找不到：reject_reason = "no_gps_coverage"

2. 判断照片上下文
   - 前后照片都在 context_window 内 → middle
   - 否则 → isolated

3. 找到该 segment 中照片时间前后的 GPS 点（prev_point, next_point）

4. 根据上下文选择匹配方式：
   - middle + 有前后点 + 距离 <= max_gps_distance：
     → 线性插值（按时间比例算经纬度），method = "interpolated"
   - middle + 有前后点 + 距离 > max_gps_distance：
     → reject_reason = "gps_distance"
   - middle + 只有单侧点：
     → 就近匹配，method = "nearest"
   - isolated + match_tail=True + 时间差 <= isolated_window：
     → 就近匹配，method = "nearest"
   - isolated + match_tail=False：
     → reject_reason = "tail_isolated"
   - isolated + 时间差 > isolated_window：
     → reject_reason = "time_diff"

5. 插值公式：
   ratio = (photo_time - prev.timestamp) / (next.timestamp - prev.timestamp)
   lat = prev.latitude + ratio * (next.latitude - prev.latitude)
   lon = prev.longitude + ratio * (next.longitude - prev.longitude)
   alt = prev.altitude + ratio * (next.altitude - prev.altitude)
```

**与原项目 V3 的关键区别：**
- 真正实现了线性插值（原 V3 只找最近点）
- 所有构造参数（MatcherConfig）必须在逻辑中被消费
- prev/next 为 None 时安全处理

### 4.3 EXIFWriter

职责：读写照片 EXIF 数据。

**写入 GPS：**
- GPS Version ID: (2, 3, 0, 0) — EXIF 2.3 标准
- 经纬度：十进制 → DMS 格式
- 海拔：(int(abs(altitude) * 100), 100) — 0.01m 精度
- 负海拔：GPSAltitudeRef = 1
- altitude = 0 正确写入（用 `is not None` 判断，不用 truthy）
- 保留原始 EXIF 其他字段

**读取：**
- 拍摄时间：DateTimeOriginal → DateTimeDigitized → DateTime，优先级递减
- 已有 GPS：解析 GPS IFD，返回 GPSInfo 或 None

### 4.4 FileIO 层

职责：文件系统操作，统一处理本地和网络磁盘。

```python
class FileProvider:
    def list_files(self, directory: Path, patterns: list[str]) -> list[Path]
    def read_exif(self, path: Path) -> dict | None
    def write_exif(self, src: Path, dst: Path, gps: GPSInfo) -> bool
    def copy_file(self, src: Path, dst: Path) -> bool
```

**网络磁盘处理：**
- 所有 IO 操作加重试（retry 3 次，指数退避）
- 超时设置（单文件操作 30 秒超时）
- 权限错误、磁盘错误记录日志并跳过

---

## 5. Service 层设计

```python
class GPSTaggingService:
    def scan_gpx(self, gpx_dir: Path) -> list[GPXSegment]
    def scan_photos(self, photo_dir: Path) -> list[PhotoInfo]
    def preview(self, segments, photos, config) -> BatchResult
    def process(self, segments, photos, config, mode, output_dir) -> BatchResult
```

**三种模式的处理逻辑：**

| 模式 | 匹配成功的照片 | 已有GPS的照片 | 匹配失败的照片 |
|------|--------------|-------------|--------------|
| preview | 不动 | 不动 | 不动 |
| copy | 拷贝+写GPS | 只拷贝 | 只拷贝 |
| overwrite | 原地写GPS | 跳过(或覆盖) | 不动 |

**拷贝模式的契约：输出数量 == 输入数量。** 每张照片必须有对应的输出。

**可集成性：** `GPSTaggingService` 是纯 Python 类，可以被任何代码 import 调用，不依赖 GUI。

---

## 6. GUI 层设计

### 6.1 主窗口布局

```
┌──────────────────────────────────────────┐
│  GPS Photo Tracker                       │
├──────────────────────────────────────────┤
│  📂 文件选择                              │
│  ┌────────────────────────────┐          │
│  │ GPS目录： [__________] [浏览]         │
│  │ 照片目录： [__________] [浏览]         │
│  │ 输出目录： [__________] [浏览]         │
│  └────────────────────────────┘          │
│                                          │
│  ⚙️ 参数配置                              │
│  ┌────────────────────────────┐          │
│  │ 孤立窗口 [===●===] 5分     │          │
│  │ 中间窗口 [====●==] 60分    │          │
│  │ 上下文窗口 [===●===] 5分   │          │
│  │ 距离阈值 [===●===] 200m   │          │
│  │ ☑ 匹配首尾照片              │          │
│  │ ☐ 覆盖已有GPS               │          │
│  └────────────────────────────┘          │
│                                          │
│  ◉ 预览  ○ 拷贝  ○ 覆盖                  │
│                                          │
│  [        🚀 开始处理        ]            │
│                                          │
│  📊 结果                                  │
│  ┌────────────────────────────┐          │
│  │ 总数: 1832  成功: 1523     │          │
│  │ 跳过: 189   失败: 120      │          │
│  │ 成功率: 83.1%              │          │
│  │                            │          │
│  │ [失败照片列表 - 可排序/筛选] │          │
│  └────────────────────────────┘          │
└──────────────────────────────────────────┘
```

### 6.2 交互流程

1. 用户选择 GPS 目录 → 立即扫描，显示 GPX 文件数和轨迹点数
2. 用户选择照片目录 → 立即扫描，显示照片数和已有 GPS 数
3. 用户调整参数（有默认值，可选）
4. 点击"预览" → Dry run，显示匹配统计
5. 确认后切换到"拷贝"模式 → 选择输出目录 → 处理
6. 进度条实时更新，支持取消
7. 处理完成显示结果统计 + 失败照片列表

### 6.3 线程模型

- 所有文件操作在 QThread 中执行（不在主线程）
- 主线程通过 Qt Signal/Slot 接收进度和结果
- 严禁在 QThread 中直接操作 UI 组件
- 参数在主线程打包后传给工作线程

---

## 7. 日志系统

4 个日志文件，与原项目保持一致：

| 文件 | 内容 |
|------|------|
| `operations.log` | 任务开始/结束、参数、统计 |
| `matches.log` | 每张照片的匹配结果 |
| `writes.log` | GPS 写入操作、覆盖记录 |
| `errors.log` | 异常、警告 |

**硬规则：** 每个 except 块必须记录到 errors.log。

---

## 8. 测试策略

详细策略见 [test-data-strategy.md](../test-data-strategy.md)。

核心原则：
- 原始测试数据只读，测试时复制到工作目录
- 四层测试：单元(mock) → 集成(3张) → 批量(179张) → 全量(1832张)
- 基准对标 v7.2.0：成功率 ≥ 83.1%，目标 ≥ 85%（含插值后）
- 每个 MatcherConfig 参数必须有测试验证其生效

---

## 9. 项目结构

```
gps-photo-tracker-claude/
├── src/
│   ├── core/                    # 核心算法层（无 IO 依赖）
│   │   ├── __init__.py
│   │   ├── models.py            # 所有 dataclass 定义
│   │   ├── gpx_parser.py        # GPX 解析
│   │   ├── gps_matcher.py       # GPS 匹配算法（含插值）
│   │   └── exif_writer.py       # EXIF 读写
│   ├── service/                 # Service 层（业务编排）
│   │   ├── __init__.py
│   │   ├── tagging_service.py   # 主服务
│   │   └── file_provider.py     # 文件系统抽象（含重试）
│   ├── gui/                     # GUI 层
│   │   ├── __init__.py
│   │   ├── main_window.py       # 主窗口
│   │   ├── workers.py           # QThread 工作线程
│   │   └── result_panel.py      # 结果展示面板
│   └── logging_/                # 日志
│       ├── __init__.py
│       └── logger.py
├── tests/                       # 测试
│   ├── conftest.py              # mock 数据工厂
│   ├── unit/                    # 单元测试
│   │   ├── test_matcher.py
│   │   ├── test_parser.py
│   │   └── test_exif.py
│   ├── integration/             # 集成测试（真实文件）
│   └── batch/                   # 批量测试
├── test-data/                   # 测试数据（从原项目复制）
├── test-work/                   # 测试工作区（可写入）
├── docs/                        # 文档
├── pyproject.toml
└── README.md
```

---

## 10. 依赖

```
PySide6 >= 6.6
piexif >= 1.1.3
gpxpy >= 1.6.0
Pillow >= 10.0.0
geopy >= 2.4.0
```

---

## 11. 避坑清单（从原项目 bug-history 提取）

开发时必须遵守的硬规则：

1. **数据结构**：跨模块传数据用 models.py 里的 dataclass，禁止裸 dict
2. **数值判断**：用 `is not None`，禁止 truthy 检查数值（防 altitude=0 丢失）
3. **空指针**：遍历邻居时检查 prev/next 为 None
4. **时间戳**：内部统一 UTC，展示层才转本地时间
5. **参数生效**：MatcherConfig 每个字段必须有测试验证
6. **线程安全**：工作线程只接收纯 Python 数据，不碰 UI 对象
7. **资源管理**：所有文件操作用 context manager（with 语句）
8. **异常日志**：每个 except 块必须记录到 errors.log
9. **拷贝模式**：输出数量 == 输入数量，每条路径都必须拷贝
10. **变量初始化**：函数入口统一初始化所有后续分支用到的变量
