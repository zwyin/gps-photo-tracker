# Round 1: 项目骨架 + Models + Exceptions + GPXParser

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立项目基础结构，完成数据模型、异常体系、GPX 解析器，TDD 验证通过。

**Architecture:** src layout，core 层无 IO 依赖，所有数据结构用 dataclass。

**Tech Stack:** Python 3.11+, gpxpy, pytest

---

### Task 1: 项目骨架和 pyproject.toml

**Files:**
- Create: `pyproject.toml`
- Create: `src/gps_photo_tracker/__init__.py`
- Create: `src/gps_photo_tracker/__main__.py`
- Create: `src/gps_photo_tracker/core/__init__.py`
- Create: `src/gps_photo_tracker/service/__init__.py`
- Create: `src/gps_photo_tracker/gui/__init__.py`
- Create: `src/gps_photo_tracker/logging_/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`

- [x] **Step 1:** 创建目录结构 `src/gps_photo_tracker/{core,service,gui,logging_}` + `tests/{unit,integration,batch}`
- [x] **Step 2:** 编写 pyproject.toml（依赖、pytest 配置、coverage 配置）
- [x] **Step 3:** 创建各 `__init__.py`（core/service/gui/logging_ 为空文件，包根写 `__version__`）
- [x] **Step 4:** 创建 `__main__.py`（入口函数 main → 调用 GUI run_app）
- [x] **Step 5:** `pip install -e ".[dev]"` 验证安装成功

### Task 2: models.py — 数据模型和异常

**Files:**
- Create: `src/gps_photo_tracker/core/models.py`
- Test: 隐式验证（被后续所有测试引用）

**内容：**
- 异常体系：GPSTrackerError 基类 + 6 个子类（GPXParseError, EXIFReadError, EXIFWriteError, MatchingError, OperationCancelledError, FileAccessError 及其 3 个子类）
- 枚举：ProcessMode, ProgressPhase
- 常量：RejectReason（5 个字符串常量）
- 数据类：TrackPoint, GPXSegment, GPSInfo, PhotoInfo, MatchResult, BatchResult, MatcherConfig, ProcessOptions, ProgressUpdate

- [x] **Step 1:** 编写 models.py，包含所有异常、枚举、常量、dataclass
- [ ] **Step 2:** 验证 import 无报错（`python -c "from gps_photo_tracker.core.models import *"`）

### Task 3: GPXParser — GPX 文件解析

**Files:**
- Create: `src/gps_photo_tracker/core/gpx_parser.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_gpx_parser.py`

**接口：**
```python
class GPXParser:
    def parse_file(self, path: Path) -> list[GPXSegment]
    def parse_directory(self, dir: Path) -> list[GPXSegment]
```

**实现要点：**
- 用 gpxpy 解析，每个 `<trkseg>` 产生一个 GPXSegment
- timestamp 统一用 `utc_time.timestamp()`（不硬编码时区偏移）
- altitude：缺少 `<ele>` 时设为 None
- points 按 timestamp 排序
- parse_directory：glob *.gpx（非递归），单文件失败跳过，全部失败才抛异常

- [x] **Step 1:** 编写 gpx_parser.py 实现
- [ ] **Step 2:** 编写 tests/conftest.py（utc 时间工厂、make_point、make_segment、make_photo）
- [ ] **Step 3:** 编写 test_gpx_parser.py — 测试用例：
  - 解析单个 GPX 文件（多 track 多 segment）
  - 缺少 `<ele>` 时 altitude=None
  - 空文件返回空列表
  - 非法 GPX 抛 GPXParseError
  - parse_directory 扫描目录
  - 时间戳为 UTC（不随本地时区变化）
- [ ] **Step 4:** 运行测试 `pytest tests/unit/test_gpx_parser.py -v`
- [ ] **Step 5:** 运行覆盖率 `pytest --cov=src/gps_photo_tracker/core tests/unit/`，目标 ≥ 90%

### Task 4: 提交 Round 1

- [ ] **Step 1:** `git add` 所有新文件
- [ ] **Step 2:** `git commit -m "feat: Round 1 - project skeleton, models, exceptions, GPXParser"`

---

**Round 1 验收标准：**
- `pytest tests/unit/` 全部通过
- GPXParser 覆盖率 ≥ 90%
- `pip install -e .` 成功
- import 链路正确：`from gps_photo_tracker.core.models import MatcherConfig` 无报错

**当前状态：** Task 1 完成，Task 2 代码已写（需验证），Task 3 实现已写（需写测试）
