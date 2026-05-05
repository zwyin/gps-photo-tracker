# GPS Photo Tracker 重写设计规格

**日期：** 2026-05-05
**状态：** v3（待审阅）
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

**写入 GPS（精确字段规格，基于 DSC02258.JPG 实测数据验证）：**

GPS IFD 包含 7 个 tag，写入后通过 `piexif.load()` 验证或 macOS `mdls` 验证：

| Tag | IFD 字段名 | 值格式 | 示例（DSC02258.JPG, 25.953°N 102.758°E, 1810.6m） |
|-----|-----------|--------|-----|
| 0 | GPSVersionID | `(2, 3, 0, 0)` — EXIF 2.3 标准 | `(2, 3, 0, 0)` |
| 1 | GPSLatitudeRef | `b'N'` 或 `b'S'` | `b'N'` |
| 2 | GPSLatitude | `((度, 1), (分, 1), (秒×10000, 10000))` — 有理数 DMS | `((24, 1), (57, 1), (11601, 2500))` |
| 3 | GPSLongitudeRef | `b'E'` 或 `b'W'` | `b'E'` |
| 4 | GPSLongitude | 同 GPSLatitude 格式 | `((102, 1), (45, 1), (27603, 2500))` |
| 5 | GPSAltitudeRef | `0`（海平面以上）或 `1`（海平面以下） | `0` |
| 6 | GPSAltitude | `(int(abs(alt) * 100), 100)` — 0.01m 精度有理数 | `(181060, 100)` = 1810.6m |

**经纬度转换公式（十进制 → DMS 有理数）：**
```python
def _to_dms_rational(decimal: float) -> tuple:
    """十进制度 → EXIF GPS DMS 有理数格式"""
    degrees = int(decimal)
    minutes_decimal = (decimal - degrees) * 60
    minutes = int(minutes_decimal)
    seconds = (minutes_decimal - minutes) * 60
    return ((degrees, 1), (minutes, 1), (int(seconds * 10000), 10000))

# 示例: 25.953° → ((24, 1), (57, 1), (46800, 10000))
# 验证: 24 + 57/60 + 46800/(10000*3600) = 24 + 0.95 + 0.0013 ≈ 25.9513°
```

**海拔转换：**
```python
def _to_altitude_rational(altitude: float) -> tuple:
    """海拔 → EXIF GPS 有理数格式，0.01m 精度"""
    return (int(abs(altitude) * 100), 100)

# 示例: 1810.6m → (181060, 100)
# altitude = 0 → (0, 100)  ← 必须写入，不能用 truthy 跳过
# altitude = -50.3 → GPSAltitudeRef = 1, (5030, 100)
```

**写入规则：**
- GPS Version ID 固定 `(2, 3, 0, 0)`，不依赖记忆，参考 EXIF 2.3 规范
- altitude = 0 时正确写入 `(0, 100)`（用 `is not None` 判断，防范 Bug-EXIF-01）
- altitude = None 时跳过 Tag 5 和 Tag 6（不写入海拔相关 tag）
- 负海拔：GPSAltitudeRef = 1，GPSAltitude 取绝对值
- 保留原始 EXIF 其他所有字段（相机信息、拍摄时间等）
- src == dst 时原地写入（覆盖模式）
- 写入后验证：立即用 `piexif.load()` 读回，比对经纬度误差 < 0.001 度

**验证方法：**
```python
# macOS 命令行验证
mdls -name kMDItemGPSStatus DSC02258.JPG
# 期望: kMDItemGPSStatus = "GPS Present"

# Python 验证
exif_dict = piexif.load(dst_path)
gps_ifd = exif_dict.get("GPS", {})
assert gps_ifd.get(piexif.GPSIFD.GPSVersionID) == (2, 3, 0, 0)
assert gps_ifd.get(piexif.GPSIFD.GPSAltitude) == expected_rational
```

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

### 5.1 接口

