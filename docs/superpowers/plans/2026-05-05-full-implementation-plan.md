# GPS Photo Tracker 完整实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 从零重写 GPS Photo Tracker，5 轮迭代，每轮产出可测试的增量。

**Architecture:** 四层解耦：GUI → Service → Core → FileIO。src layout。所有跨模块数据用 dataclass。

**Tech Stack:** Python 3.11+, PySide6, piexif, gpxpy, Pillow, geopy, tenacity, pytest

**Spec:** `docs/superpowers/specs/2026-05-05-gps-photo-tracker-rewrite-design.md` (v3)

**Coverage gates:** Core ≥ 90%, Service ≥ 80%, Overall ≥ 75%

---

## Round 1: 项目骨架 + Models + Exceptions + GPXParser

### Task 1.1: 项目骨架

**Files:**
- Create: `pyproject.toml`
- Create: `src/gps_photo_tracker/__init__.py` (含 `__version__`)
- Create: `src/gps_photo_tracker/__main__.py` (入口 `main()`)
- Create: `src/gps_photo_tracker/{core,service,gui,logging_}/__init__.py`
- Create: `tests/{__init__.py,unit/__init__.py,integration/__init__.py,batch/__init__.py}`
- Create: `test-data/.gitkeep`
- Create: `test-work/.gitkeep`（内容加入 .gitignore）
- Create: `LICENSE` (MIT)

- [x] 创建目录结构
- [x] 编写 pyproject.toml（6 个依赖 + pytest/cov + coverage source 配置）
- [x] `pip install -e ".[dev]"` 成功
- [ ] 创建 LICENSE 和 .gitignore（忽略 test-work/ 内容）

### Task 1.2: models.py

**Files:**
- Create: `src/gps_photo_tracker/core/models.py`

**内容（全部来自 Spec Section 3 + Section 8）：**
- 异常层级：`GPSTrackerError` → `GPXParseError`, `EXIFReadError`, `EXIFWriteError`, `MatchingError`, `OperationCancelledError`, `FileAccessError` → `PermissionDeniedError`, `DiskFullError`, `NetworkTimeoutError`
- 枚举：`ProcessMode` (preview/copy/overwrite), `ProgressPhase` (4 阶段)
- 常量：`RejectReason` (5 个字符串常量)
- 数据类：`TrackPoint`, `GPXSegment`, `GPSInfo`, `PhotoInfo`, `MatchResult`, `BatchResult`, `MatcherConfig`, `ProcessOptions`, `ProgressUpdate`
- 类型别名：`OnPhotoProcessed = Callable[[MatchResult], None]`, `OnProgress = Callable[[ProgressUpdate], None]`
- MatchResult 增加插值上下文字段（供 GUI 详情对话框展示，Spec Section 6.5）：`interpolation_prev: TrackPoint | None`, `interpolation_next: TrackPoint | None`, `interpolation_distance: float | None`, `interpolation_ratio: float | None`

- [x] 编写 models.py
- [ ] 验证 import 无报错

### Task 1.3: GPXParser + 测试

**Files:**
- Create: `src/gps_photo_tracker/core/gpx_parser.py`
- Create: `tests/conftest.py` (时间工厂 `utc()`, `make_point()`, `make_segment()`, `make_photo()`)
- Create: `tests/unit/test_gpx_parser.py`

**接口（Spec Section 4.1）：**
```python
class GPXParser:
    def parse_file(self, path: Path) -> list[GPXSegment]  # 单文件
    def parse_directory(self, dir: Path) -> list[GPXSegment]  # 目录扫描
```

**实现要点：**
- 用 gpxpy 解析，每个 `<trkseg>` → 一个 GPXSegment
- `timestamp = utc_time.timestamp()`，不硬编码时区偏移（防范 Bug-ALG-05）
- 缺少 `<ele>` 时 `altitude = None`（键名统一 altitude，防范 Bug-EXIF-02）
- points 按 timestamp 排序
- parse_directory: glob `*.gpx` 非递归，单文件失败跳过，全部失败才抛 GPXParseError
- 解析失败抛 GPXParseError（不返回空列表吞掉错误，防范 Bug-LOG-02）

