# EF-07: Interactive Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert a mandatory review step between GPS matching and EXIF writing, letting users skip, manually select GPS track points, or enter coordinates for failed matches.

**Architecture:** Service layer splits into match/review/write phases. New `ReviewState` data model holds user decisions. Worker emits `review_ready` signal after match; MainWindow opens `ReviewDialog`; after confirmation, Worker continues to write phase.

**Tech Stack:** Python 3.11+, PySide6, pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/gps_photo_tracker/core/models.py` | `ReviewAction`, `ReviewDecision`, `ReviewState` enums/dataclasses; `review_gps` field on `MatchResult` |
| `src/gps_photo_tracker/service/tagging_service.py` | `prepare_review()`, `apply_review()`, `write_phase()` methods; refactor `_run_pipeline` |
| `src/gps_photo_tracker/gui/review_dialog.py` | **New** — list-driven review dialog (QDialog) |
| `src/gps_photo_tracker/gui/gps_point_picker.py` | **New** — GPS track point picker sub-dialog |
| `src/gps_photo_tracker/gui/worker.py` | Split run() into match/write phases with `review_ready` signal |
| `src/gps_photo_tracker/gui/main_window.py` | `_on_done` intercepts review state, opens ReviewDialog |
| `tests/unit/test_review.py` | **New** — unit tests for ReviewState, prepare_review, apply_review |
| `tests/unit/test_review_dialog.py` | **New** — GUI tests for ReviewDialog and GPSPointPicker |
| `tests/integration/test_review_flow.py` | **New** — E2E test match→review→write |

---

### Task 1: Add review data models to core/models.py

**Files:**
- Modify: `src/gps_photo_tracker/core/models.py`
- Test: `tests/unit/test_models_fields.py` (extend existing)

- [ ] **Step 1: Write failing test for new model fields**

Add to `tests/unit/test_models_fields.py`:

```python
class TestReviewModels:

    def test_review_action_values(self):
        from gps_photo_tracker.core.models import ReviewAction
        assert ReviewAction.KEEP_SKIP.value == "keep_skip"
        assert ReviewAction.MANUAL_GPS.value == "manual_gps"
        assert ReviewAction.MANUAL_COORD.value == "manual_coord"
        assert ReviewAction.SKIP.value == "skip"

    def test_review_decision_defaults(self):
        from gps_photo_tracker.core.models import ReviewDecision, ReviewAction
        d = ReviewDecision(photo_path="/tmp/test.jpg", action=ReviewAction.SKIP)
        assert d.selected_point is None
        assert d.manual_lat is None
        assert d.manual_lon is None

    def test_review_state_defaults(self):
        from gps_photo_tracker.core.models import ReviewState
        state = ReviewState(failed_results=[])
        assert state.decisions == {}
        assert state.gps_segments == []

    def test_match_result_has_review_gps(self):
        from gps_photo_tracker.core.models import MatchResult, PhotoInfo
        photo = PhotoInfo(path=Path("/tmp/test.jpg"), filename="test.jpg",
                          timestamp=1000.0, has_gps=False)
        result = MatchResult(photo=photo, success=True)
        assert result.review_gps is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_models_fields.py::TestReviewModels -v`
Expected: FAIL — `ImportError` for `ReviewAction`

- [ ] **Step 3: Add ReviewAction, ReviewDecision, ReviewState to models.py; add review_gps to MatchResult**

In `src/gps_photo_tracker/core/models.py`:

Add `ReviewAction` enum after `RejectReason` class (after line 75):

```python
class ReviewAction(Enum):
    KEEP_SKIP = "keep_skip"
    MANUAL_GPS = "manual_gps"
    MANUAL_COORD = "manual_coord"
    SKIP = "skip"
```

Add `review_gps` field to `MatchResult` (after line 125):

```python
    review_gps: GPSInfo | None = None  # Set by apply_review if user assigns GPS
```

Insert `ReviewDecision` and `ReviewState` dataclasses after `MatchResult` (after line 126) and before `BatchResult`:

```python
@dataclass
class ReviewDecision:
    photo_path: str
    action: ReviewAction
    selected_point: TrackPoint | None = None
    manual_lat: float | None = None
    manual_lon: float | None = None


@dataclass
class ReviewState:
    failed_results: list[MatchResult]
    decisions: dict[str, ReviewDecision] = field(default_factory=dict)
    gps_segments: list[GPXSegment] = field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_models_fields.py::TestReviewModels -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `pytest tests/ -v --tb=short`
Expected: All existing tests pass

- [ ] **Step 6: Commit**

```bash
git add src/gps_photo_tracker/core/models.py tests/unit/test_models_fields.py
git commit -m "feat: add ReviewAction, ReviewDecision, ReviewState models for EF-07"
```

---

### Task 2: Add prepare_review() and apply_review() to GPSTaggingService

**Files:**
- Modify: `src/gps_photo_tracker/service/tagging_service.py`
- Test: `tests/unit/test_review.py` (new file)

- [ ] **Step 1: Write failing tests for prepare_review and apply_review**

Create `tests/unit/test_review.py`:

