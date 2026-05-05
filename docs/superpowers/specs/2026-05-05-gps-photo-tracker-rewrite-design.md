# GPS Photo Tracker 重写设计规格

**日期：** 2026-05-05
**状态：** 待审阅（二轮审修）
**技术栈：** Python 3.11+ / PySide6 / piexif / gpxpy / Pillow
**范围：** Core Features (CF-01~06) + Basic Features (BF-01~05) + EF-01（线性插值）。其他 EF 项后续迭代。

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
from enum import Enum


class ProcessMode(Enum):
    PREVIEW = "preview"
    COPY = "copy"
    OVERWRITE = "overwrite"


class RejectReason:
    NO_GPS_COVERAGE = "no_gps_coverage"
    GPS_DISTANCE = "gps_distance"
    TAIL_ISOLATED = "tail_isolated"
    TIME_DIFF = "time_diff"
    NO_TRACK_POINTS = "no_track_points"


@dataclass
class TrackPoint:
    timestamp: float        # UTC 时间戳，内部比较统一用这个
    latitude: float
    longitude: float
    altitude: float | None  # None 表示无海拔数据（GPX 中缺少 <ele> 标签）

@dataclass
class GPXSegment:
    filename: str           # 来源 GPX 文件名（同一文件的多 segment 共享此值）
    start: float            # UTC 时间戳
    end: float              # UTC 时间戳
    points: list[TrackPoint]

@dataclass
class GPSInfo:
    latitude: float
    longitude: float
    altitude: float | None  # None 时不写海拔 tag

@dataclass
class PhotoInfo:
    path: Path
    filename: str
    timestamp: float        # UTC 时间戳（扫描时从 EXIF 拍摄时间转换得到）
    has_gps: bool
    existing_gps: GPSInfo | None = None

@dataclass
class MatchResult:
    photo: PhotoInfo
    success: bool
    gps: GPSInfo | None = None
    method: str | None = None       # "interpolated" | "nearest"
    time_diff: float | None = None  # 秒
    reject_reason: str | None = None  # RejectReason 常量

@dataclass
class BatchResult:
    total: int
    matched: int
    skipped: int           # 已有 GPS 且不覆盖
    failed: int            # 匹配失败
    overwritten: int       # 覆盖了已有 GPS 的数量
    success_rate: float
    results: list[MatchResult]
    reject_groups: dict[str, list[str]]  # RejectReason -> [filename, ...]

@dataclass
class MatcherConfig:
    isolated_window: int = 300       # 孤立照片时间窗口（秒）
    middle_time_window: int = 3600   # 中间照片时间窗口（秒）
    context_window: int = 300        # 上下文窗口（秒）
    max_gps_distance: int = 200      # GPS 距离阈值（米）
    match_tail: bool = True          # 是否匹配首尾孤立照片
    time_offset: int = 0             # 照片时间偏移（秒），正值=照片时间+偏移

@dataclass
class ProcessOptions:
    mode: ProcessMode
    output_dir: Path | None = None        # copy 模式必需
    keep_structure: bool = True           # copy 模式保持目录结构
    overwrite_gps: bool = False           # 是否覆盖已有 GPS
```

**设计决策记录：**
- `PhotoInfo.timestamp` 用 `float`（UTC 时间戳）而非 `datetime`，与 `TrackPoint.timestamp` 类型一致，避免时区混淆（防范 Bug-ALG-05）
- `TrackPoint.altitude` 和 `GPSInfo.altitude` 允许 None，因为 GPX 可能缺少海拔数据
- `RejectReason` 用常量类而非裸字符串（防范 Bug-LOG-01 键名不一致）
- `ProcessOptions` 独立于 `MatcherConfig`，将处理选项和算法参数分离

---

## 4. 核心层设计

### 4.1 GPXParser

职责：解析 GPX 文件，输出 `list[GPXSegment]`。

```python
class GPXParser:
    def parse_file(self, path: Path) -> list[GPXSegment]
    def parse_directory(self, dir: Path) -> list[GPXSegment]