**测试用例（test_gpx_parser.py）：**
- `test_parse_single_track_single_segment`: 基本解析，验证 GPXSegment 字段
- `test_parse_multi_segment`: 同一文件多个 `<trkseg>` 产生多个 segment
- `test_missing_elevation`: 无 `<ele>` 标签 → altitude=None
- `test_empty_gpx`: 空轨迹 → 返回空列表
- `test_invalid_gpx_raises`: 非法内容 → 抛 GPXParseError
- `test_parse_directory`: 目录扫描，跳过非 .gpx 文件
- `test_parse_directory_all_fail`: 所有文件无效 → 抛 GPXParseError
- `test_timestamp_is_utc`: 验证 timestamp 不受本地时区影响
- `test_points_sorted`: 验证 segment 内 points 按 timestamp 升序

- [x] 编写 gpx_parser.py
- [ ] 编写 conftest.py
- [ ] 编写 test_gpx_parser.py (9 个用例)
- [ ] `pytest tests/unit/test_gpx_parser.py -v` 全绿
- [ ] `pytest --cov=src/gps_photo_tracker/core/gpx_parser` ≥ 90%

### Task 1.4: 提交 Round 1

- [ ] `git add && git commit -m "feat: Round 1 - project skeleton, models, exceptions, GPXParser with tests"`

---

## Round 2: GPSMatcher（含线性插值）

### Task 2.1: GPSMatcher 实现

**Files:**
- Create: `src/gps_photo_tracker/core/gps_matcher.py`
- Create: `tests/unit/test_gps_matcher.py`

**接口（Spec Section 4.2）：**
```python
class GPSMatcher:
    def __init__(self, config: MatcherConfig)
    def match(self, photos: list[PhotoInfo], segments: list[GPXSegment]) -> list[MatchResult]
```

**匹配流程（5 步，Spec Section 4.2 完整定义）：**
1. 应用 time_offset：`adjusted_time = photo.timestamp + config.time_offset`
2. 找 segment：`segment.start <= adjusted_time <= segment.end`
3. 判断上下文：prev/next 在 context_window 内 → "middle"，否则 "isolated"
4. 匹配方式：
   - middle + 双侧 GPS 点 + 距离 ≤ max_gps_distance + 时间差 ≤ middle_time_window → **线性插值** "interpolated"
   - middle + 单侧点 + 时间差 ≤ middle_time_window → 就近匹配 "nearest"
   - isolated + match_tail=True + 时间差 ≤ isolated_window → 就近匹配 "nearest"
5. 插值公式：按时间比例计算 lat/lon/alt（None 按 0 处理）

**关键防范（来自 Bug-History）：**
- Bug-ALG-01：所有阈值用 `self.config.xxx`，禁止硬编码
- Bug-ALG-02：prev/next 为 None 时安全退化为 isolated
- Bug-ALG-03：match_tail=False 时拒绝 isolated 照片
- Bug-ALG-05：时间比较统一用 UTC float
- Bug-ALG-06：默认参数用 MatcherConfig 的值（实测验证过）
- Bug-WEB-01：只保留一个 GPSMatcher 类，不使用 _v2/_v3 后缀
- Spec Rule 12：距离用 `geopy.distance.geodesic()`
- altitude 插值规则：前后两点 altitude 都为 None → 结果 altitude=None；只有一侧 None → None 按 0 参与计算