```python
# 进度回调类型
class ProgressPhase(Enum):
    SCANNING_GPX = "scanning_gpx"
    SCANNING_PHOTOS = "scanning_photos"
    MATCHING = "matching"
    WRITING = "writing"

@dataclass
class ProgressUpdate:
    phase: ProgressPhase
    current: int
    total: int
    current_file: str      # 当前正在处理的文件名
    elapsed_seconds: float

# 逐条结果回调：每处理完一张照片就回调一次
OnPhotoProcessed = Callable[[MatchResult], None]
# 进度回调：每有进度变化就回调
OnProgress = Callable[[ProgressUpdate], None]

class GPSTaggingService:
    def scan_gpx(self, gpx_dir: Path) -> list[GPXSegment]
    def scan_photos(self, photo_dir: Path) -> list[PhotoInfo]
    def preview(self, segments: list[GPXSegment], photos: list[PhotoInfo],
                config: MatcherConfig,
                on_progress: OnProgress | None = None,
                on_photo_processed: OnPhotoProcessed | None = None,
                cancel: CancellationToken | None = None) -> BatchResult
    def process(self, segments: list[GPXSegment], photos: list[PhotoInfo],
                config: MatcherConfig, options: ProcessOptions,
                on_progress: OnProgress | None = None,
                on_photo_processed: OnPhotoProcessed | None = None,
                cancel: CancellationToken | None = None) -> BatchResult
```

### 5.2 实时进度机制

Service 层通过两个回调向 GUI 实时推送状态：

**OnProgress（进度回调）：**
- 在扫描 GPX 文件时：每解析完一个 GPX 文件回调一次
- 在扫描照片时：每读取完一张照片的 EXIF 回调一次
- 在匹配阶段：每匹配完一张照片回调一次
- 在写入阶段：每写入完一张照片回调一次
- 回调内容包含：当前阶段、进度 (current/total)、当前文件名、已用时间

**OnPhotoProcessed（逐条结果回调）：**
- 每张照片处理完成后立即回调
- 回调内容是完整的 `MatchResult`（包含 GPS 坐标、匹配方式、拒绝原因）
- GUI 可据此实时更新结果表格，无需等待全部完成

**估算剩余时间：** GUI 根据 `elapsed_seconds / current * (total - current)` 计算，在 progress 回调中已有足够数据。

### 5.3 处理逻辑

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

### 5.4 取消机制

- `CancellationToken` 基于 `threading.Event`
- Service 在每张照片处理后检查 `cancel.is_cancelled`
- 取消时立即停止，已写入的文件保留（不回滚）
- GUI 层调用 `worker.cancel()` 触发

### 5.5 错误策略

- 单文件失败：记录 errors.log，跳过，继续处理下一张
- 系统性失败（输出目录不可写、磁盘满）：抛异常，中止整批
- GPX 解析失败：跳过该文件，记录 errors.log
- 永远不在 GUI 层显示原始 Python traceback，Service 层包装为用户友好消息

### 5.6 可集成性

`GPSTaggingService` 是纯 Python 类，不依赖 GUI 或 Qt，可被任何代码 import。回调是可选的（传 None 则不推送进度）。

---

## 6. GUI 层设计

### 6.1 主窗口布局（三区域）

主窗口分为左侧配置区 + 右侧预览/结果区。处理过程中右侧实时更新，用户无需等待全部完成即可看到逐条结果。