```

**分段规则：**
- 每个 GPX 文件的每个 `<trkseg>` 产生一个独立的 `GPXSegment`
- 同一 `<trk>` 下的不同 `<trkseg>` 是不同 segment（有间隙）
- 不同 GPX 文件的 segment 不合并，全部传给 matcher
- `filename` 字段为来源 GPX 文件名（同一文件的多 segment 共享）
- 缺少 `<ele>` 的点：`altitude = None`

**时间处理：**
- `timestamp` 统一用 `utc_time.timestamp()`，内部不用本地时间戳
- altitude 键名统一为 `altitude`（不是 elevation）

### 4.2 GPSMatcher

职责：输入照片列表 + GPX 分段，输出 `list[MatchResult]`。

```python
class GPSMatcher:
    def __init__(self, config: MatcherConfig): ...
    def match(self, photos: list[PhotoInfo], segments: list[GPXSegment]) -> list[MatchResult]:
        """
        1. 按照片 timestamp 排序
        2. 对每张照片执行匹配
        3. 返回与输入等长的 MatchResult 列表
        """
```

**匹配流程（每张照片）：**

```
0. 应用时间偏移：adjusted_time = photo.timestamp + config.time_offset
   （不修改 PhotoInfo 原始数据，只在匹配计算中使用 adjusted_time）

1. 找到 adjusted_time 所在的 GPXSegment（segment.start <= adjusted_time <= segment.end）
   → 首个匹配的 segment 生效（多 segment 重叠时先到先得）
   → 找不到：reject_reason = NO_GPS_COVERAGE

2. 判断照片上下文（基于排序后的邻居照片）
   - prev_photo 存在 且 (adjusted_time - prev_photo.timestamp) <= context_window
   - next_photo 存在 且 (next_photo.timestamp - adjusted_time) <= context_window
   - 两个条件都满足 → context = "middle"
   - 任一不满足（含首尾照片 prev/next 为 None）→ context = "isolated"

3. 在该 segment 中找到 adjusted_time 前后的 GPS 点
   - prev_point: segment 中 timestamp < adjusted_time 的最后一个点
   - next_point: segment 中 timestamp > adjusted_time 的第一个点
   - 都不存在：reject_reason = NO_TRACK_POINTS

4. 根据上下文选择匹配方式：
   a. context == "middle" 且 prev_point 和 next_point 都存在：
      - 距离 = geopy.distance.geodesic(prev_point, next_point).meters
      - 距离 <= max_gps_distance 且 time_diff <= middle_time_window：
        → 线性插值，method = "interpolated"
      - 距离 > max_gps_distance：
        → reject_reason = GPS_DISTANCE
      - time_diff > middle_time_window：
        → reject_reason = TIME_DIFF
   b. context == "middle" 但只有单侧点：
      - 时间差 <= middle_time_window → 就近匹配，method = "nearest"
      - 否则 → reject_reason = TIME_DIFF
   c. context == "isolated"：
      - match_tail == False → reject_reason = TAIL_ISOLATED
      - 最近 GPS 点时间差 <= isolated_window → 就近匹配，method = "nearest"
      - 时间差 > isolated_window → reject_reason = TIME_DIFF

5. 线性插值公式（仅 step 4a 命中时执行）：
   ratio = (adjusted_time - prev.timestamp) / (next.timestamp - prev.timestamp)
   lat = prev.latitude + ratio * (next.latitude - prev.latitude)
   lon = prev.longitude + ratio * (next.longitude - prev.longitude)
   alt = prev.altitude + ratio * (next.altitude - prev.altitude)  # None 按 0 处理
```

**与原项目 V3 的关键区别：**
- 真正实现了线性插值（原 V3 只找最近点）
- `time_offset` 在 step 0 显式消费
- `middle_time_window` 在 step 4a/4b 显式消费
- `context_window` 在 step 2 显式消费
- prev/next 为 None 时退化为 isolated（step 2 安全处理）

### 4.3 EXIFWriter

职责：读写照片 EXIF 数据。

```python
class EXIFWriter:
    @staticmethod
    def read_datetime(path: Path) -> float | None  # 返回 UTC 时间戳
    @staticmethod
    def read_gps(path: Path) -> GPSInfo | None
    @staticmethod
    def write_gps(src: Path, dst: Path, gps: GPSInfo) -> None  # 失败抛 EXIFWriteError