```python
"""Tests for review phase: prepare_review, apply_review."""

from pathlib import Path

from gps_photo_tracker.core.models import (
    GPSInfo,
    GPXSegment,
    MatcherConfig,
    MatchResult,
    PhotoInfo,
    ReviewAction,
    ReviewDecision,
    ReviewState,
    TrackPoint,
)
from gps_photo_tracker.service.tagging_service import GPSTaggingService


def _make_photo(filename: str, timestamp: float = 1000.0) -> PhotoInfo:
    return PhotoInfo(path=Path(f"/tmp/{filename}"), filename=filename,
                     timestamp=timestamp, has_gps=False)


def _make_failed_result(filename: str, reason: str = "time_diff") -> MatchResult:
    return MatchResult(photo=_make_photo(filename), success=False,
                       reject_reason=reason)


def _make_success_result(filename: str) -> MatchResult:
    return MatchResult(photo=_make_photo(filename), success=True,
                       gps=GPSInfo(latitude=25.0, longitude=100.0))


def _make_segment() -> GPXSegment:
    return GPXSegment(
        filename="track.gpx",
        start=900.0, end=1100.0,
        points=[
            TrackPoint(timestamp=950.0, latitude=25.0, longitude=100.0, altitude=100),
            TrackPoint(timestamp=1000.0, latitude=25.001, longitude=100.001, altitude=110),
            TrackPoint(timestamp=1050.0, latitude=25.002, longitude=100.002, altitude=120),
        ],
    )


class TestPrepareReview:

    def test_extracts_failed_results(self):
        service = GPSTaggingService()
        results = [_make_success_result("ok.jpg"), _make_failed_result("fail.jpg")]
        state = service.prepare_review(results, [_make_segment()])
        assert len(state.failed_results) == 1
        assert state.failed_results[0].photo.filename == "fail.jpg"

    def test_includes_gps_segments(self):
        service = GPSTaggingService()
        seg = _make_segment()
        state = service.prepare_review([], [seg])
        assert len(state.gps_segments) == 1

    def test_empty_when_all_succeed(self):
        service = GPSTaggingService()
        results = [_make_success_result("a.jpg"), _make_success_result("b.jpg")]
        state = service.prepare_review(results, [])
        assert len(state.failed_results) == 0


class TestApplyReview:

    def test_manual_gps_sets_review_gps_and_success(self):
        service = GPSTaggingService()
        seg = _make_segment()
        results = [_make_failed_result("fail.jpg")]
        state = ReviewState(
            failed_results=results,
            gps_segments=[seg],
        )
        state.decisions["/tmp/fail.jpg"] = ReviewDecision(
            photo_path="/tmp/fail.jpg",
            action=ReviewAction.MANUAL_GPS,
            selected_point=TrackPoint(timestamp=1000.0, latitude=25.001, longitude=100.001),
        )
        modified = service.apply_review(results, state)
        assert modified[0].success is True
        assert modified[0].review_gps is not None
        assert modified[0].review_gps.latitude == 25.001
        assert modified[0].review_gps.longitude == 100.001

    def test_manual_coord_sets_review_gps(self):
        service = GPSTaggingService()
        results = [_make_failed_result("fail.jpg")]
        state = ReviewState(failed_results=results)
        state.decisions["/tmp/fail.jpg"] = ReviewDecision(
            photo_path="/tmp/fail.jpg",
            action=ReviewAction.MANUAL_COORD,
            manual_lat=30.0,
            manual_lon=120.0,
        )
        modified = service.apply_review(results, state)
        assert modified[0].success is True
        assert modified[0].review_gps == GPSInfo(latitude=30.0, longitude=120.0)

    def test_skip_keeps_failure(self):
        service = GPSTaggingService()
        results = [_make_failed_result("fail.jpg")]
        state = ReviewState(failed_results=results)
        state.decisions["/tmp/fail.jpg"] = ReviewDecision(
            photo_path="/tmp/fail.jpg",
            action=ReviewAction.SKIP,
        )
        modified = service.apply_review(results, state)
        assert modified[0].success is False
        assert modified[0].review_gps is None

    def test_keep_skip_does_nothing(self):
        service = GPSTaggingService()
        results = [_make_failed_result("fail.jpg")]
        state = ReviewState(failed_results=results)
        state.decisions["/tmp/fail.jpg"] = ReviewDecision(
            photo_path="/tmp/fail.jpg",
            action=ReviewAction.KEEP_SKIP,
        )
        modified = service.apply_review(results, state)
        assert modified[0].success is False
        assert modified[0].review_gps is None

    def test_no_decision_for_photo_keeps_failure(self):
        service = GPSTaggingService()
        results = [_make_failed_result("fail.jpg")]
        state = ReviewState(failed_results=results)
        modified = service.apply_review(results, state)
        assert modified[0].success is False

    def test_manual_gps_includes_altitude(self):
        service = GPSTaggingService()
        results = [_make_failed_result("fail.jpg")]
        state = ReviewState(failed_results=results)
        state.decisions["/tmp/fail.jpg"] = ReviewDecision(
            photo_path="/tmp/fail.jpg",
            action=ReviewAction.MANUAL_GPS,
            selected_point=TrackPoint(timestamp=1000.0, latitude=25.0, longitude=100.0, altitude=500.0),
        )
        modified = service.apply_review(results, state)
        assert modified[0].review_gps.altitude == 500.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_review.py -v`
Expected: FAIL — `AttributeError` for `prepare_review`

- [ ] **Step 3: Implement prepare_review() and apply_review() in tagging_service.py**

Add imports at top of `service/tagging_service.py` (add to the existing import from models after line 25):

```python
    ReviewAction,
    ReviewDecision,
    ReviewState,
```

Add two new methods to `GPSTaggingService` after `auto_tune` (after line 47):