**测试用例（test_gps_matcher.py）：**
- `test_basic_interpolation`: 中间照片，前后 GPS 点都在 context_window 内 → 插值匹配
- `test_interpolation_accuracy`: 合成数据（均匀 GPS 点 + 中点照片），误差 < 1 米
- `test_nearest_match_single_side`: 中间照片但只有单侧 GPS 点 → 就近匹配
- `test_isolated_match_tail_true`: 孤立照片 + match_tail=True → 就近匹配
- `test_isolated_reject_tail_false`: 孤立照片 + match_tail=False → TAIL_ISOLATED
- `test_no_gps_coverage`: 照片不在任何 segment 内 → NO_GPS_COVERAGE
- `test_gps_distance_exceeded`: 前后 GPS 点距离 > 200m → GPS_DISTANCE
- `test_time_diff_exceeded_middle`: 中间照片时间差 > middle_time_window → TIME_DIFF
- `test_time_diff_exceeded_isolated`: 孤立照片时间差 > isolated_window → TIME_DIFF
- `test_no_track_points`: segment 内无 GPS 点 → NO_TRACK_POINTS
- `test_time_offset_positive`: time_offset=+60 → 匹配结果与 offset=0 不同
- `test_time_offset_negative`: time_offset=-60 → 匹配结果与 offset=0 不同
- `test_context_window_effect`: 不同 context_window 值改变 middle/isolated 判定
- `test_middle_time_window_effect`: 不同 middle_time_window 改变匹配/拒绝
- `test_isolated_window_effect`: 不同 isolated_window 改变匹配/拒绝
- `test_max_gps_distance_effect`: 不同 max_gps_distance 改变插值/拒绝
- `test_altitude_none_in_interpolation`: GPS 点 altitude=None → 插值结果 altitude 正确处理
- `test_altitude_both_none_in_interpolation`: 前后 GPS 点 altitude 都为 None → 结果 altitude=None（非 0）
- `test_first_photo_prev_none`: 第一张照片 prev=None → 安全退化为 isolated（防范 Bug-ALG-02）
- `test_last_photo_next_none`: 最后一张照片 next=None → 安全退化
- `test_single_photo_no_neighbors`: 只有一张照片 → 退化为 isolated
- `test_time_offset_shifts_match_target`: time_offset=+60 时匹配到的时间点确实是原始+60s 对应的 GPS 位置
- `test_returns_equal_length`: match() 返回列表长度 == 输入照片数量
- `test_batch_result_integration`: 多张照片混合场景，验证各种匹配方式
- `test_interpolation_context_fields`: MatchResult 的 interpolation_prev/next/distance/ratio 字段正确填充

- [ ] 编写 gps_matcher.py
- [ ] 编写 test_gps_matcher.py (24 个用例)
- [ ] `pytest tests/unit/test_gps_matcher.py -v` 全绿
- [ ] `pytest --cov=src/gps_photo_tracker/core/gps_matcher` ≥ 90%

### Task 2.2: 提交 Round 2

- [ ] `git commit -m "feat: Round 2 - GPSMatcher with linear interpolation, 24 test cases"`

---

## Round 3: EXIFWriter + FileProvider

### Task 3.1: EXIFWriter

**Files:**
- Create: `src/gps_photo_tracker/core/exif_writer.py`
- Create: `tests/unit/test_exif_writer.py`

**接口（Spec Section 4.3）：**
```python
class EXIFWriter:
    @staticmethod
    def read_datetime(path: Path) -> float | None  # UTC timestamp
    @staticmethod
    def read_gps(path: Path) -> GPSInfo | None
    @staticmethod
    def write_gps(src: Path, dst: Path, gps: GPSInfo) -> None  # raises EXIFWriteError
```

**GPS IFD 7 个 Tag（Spec Section 4.3 实测数据）：**
- GPSVersionID: `(2, 3, 0, 0)` — EXIF 2.3
- GPSLatitudeRef: `b'N'`/`b'S'`
- GPSLatitude: `((度,1),(分,1),(秒×10000,10000))`
- GPSLongitudeRef: `b'E'`/`b'W'`
- GPSLongitude: 同上格式
- GPSAltitudeRef: 0/1（海拔=0 必须写 `(0, 100)`，用 `is not None` 判断，防范 Bug-EXIF-01）
- GPSAltitude: `(int(abs(alt)*100), 100)` — 0.01m 精度