```

**写入 GPS：**
- GPS Version ID: (2, 3, 0, 0) — EXIF 2.3 标准
- 经纬度：十进制 → DMS 格式
- 海拔：(int(abs(altitude) * 100), 100) — 0.01m 精度
- 负海拔：GPSAltitudeRef = 1
- altitude = 0 正确写入（用 `is not None` 判断，不用 truthy）
- altitude = None 时跳过海拔 tag（不写入）
- 保留原始 EXIF 其他字段
- src == dst 时原地写入（覆盖模式）

**读取：**
- 拍摄时间：DateTimeOriginal → DateTimeDigitized → DateTime，优先级递减
- EXIF 时间格式 `YYYY:MM:DD HH:MM:SS` 为 naive datetime（本地时间），转换为 UTC 时间戳
- 已有 GPS：解析 GPS IFD，返回 GPSInfo 或 None

**支持格式：** JPEG (.jpg/.jpeg)。PNG 不支持 EXIF（piexif 限制），扫描时跳过 PNG。HEIC 后续迭代。

### 4.4 FileIO 层

职责：文件系统操作，统一处理本地和网络磁盘。

```python
class FileAccessError(GPSTrackerError): ...
class PermissionDeniedError(FileAccessError): ...
class DiskFullError(FileAccessError): ...
class NetworkTimeoutError(FileAccessError): ...

class FileProvider:
    def list_photos(self, directory: Path) -> list[Path]  # rglob *.jpg *.jpeg，递归无深度限制
    def list_gpx(self, directory: Path) -> list[Path]     # glob *.gpx *.GPX（非递归）
    def copy_file(self, src: Path, dst: Path) -> None     # 失败抛 FileAccessError
```

**网络磁盘处理：**
- 所有 IO 操作加重试（retry 3 次，指数退避 1s/2s/4s）
- 超时设置（单文件操作 30 秒）
- `copy_file` 中自动创建目标目录（`mkdir -p`）
- 网络断连时抛 `NetworkTimeoutError`，由 Service 层决定跳过还是中止

---

## 5. Service 层设计

```python
class GPSTaggingService:
    def scan_gpx(self, gpx_dir: Path) -> list[GPXSegment]
    def scan_photos(self, photo_dir: Path) -> list[PhotoInfo]
    def preview(self, segments: list[GPXSegment], photos: list[PhotoInfo],
                config: MatcherConfig) -> BatchResult
    def process(self, segments: list[GPXSegment], photos: list[PhotoInfo],
                config: MatcherConfig, options: ProcessOptions,
                cancel: CancellationToken | None = None) -> BatchResult
```

**三种模式的处理逻辑：**

| 模式 | 匹配成功的照片 | 已有GPS + 不覆盖 | 已有GPS + 覆盖 | 匹配失败的照片 |
|------|--------------|----------------|---------------|--------------|
| preview | 不动 | 不动 | 不动 | 不动 |
| copy | 拷贝+写GPS | 只拷贝 | 拷贝+写GPS | 只拷贝 |
| overwrite | 原地写GPS | 不动 | 原地写GPS | 不动 |

- `overwrite_gps` 是独立于 `mode` 的选项（三个模式都适用）
- 覆盖已有 GPS 时记录新旧 GPS 对比到 writes.log，`BatchResult.overwritten` 计数
- **拷贝模式契约：输出数量 == 输入数量。** 每条路径都必须拷贝
- `keep_structure=True` 时保持源目录的相对路径结构到输出目录

**取消机制：**
- `CancellationToken` 基于 `threading.Event`
- Service 在每张照片处理后检查 `cancel.is_cancelled`
- 取消时立即停止，已写入的文件保留（不回滚）
- GUI 层调用 `worker.cancel()` 触发

**错误策略：**
- 单文件失败：记录 errors.log，跳过，继续处理下一张
- 系统性失败（输出目录不可写、磁盘满）：抛异常，中止整批
- GPX 解析失败：跳过该文件，记录 errors.log
- 永远不在 GUI 层显示原始 Python traceback，Service 层包装为用户友好消息

**可集成性：** `GPSTaggingService` 是纯 Python 类，不依赖 GUI 或 Qt，可被任何代码 import。

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
│  │ ☑ 保持目录结构              │          │
│  └────────────────────────────┘          │
│                                          │
│  ◉ 预览  ○ 拷贝  ○ 覆盖                  │
│                                          │
│  [        🚀 开始处理        ]  [取消]   │
│                                          │
│  📊 结果                                  │
│  ┌────────────────────────────┐          │
│  │ 总数: 1832  成功: 1523     │          │
│  │ 跳过: 189   失败: 120      │          │
│  │ 覆盖: 5     成功率: 83.1%  │          │
│  │                            │          │
│  │ [QTableView - 虚拟滚动]     │          │
│  └────────────────────────────┘          │
└──────────────────────────────────────────┘
```

**交互模式：** 预览/拷贝/覆盖是单选模式（RadioButton）。点击"开始处理"执行当前选中的模式。预览模式始终是 dry run。用户可先预览确认，再切换到拷贝模式正式处理。