```python
    def prepare_review(self, results: list[MatchResult], segments: list[GPXSegment]) -> ReviewState:
        """Extract failed match results into a ReviewState for GUI review."""
        failed = [r for r in results if not r.success]
        return ReviewState(failed_results=failed, gps_segments=segments)

    def apply_review(self, results: list[MatchResult], state: ReviewState) -> list[MatchResult]:
        """Merge user review decisions back into match results."""
        for result in results:
            if result.success:
                continue
            path_str = str(result.photo.path)
            decision = state.decisions.get(path_str)
            if not decision:
                continue
            if decision.action == ReviewAction.MANUAL_GPS and decision.selected_point:
                pt = decision.selected_point
                result.review_gps = GPSInfo(
                    latitude=pt.latitude,
                    longitude=pt.longitude,
                    altitude=pt.altitude,
                )
                result.success = True
                result.method = "manual_gps"
            elif decision.action == ReviewAction.MANUAL_COORD:
                if decision.manual_lat is not None and decision.manual_lon is not None:
                    result.review_gps = GPSInfo(
                        latitude=decision.manual_lat,
                        longitude=decision.manual_lon,
                    )
                    result.success = True
                    result.method = "manual_coord"
            # KEEP_SKIP and SKIP: no change
        return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_review.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All existing tests pass

- [ ] **Step 6: Commit**

```bash
git add src/gps_photo_tracker/service/tagging_service.py tests/unit/test_review.py
git commit -m "feat: add prepare_review and apply_review to GPSTaggingService"
```

---

### Task 3: Add write_phase() to GPSTaggingService

**Files:**
- Modify: `src/gps_photo_tracker/service/tagging_service.py`
- Modify: `tests/unit/test_review.py`

This method extracts write logic so it can be called after review. Uses `review_gps` when set.

- [ ] **Step 1: Write failing test for write_phase with review_gps**

Add to `tests/unit/test_review.py`:

```python
class TestWritePhaseWithReviewGPS:

    def test_write_phase_uses_review_gps(self, tmp_path):
        """write_phase should use review_gps when set, overriding gps."""
        service = GPSTaggingService()
        from PIL import Image
        img = Image.new("RGB", (10, 10))
        img.save(tmp_path / "test.jpg", "JPEG")

        result = MatchResult(
            photo=PhotoInfo(path=tmp_path / "test.jpg", filename="test.jpg",
                            timestamp=1000.0, has_gps=False),
            success=True,
            gps=GPSInfo(latitude=0.0, longitude=0.0),
            review_gps=GPSInfo(latitude=39.9, longitude=116.4),
            method="manual_coord",
        )
        options = ProcessOptions(mode=ProcessMode.OVERWRITE)
        batch = service.write_phase([result], options)
        assert batch.matched == 1
        from gps_photo_tracker.core.exif_writer import EXIFWriter
        written = EXIFWriter.read_gps(tmp_path / "test.jpg")
        assert written is not None
        assert abs(written.latitude - 39.9) < 0.01
        assert abs(written.longitude - 116.4) < 0.01

    def test_write_phase_skips_failed(self, tmp_path):
        service = GPSTaggingService()
        result = _make_failed_result("fail.jpg")
        options = ProcessOptions(mode=ProcessMode.OVERWRITE)
        batch = service.write_phase([result], options)
        assert batch.matched == 0
        assert batch.failed == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_review.py::TestWritePhaseWithReviewGPS -v`
Expected: FAIL — `AttributeError` for `write_phase`

- [ ] **Step 3: Implement write_phase() in tagging_service.py**

Add `write_phase` method to `GPSTaggingService` after `apply_review`. This method uses `review_gps` when set, otherwise `gps`:

```python
    def write_phase(
        self,
        results: list[MatchResult],
        options: ProcessOptions,
        photo_dir: Path | None = None,
        on_progress: Callable | None = None,
        on_photo_processed: Callable | None = None,
        cancel: CancellationToken | None = None,
    ) -> BatchResult:
        """Write GPS data for matched/reviewed photos. Uses review_gps when set."""
        start = time.time()
        is_preview = options.mode == ProcessMode.PREVIEW
        is_copy = options.mode == ProcessMode.COPY
        matched = 0
        skipped = 0
        failed = 0
        overwritten = 0
        reject_groups: dict[str, list[str]] = {}

        for i, result in enumerate(results):
            if cancel and cancel.is_cancelled:
                break

            effective_gps = result.review_gps if result.review_gps else result.gps

            if on_progress:
                on_progress(ProgressUpdate(
                    phase=ProgressPhase.WRITING if not is_preview else ProgressPhase.MATCHING,
                    current=i + 1,
                    total=len(results),
                    current_file=result.photo.filename,
                    elapsed_seconds=time.time() - start,
                ))

            if result.success and effective_gps:
                matched += 1
                if not is_preview:
                    write_result = MatchResult(
                        photo=result.photo, success=True, gps=effective_gps,
                        method=result.method, time_diff=result.time_diff,
                    )
                    if self._should_write(write_result, options):
                        if result.photo.has_gps:
                            overwritten += 1
                        try:
                            dst = self._write_photo(write_result, options, photo_dir)
                            if self._op_logger:
                                self._op_logger.log_write_success(result.photo, effective_gps, dest=dst)
                        except Exception as e:
                            failed += 1
                            matched -= 1
                            if self._op_logger:
                                self._op_logger.log_error(f"write: {result.photo.filename}", e)
                            if is_copy and options.output_dir:
                                try:
                                    dst = self._copy_destination(result.photo.path, options, photo_dir)
                                    self._file_provider.copy_file(result.photo.path, dst)
                                except Exception as copy_err:
                                    if self._op_logger:
                                        self._op_logger.log_error(f"copy_fallback: {result.photo.filename}", copy_err)
                    else:
                        skipped += 1
                        if is_copy and options.output_dir:
                            dst = self._copy_destination(result.photo.path, options, photo_dir)
                            self._file_provider.copy_file(result.photo.path, dst)
            else:
                failed += 1
                reason = result.reject_reason or "unknown"
                reject_groups.setdefault(reason, []).append(result.photo.filename)
                if is_copy and options.output_dir:
                    dst = self._copy_destination(result.photo.path, options, photo_dir)
                    self._file_provider.copy_file(result.photo.path, dst)

            if on_photo_processed:
                on_photo_processed(result)

        elapsed = time.time() - start
        success_rate = matched / len(results) if results else 0.0
        return BatchResult(
            total=len(results),
            matched=matched,
            skipped=skipped,
            failed=failed,
            overwritten=overwritten,
            success_rate=success_rate,
            results=results,
            reject_groups=reject_groups,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_review.py::TestWritePhaseWithReviewGPS -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/gps_photo_tracker/service/tagging_service.py tests/unit/test_review.py
git commit -m "feat: add write_phase method with review_gps support"
```

---

### Task 4: Update Worker to emit review_ready signal

**Files:**
- Modify: `src/gps_photo_tracker/gui/worker.py`
- Test: `tests/unit/test_review.py` (extend)

- [ ] **Step 1: Write failing test for Worker review flow**

Add to `tests/unit/test_review.py`:

```python
class TestWorkerReviewSignal:

    def test_worker_emits_review_ready_on_failure(self, qtbot, tmp_path):
        """Worker should emit review_ready when preview finds failures."""
        import textwrap
        from gps_photo_tracker.gui.worker import Worker
        from gps_photo_tracker.core.models import ProcessMode, ProcessOptions, MatcherConfig
        from PIL import Image
        import piexif

        gpx = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>
            <trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:05:00Z</time></trkpt>
          </trkseg></trk>
        </gpx>
        """)
        (tmp_path / "track.gpx").write_text(gpx)

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 20:00:00"}}
        img.save(tmp_path / "photo.jpg", "JPEG", exif=piexif.dump(exif))

        options = ProcessOptions(mode=ProcessMode.PREVIEW)
        config = MatcherConfig()
        worker = Worker(
            gps_dir=tmp_path, photo_dir=tmp_path,
            config=config, options=options,
        )

        signals = []
        worker.review_ready_signal.connect(lambda s: signals.append(s))

        with qtbot.waitSignal(worker.done_signal, timeout=10000):
            worker.run()

        assert len(signals) == 1
        assert len(signals[0]["failed_results"]) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_review.py::TestWorkerReviewSignal -v`
Expected: FAIL — `AttributeError` for `review_ready_signal`

- [ ] **Step 3: Add review_ready_signal to Worker and update run()**

In `src/gps_photo_tracker/gui/worker.py`:

Add `ReviewState` to the models import.

Add new signal after existing signals (line 25):

```python
    review_ready_signal = Signal(dict)  # ReviewState serialized as dict
```

In `run()`, after the main preview/process call succeeds, before emitting `done_signal`, add review check logic. Find the block that emits `done_signal` (starting around line 185) and insert before it:

```python
            # Check for failures needing review (PREVIEW mode only)
            failed_results = [r for r in result.results if not r.success]
            if failed_results and self._options.mode == ProcessMode.PREVIEW:
                review_state = service.prepare_review(result.results, segments)
                self.review_ready_signal.emit({
                    "failed_results": [
                        {
                            "photo_path": str(r.photo.path),
                            "filename": r.photo.filename,
                            "timestamp": r.photo.timestamp,
                            "reject_reason": r.reject_reason,
                            "time_diff": r.time_diff,
                        }
                        for r in review_state.failed_results
                    ],
                    "gps_segments": [
                        {
                            "filename": s.filename,
                            "start": s.start,
                            "end": s.end,
                            "points": [
                                {"timestamp": p.timestamp, "latitude": p.latitude,
                                 "longitude": p.longitude, "altitude": p.altitude}
                                for p in s.points
                            ],
                        }
                        for s in review_state.gps_segments
                    ],
                    "total": result.total,
                    "matched": result.matched,
                    "failed": result.failed,
                })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_review.py::TestWorkerReviewSignal -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/gps_photo_tracker/gui/worker.py tests/unit/test_review.py
git commit -m "feat: Worker emits review_ready_signal on preview failures"
```

---

### Task 5: Create GPSPointPicker dialog

**Files:**
- Create: `src/gps_photo_tracker/gui/gps_point_picker.py`
- Test: `tests/unit/test_review_dialog.py` (new file)

- [ ] **Step 1: Write failing tests for GPSPointPicker**

Create `tests/unit/test_review_dialog.py`:

```python
"""Tests for GPSPointPicker and ReviewDialog GUI components."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gps_photo_tracker.core.models import TrackPoint


@pytest.fixture
def app(qtbot):
    return QApplication.instance() or QApplication([])


class TestGPSPointPicker:

    def test_populates_track_points(self, app, qtbot):
        from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker
        points = [
            TrackPoint(timestamp=1000.0, latitude=25.0, longitude=100.0, altitude=100),
            TrackPoint(timestamp=1050.0, latitude=25.001, longitude=100.001, altitude=110),
        ]
        picker = GPSPointPicker(points, photo_timestamp=1025.0)
        qtbot.addWidget(picker)
        assert picker._table.rowCount() == 2

    def test_confirm_returns_selected_point(self, app, qtbot):
        from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker
        points = [
            TrackPoint(timestamp=1000.0, latitude=25.0, longitude=100.0, altitude=100),
            TrackPoint(timestamp=1050.0, latitude=25.001, longitude=100.001, altitude=110),
        ]
        picker = GPSPointPicker(points, photo_timestamp=1025.0)
        qtbot.addWidget(picker)
        picker._table.selectRow(0)
        result = picker.get_selected_point()
        assert result is not None
        assert result.latitude == 25.0

    def test_no_selection_returns_none(self, app, qtbot):
        from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker
        points = [
            TrackPoint(timestamp=1000.0, latitude=25.0, longitude=100.0),
        ]
        picker = GPSPointPicker(points, photo_timestamp=1000.0)
        qtbot.addWidget(picker)
        picker._table.clearSelection()
        assert picker.get_selected_point() is None

    def test_empty_points_disables_confirm(self, app, qtbot):
        from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker
        picker = GPSPointPicker([], photo_timestamp=1000.0)
        qtbot.addWidget(picker)
        assert not picker._confirm_btn.isEnabled()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_review_dialog.py::TestGPSPointPicker -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement GPSPointPicker**

Create `src/gps_photo_tracker/gui/gps_point_picker.py`:

```python
"""GPS track point picker dialog for manual GPS assignment."""

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QDialogButtonBox,
)

from gps_photo_tracker.core.models import TrackPoint


class GPSPointPicker(QDialog):
    """Dialog to pick a GPS track point near a photo's capture time."""

    def __init__(self, points: list[TrackPoint], photo_timestamp: float, parent=None):
        super().__init__(parent)
        self._points = points
        self._photo_timestamp = photo_timestamp
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("选择 GPS 轨迹点")
        self.setMinimumSize(500, 350)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            f"拍摄时间: {self._format_time(self._photo_timestamp)}  |  "
            f"共 {len(self._points)} 个附近轨迹点"
        ))

        self._table = QTableWidget(len(self._points), 4)
        self._table.setHorizontalHeaderLabels(["时间", "纬度", "经度", "时间差"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        for row, pt in enumerate(self._points):
            self._table.setItem(row, 0, QTableWidgetItem(self._format_time(pt.timestamp)))
            self._table.setItem(row, 1, QTableWidgetItem(f"{pt.latitude:.6f}"))
            self._table.setItem(row, 2, QTableWidgetItem(f"{pt.longitude:.6f}"))
            diff = abs(pt.timestamp - self._photo_timestamp)
            mins, secs = divmod(int(diff), 60)
            self._table.setItem(row, 3, QTableWidgetItem(
                f"{mins}m{secs:02d}s" if mins > 0 else f"{secs}s"
            ))

        self._table.selectRow(0)
        layout.addWidget(self._table)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._confirm_btn = btn_box.button(QDialogButtonBox.StandardButton.Ok)
        self._confirm_btn.setText("确认选择")
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self._confirm_btn.setEnabled(len(self._points) > 0)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_selected_point(self) -> TrackPoint | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._points[rows[0].row()]

    @staticmethod
    def _format_time(ts: float) -> str:
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")
        except (OSError, ValueError):
            return str(ts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_review_dialog.py::TestGPSPointPicker -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/gps_photo_tracker/gui/gps_point_picker.py tests/unit/test_review_dialog.py
git commit -m "feat: add GPSPointPicker dialog for manual GPS selection"
```

---

### Task 6: Create ReviewDialog

**Files:**
- Create: `src/gps_photo_tracker/gui/review_dialog.py`
- Modify: `tests/unit/test_review_dialog.py`

- [ ] **Step 1: Write failing tests for ReviewDialog**

Add to `tests/unit/test_review_dialog.py` (after `TestGPSPointPicker`):

```python
from pathlib import Path
from gps_photo_tracker.core.models import (
    GPSInfo, GPXSegment, MatchResult, PhotoInfo,
    ReviewAction, ReviewDecision, ReviewState,
)


def _make_failed_result(filename: str, reason: str = "time_diff") -> MatchResult:
    return MatchResult(
        photo=PhotoInfo(path=Path(f"/tmp/{filename}"), filename=filename,
                        timestamp=1000.0, has_gps=False),
        success=False, reject_reason=reason,
    )


def _make_review_state():
    seg = GPXSegment(
        filename="track.gpx", start=900.0, end=1100.0,
        points=[
            TrackPoint(timestamp=950.0, latitude=25.0, longitude=100.0, altitude=100),
            TrackPoint(timestamp=1000.0, latitude=25.001, longitude=100.001, altitude=110),
        ],
    )
    return ReviewState(
        failed_results=[_make_failed_result("fail1.jpg"), _make_failed_result("fail2.jpg")],
        gps_segments=[seg],
    )


class TestReviewDialog:

    def test_table_shows_all_failures(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        assert dialog._table.rowCount() == 2

    def test_skip_all_sets_skip_decisions(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._skip_all()
        assert len(dialog._state.decisions) == 2
        for d in dialog._state.decisions.values():
            assert d.action == ReviewAction.SKIP

    def test_confirm_with_no_decisions_treated_as_skip(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._confirm()
        for d in dialog._state.decisions.values():
            assert d.action == ReviewAction.SKIP

    def test_get_state_returns_review_state(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        assert dialog.get_state() is state
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_review_dialog.py::TestReviewDialog -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement ReviewDialog**

Create `src/gps_photo_tracker/gui/review_dialog.py`:

```python
"""Review dialog for failed GPS matches — list-driven layout."""

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QComboBox, QHeaderView, QGroupBox, QCheckBox,
    QSplitter, QMessageBox, QDialogButtonBox, QWidget, QInputDialog,
)

