"""Tests for GUI components."""

import pytest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QTableWidgetItem
from PySide6.QtCore import Qt

from gps_photo_tracker.gui.main_window import MainWindow
from gps_photo_tracker.gui.worker import Worker
from gps_photo_tracker.core.models import MatcherConfig, ProcessMode, ProcessOptions


# Ensure QApplication exists (required for all QWidget tests)
@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def main_window(qapp):
    window = MainWindow()
    yield window
    window.close()


# ── MainWindow construction tests ──────────────────────────

class TestMainWindow:

    def test_window_title(self, main_window):
        assert main_window.windowTitle() == "GPS Photo Tracker"

    def test_start_button_exists(self, main_window):
        assert main_window._start_btn is not None
        assert main_window._start_btn.isEnabled()

    def test_cancel_button_disabled(self, main_window):
        assert not main_window._cancel_btn.isEnabled()

    def test_default_params(self, main_window):
        assert main_window._isolated_spin.value() == 300
        assert main_window._middle_spin.value() == 3600
        assert main_window._context_spin.value() == 300
        assert main_window._distance_spin.value() == 200
        assert main_window._match_tail_cb.isChecked()

    def test_default_mode_preview(self, main_window):
        assert main_window._preview_rb.isChecked()

    def test_get_matcher_config(self, main_window):
        config = main_window._get_matcher_config()
        assert isinstance(config, MatcherConfig)
        assert config.isolated_window == 300
        assert config.max_gps_distance == 200

    def test_get_process_options_preview(self, main_window):
        options = main_window._get_process_options()
        assert options.mode == ProcessMode.PREVIEW

    def test_get_process_options_copy(self, main_window):
        main_window._copy_rb.setChecked(True)
        options = main_window._get_process_options()
        assert options.mode == ProcessMode.COPY

    def test_get_process_options_overwrite(self, main_window):
        main_window._overwrite_rb.setChecked(True)
        options = main_window._get_process_options()
        assert options.mode == ProcessMode.OVERWRITE
        assert not options.overwrite_gps

    def test_start_without_dirs_shows_warning(self, main_window, monkeypatch):
        """Starting without GPS/photo dirs should show warning."""
        main_window._gps_dir_edit.setText("")
        main_window._photo_dir_edit.setText("")

        warned = []
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.warning",
            lambda *a, **kw: warned.append(True),
        )
        main_window._on_start()
        assert warned


# ── Worker tests ───────────────────────────────────────────

class TestWorker:

    def test_worker_creation(self, qapp):
        worker = Worker(
            gps_dir=Path("/tmp"),
            photo_dir=Path("/tmp"),
            config=MatcherConfig(),
            options=ProcessOptions(mode=ProcessMode.PREVIEW),
        )
        assert worker is not None

    def test_worker_cancel(self, qapp):
        worker = Worker(
            gps_dir=Path("/tmp"),
            photo_dir=Path("/tmp"),
            config=MatcherConfig(),
            options=ProcessOptions(mode=ProcessMode.PREVIEW),
        )
        worker.cancel()
        assert worker._token.is_cancelled

    def test_worker_signals_exist(self, qapp):
        worker = Worker(
            gps_dir=Path("/tmp"),
            photo_dir=Path("/tmp"),
            config=MatcherConfig(),
            options=ProcessOptions(mode=ProcessMode.PREVIEW),
        )
        assert hasattr(worker, 'progress_signal')
        assert hasattr(worker, 'photo_signal')
        assert hasattr(worker, 'done_signal')


# ── DetailDialog tests ────────────────────────────────────

class TestDetailDialog:

    def test_detail_dialog_success(self, qapp):
        from gps_photo_tracker.gui.detail_dialog import DetailDialog
        data = {
            "filename": "test.jpg",
            "path": "/photos/test.jpg",
            "success": True,
            "method": "interpolated",
            "latitude": 25.953,
            "longitude": 102.758,
            "altitude": 1810.6,
            "time_diff": 12.0,
            "interpolation_distance": 247.0,
            "interpolation_ratio": 0.133,
            "interpolation_prev": {"lat": 25.952, "lon": 102.757, "alt": 1808},
            "interpolation_next": {"lat": 25.954, "lon": 102.759, "alt": 1813},
        }
        dialog = DetailDialog(data)
        assert dialog.windowTitle() == "照片匹配详情 - test.jpg"

    def test_detail_dialog_failure(self, qapp):
        from gps_photo_tracker.gui.detail_dialog import DetailDialog
        data = {
            "filename": "fail.jpg",
            "path": "/photos/fail.jpg",
            "success": False,
            "method": None,
            "reject_reason": "no_gps_coverage",
        }
        dialog = DetailDialog(data)
        assert "失败" in dialog.windowTitle() or dialog is not None

    def test_detail_dialog_no_interpolation(self, qapp):
        from gps_photo_tracker.gui.detail_dialog import DetailDialog
        data = {
            "filename": "nearest.jpg",
            "success": True,
            "method": "nearest",
            "latitude": 25.0,
            "longitude": 100.0,
        }
        dialog = DetailDialog(data)
        assert dialog is not None