### 6.2 交互流程

1. 用户选择 GPS 目录 → 立即扫描，显示 GPX 文件数和轨迹点数
2. 用户选择照片目录 → 立即扫描，显示照片数和已有 GPS 数
3. 用户调整参数（有默认值，可选）
4. 选中"预览"模式 → 点击"开始处理" → Dry run，显示匹配统计
5. 确认后切换到"拷贝"模式 → 输出目录自动填入 → 点击"开始处理"
6. 进度条实时更新（4 阶段：扫描GPS → 扫描照片 → 匹配 → 写入）
7. 处理完成显示结果统计 + 失败照片表格（QTableView，虚拟滚动，无分页）
8. 用户可随时点击"取消"中止处理

### 6.3 线程模型

```python
class ProcessingWorker(QThread):
    progress = Signal(str, int, int)   # phase_name, current, total
    finished = Signal(object)          # BatchResult
    error = Signal(str)                # 用户友好的错误消息

    def __init__(self, service: GPSTaggingService,
                 segments: list[GPXSegment],
                 photos: list[PhotoInfo],
                 config: MatcherConfig,
                 options: ProcessOptions):
        super().__init__()
        self._cancel = CancellationToken()
        # 所有参数在主线程打包，工作线程只读取这些纯 Python 数据

    def run(self):
        try:
            if options.mode == ProcessMode.PREVIEW:
                result = service.preview(...)
            else:
                result = service.process(..., cancel=self._cancel)
            self.finished.emit(result)
        except GPSTrackerError as e:
            self.error.emit(str(e))  # 用户友好消息
        except Exception as e:
            self.error.emit(f"处理失败：{e}")

    def cancel(self):
        self._cancel.cancel()
```

**硬规则：**
- 工作线程只接收纯 Python 数据（dataclass、float、str），不碰任何 Qt/UI 对象
- 进度通过 Signal 发射，主线程 Slot 接收更新 UI
- 取消通过 CancellationToken，不通过 Qt 信号反向传递
- QFileDialog 使用 `DontUseNativeDialog` 作为网络路径的回退方案

### 6.4 配置持久化

- 参数通过 QSettings 持久化（macOS: plist, Windows: registry, Linux: ini）
- 首次启动使用 MatcherConfig 默认值
- 用户修改参数后自动保存
- 路径历史记录（最近使用的 GPS/照片/输出目录）

---

## 7. 日志系统

4 个日志文件：

| 文件 | 内容 |
|------|------|
| `operations.log` | 任务开始/结束、参数、统计 |
| `matches.log` | 每张照片的匹配结果 |
| `writes.log` | GPS 写入操作、覆盖记录（含新旧 GPS 对比） |
| `errors.log` | 异常、警告 |

**接口规则：** 所有 logger 方法参数使用 dataclass（`MatchResult`, `PhotoInfo`, `GPSInfo`），禁止裸 dict。

```python
class OperationLogger:
    def log_match_success(self, result: MatchResult): ...
    def log_match_failed(self, result: MatchResult): ...
    def log_write_success(self, photo: PhotoInfo, gps: GPSInfo, dest: Path): ...
    def log_gps_overwrite(self, photo: PhotoInfo, old: GPSInfo, new: GPSInfo): ...
    def log_error(self, context: str, error: Exception): ...
```

**硬规则：** 每个 except 块必须调用 `log_error()` 记录到 errors.log。

---

## 8. 异常体系

```python
class GPSTrackerError(Exception):
    """所有业务异常的基类"""

class GPXParseError(GPSTrackerError):
    """GPX 文件解析失败"""

class EXIFReadError(GPSTrackerError):
    """EXIF 读取失败"""

class EXIFWriteError(GPSTrackerError):
    """EXIF 写入失败"""

class MatchingError(GPSTrackerError):
    """匹配过程错误"""

class OperationCancelledError(GPSTrackerError):
    """用户取消操作"""

class FileAccessError(GPSTrackerError):
    """文件访问失败"""
    # 子类: PermissionDeniedError, DiskFullError, NetworkTimeoutError
```

**使用规则：**
- Core 层抛具体异常（`EXIFWriteError` 等），不抛裸 `Exception`
- Service 层捕获 Core 异常，决定跳过还是中止
- GUI 层只捕获 `GPSTrackerError`，显示 `str(e)` 作为用户消息
- `OperationCancelledError` 在 GUI 层特殊处理（不弹错误对话框）