from gps_photo_tracker.core.models import (
    ReviewAction, ReviewDecision, ReviewState, TrackPoint,
)
from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker

_REASON_LABELS = {
    "no_gps_coverage": "无 GPS 覆盖",
    "time_diff": "时间差过大",
    "gps_distance": "距离过大",
    "tail_isolated": "孤立照片",
    "no_track_points": "无轨迹点",
}


class ReviewDialog(QDialog):
    """Review failed GPS matches and assign manual GPS or skip."""

    def __init__(self, state: ReviewState, parent=None):
        super().__init__(parent)
        self._state = state
        self._action_combos: list[QComboBox] = []
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle(f"审核失败项 — 共 {len(self._state.failed_results)} 张")
        self.setMinimumSize(900, 500)
        main_layout = QVBoxLayout(self)

        # Top bar
        top_bar = QHBoxLayout()
        self._select_all_cb = QCheckBox("全选")
        self._select_all_cb.setChecked(True)
        self._select_all_cb.stateChanged.connect(self._on_select_all)
        top_bar.addWidget(self._select_all_cb)
        top_bar.addStretch()
        skip_all_btn = QPushButton("全部跳过")
        skip_all_btn.clicked.connect(self._skip_all)
        top_bar.addWidget(skip_all_btn)
        main_layout.addLayout(top_bar)

        # Splitter: table | detail panel
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: table
        self._table = QTableWidget(len(self._state.failed_results), 5)
        self._table.setHorizontalHeaderLabels(["☑", "文件名", "拍摄时间", "失败原因", "操作"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.cellClicked.connect(self._on_row_clicked)

        for row, result in enumerate(self._state.failed_results):
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.addWidget(checkbox)
            cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self._table.setCellWidget(row, 0, cb_widget)

            self._table.setItem(row, 1, QTableWidgetItem(result.photo.filename))
            self._table.setItem(row, 2, QTableWidgetItem(self._format_time(result.photo.timestamp)))
            reason = result.reject_reason or "unknown"
            self._table.setItem(row, 3, QTableWidgetItem(
                _REASON_LABELS.get(reason, reason)
            ))

            combo = QComboBox()
            combo.addItems(["待定", "跳过", "手动选 GPS", "输入坐标"])
            combo.currentIndexChanged.connect(lambda idx, r=row: self._on_action_changed(r, idx))
            self._table.setCellWidget(row, 4, combo)
            self._action_combos.append(combo)

        splitter.addWidget(self._table)

        # Right: detail panel
        detail_panel = QVBoxLayout()
        self._preview_label = QLabel("点击左侧照片查看预览")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumSize(180, 140)
        detail_panel.addWidget(self._preview_label)

        self._info_label = QLabel("")
        self._info_label.setWordWrap(True)
        detail_panel.addWidget(self._info_label)

        batch_group = QGroupBox("批量操作（已选照片）")
        batch_layout = QHBoxLayout(batch_group)
        batch_skip_btn = QPushButton("跳过")
        batch_skip_btn.clicked.connect(lambda: self._batch_action(1))
        batch_layout.addWidget(batch_skip_btn)
        batch_gps_btn = QPushButton("手动选 GPS")
        batch_gps_btn.clicked.connect(lambda: self._batch_action(2))
        batch_layout.addWidget(batch_gps_btn)
        batch_coord_btn = QPushButton("输入坐标")
        batch_coord_btn.clicked.connect(lambda: self._batch_action(3))
        batch_layout.addWidget(batch_coord_btn)
        detail_panel.addWidget(batch_group)
        detail_panel.addStretch()

        right_widget = QWidget()
        right_widget.setLayout(detail_panel)
        splitter.addWidget(right_widget)
        splitter.setSizes([600, 300])
        main_layout.addWidget(splitter)

        # Bottom bar
        bottom_bar = QHBoxLayout()
        self._progress_label = QLabel(f"已处理 0/{len(self._state.failed_results)}")
        bottom_bar.addWidget(self._progress_label)
        bottom_bar.addStretch()
        confirm_btn = QPushButton("确认")
        confirm_btn.clicked.connect(self._confirm)
        bottom_bar.addWidget(confirm_btn)
        main_layout.addLayout(bottom_bar)

    def get_state(self) -> ReviewState:
        return self._state

    def _skip_all(self):
        for result in self._state.failed_results:
            path_str = str(result.photo.path)
            self._state.decisions[path_str] = ReviewDecision(
                photo_path=path_str, action=ReviewAction.SKIP,
            )
        self.accept()

    def _confirm(self):
        for row, result in enumerate(self._state.failed_results):
            path_str = str(result.photo.path)
            if path_str in self._state.decisions:
                continue
            combo_idx = self._action_combos[row].currentIndex()
            if combo_idx == 0:
                self._state.decisions[path_str] = ReviewDecision(
                    photo_path=path_str, action=ReviewAction.SKIP,
                )
            elif combo_idx == 1:
                self._state.decisions[path_str] = ReviewDecision(
                    photo_path=path_str, action=ReviewAction.SKIP,
                )
            # combo_idx 2 and 3 are handled in _on_action_changed
        self.accept()

    def _on_row_clicked(self, row, col):
        result = self._state.failed_results[row]
        reason = result.reject_reason or "未知"
        info = f"<b>文件:</b> {result.photo.filename}<br>"
        info += f"<b>拍摄时间:</b> {self._format_time(result.photo.timestamp)}<br>"
        info += f"<b>失败原因:</b> {_REASON_LABELS.get(reason, reason)}<br>"
        if result.time_diff is not None:
            info += f"<b>时间差:</b> {result.time_diff:.0f}s"
        self._info_label.setText(info)
        try:
            pixmap = QPixmap(str(result.photo.path))
            if not pixmap.isNull():
                self._preview_label.setPixmap(
                    pixmap.scaled(180, 140, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
                )
        except Exception:
            self._preview_label.setText("无法加载预览")

    def _on_action_changed(self, row: int, combo_idx: int):
        result = self._state.failed_results[row]
        path_str = str(result.photo.path)
        if combo_idx == 1:
            self._state.decisions[path_str] = ReviewDecision(
                photo_path=path_str, action=ReviewAction.SKIP,
            )
        elif combo_idx == 2:
            self._open_gps_picker(row)
        elif combo_idx == 3:
            self._open_coord_input(row)
        self._update_progress()

    def _open_gps_picker(self, row: int):
        result = self._state.failed_results[row]
        nearby = self._get_nearby_points(result.photo.timestamp or 0, window=1800)
        if not nearby:
            QMessageBox.information(self, "无轨迹点", "拍摄时间附近 30 分钟内无 GPS 轨迹点")
            self._action_combos[row].setCurrentIndex(0)
            return
        picker = GPSPointPicker(nearby, result.photo.timestamp or 0, self)
        if picker.exec() == QDialog.DialogCode.Accepted:
            pt = picker.get_selected_point()
            if pt:
                path_str = str(result.photo.path)
                self._state.decisions[path_str] = ReviewDecision(
                    photo_path=path_str,
                    action=ReviewAction.MANUAL_GPS,
                    selected_point=pt,
                )
        else:
            self._action_combos[row].setCurrentIndex(0)

    def _open_coord_input(self, row: int):
        result = self._state.failed_results[row]
        lat_str, ok1 = QInputDialog.getText(self, "输入纬度", "纬度 (-90 ~ 90):")
        if not ok1:
            self._action_combos[row].setCurrentIndex(0)
            return
        lon_str, ok2 = QInputDialog.getText(self, "输入经度", "经度 (-180 ~ 180):")
        if not ok2:
            self._action_combos[row].setCurrentIndex(0)
            return
        try:
            lat = float(lat_str)
            lon = float(lon_str)
        except ValueError:
            QMessageBox.warning(self, "格式错误", "请输入有效的数字")
            self._action_combos[row].setCurrentIndex(0)
            return
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            QMessageBox.warning(self, "范围错误", "纬度 -90~90，经度 -180~180")
            self._action_combos[row].setCurrentIndex(0)
            return
        path_str = str(result.photo.path)
        self._state.decisions[path_str] = ReviewDecision(
            photo_path=path_str,
            action=ReviewAction.MANUAL_COORD,
            manual_lat=lat,
            manual_lon=lon,
        )

    def _batch_action(self, combo_idx: int):
        for row in range(len(self._state.failed_results)):
            cb_widget = self._table.cellWidget(row, 0)
            checkbox = cb_widget.findChild(QCheckBox) if cb_widget else None
            if checkbox and checkbox.isChecked():
                self._action_combos[row].setCurrentIndex(combo_idx)
        self._update_progress()

    def _on_select_all(self, state):
        checked = state == Qt.CheckState.Checked.value
        for row in range(len(self._state.failed_results)):
            cb_widget = self._table.cellWidget(row, 0)
            checkbox = cb_widget.findChild(QCheckBox) if cb_widget else None
            if checkbox:
                checkbox.setChecked(checked)

    def _get_nearby_points(self, photo_ts: float, window: float = 1800) -> list[TrackPoint]:
        points = []
        for seg in self._state.gps_segments:
            for pt in seg.points:
                if abs(pt.timestamp - photo_ts) <= window:
                    points.append(pt)
        points.sort(key=lambda p: abs(p.timestamp - photo_ts))
        return points

    def _update_progress(self):
        total = len(self._state.failed_results)
        decided = len(self._state.decisions)
        self._progress_label.setText(f"已处理 {decided}/{total}")

    @staticmethod
    def _format_time(ts: float | None) -> str:
        if ts is None:
            return "—"
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")
        except (OSError, ValueError):
            return str(ts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_review_dialog.py::TestReviewDialog -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/gps_photo_tracker/gui/review_dialog.py tests/unit/test_review_dialog.py
git commit -m "feat: add ReviewDialog with list-driven review layout"
```

---

### Task 7: Integrate ReviewDialog into MainWindow

**Files:**
- Modify: `src/gps_photo_tracker/gui/main_window.py`

- [ ] **Step 1: Add imports**

Add to existing imports in `main_window.py`:

```python
from gps_photo_tracker.core.models import MatcherConfig, ProcessMode, ProcessOptions, ReviewAction, ReviewDecision, ReviewState
from gps_photo_tracker.gui.review_dialog import ReviewDialog
```

Note: `MatcherConfig`, `ProcessMode`, `ProcessOptions` are already imported — just add the review-related ones.

- [ ] **Step 2: Initialize review state in __init__**

In `MainWindow.__init__`, add after existing `self._` initialization (around line 77):

```python
        self._review_decisions: dict = {}
        self._reviewed_results: list = []
```

- [ ] **Step 3: Connect review_ready_signal in _on_start**

In `_on_start`, after the line `self._worker.photos_scanned_signal.connect(self._on_photos_scanned)`, add:

```python
        self._worker.review_ready_signal.connect(self._on_review_ready)
```

- [ ] **Step 4: Add _on_review_ready method**

Add new method before `_on_done` (around line 487):

```python
    def _on_review_ready(self, review_data: dict):
        """Handle review_ready_signal: show ReviewDialog for failed matches."""
        failed_results = []
        for fr in review_data.get("failed_results", []):
            photo = PhotoInfo(
                path=Path(fr["photo_path"]),
                filename=fr["filename"],
                timestamp=fr.get("timestamp"),
                has_gps=False,
            )
            result = MatchResult(
                photo=photo, success=False,
                reject_reason=fr.get("reject_reason"),
                time_diff=fr.get("time_diff"),
            )
            failed_results.append(result)

        segments = []
        for sd in review_data.get("gps_segments", []):
            from gps_photo_tracker.core.models import TrackPoint, GPXSegment
            points = [
                TrackPoint(
                    timestamp=p["timestamp"],
                    latitude=p["latitude"],
                    longitude=p["longitude"],
                    altitude=p.get("altitude"),
                )
                for p in sd.get("points", [])
            ]
            segments.append(GPXSegment(
                filename=sd["filename"],
                start=sd["start"],
                end=sd["end"],
                points=points,
            ))

        state = ReviewState(failed_results=failed_results, gps_segments=segments)
        dialog = ReviewDialog(state, self)
        dialog.exec()

        reviewed_state = dialog.get_state()
        if reviewed_state.decisions:
            self._review_decisions = reviewed_state.decisions
            self._reviewed_results = failed_results
            manual_count = sum(
                1 for d in reviewed_state.decisions.values()
                if d.action in (ReviewAction.MANUAL_GPS, ReviewAction.MANUAL_COORD)
            )
            skip_count = sum(
                1 for d in reviewed_state.decisions.values()
                if d.action in (ReviewAction.SKIP, ReviewAction.KEEP_SKIP)
            )
            self.statusBar().showMessage(
                f"审核完成: {manual_count} 张手动指定, {skip_count} 张跳过"
            )
```

Also add `from gps_photo_tracker.core.models import TrackPoint, GPXSegment` to the imports at the top of the file (or use local imports inside the method as shown).

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/gps_photo_tracker/gui/main_window.py
git commit -m "feat: integrate ReviewDialog into MainWindow workflow"
```

---

### Task 8: Integration test — end-to-end review flow

**Files:**
- Create: `tests/integration/test_review_flow.py`

- [ ] **Step 1: Write integration test**

Create `tests/integration/test_review_flow.py`:

```python
"""Integration test: match -> review -> apply -> write flow."""

import textwrap
from pathlib import Path

import piexif
from PIL import Image

from gps_photo_tracker.core.models import (
    GPSInfo, GPXSegment, MatcherConfig, MatchResult, PhotoInfo,
    ProcessMode, ProcessOptions, ReviewAction, ReviewDecision, ReviewState,
    TrackPoint,
)
from gps_photo_tracker.service.tagging_service import GPSTaggingService


def _create_test_photo(path: Path, dt_bytes: bytes = b"2026:02:17 20:00:00"):
    img = Image.new("RGB", (10, 10))
    exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: dt_bytes}}
    img.save(path, "JPEG", exif=piexif.dump(exif))


def _create_test_gpx(path: Path):
    gpx = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
      <trk><trkseg>
        <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>
        <trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:05:00Z</time></trkpt>
      </trkseg></trk>
    </gpx>
    """)
    path.write_text(gpx)


class TestReviewFlow:

    def test_full_review_flow_manual_gps(self, tmp_path):
        _create_test_gpx(tmp_path / "track.gpx")
        _create_test_photo(tmp_path / "photo.jpg")

        service = GPSTaggingService()
        segments = service.scan_gpx(tmp_path)
        photos = service.scan_photos(tmp_path)
        config = MatcherConfig()

        result = service.preview(segments, photos, config)
        assert result.failed > 0

        state = service.prepare_review(result.results, segments)
        assert len(state.failed_results) > 0

        failed_photo = state.failed_results[0]
        state.decisions[str(failed_photo.photo.path)] = ReviewDecision(
            photo_path=str(failed_photo.photo.path),
            action=ReviewAction.MANUAL_GPS,
            selected_point=TrackPoint(timestamp=1000.0, latitude=25.0, longitude=100.0),
        )
        modified = service.apply_review(result.results, state)
        assert modified[0].success is True
        assert modified[0].review_gps is not None

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output_dir)
        batch = service.write_phase(modified, options, photo_dir=tmp_path)
        assert batch.matched >= 1

        from gps_photo_tracker.core.exif_writer import EXIFWriter
        output_photo = output_dir / "photo.jpg"
        assert output_photo.exists()
        written_gps = EXIFWriter.read_gps(output_photo)
        assert written_gps is not None
        assert abs(written_gps.latitude - 25.0) < 0.01

    def test_full_review_flow_skip(self, tmp_path):
        _create_test_gpx(tmp_path / "track.gpx")
        _create_test_photo(tmp_path / "photo.jpg")

        service = GPSTaggingService()
        segments = service.scan_gpx(tmp_path)
        photos = service.scan_photos(tmp_path)
        config = MatcherConfig()

        result = service.preview(segments, photos, config)
        state = service.prepare_review(result.results, segments)

        failed_photo = state.failed_results[0]
        state.decisions[str(failed_photo.photo.path)] = ReviewDecision(
            photo_path=str(failed_photo.photo.path),
            action=ReviewAction.SKIP,
        )
        modified = service.apply_review(result.results, state)
        assert modified[0].success is False

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output_dir)
        batch = service.write_phase(modified, options, photo_dir=tmp_path)
        assert batch.matched == 0
        assert batch.failed >= 1
        assert (output_dir / "photo.jpg").exists()
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/integration/test_review_flow.py -v`
Expected: All PASS

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_review_flow.py
git commit -m "test: add integration test for match-review-write flow"
```

---

### Task 9: Version bump and CHANGELOG

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/gps_photo_tracker/__init__.py`
- Modify: `gps-photo-tracker.spec`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Bump version from 0.8.1 to 0.9.0**

In `pyproject.toml`, change `version = "0.8.1"` to `version = "0.9.0"`.

In `src/gps_photo_tracker/__init__.py`, change `__version__ = "0.8.1"` to `__version__ = "0.9.0"`.

In `gps-photo-tracker.spec`, update version reference if present.

- [ ] **Step 2: Update CHANGELOG.md**

Add new section at top:

```markdown
## [0.9.0] - 2026-05-15

### Added

- EF-07: Interactive review dialog for failed GPS matches
  - Auto-popup after Preview when failures detected
  - Manual GPS track point selection
  - Manual coordinate input with validation
  - Batch skip/select operations
  - GPSPointPicker sub-dialog for nearby track points
- Service layer split: match -> review -> write phases
- ReviewState data model for user decisions

[0.9.0]: https://github.com/zwyin/gps-photo-tracker-claude/releases/tag/v0.9.0
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml src/gps_photo_tracker/__init__.py gps-photo-tracker.spec CHANGELOG.md
git commit -m "chore: bump version 0.8.1 -> 0.9.0 with EF-07 interactive review"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** Task 1-3 cover data models + service methods; Task 4 covers Worker; Task 5-6 cover GUI; Task 7 covers MainWindow integration; Task 8 covers E2E; Task 9 covers version/docs.
- [x] **Placeholder scan:** No TBD/TODO. All code blocks contain complete implementations.
- [x] **Type consistency:** `ReviewAction`, `ReviewDecision`, `ReviewState`, `review_gps` field used consistently. `photo_path` is `str(result.photo.path)` throughout. Method signatures match definition and usage.