```
┌─────────────────────────────────────────────────────────────────┐
│  GPS Photo Tracker                                    [─][□][×] │
├──────────────────────────────┬──────────────────────────────────┤
│  📂 文件选择                 │  📊 匹配结果（实时更新）           │
│  ┌────────────────────────┐ │  ┌──────────────────────────────┐│
│  │ GPS: [/path/] [浏览]   │ │  │ 统计卡片                      ││
│  │ 照片: [/path/] [浏览]  │ │  │ 总数:1832 成功:1523 跳过:189 ││
│  │ 输出: [/path/] [浏览]  │ │  │ 失败:120 覆盖:5  成功率:83%  ││
│  │ GPS: 36文件 12000点    │ │  └──────────────────────────────┘│
│  │ 照片: 1832张 189有GPS  │ │                                  │
│  └────────────────────────┘ │  📋 照片详情列表 (QTableView)     │
│                             │  ┌──────────────────────────────┐│
│  ⚙️ 参数配置                 │  │文件名    │GPS(前)│GPS(后)    ││
│  ┌────────────────────────┐ │  │          │(匹配) │(结果)     ││
│  │ 孤立窗口 [===●===] 5分 │ │  ├──────────┼───────┼───────────┤│
│  │ 中间窗口 [====●==] 60分│ │  │DSC01.JPG │无     │25.05,    ││
│  │ 上下文窗口 [===●===]5分│ │  │          │       │102.71    ││
│  │ 距离阈值 [===●===]200m│ │  │方式:插值  │时差:12s│海拔:1811  ││
│  │ ☑ 匹配首尾 ☐ 覆盖GPS  │ │  ├──────────┼───────┼───────────┤│
│  │ ☑ 保持目录结构         │ │  │DSC02.JPG │有     │(跳过)     ││
│  └────────────────────────┘ │  │原GPS: 25.03, 102.68          ││
│                             │  ├──────────┼───────┼───────────┤│
│  ◉ 预览 ○ 拷贝 ○ 覆盖      │  │DSC03.JPG │无     │❌ 未匹配  ││
│                             │  │原因: GPS数据缺失              ││
│  [🚀 开始处理]  [取消]      │  └──────────────────────────────┘│
│                             │                                  │
│  ┌────────────────────────┐ │  🔍 照片预览（选中行时显示）       │
│  │ 扫描GPS  ██████░░ 80%  │ │  ┌──────────────────────────────┐│
│  │ 扫描照片 ████░░░░ 45%  │ │  │ [缩略图 200x200]  DSC01.JPG ││
│  │ 匹配    ██░░░░░░ 20%  │ │  │ 拍摄: 2026-02-17 14:32:15   ││
│  │ 写入    ░░░░░░░░  0%   │ │  │ GPS(新): 25.052, 102.708    ││
│  │ 当前: DSC0142.JPG      │ │  │ 海拔: 1811m                  ││
│  │ 已用: 45s  剩余: ~3min │ │  │ 方式: 线性插值  时差: 12秒   ││
│  └────────────────────────┘ │  └──────────────────────────────┘│
└──────────────────────────────┴──────────────────────────────────┘
```

### 6.2 实时进度面板

左侧下方的进度面板在处理期间显示：

**4 阶段独立进度条：**
- 扫描 GPS：已解析 GPX 文件数 / 总数
- 扫描照片：已读取 EXIF 照片数 / 总数
- 匹配：已匹配照片数 / 总数
- 写入：已写入照片数 / 待写入数（预览模式跳过此阶段）

**实时信息：**
- 当前正在处理的文件名（如 `DSC0142.JPG`）
- 已用时间（秒）
- 预估剩余时间（根据已处理速度估算）
- 处理速度（张/分钟）

进度数据来源：Service 层的 `OnProgress` 回调 → Worker 的 Signal → 主线程 Slot。

### 6.3 GPX 轨迹浏览对话框

从主窗口左侧"GPS: 36文件 12000点"处可点击展开，查看 GPX 轨迹详情。

```
┌──────────────────────────────────────────────────────────┐
│  GPX 轨迹详情                                     [×]   │
├──────────────────────────────────────────────────────────┤
│  📁 GPX 文件列表                                         │
│  ┌────────────────────────────────────────────────────┐  │
│  │ ☑ 20260207登山.gpx    2026-02-07  328点  08:00-17:30│  │
│  │ ☑ 20260208徒步.gpx    2026-02-08  156点  09:00-14:20│  │
│  │ ☑ 20260209骑行.gpx    2026-02-09  412点  07:30-18:00│  │
│  │ ☐ 20260210休息.gpx    2026-02-10  12点   10:00-10:30│  │
│  │ ... (36 个文件)                                    │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  选中文件: 20260207登山.gpx                               │
│  ┌────────────────────────────────────────────────────┐  │
│  │ Track 1                                            │  │
│  │   Segment 1: 08:00-12:30 (202点)                   │  │
│  │   Segment 2: 13:00-17:30 (126点)                   │  │
│  │ 起止坐标: 25.123°N 102.456°E → 25.987°N 102.789°E │  │
│  │ 海拔范围: 1850m - 3950m                            │  │
│  │ 时间覆盖: 2026-02-07 08:00 ~ 17:30 (UTC+8)        │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  时间覆盖总览（所有勾选文件）                               │
│  ┌────────────────────────────────────────────────────┐  │
│  │ 02/07 ████████████████████████░░░░ 08:00-17:30     │  │
│  │ 02/08 ██████████████░░░░░░░░░░░░░ 09:00-14:20     │  │
│  │ 02/09 ████████████████████████████ 07:30-18:00     │  │
│  │ 02/10 ██░░░░░░░░░░░░░░░░░░░░░░░░░ 10:00-10:30     │  │
│  │ ...                                                │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  [取消选择] [全部选择]                        [确定]      │
└──────────────────────────────────────────────────────────┘
```