---

## 9. 测试策略

详细策略见 [test-data-strategy.md](../test-data-strategy.md)。

核心原则：
- 原始测试数据只读，测试时复制到 test-work/ 目录
- 四层测试：单元(mock) → 集成(3张) → 批量(179张) → 全量(1832张)
- 基准对标 v7.2.0：成功率 >= 83.1%，目标 >= 85%（含插值后）
- 每个 MatcherConfig 字段必须有测试验证其生效
- 插值精度验证：构造合成数据（均匀 GPS 点 + 中点照片），验证插值位置与解析解的误差 < 1 米
- GPS 坐标精度验证：写入后重新读取，与写入值误差 < 0.001 度

---

## 10. 项目结构

```
gps-photo-tracker-claude/
├── src/
│   ├── core/                    # 核心算法层（无 IO 依赖）
│   │   ├── __init__.py
│   │   ├── models.py            # 所有 dataclass + 异常 + 常量
│   │   ├── gpx_parser.py        # GPX 解析
│   │   ├── gps_matcher.py       # GPS 匹配算法（含插值）
│   │   └── exif_writer.py       # EXIF 读写
│   ├── service/                 # Service 层（业务编排）
│   │   ├── __init__.py
│   │   ├── tagging_service.py   # 主服务
│   │   ├── file_provider.py     # 文件系统抽象（含重试）
│   │   └── cancel_token.py      # CancellationToken
│   ├── gui/                     # GUI 层
│   │   ├── __init__.py
│   │   ├── main_window.py       # 主窗口
│   │   ├── workers.py           # QThread 工作线程
│   │   └── result_panel.py      # QTableView 结果面板
│   ├── logging_/                # 日志
│   │   ├── __init__.py
│   │   └── logger.py
│   └── __main__.py              # 入口
├── tests/                       # 测试
│   ├── conftest.py              # mock 数据工厂 + TrackPoint/PhotoInfo 构造器
│   ├── unit/                    # 单元测试（mock，不依赖文件）
│   │   ├── test_matcher.py
│   │   ├── test_parser.py
│   │   └── test_exif.py
│   ├── integration/             # 集成测试（safe_test_data，3 张）
│   └── batch/                   # 批量测试（179 张 + 1832 张）
├── test-data/                   # 测试数据（从原项目复制，只读）
├── test-work/                   # 测试工作区（可写入）
├── docs/                        # 文档
├── pyproject.toml
└── README.md
```

---

## 11. 依赖

```
PySide6 >= 6.6
piexif >= 1.1.3
gpxpy >= 1.6.0
Pillow >= 10.0.0
geopy >= 2.4.0
tenacity >= 8.0.0           # 重试机制
```

---

## 12. 打包分发

- **工具**：PyInstaller（`--onefile` 或 `--onedir`）
- **macOS**：生成 .app bundle，考虑 codesign
- **Windows**：生成 .exe，可选 NSIS 安装器
- **Linux**：生成 AppImage
- 目标包体积 < 100MB（PySide6 是主要体积来源）

---

## 13. 避坑清单（从原项目 bug-history 提取）

开发时必须遵守的硬规则：

1. **数据结构**：跨模块传数据用 models.py 里的 dataclass，禁止裸 dict
2. **数值判断**：用 `is not None`，禁止 truthy 检查数值（防 altitude=0 丢失）
3. **空指针**：遍历邻居时检查 prev/next 为 None，边界照片自动归为 isolated
4. **时间戳**：内部统一 UTC float，展示层才转本地时间。PhotoInfo.timestamp 和 TrackPoint.timestamp 类型一致
5. **参数生效**：MatcherConfig 每个字段必须在算法中有明确的消费点，且有测试验证
6. **线程安全**：工作线程只接收纯 Python 数据（dataclass），不碰 UI 对象
7. **资源管理**：所有文件操作用 context manager（with 语句）
8. **异常日志**：每个 except 块必须调用 log_error() 记录到 errors.log
9. **拷贝模式**：输出数量 == 输入数量，每条路径都必须拷贝
10. **变量初始化**：函数入口统一初始化所有后续分支用到的变量
11. **单一实现**：每个功能只有一个实现类，禁止 _v2/_v3 后缀共存
12. **距离计算**：用 `geopy.distance.geodesic()`，考虑地球曲率

**默认参数来源：** 这些默认值在原项目 v7.2.0 中通过 1832 张照片实测验证，达到 83.1% 成功率。