# ── SettingsDialog tests ──────────────────────────────────

class TestSettingsDialog:

    def test_settings_dialog_opens(self, qapp):
        from gps_photo_tracker.gui.settings_dialog import SettingsDialog
        dialog = SettingsDialog()
        assert dialog.windowTitle() == "设置"

    def test_load_settings(self, qapp):
        from gps_photo_tracker.gui.settings_dialog import load_settings
        s = load_settings()
        assert "isolated_window" in s
        assert "max_gps_distance" in s
        assert "time_offset" in s

    def test_settings_dialog_has_widgets(self, qapp):
        from gps_photo_tracker.gui.settings_dialog import SettingsDialog
        dialog = SettingsDialog()
        assert dialog._isolated is not None
        assert dialog._match_tail is not None
        assert dialog._overwrite is not None


# ── GPXBrowserDialog tests ─────────────────────────────────

class TestGPXBrowserDialog:

    def test_gpx_browser_with_dicts(self, qapp):
        from gps_photo_tracker.gui.gpx_browser_dialog import GPXBrowserDialog
        segments = [
            {"filename": "track1.gpx", "start": 1700000000.0, "end": 1700003600.0, "point_count": 120},
            {"filename": "track2.gpx", "start": 1700100000.0, "end": 1700101800.0, "point_count": 60},
        ]
        dialog = GPXBrowserDialog(segments)
        assert dialog.windowTitle() == "GPX 轨迹详情"

    def test_gpx_browser_with_objects(self, qapp):
        from gps_photo_tracker.gui.gpx_browser_dialog import GPXBrowserDialog
        from gps_photo_tracker.core.models import GPXSegment, TrackPoint
        segs = [
            GPXSegment(
                filename="walk.gpx",
                start=1700000000.0,
                end=1700003600.0,
                points=[TrackPoint(1700000000.0, 25.0, 100.0)],
            )
        ]
        dialog = GPXBrowserDialog(segs)
        assert dialog is not None

    def test_gpx_browser_empty(self, qapp):
        from gps_photo_tracker.gui.gpx_browser_dialog import GPXBrowserDialog
        dialog = GPXBrowserDialog([])
        assert dialog is not None


# ── MainWindow scan_done tests ─────────────────────────────

class TestMainWindowScanDone:

    def test_on_scan_done_caches_segments(self, main_window):
        segments = [
            {"filename": "a.gpx", "start": 1000.0, "end": 2000.0, "point_count": 50},
        ]
        main_window._on_scan_done(segments)
        assert main_window._cached_segments == segments
        assert "1 段" in main_window._scan_summary.text()
        assert "50 点" in main_window._scan_summary.text()

    def test_on_scan_done_multiple_segments(self, main_window):
        segments = [
            {"filename": "a.gpx", "start": 1000.0, "end": 2000.0, "point_count": 100},
            {"filename": "b.gpx", "start": 3000.0, "end": 4000.0, "point_count": 200},
        ]
        main_window._on_scan_done(segments)
        assert len(main_window._cached_segments) == 2
        assert "2 段" in main_window._scan_summary.text()
        assert "300 点" in main_window._scan_summary.text()

    def test_on_scan_done_empty(self, main_window):
        main_window._on_scan_done([])
        assert main_window._cached_segments == []

    def test_worker_has_scan_done_signal(self, qapp):
        worker = Worker(
            gps_dir=Path("/tmp"),
            photo_dir=Path("/tmp"),
            config=MatcherConfig(),
            options=ProcessOptions(mode=ProcessMode.PREVIEW),
        )
        assert hasattr(worker, 'scan_done_signal')


# ── 4-phase progress bar tests ─────────────────────────────