**功能：**
- 文件列表可多选/取消选择（勾选框控制哪些 GPX 参与匹配）
- 选中文件后显示 track/segment 层级、起止坐标、海拔范围、时间覆盖
- 时间覆盖总览帮助用户判断哪些日期有 GPS 数据，哪些日期缺失
- 取消勾选的 GPX 文件不参与匹配

### 6.4 照片浏览对话框

从主窗口左侧"照片: 1832张 189有GPS"处可点击展开，查看照片详情列表。

```
┌──────────────────────────────────────────────────────────────┐
│  照片列表                                              [×]  │
├──────────────────────────────────────────────────────────────┤
│  筛选: [全部▾] [排序: 文件名↑▾]  搜索: [____________]       │
├──────────────────────────────────────────────────────────────┤
│  文件名       │拍摄时间          │GPS状态│GPS坐标           │
│  ────────────┼─────────────────┼───────┼────────────────── │
│  DSC02258.JPG│2026-02-17 14:32 │无     │—                  │
│  DSC02259.JPG│2026-02-17 14:33 │无     │—                  │
│  DSC02264.JPG│2026-02-17 14:45 │有     │25.053°N 102.758°E│
│  DSC02270.JPG│2026-02-17 15:01 │有     │25.058°N 102.762°E│
│  ... (1832 张)                                               │
├──────────────────────────────────────────────────────────────┤
│  [缩略图 150x150]  DSC02264.JPG                             │
│  路径: /Volumes/photos/202602/DSC02264.JPG                  │
│  拍摄: 2026-02-17 14:45:23 (UTC+8)                          │
│  GPS: 25.053°N, 102.758°E  海拔: 1815m                      │
│  相机: SONY ILCE-7M4  镜头: FE 24-70mm                      │
└──────────────────────────────────────────────────────────────┘
```

**功能：**
- 显示所有扫描到的照片，含文件名、拍摄时间、GPS 状态（有/无）
- 筛选：全部 / 有GPS / 无GPS
- 排序：按文件名、拍摄时间
- 搜索：按文件名模糊搜索
- 选中行显示缩略图 + 完整 EXIF 摘要（相机型号、镜头等）
- 已有 GPS 的照片显示坐标，无 GPS 的显示"—"
- 缩略图异步加载，QPixmapCache 缓存，资源用后释放

### 6.5 匹配结果详情对话框

从主窗口结果列表双击某行弹出，展示该照片匹配前后的完整信息。

```
┌──────────────────────────────────────────────────────────┐
│  照片匹配详情                                      [×]   │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────┐  DSC02258.JPG                          │
│  │              │  拍摄时间: 2026-02-17 14:32:15 (UTC+8) │
│  │  [缩略图     │  文件路径: /photos/202602/DSC02258.JPG │
│  │   300x300]   │  相机: SONY ILCE-7M4                   │
│  │              │                                        │
│  └──────────────┘                                        │
│                                                          │
│  ── GPS 匹配结果 ──────────────────────────────────────  │
│                                                          │
│  匹配前:  无 GPS 信息                                    │
│  匹配后:  25.953°N, 102.758°E                            │
│  海拔:    1810.6m                                        │
│  方式:    线性插值                                        │
│  时间差:  12秒                                            │
│  来源:    20260217户外步行.gpx (Segment 1)                │
│                                                          │
│  ── 插值参考点 ────────────────────────────────────────  │
│                                                          │
│  前一点:  14:31:58  25.952°N, 102.757°E  1808m  (2s前)   │
│  后一点:  14:32:30  25.954°N, 102.759°E  1813m  (15s后)  │
│  前后距离: 247m  插值比例: 13.3%                          │
│                                                          │
│  [在地图中查看]                              [关闭]       │
└──────────────────────────────────────────────────────────┘
```