**关键防范：**
- Bug-EXIF-01：altitude=0 用 `is not None` 判断
- Bug-EXIF-02：altitude 键名统一（models.py 已统一）
- Bug-EXIF-03：精度固定 `*100/100`，不反复改
- Bug-EXIF-04：GPS Version `(2,3,0,0)` EXIF 2.3
- Bug-UI-03：Image.open 用 `with` 语句

**测试用例（需创建测试用 JPEG）：**
- `test_write_read_roundtrip`: 写入 GPS 后读回，经纬度误差 < 0.001 度
- `test_write_altitude_zero`: altitude=0 正确写入（不被当成 False）
- `test_write_negative_altitude`: 负海拔 → GPSAltitudeRef=1
- `test_write_no_altitude`: altitude=None → 不写海拔 Tag
- `test_write_preserves_exif`: 写入 GPS 后原始 EXIF（拍摄时间、相机型号）保留
- `test_read_datetime_priority`: DateTimeOriginal > DateTimeDigitized > DateTime
- `test_read_gps_existing`: 读取已有 GPS → GPSInfo
- `test_read_gps_none`: 无 GPS → None
- `test_write_overwrite_mode`: src==dst 时原地写入
- `test_invalid_image_raises`: 非法文件 → EXIFWriteError/EXIFReadError

- [ ] 编写 exif_writer.py
- [ ] 编写 test_exif_writer.py（用 Pillow 创建测试 JPEG + EXIF）
- [ ] `pytest tests/unit/test_exif_writer.py -v` 全绿
- [ ] 覆盖率 ≥ 90%

### Task 3.2: FileProvider

**Files:**
- Create: `src/gps_photo_tracker/service/file_provider.py`
- Create: `tests/unit/test_file_provider.py`

**接口（Spec Section 4.4）：**
```python
class FileProvider:
    def list_photos(self, directory: Path) -> list[Path]  # rglob *.jpg *.jpeg
    def list_gpx(self, directory: Path) -> list[Path]     # glob *.gpx (非递归)
    def copy_file(self, src: Path, dst: Path) -> None     # raises FileAccessError
```

**网络磁盘处理（Spec Section 4.4）：**
- tenacity retry: stop=3, wait=exponential(1,2,4)
- 单文件操作超时 30 秒
- copy_file 自动创建目标目录
- 失败抛 FileAccessError 子类（PermissionDeniedError / NetworkTimeoutError）

**测试用例：**
- `test_list_photos_jpeg_jpg`: 扫描 .jpg 和 .jpeg
- `test_list_photos_recursive`: 递归扫描子目录
- `test_list_photos_skips_png`: 跳过 .png
- `test_list_gpx_non_recursive`: 非递归扫描
- `test_list_gpx_case_insensitive`: .GPX 大小写
- `test_copy_file_creates_dest_dir`: 自动创建目标目录
- `test_copy_file_preserves_content`: 内容一致
- `test_copy_nonexistent_raises`: 源文件不存在 → FileAccessError
- `test_copy_permission_denied`: 模拟权限拒绝 → PermissionDeniedError
- `test_copy_timeout_raises`: 模拟超时 → NetworkTimeoutError
- `test_copy_retries_on_transient_error`: 临时错误时重试 3 次
- `test_list_empty_directory`: 空目录 → 空列表

- [ ] 编写 file_provider.py
- [ ] 编写 test_file_provider.py（用 tmp_path fixture）
- [ ] `pytest tests/unit/test_file_provider.py -v` 全绿

### Task 3.3: 提交 Round 3

- [ ] `git commit -m "feat: Round 3 - EXIFWriter with GPS IFD spec, FileProvider with retry"`

---

## Round 4: Service 层 + 日志 + 端到端测试

### Task 4.1: CancellationToken

**Files:**
- Create: `src/gps_photo_tracker/service/cancel_token.py`