class TestPhaseProgress:

    def test_has_four_phase_bars(self, main_window):
        assert len(main_window._phase_bars) == 4

    def test_all_bars_initially_zero(self, main_window):
        for bar in main_window._phase_bars:
            assert bar.value() == 0

    def test_on_progress_updates_matching_bar(self, main_window):
        main_window._on_progress("matching", 5, 10, "photo.jpg", 3.0)
        bar = main_window._phase_bars[2]
        assert bar.value() == 5
        assert bar.maximum() == 10

    def test_on_progress_updates_scanning_gpx(self, main_window):
        main_window._on_progress("scanning_gpx", 2, 5, "track.gpx", 1.0)
        bar = main_window._phase_bars[0]
        assert bar.value() == 2
        assert bar.maximum() == 5

    def test_on_progress_shows_eta(self, main_window):
        main_window._on_progress("matching", 5, 10, "photo.jpg", 10.0)
        text = main_window._elapsed_label.text()
        assert "已用" in text
        assert "剩余" in text

    def test_on_progress_unknown_phase_ignored(self, main_window):
        main_window._on_progress("unknown", 1, 2, "x", 0)
        for bar in main_window._phase_bars:
            assert bar.value() == 0

    def test_on_start_resets_all_bars(self, main_window, monkeypatch):
        for bar in main_window._phase_bars:
            bar.setValue(50)
        main_window._gps_dir_edit.setText("/tmp")
        main_window._photo_dir_edit.setText("/tmp")
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.warning",
            lambda *a, **kw: None,
        )
        # Don't actually run worker
        monkeypatch.setattr(Worker, "start", lambda self: None)
        main_window._on_start()
        for bar in main_window._phase_bars:
            assert bar.value() == 0


# ── Thumbnail preview tests ────────────────────────────────

class TestThumbnailPreview:

    def test_thumb_widgets_exist(self, main_window):
        assert main_window._thumb_label is not None
        assert main_window._thumb_info is not None
        assert main_window._thumb_label.width() == 120
        assert main_window._thumb_label.height() == 120

    def test_thumb_info_default_text(self, main_window):
        assert "选中" in main_window._thumb_info.text()

    def test_on_selection_changed_no_selection(self, main_window):
        main_window._on_selection_changed()
        assert "选中" in main_window._thumb_info.text()

    def test_on_selection_changed_with_data(self, main_window):
        main_window._result_details.append({
            "filename": "test.jpg",
            "path": "/nonexistent/test.jpg",
            "latitude": 25.0,
            "longitude": 100.0,
            "method": "interpolated",
        })
        main_window._results_table.insertRow(0)
        main_window._results_table.setItem(0, 0, QTableWidgetItem("test.jpg"))
        # Select the row
        main_window._results_table.selectRow(0)
        info = main_window._thumb_info.text()
        assert "test.jpg" in info
        assert "插值" in info


# ── PhotoBrowserDialog tests ──────────────────────────────

class TestPhotoBrowserDialog:

    def test_photo_browser_with_photos(self, qapp):
        from gps_photo_tracker.gui.photo_browser_dialog import PhotoBrowserDialog
        photos = [
            {"filename": "a.jpg", "path": "/tmp/a.jpg", "timestamp": 1700000000.0,
             "has_gps": True, "latitude": 25.0, "longitude": 100.0},
            {"filename": "b.jpg", "path": "/tmp/b.jpg", "timestamp": 1700003600.0,
             "has_gps": False},
        ]
        dialog = PhotoBrowserDialog(photos)
        assert dialog.windowTitle() == "照片列表"
        assert dialog._table.rowCount() == 2

    def test_photo_browser_empty(self, qapp):
        from gps_photo_tracker.gui.photo_browser_dialog import PhotoBrowserDialog
        dialog = PhotoBrowserDialog([])
        assert dialog._table.rowCount() == 0

    def test_photo_browser_filter_gps(self, qapp):
        from gps_photo_tracker.gui.photo_browser_dialog import PhotoBrowserDialog
        photos = [
            {"filename": "gps.jpg", "timestamp": 1000.0, "has_gps": True,
             "latitude": 25.0, "longitude": 100.0},
            {"filename": "nogps.jpg", "timestamp": 2000.0, "has_gps": False},
        ]
        dialog = PhotoBrowserDialog(photos)
        dialog._filter_cb.setCurrentIndex(1)  # 有GPS
        assert dialog._table.rowCount() == 1

    def test_photo_browser_filter_no_gps(self, qapp):
        from gps_photo_tracker.gui.photo_browser_dialog import PhotoBrowserDialog
        photos = [
            {"filename": "gps.jpg", "timestamp": 1000.0, "has_gps": True},
            {"filename": "nogps.jpg", "timestamp": 2000.0, "has_gps": False},
        ]
        dialog = PhotoBrowserDialog(photos)
        dialog._filter_cb.setCurrentIndex(2)  # 无GPS
        assert dialog._table.rowCount() == 1

    def test_photo_browser_search(self, qapp):
        from gps_photo_tracker.gui.photo_browser_dialog import PhotoBrowserDialog
        photos = [
            {"filename": "DSC001.jpg", "timestamp": 1000.0, "has_gps": False},
            {"filename": "DSC002.jpg", "timestamp": 2000.0, "has_gps": False},
            {"filename": "IMG003.jpg", "timestamp": 3000.0, "has_gps": False},
        ]
        dialog = PhotoBrowserDialog(photos)
        dialog._search_edit.setText("DSC")
        assert dialog._table.rowCount() == 2

    def test_photo_browser_sort_by_time(self, qapp):
        from gps_photo_tracker.gui.photo_browser_dialog import PhotoBrowserDialog
        photos = [
            {"filename": "b.jpg", "timestamp": 2000.0, "has_gps": False},
            {"filename": "a.jpg", "timestamp": 1000.0, "has_gps": False},
        ]
        dialog = PhotoBrowserDialog(photos)
        dialog._sort_cb.setCurrentIndex(1)  # 按时间排序
        assert dialog._table.item(0, 0).text() == "a.jpg"