**功能：**
- 显示照片缩略图（300x300）和完整 EXIF 摘要
- GPS 匹配前后对比（无→有，或旧GPS→新GPS）
- 匹配方式：线性插值 / 就近匹配 / 跳过（已有GPS）/ 失败
- 插值参考点：显示前后的 GPS 点坐标、时间、距离
- 失败的照片显示拒绝原因和详细解释
- 覆盖模式显示旧GPS → 新GPS 坐标和距离差

### 6.6 设置对话框

从主窗口菜单或工具栏打开，配置持久化参数。

```
┌──────────────────────────────────────────────────────────┐
│  设置                                                [×] │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ── 匹配参数 ──────────────────────────────────────────  │
│  孤立照片时间窗口  [=====●=====] 300秒  (60-3600)       │
│  中间照片时间窗口  [==========●] 3600秒 (600-7200)      │
│  上下文窗口        [=====●=====] 300秒  (60-1800)       │
│  GPS 距离阈值      [=====●=====] 200米  (50-1000)       │
│  ☑ 匹配首尾孤立照片                                     │
│  时间偏移          [___0___] 秒 (-3600~3600)             │
│                                                          │
│  ── 处理选项 ──────────────────────────────────────────  │
│  默认处理模式  ◉ 预览  ○ 拷贝  ○ 覆盖                  │
│  ☑ 保持目录结构                                          │
│  ☐ 覆盖已有 GPS 坐标                                    │
│                                                          │
│  ── 日志 ──────────────────────────────────────────────  │
│  日志目录: [/path/to/logs] [浏览]                        │
│  日志保留天数: [30] 天                                   │
│                                                          │
│  ── 关于 ──────────────────────────────────────────────  │
│  GPS Photo Tracker v1.0.0                                │
│  Python 3.11+ / PySide6 / piexif                         │
│                                                          │
│  [恢复默认值]                                [保存]      │
└──────────────────────────────────────────────────────────┘
```

**功能：**
- 所有 MatcherConfig 字段可视化配置（滑块 + 数值输入双控）
- 处理选项持久化（QSettings）
- 日志目录可自定义，保留天数可配置
- 恢复默认值一键重置为 MatcherConfig 的默认值
- 保存时自动写入 QSettings，下次启动自动加载

### 6.7 匹配结果面板（右侧，实时更新）

**统计卡片（顶部）：**
- 处理过程中实时更新计数（每处理完一张照片 +1）
- 总数 / 成功 / 跳过 / 失败 / 覆盖 / 成功率

**照片详情列表（QTableView，虚拟滚动）：**
- 每处理完一张照片就新增一行（通过 `OnPhotoProcessed` 回调）
- 列：文件名 | GPS(前) | GPS(后/结果) | 匹配方式 | 时间差
- 成功的照片：显示 GPS 坐标 + 海拔 + 匹配方式（插值/就近）+ 时间差
- 跳过的照片：显示原 GPS 坐标 + "跳过(已有GPS)"
- 覆盖的照片：显示旧GPS → 新GPS + "已覆盖"
- 失败的照片：显示拒绝原因（GPS缺失/时间差过大/距离过大/尾部孤立）
- 可按任意列排序
- 可按结果筛选（全部/成功/跳过/失败）
- 双击行可弹出详情对话框

**照片预览（底部）：**
- 选中列表中的某一行时，底部显示该照片的缩略图（200x200）+ 详细信息
- 包含：拍摄时间、GPS 前/后对比、匹配方式、时间差、海拔
- 缩略图异步加载（不阻塞 UI），使用 QPixmapCache 缓存
- 方向自动校正（EXIF Orientation）
- 资源管理：缩略图使用后释放（防范 Bug-UI-03）

### 6.8 交互流程