```python
class CancellationToken:
    def cancel(self) -> None: ...
    @property
    def is_cancelled(self) -> bool: ...
```

基于 `threading.Event`（Spec Section 5.4）。

- [ ] 编写 cancel_token.py + 测试

### Task 4.2: OperationLogger

**Files:**
- Create: `src/gps_photo_tracker/logging_/logger.py`
- Create: `tests/unit/test_logger.py`

**4 个日志文件（Spec Section 7）：**
- `operations.log`: 任务开始/结束、参数、统计
- `matches.log`: 每张照片匹配结果
- `writes.log`: GPS 写入、覆盖记录
- `errors.log`: 异常、警告

**接口：**
```python
class OperationLogger:
    def log_match_success(self, result: MatchResult): ...
    def log_match_failed(self, result: MatchResult): ...
    def log_write_success(self, photo: PhotoInfo, gps: GPSInfo, dest: Path): ...
    def log_gps_overwrite(self, photo: PhotoInfo, old: GPSInfo, new: GPSInfo): ...
    def log_error(self, context: str, error: Exception): ...
```

**防范 Bug-LOG-01：** 参数全部用 dataclass，禁止裸 dict。

**补充方法：**
```python
def cleanup_old_logs(self, retention_days: int = 30) -> None: ...
```

- [ ] 编写 logger.py + test_logger.py
- [ ] `pytest tests/unit/test_logger.py -v` 全绿

### Task 4.3: GPSTaggingService

**Files:**
- Create: `src/gps_photo_tracker/service/tagging_service.py`
- Create: `tests/unit/test_tagging_service.py`

**接口（Spec Section 5.1）：**
```python
class GPSTaggingService:
    def scan_gpx(self, gpx_dir: Path) -> list[GPXSegment]
    def scan_photos(self, photo_dir: Path) -> list[PhotoInfo]
    def preview(self, segments, photos, config, on_progress, on_photo_processed, cancel) -> BatchResult
    def process(self, segments, photos, config, options, on_progress, on_photo_processed, cancel) -> BatchResult
```

**处理逻辑（Spec Section 5.3 三种模式表）：**

| 模式 | 匹配成功 | 已有GPS+不覆盖 | 已有GPS+覆盖 | 匹配失败 |
|------|---------|--------------|------------|---------|
| preview | 不动 | 不动 | 不动 | 不动 |
| copy | 拷贝+写GPS | 只拷贝 | 拷贝+写GPS | 只拷贝 |
| overwrite | 原地写GPS | 不动 | 原地写GPS | 不动 |

**关键契约：**
- 拷贝模式：输出数量 == 输入数量（防范 Bug-DATA-02）
- 覆盖时记录新旧 GPS 对比到 writes.log
- 单文件失败跳过继续（防范 Bug-LOG-02 每个 except 有日志）
- 系统性失败（输出目录不可写、磁盘满）→ 抛异常中止整批（Spec Section 5.5）
- 取消时立即停止，已写入文件保留（Spec Section 5.4）
- 进度回调：每张照片处理完回调一次 OnProgress + OnPhotoProcessed
- 计数器变量在函数入口统一初始化为 0（防范 Bug-UI-02/Bug-DATA-01）

**测试用例：**
- `test_preview_mode`: 不修改任何文件
- `test_copy_mode_success`: 匹配成功 → 拷贝 + GPS 写入正确
- `test_copy_mode_skipped`: 已有 GPS + 不覆盖 → 只拷贝
- `test_copy_mode_failed`: 匹配失败 → 只拷贝
- `test_copy_output_equals_input`: 输出数量 == 输入数量
- `test_overwrite_mode`: 原地写入 GPS
- `test_overwrite_gps_flag`: overwrite_gps=True 时覆盖已有 GPS
- `test_keep_structure`: keep_structure=True 保持目录结构
- `test_cancel_stops_early`: CancellationToken 取消后停止处理
- `test_progress_callbacks`: 验证 on_progress 回调被调用
- `test_photo_processed_callback`: 验证 on_photo_processed 逐条回调
- `test_gpx_parse_failure_skipped`: 单个 GPX 解析失败 → 跳过继续
- `test_systemic_failure_raises`: 输出目录不可写 → 抛异常中止整批
- `test_reject_groups_in_batch_result`: BatchResult.reject_groups 正确分类
- `test_overwritten_count`: 覆盖已有 GPS 时 overwritten 计数正确
- `test_service_no_qt_import`: GPSTaggingService 模块不 import 任何 PySide6/Qt 模块