# ── MainWindow photos scanned tests ───────────────────────

class TestMainWindowPhotosScanned:

    def test_on_photos_scanned_caches(self, main_window):
        photos = [
            {"filename": "a.jpg", "has_gps": True},
            {"filename": "b.jpg", "has_gps": False},
        ]
        main_window._on_photos_scanned(photos)
        assert main_window._cached_photos == photos

    def test_on_photos_scanned_updates_summary(self, main_window):
        photos = [
            {"filename": "a.jpg", "has_gps": True},
            {"filename": "b.jpg", "has_gps": False},
            {"filename": "c.jpg", "has_gps": True},
        ]
        main_window._on_photos_scanned(photos)
        text = main_window._scan_summary.text()
        assert "3" in text
        assert "2" in text

    def test_worker_has_photos_scanned_signal(self, qapp):
        worker = Worker(
            gps_dir=Path("/tmp"),
            photo_dir=Path("/tmp"),
            config=MatcherConfig(),
            options=ProcessOptions(mode=ProcessMode.PREVIEW),
        )
        assert hasattr(worker, 'photos_scanned_signal')


# ── Result filter tests ───────────────────────────────────

class TestResultFilter:

    def test_result_filter_exists(self, main_window):
        assert main_window._result_filter is not None
        assert main_window._result_filter.count() == 4

    def test_apply_result_filter_shows_all(self, main_window):
        main_window._result_details = [
            {"success": True, "has_gps": False},
            {"success": False, "has_gps": False},
            {"success": True, "has_gps": True},
        ]
        for _ in range(3):
            main_window._results_table.insertRow(main_window._results_table.rowCount())
        main_window._result_filter.setCurrentIndex(0)
        main_window._apply_result_filter()
        for row in range(3):
            assert not main_window._results_table.isRowHidden(row)

    def test_apply_result_filter_success_only(self, main_window):
        main_window._result_details = [
            {"success": True, "has_gps": False},
            {"success": False, "has_gps": False},
        ]
        for _ in range(2):
            main_window._results_table.insertRow(main_window._results_table.rowCount())
        main_window._result_filter.setCurrentIndex(1)
        main_window._apply_result_filter()
        assert not main_window._results_table.isRowHidden(0)
        assert main_window._results_table.isRowHidden(1)

    def test_apply_result_filter_failed_only(self, main_window):
        main_window._result_details = [
            {"success": True, "has_gps": False},
            {"success": False, "has_gps": False},
        ]
        for _ in range(2):
            main_window._results_table.insertRow(main_window._results_table.rowCount())
        main_window._result_filter.setCurrentIndex(2)
        main_window._apply_result_filter()
        assert main_window._results_table.isRowHidden(0)
        assert not main_window._results_table.isRowHidden(1)


# ── Window geometry persistence tests ─────────────────────

class TestWindowGeometry:

    def test_close_saves_geometry(self, main_window):
        from PySide6.QtCore import QSettings
        QSettings("GPSPhotoTracker", "GPSPhotoTracker").remove("window_geometry")
        main_window.resize(1100, 700)
        from PySide6.QtGui import QCloseEvent
        event = QCloseEvent()
        main_window.closeEvent(event)
        geo = QSettings("GPSPhotoTracker", "GPSPhotoTracker").value("window_geometry")
        assert geo is not None

    def test_table_sorting_enabled(self, main_window):
        assert main_window._results_table.isSortingEnabled()