1. 用户选择 GPS 目录 → 立即扫描，左侧显示 GPX 文件数和轨迹点数
2. 用户选择照片目录 → 立即扫描，左侧显示照片数和已有 GPS 数
3. 用户调整参数（有默认值，可选）
4. 点击"开始处理"（默认预览模式）→ 右侧开始实时显示匹配结果
5. 处理过程中：进度条更新、统计卡片更新、结果列表逐行填充
6. 用户可随时调整筛选/排序查看已出结果，不用等全部完成
7. 预览确认满意后 → 切换到"拷贝"模式 → 选择输出目录 → 再次"开始处理"
8. 拷贝过程中同样实时更新（写入阶段进度条也动起来）
9. 完成后弹窗通知，右侧保留完整结果可浏览

### 6.9 线程模型

```python
class ProcessingWorker(QThread):
    progress = Signal(str, int, int, str, float)
        # phase_name, current, total, current_file, elapsed_seconds
    photo_processed = Signal(object)
        # MatchResult — 每张照片处理完立即发射
    finished = Signal(object)          # BatchResult
    error = Signal(str)                # 用户友好错误消息

    def __init__(self, service: GPSTaggingService,
                 segments: list[GPXSegment],
                 photos: list[PhotoInfo],
                 config: MatcherConfig,
                 options: ProcessOptions):
        super().__init__()
        self._cancel = CancellationToken()
        self._service = service
        # 所有参数在主线程打包，工作线程只读取这些纯 Python 数据

    def run(self):
        try:
            if self._options.mode == ProcessMode.PREVIEW:
                result = self._service.preview(
                    ..., on_progress=self._on_progress,
                    on_photo_processed=self._on_photo,
                    cancel=self._cancel)
            else:
                result = self._service.process(
                    ..., on_progress=self._on_progress,
                    on_photo_processed=self._on_photo,
                    cancel=self._cancel)
            self.finished.emit(result)
        except OperationCancelledError:
            pass  # 用户主动取消，不弹错误
        except GPSTrackerError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"处理失败：{e}")

    def _on_progress(self, update: ProgressUpdate):
        self.progress.emit(
            update.phase.value, update.current, update.total,
            update.current_file, update.elapsed_seconds)

    def _on_photo(self, result: MatchResult):
        self.photo_processed.emit(result)

    def cancel(self):
        self._cancel.cancel()
```

**硬规则：**
- 工作线程只接收纯 Python 数据（dataclass、float、str），不碰任何 Qt/UI 对象
- 进度和结果通过 Signal 发射，主线程 Slot 接收更新 UI
- 取消通过 CancellationToken，不通过 Qt 信号反向传递
- 缩略图加载在主线程用 QTimer 延迟执行，避免阻塞
- QFileDialog 使用 `DontUseNativeDialog` 作为网络路径的回退方案

### 6.10 配置持久化

- 参数通过 QSettings 持久化（macOS: plist, Windows: registry, Linux: ini）
- 首次启动使用 MatcherConfig 默认值
- 用户修改参数后自动保存
- 路径历史记录（最近使用的 GPS/照片/输出目录）
- 窗口位置和大小保存恢复

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