- [ ] 编写 tagging_service.py
- [ ] 编写 test_tagging_service.py（14 个用例，mock FileProvider 和 EXIFWriter）
- [ ] `pytest tests/unit/test_tagging_service.py -v` 全绿

### Task 4.4: 集成测试（safe_test_data）

**Files:**
- Create: `tests/integration/test_e2e.py`

**前提：** 从原项目复制 safe_test_data（1 GPX + 3 JPG）到 test-data/

**测试用例：**
- `test_e2e_preview`: 完整流程预览模式
- `test_e2e_copy`: 完整流程拷贝模式，验证 GPS 写入
- `test_e2e_gps_accuracy`: 写入后读回，经纬度误差 < 0.001 度
- `test_e2e_altitude_none`: GPS 点无海拔数据 → EXIF 不含海拔 tag
- `test_e2e_copy_output_count`: 拷贝模式输出数量 == 输入数量

- [ ] 复制 safe_test_data 到 test-data/
- [ ] 编写 test_e2e.py
- [ ] `pytest tests/integration/ -v` 全绿

### Task 4.5: 提交 Round 4

- [ ] `git commit -m "feat: Round 4 - Service layer, logger, cancellation, e2e integration tests"`

---

## Round 5: GUI（PySide6）

### Task 5.1: QThread Worker

**Files:**
- Create: `src/gps_photo_tracker/gui/workers.py`

**接口（Spec Section 6.9）：**
```python
class ProcessingWorker(QThread):
    progress = Signal(str, int, int, str, float)
    photo_processed = Signal(object)
    finished = Signal(object)
    error = Signal(str)
```

**防范 Bug-UI-01：** 工作线程只接收纯 Python 数据（dataclass），不碰 UI 对象。

- [ ] 编写 workers.py

### Task 5.2: 主窗口框架

**Files:**
- Create: `src/gps_photo_tracker/gui/main_window.py`
- Create: `src/gps_photo_tracker/gui/config_panel.py`
- Create: `src/gps_photo_tracker/gui/progress_panel.py`
- Create: `src/gps_photo_tracker/gui/result_table.py`
- Create: `src/gps_photo_tracker/gui/photo_preview.py`

**布局（Spec Section 6.1）：** 左侧配置区 + 右侧结果区。三区域：文件选择 + 参数配置 + 进度 | 统计卡片 + 结果表格 + 照片预览。

**交互流程（Spec Section 6.8）：** 选 GPS → 选照片 → 调参 → 预览 → 确认 → 拷贝。

**各组件实现要点：**
- config_panel.py: 参数滑块 + 数值输入双控，所有数值参数做范围校验（Spec Section 6.6 定义的参数范围）
- result_table.py: QSortFilterProxyModel 实现实时筛选（全部/成功/跳过/失败）和排序，处理过程中可动态切换（Spec Section 6.7）
- progress_panel.py: 4 阶段独立进度条 + ETA + 当前文件名 + 处理速度
- photo_preview.py: QPixmapCache 缓存缩略图 + EXIF Orientation 自动校正 + Image.open 用 with 语句（防范 Bug-UI-03）

**配置持久化（Spec Section 6.10）：** QSettings 存参数 + 路径历史 + 窗口位置。

- [ ] 编写 5 个 GUI 组件文件
- [ ] 手动启动验证窗口能打开