采用 Python src layout（`src/` 包目录），是现代 Python 项目惯例，配合 `pyproject.toml` 实现 pip installable。参考 [scientific-python/cookiecutter](https://github.com/scientific-python/cookiecutter) 的目录规范。

```
gps-photo-tracker-claude/
├── src/
│   └── gps_photo_tracker/         # 可 install 的包名（下划线，PEP 8）
│       ├── __init__.py             # 版本号 __version__
│       ├── __main__.py             # python -m gps_photo_tracker 入口
│       ├── core/                   # 核心算法层（无 IO 依赖，可独立测试）
│       │   ├── __init__.py
│       │   ├── models.py           # 所有 dataclass + 异常 + 常量
│       │   ├── gpx_parser.py       # GPX 解析
│       │   ├── gps_matcher.py      # GPS 匹配算法（含插值）
│       │   └── exif_writer.py      # EXIF 读写
│       ├── service/                # Service 层（业务编排，纯 Python）
│       │   ├── __init__.py
│       │   ├── tagging_service.py  # 主服务
│       │   ├── file_provider.py    # 文件系统抽象（含重试）
│       │   └── cancel_token.py     # CancellationToken
│       ├── gui/                    # GUI 层（PySide6）
│       │   ├── __init__.py
│       │   ├── main_window.py      # 主窗口（左右布局）
│       │   ├── config_panel.py     # 左侧配置面板
│       │   ├── progress_panel.py   # 实时进度面板（4阶段进度条+ETA）
│       │   ├── result_table.py     # QTableView 匹配结果表格
│       │   ├── photo_preview.py    # 照片缩略图预览组件
│       │   ├── gpx_browser.py      # GPX 轨迹浏览对话框（6.3）
│       │   ├── photo_browser.py    # 照片浏览对话框（6.4）
│       │   ├── detail_dialog.py    # 匹配结果详情对话框（6.5）
│       │   ├── settings_dialog.py  # 设置对话框（6.6）
│       │   └── workers.py          # QThread 工作线程（含回调适配）
│       └── logging_/               # 日志
│           ├── __init__.py
│           └── logger.py
├── tests/                          # 测试
│   ├── conftest.py                 # mock 数据工厂
│   ├── unit/                       # 单元测试（mock，不依赖文件）
│   │   ├── test_matcher.py
│   │   ├── test_parser.py
│   │   └── test_exif.py
│   ├── integration/                # 集成测试（safe_test_data，3 张）
│   └── batch/                      # 批量测试（179 张 + 1832 张）
├── test-data/                      # 测试数据（从原项目复制，只读）
├── test-work/                      # 测试工作区（可写入）
├── docs/                           # 文档
│   ├── requirements-analysis.md
│   ├── bug-history-and-lessons.md
│   ├── test-data-strategy.md
│   └── superpowers/specs/          # 设计规格
├── pyproject.toml                  # 项目配置
├── LICENSE                         # MIT
└── README.md
```

**pyproject.toml 关键配置：**
```toml
[project]
name = "gps-photo-tracker"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = [
    "PySide6>=6.6",
    "piexif>=1.1.3",
    "gpxpy>=1.6.0",
    "Pillow>=10.0.0",
    "geopy>=2.4.0",
    "tenacity>=8.0.0",
]

[project.scripts]
gps-photo-tracker = "gps_photo_tracker.__main__:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["slow: marks tests as slow"]

[tool.coverage.run]
source = ["src/gps_photo_tracker"]

[tool.coverage.report]
fail_under = 75
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

### 12.1 工具选型：Nuitka + pyside6-deploy

**不使用 PyInstaller**（依赖宿主机 Python 运行环境，不满足"傻瓜式安装"需求）。

**使用 Nuitka**：将 Python 编译为原生 C 代码，生成独立可执行文件，无需宿主 Python。
- Qt 官方推荐打包方式：`pyside6-deploy` 底层使用 Nuitka
- 编译产物为原生二进制，启动速度快，无需 Python 运行时
- 跨平台支持好，macOS/Windows/Linux 均可生成独立安装包

### 12.2 各平台打包方案

| 平台 | 打包命令 | 产物 | 分发方式 |
|------|---------|------|---------|
| macOS | `pyside6-deploy` | `.app` bundle | .dmg 安装镜像，考虑 codesign |
| Windows | `pyside6-deploy` | `.exe` | .msi 或 NSIS 安装器 |
| Linux | `pyside6-deploy` | 可执行文件 | AppImage 或 .deb/.rpm |

### 12.3 打包配置

在项目根目录创建 `pysidedeploy.spec`（pyside6-deploy 配置文件）：

```yaml
app: src/gps_photo_tracker/__main__.py
target: GPS Photo Tracker
packages:
  - gps_photo_tracker
excluded_modules:
  - tkinter
  - unittest
  - test
  - tests
qml: false
uib: false
```

### 12.4 目标指标

- 包体积 < 150MB（PySide6 是主要体积来源，Nuitka 编译后可减小部分体积）
- 首次启动时间 < 3 秒
- 无需安装 Python 或任何运行时
- 双击即用，无需命令行操作

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