### Task 5.3: 对话框

**Files:**
- Create: `src/gps_photo_tracker/gui/gpx_browser.py` (Spec Section 6.3)
- Create: `src/gps_photo_tracker/gui/photo_browser.py` (Spec Section 6.4)
- Create: `src/gps_photo_tracker/gui/detail_dialog.py` (Spec Section 6.5)
- Create: `src/gps_photo_tracker/gui/settings_dialog.py` (Spec Section 6.6)

**各对话框实现要点：**
- gpx_browser.py: 返回用户选择的 `list[GPXSegment]` 子集，勾选/取消勾选影响后续匹配
- photo_browser.py: 筛选（全部/有GPS/无GPS）+ 排序（文件名/拍摄时间）+ 搜索（文件名模糊）+ 异步缩略图加载
- detail_dialog.py: 展示 MatchResult 的插值上下文字段（interpolation_prev/next/distance/ratio）
- settings_dialog.py: 含日志目录配置 + 日志保留天数（Spec Section 6.6）

- [ ] 编写 4 个对话框
- [ ] 手动验证各对话框能打开和交互

### Task 5.4: 端到端 GUI 测试

**Files:**
- Create: `tests/integration/test_gui.py`

- [ ] 验证主窗口启动不崩溃
- [ ] 验证 Worker Signal/Slot 连通

### Task 5.5: 提交 Round 5

- [ ] `git commit -m "feat: Round 5 - PySide6 GUI, main window, dialogs, workers"`

---

## 跨轮验收检查

每轮结束后运行：

```bash
# 全量单元测试
pytest tests/unit/ -v

# 覆盖率报告
pytest --cov=src/gps_photo_tracker --cov-report=term-missing tests/unit/

# 集成测试（Round 4+）
pytest tests/integration/ -v
```

**覆盖率门禁：**
- Round 1-3 结束后：Core ≥ 90%
- Round 4 结束后：Core ≥ 90%, Service ≥ 80%
- Round 5 结束后：Overall ≥ 75%

**性能测试（Round 4 完成后）：**
- safe_test_data (3 张): < 5 秒
- small_batch (179 张): < 60 秒

**最终验收：**
- 成功率 ≥ 83%（对标 v7.2.0 基准 83.1%）
- GPS 写入 100%（所有匹配成功的照片 GPS 正确）
- 拷贝模式：输出数量 == 输入数量

---

## Feature 覆盖矩阵

需求定义在 `docs/requirements-analysis.md`。

| Feature | 名称 | 计划 Task | 状态 |
|---------|------|----------|------|
| CF-01 | GPX 文件解析 | Task 1.3 GPXParser | Round 1 |
| CF-02 | 照片扫描与读取 | Task 3.1 EXIFWriter.read_datetime + Task 3.2 FileProvider.list_photos | Round 3 |
| CF-03 | GPS 时间匹配算法 | Task 2.1 GPSMatcher | Round 2 |
| CF-04 | GPS 坐标写入 EXIF | Task 3.1 EXIFWriter.write_gps | Round 3 |
| CF-05 | 输出模式（preview/copy/overwrite） | Task 4.3 GPSTaggingService | Round 4 |
| CF-06 | GPS 数据保护 | Task 4.3 test_overwrite_gps_flag | Round 4 |
| BF-01 | 参数配置 | Task 1.2 MatcherConfig + Task 5.2 config_panel | Round 1+5 |
| BF-02 | 进度反馈 | Task 4.3 callbacks + Task 5.1 Worker + Task 5.2 progress_panel | Round 4+5 |
| BF-03 | 结果报告 | Task 4.3 BatchResult + Task 5.2 result_table | Round 4+5 |
| BF-04 | 容错处理 | Task 4.3 error strategy tests | Round 4 |
| BF-05 | 日志系统 | Task 4.2 OperationLogger | Round 4 |
| EF-01 | GPS 线性插值 | Task 2.1 GPSMatcher interpolation | Round 2 |
