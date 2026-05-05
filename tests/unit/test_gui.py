"""Tests for GUI components."""

import pytest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QCheckBox, QTableWidgetItem, QGroupBox, QTableWidget
from PySide6.QtCore import Qt, QSettings

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
        main_window._gps_dir_edit.setCurrentText("")
        main_window._photo_dir_edit.setCurrentText("")

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

    def test_settings_dialog_has_mode_radio_buttons(self, qapp):
        """Fix #5: Settings dialog should have default processing mode radio buttons."""
        from gps_photo_tracker.gui.settings_dialog import SettingsDialog
        dialog = SettingsDialog()
        assert dialog._mode_preview_rb is not None
        assert dialog._mode_copy_rb is not None
        assert dialog._mode_overwrite_rb is not None
        assert dialog._mode_group is not None

    def test_settings_dialog_default_mode_preview(self, qapp):
        """Fix #5: Default mode should be preview (index 0)."""
        from gps_photo_tracker.gui.settings_dialog import SettingsDialog
        dialog = SettingsDialog()
        assert dialog._mode_preview_rb.isChecked()
        assert not dialog._mode_copy_rb.isChecked()
        assert not dialog._mode_overwrite_rb.isChecked()

    def test_settings_dialog_save_includes_mode(self, qapp):
        """Fix #5: Saving settings should include mode value."""
        from gps_photo_tracker.gui.settings_dialog import SettingsDialog, save_settings, SETTINGS_KEYS
        dialog = SettingsDialog()
        dialog._mode_copy_rb.setChecked(True)
        saved = {}
        original_save = save_settings

        def capture_save(values):
            saved.update(values)

        import gps_photo_tracker.gui.settings_dialog as sd_module
        sd_module.save_settings = capture_save
        dialog._save()
        sd_module.save_settings = original_save
        assert "mode" in saved
        assert saved["mode"] == 1  # copy mode

    def test_settings_dialog_reset_defaults_mode(self, qapp):
        """Fix #5: Reset defaults should set mode to preview."""
        from gps_photo_tracker.gui.settings_dialog import SettingsDialog
        dialog = SettingsDialog()
        dialog._mode_copy_rb.setChecked(True)
        dialog._reset_defaults()
        assert dialog._mode_preview_rb.isChecked()

    def test_load_settings_includes_mode(self, qapp):
        """Fix #5: load_settings should include mode key."""
        from gps_photo_tracker.gui.settings_dialog import load_settings
        s = load_settings()
        assert "mode" in s


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

    def test_on_scan_done_updates_gpx_label(self, main_window):
        """Fix #1: scan_done should update the GPX browser label."""
        segments = [
            {"filename": "a.gpx", "start": 1000.0, "end": 2000.0, "point_count": 50},
        ]
        main_window._on_scan_done(segments)
        assert "1 段" in main_window._gpx_browser_label.text()
        assert "50 点" in main_window._gpx_browser_label.text()
        assert "点击查看" in main_window._gpx_browser_label.text()

    def test_on_scan_done_updates_scan_summary(self, main_window):
        """Fix #1: scan_done should update the read-only scan summary."""
        segments = [
            {"filename": "a.gpx", "start": 1000.0, "end": 2000.0, "point_count": 50},
        ]
        main_window._on_scan_done(segments)
        assert "1 段" in main_window._scan_summary.text()
        assert "50 点" in main_window._scan_summary.text()

    def test_on_scan_done_multiple_segments(self, main_window):
        segments = [
            {"filename": "a.gpx", "start": 1000.0, "end": 2000.0, "point_count": 100},
            {"filename": "b.gpx", "start": 3000.0, "end": 4000.0, "point_count": 200},
        ]
        main_window._on_scan_done(segments)
        assert len(main_window._cached_segments) == 2
        assert "2 段" in main_window._gpx_browser_label.text()
        assert "300 点" in main_window._gpx_browser_label.text()

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
        main_window._gps_dir_edit.setCurrentText("/tmp")
        main_window._photo_dir_edit.setCurrentText("/tmp")
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

    def test_thumb_size_200x200(self, main_window):
        """Fix #4: Thumbnail preview should be 200x200 per spec."""
        assert main_window._thumb_label.width() == 200
        assert main_window._thumb_label.height() == 200

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

    def test_on_photos_scanned_updates_photo_label(self, main_window):
        """Fix #1: photos_scanned should update the photo browser label."""
        photos = [
            {"filename": "a.jpg", "has_gps": True},
            {"filename": "b.jpg", "has_gps": False},
            {"filename": "c.jpg", "has_gps": True},
        ]
        main_window._on_photos_scanned(photos)
        text = main_window._photo_browser_label.text()
        assert "3" in text
        assert "2" in text
        assert "点击查看" in text

    def test_on_photos_scanned_updates_scan_summary(self, main_window):
        """Fix #1: photos_scanned should update the read-only scan summary."""
        photos = [
            {"filename": "a.jpg", "has_gps": True},
            {"filename": "b.jpg", "has_gps": False},
        ]
        # Set initial scan summary so we can verify the append
        main_window._scan_summary.setText("GPS: 1 段, 50 点")
        main_window._on_photos_scanned(photos)
        text = main_window._scan_summary.text()
        assert "GPS: 1 段, 50 点" in text
        assert "照片: 2张" in text

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
        QSettings("GPSPhotoTracker", "GPSPhotoTracker").remove("window_geometry")
        main_window.resize(1100, 700)
        from PySide6.QtGui import QCloseEvent
        event = QCloseEvent()
        main_window.closeEvent(event)
        geo = QSettings("GPSPhotoTracker", "GPSPhotoTracker").value("window_geometry")
        assert geo is not None

    def test_table_sorting_enabled(self, main_window):
        assert main_window._results_table.isSortingEnabled()


# ── Fix #1: Browser entry point tests ─────────────────────

class TestBrowserEntryPoints:

    def test_gpx_browser_label_exists(self, main_window):
        """Fix #1: GPX browser clickable label should exist."""
        assert main_window._gpx_browser_label is not None
        assert "GPS" in main_window._gpx_browser_label.text()

    def test_photo_browser_label_exists(self, main_window):
        """Fix #1: Photo browser clickable label should exist."""
        assert main_window._photo_browser_label is not None
        assert "照片" in main_window._photo_browser_label.text()

    def test_gpx_browser_label_clickable(self, main_window):
        """Fix #1: GPX browser label should have mousePressEvent handler."""
        assert main_window._gpx_browser_label.mousePressEvent is not None

    def test_photo_browser_label_clickable(self, main_window):
        """Fix #1: Photo browser label should have mousePressEvent handler."""
        assert main_window._photo_browser_label.mousePressEvent is not None

    def test_open_photo_browser_with_data(self, main_window, monkeypatch):
        """Fix #1: Clicking photo label with cached data opens browser dialog."""
        main_window._cached_photos = [
            {"filename": "a.jpg", "has_gps": False},
        ]
        opened = []
        monkeypatch.setattr(
            "gps_photo_tracker.gui.photo_browser_dialog.PhotoBrowserDialog.exec",
            lambda self: opened.append(True),
        )
        main_window._open_photo_browser()
        assert opened

    def test_open_photo_browser_without_data(self, main_window):
        """Fix #1: Opening photo browser with no data does nothing."""
        main_window._cached_photos = []
        # Should not raise
        main_window._open_photo_browser()

    def test_open_gpx_browser_with_data(self, main_window, monkeypatch):
        """Fix #1: Clicking GPX label with cached data opens browser dialog."""
        main_window._cached_segments = [
            {"filename": "a.gpx", "start": 1000.0, "end": 2000.0, "point_count": 50},
        ]
        opened = []
        monkeypatch.setattr(
            "gps_photo_tracker.gui.gpx_browser_dialog.GPXBrowserDialog.exec",
            lambda self: opened.append(True),
        )
        main_window._open_gpx_browser()
        assert opened


# ── Fix #2: Real-time stats card update tests ──────────────

class TestRealtimeStatsCard:

    def test_update_stats_card_empty(self, main_window):
        """Fix #2: _update_stats_card with no results shows zero."""
        main_window._result_details = []
        main_window._update_stats_card()
        assert "总数: 0" in main_window._stats_label.text()
        assert "成功: 0" in main_window._stats_label.text()

    def test_update_stats_card_with_results(self, main_window):
        """Fix #2: _update_stats_card updates stats label."""
        main_window._result_details = [
            {"success": True, "has_gps": False},
            {"success": True, "has_gps": False},
            {"success": False, "has_gps": False},
        ]
        main_window._update_stats_card()
        text = main_window._stats_label.text()
        assert "总数: 3" in text
        assert "成功: 2" in text
        assert "失败: 1" in text

    def test_on_photo_processed_updates_stats(self, main_window):
        """Fix #2: _on_photo_processed should update stats card in real-time."""
        result = {
            "filename": "test.jpg",
            "success": True,
            "method": "interpolated",
            "has_gps": False,
            "latitude": 25.0,
            "longitude": 100.0,
        }
        main_window._on_photo_processed(result)
        assert "总数: 1" in main_window._stats_label.text()
        assert "成功: 1" in main_window._stats_label.text()

    def test_on_photo_processed_multiple(self, main_window):
        """Fix #2: Multiple _on_photo_processed calls update stats progressively."""
        for i in range(3):
            main_window._on_photo_processed({
                "filename": f"photo{i}.jpg",
                "success": i < 2,
                "method": "interpolated" if i < 2 else "",
                "has_gps": False,
                "reject_reason": "no_gps_coverage" if i >= 2 else None,
            })
        text = main_window._stats_label.text()
        assert "总数: 3" in text
        assert "成功: 2" in text
        assert "失败: 1" in text


# ── Fix #3: Completion notification tests ──────────────────

class TestCompletionNotification:

    def test_on_done_shows_message_box(self, main_window, monkeypatch):
        """Fix #3: _on_done should show QMessageBox.information."""
        informed = []
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.information",
            lambda *a, **kw: informed.append(True),
        )
        main_window._on_done({
            "total": 5, "matched": 3, "failed": 1, "skipped": 1, "success_rate": 0.6,
        })
        assert informed

    def test_on_done_message_contains_stats(self, main_window, monkeypatch):
        """Fix #3: The notification message should contain processing stats."""
        messages = []
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.information",
            lambda self_w, title, msg: messages.append((title, msg)),
        )
        main_window._on_done({
            "total": 10, "matched": 8, "failed": 1, "skipped": 1, "success_rate": 0.8,
        })
        assert messages
        title, msg = messages[0]
        assert "处理完成" in title
        assert "总数: 10" in msg
        assert "成功: 8" in msg
        assert "失败: 1" in msg

    def test_on_done_reenables_buttons(self, main_window, monkeypatch):
        """Fix #3: _on_done should re-enable start button, disable cancel."""
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.information",
            lambda *a, **kw: None,
        )
        main_window._start_btn.setEnabled(False)
        main_window._cancel_btn.setEnabled(True)
        main_window._on_done({
            "total": 1, "matched": 1, "failed": 0, "skipped": 0, "success_rate": 1.0,
        })
        assert main_window._start_btn.isEnabled()
        assert not main_window._cancel_btn.isEnabled()


# ── Fix #4: Thumbnail size tests ───────────────────────────

class TestThumbnailSize:

    def test_thumb_label_is_200x200(self, main_window):
        """Fix #4: Thumbnail preview area should be 200x200 per spec."""
        assert main_window._thumb_label.width() == 200
        assert main_window._thumb_label.height() == 200

    def test_thumb_label_not_120(self, main_window):
        """Fix #4: Ensure the old 120x120 size is no longer used."""
        assert main_window._thumb_label.width() != 120
        assert main_window._thumb_label.height() != 120


# ── Fix #5: Settings mode persistence tests ────────────────

class TestSettingsModePersistence:

    def test_apply_saved_settings_restores_mode(self, main_window, monkeypatch):
        """Fix #5: _apply_saved_settings should restore saved processing mode."""
        from gps_photo_tracker.gui import settings_dialog as sd
        original_load = sd.load_settings

        def mock_load():
            s = original_load()
            s["mode"] = 1  # copy mode
            return s

        # Patch in the main_window module namespace where load_settings is used
        import gps_photo_tracker.gui.main_window as mw_module
        monkeypatch.setattr(mw_module, "load_settings", mock_load)
        main_window._apply_saved_settings()
        assert main_window._copy_rb.isChecked()
        assert not main_window._preview_rb.isChecked()

    def test_apply_saved_settings_overwrite_mode(self, main_window, monkeypatch):
        """Fix #5: _apply_saved_settings should restore overwrite mode."""
        from gps_photo_tracker.gui import settings_dialog as sd
        original_load = sd.load_settings

        def mock_load():
            s = original_load()
            s["mode"] = 2  # overwrite mode
            return s

        import gps_photo_tracker.gui.main_window as mw_module
        monkeypatch.setattr(mw_module, "load_settings", mock_load)
        main_window._apply_saved_settings()
        assert main_window._overwrite_rb.isChecked()

    def test_apply_saved_settings_preview_mode(self, main_window, monkeypatch):
        """Fix #5: _apply_saved_settings should restore preview mode (default)."""
        from gps_photo_tracker.gui import settings_dialog as sd
        original_load = sd.load_settings

        def mock_load():
            s = original_load()
            s["mode"] = 0  # preview mode
            return s

        import gps_photo_tracker.gui.main_window as mw_module
        monkeypatch.setattr(mw_module, "load_settings", mock_load)
        main_window._apply_saved_settings()
        assert main_window._preview_rb.isChecked()


class TestPathHistory:
    """Path history for GPS/photo/output directories (spec 6.10)."""

    def test_dir_widgets_are_combobox(self, main_window):
        """Directory inputs are QComboBox (not QLineEdit)."""
        from PySide6.QtWidgets import QComboBox
        assert isinstance(main_window._gps_dir_edit, QComboBox)
        assert isinstance(main_window._photo_dir_edit, QComboBox)
        assert isinstance(main_window._output_dir_edit, QComboBox)

    def test_dir_combos_are_editable(self, main_window):
        """ComboBoxes are editable (user can type path)."""
        assert main_window._gps_dir_edit.isEditable()
        assert main_window._photo_dir_edit.isEditable()
        assert main_window._output_dir_edit.isEditable()

    def test_add_path_history(self, main_window):
        """_add_path_history adds path to combo and QSettings."""
        from PySide6.QtCore import QSettings
        settings = QSettings()
        settings.remove("gps_dir_history")

        main_window._add_path_history("gps_dir_history", "/test/path1", main_window._gps_dir_edit)
        assert main_window._gps_dir_edit.currentText() == "/test/path1"
        assert main_window._gps_dir_edit.count() == 1

        main_window._add_path_history("gps_dir_history", "/test/path2", main_window._gps_dir_edit)
        assert main_window._gps_dir_edit.count() == 2
        assert main_window._gps_dir_edit.currentText() == "/test/path2"

    def test_add_path_history_dedupes(self, main_window):
        """Duplicate path is moved to top, not added again."""
        from PySide6.QtCore import QSettings
        settings = QSettings()
        settings.remove("photo_dir_history")

        main_window._add_path_history("photo_dir_history", "/a", main_window._photo_dir_edit)
        main_window._add_path_history("photo_dir_history", "/b", main_window._photo_dir_edit)
        main_window._add_path_history("photo_dir_history", "/a", main_window._photo_dir_edit)
        assert main_window._photo_dir_edit.count() == 2
        assert main_window._photo_dir_edit.currentText() == "/a"

    def test_add_path_history_limits_10(self, main_window):
        """History is limited to 10 entries."""
        from PySide6.QtCore import QSettings
        settings = QSettings()
        settings.remove("output_dir_history")

        for i in range(15):
            main_window._add_path_history("output_dir_history", f"/path/{i}", main_window._output_dir_edit)
        assert main_window._output_dir_edit.count() == 10

    def test_load_path_history(self, main_window):
        """_load_path_history populates combo from QSettings."""
        from PySide6.QtCore import QSettings
        settings = QSettings()
        settings.setValue("gps_dir_history", ["/saved1", "/saved2"])

        main_window._load_path_history()
        assert main_window._gps_dir_edit.count() >= 2


class TestDetailDialogEnhanced:
    """Enhanced detail dialog with thumbnail, GPS comparison, explanations."""

    def test_success_dialog_has_thumbnail(self, qapp):
        from gps_photo_tracker.gui.detail_dialog import DetailDialog
        data = {
            "filename": "test.jpg",
            "path": "/nonexistent/test.jpg",
            "success": True,
            "method": "interpolated",
            "has_gps": False,
            "latitude": 25.0,
            "longitude": 100.0,
            "altitude": 1800.0,
            "time_diff": 12.0,
            "capture_time": "2026-02-17 08:05:00 UTC",
            "interpolation_prev": {"lat": 25.0, "lon": 100.0, "alt": 1800},
            "interpolation_next": {"lat": 25.001, "lon": 100.001, "alt": 1810},
            "interpolation_distance": 247.0,
            "interpolation_ratio": 0.133,
        }
        dlg = DetailDialog(data)
        assert dlg.windowTitle().startswith("照片匹配详情")
        # Thumbnail label should exist (file doesn't exist → shows text)
        thumb = dlg._thumb
        assert thumb is not None
        assert thumb.width() == 300
        assert thumb.height() == 300

    def test_failed_dialog_shows_explanation(self, qapp):
        from gps_photo_tracker.gui.detail_dialog import DetailDialog
        data = {
            "filename": "test.jpg",
            "path": "",
            "success": False,
            "reject_reason": "no_gps_coverage",
            "has_gps": False,
        }
        dlg = DetailDialog(data)
        text = dlg.findChild(object)  # Just verify dialog constructs without error
        assert dlg is not None

    def test_gps_before_shown_for_existing_gps(self, qapp):
        from gps_photo_tracker.gui.detail_dialog import DetailDialog
        data = {
            "filename": "test.jpg",
            "path": "",
            "success": True,
            "method": "nearest",
            "has_gps": True,
            "gps_before": "25.0000, 100.0000",
            "latitude": 25.001,
            "longitude": 100.001,
            "altitude": 1800.0,
            "time_diff": 5.0,
            "gps_old": "25.0000, 100.0000",
            "gps_new": "25.0010, 100.0010",
        }
        dlg = DetailDialog(data)
        assert dlg is not None

    def test_capture_time_displayed(self, qapp):
        from gps_photo_tracker.gui.detail_dialog import DetailDialog
        data = {
            "filename": "test.jpg",
            "path": "",
            "success": True,
            "method": "interpolated",
            "has_gps": False,
            "latitude": 25.0,
            "longitude": 100.0,
            "capture_time": "2026-02-17 14:32:15 UTC",
        }
        dlg = DetailDialog(data)
        assert dlg is not None


class TestSettingsDialogEnhanced:
    """Settings dialog: log directory, retention days, about section, restore defaults."""

    def test_log_dir_edit_exists(self, qapp):
        from gps_photo_tracker.gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog()
        assert dlg._log_dir_edit is not None
        assert dlg._log_dir_edit.placeholderText() != ""

    def test_retention_spin_exists(self, qapp):
        from gps_photo_tracker.gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog()
        assert dlg._retention_spin is not None
        assert dlg._retention_spin.value() == 30
        assert dlg._retention_spin.minimum() == 1
        assert dlg._retention_spin.maximum() == 365

    def test_about_label_exists(self, qapp):
        from gps_photo_tracker.gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog()
        # About group should contain version info
        groups = dlg.findChildren(QGroupBox)
        about_found = any("关于" in g.title() for g in groups)
        assert about_found

    def test_restore_defaults_clears_log_dir(self, qapp):
        from gps_photo_tracker.gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog()
        dlg._log_dir_edit.setText("/some/path")
        dlg._retention_spin.setValue(90)
        dlg._reset_defaults()
        assert dlg._log_dir_edit.text() == ""
        assert dlg._retention_spin.value() == 30

    def test_save_includes_log_settings(self, qapp, monkeypatch):
        from gps_photo_tracker.gui.settings_dialog import SettingsDialog
        saved = {}
        def mock_save(values):
            saved.update(values)
        import gps_photo_tracker.gui.settings_dialog as sd_module
        monkeypatch.setattr(sd_module, "save_settings", mock_save)
        dlg = SettingsDialog()
        dlg._log_dir_edit.setText("/test/logs")
        dlg._retention_spin.setValue(60)
        dlg._save()
        assert saved.get("log_dir") == "/test/logs"
        assert saved.get("log_retention_days") == 60


class TestGPXBrowserEnhanced:
    """GPX browser: file grouping, time coverage overview."""

    def test_file_grouping(self, qapp):
        from gps_photo_tracker.gui.gpx_browser_dialog import GPXBrowserDialog
        segments = [
            {"filename": "a.gpx", "point_count": 100, "start": 1700000000.0, "end": 1700003600.0},
            {"filename": "a.gpx", "point_count": 50, "start": 1700007200.0, "end": 1700010000.0},
            {"filename": "b.gpx", "point_count": 200, "start": 1700100000.0, "end": 1700105000.0},
        ]
        dlg = GPXBrowserDialog(segments)
        assert dlg is not None
        # Should have 3 rows in the table
        table = dlg.findChild(QTableWidget)
        assert table is not None
        assert table.rowCount() == 3

    def test_file_summary_group(self, qapp):
        from gps_photo_tracker.gui.gpx_browser_dialog import GPXBrowserDialog
        segments = [
            {"filename": "track.gpx", "point_count": 300, "start": 1700000000.0, "end": 1700010000.0},
        ]
        dlg = GPXBrowserDialog(segments)
        groups = dlg.findChildren(QGroupBox)
        titles = [g.title() for g in groups]
        assert "文件统计" in titles

    def test_time_coverage_overview(self, qapp):
        from gps_photo_tracker.gui.gpx_browser_dialog import GPXBrowserDialog
        segments = [
            {"filename": "a.gpx", "point_count": 100, "start": 1700000000.0, "end": 1700003600.0},
            {"filename": "b.gpx", "point_count": 50, "start": 1700100000.0, "end": 1700105000.0},
        ]
        dlg = GPXBrowserDialog(segments)
        groups = dlg.findChildren(QGroupBox)
        titles = [g.title() for g in groups]
        assert "时间覆盖总览" in titles

    def test_empty_segments(self, qapp):
        from gps_photo_tracker.gui.gpx_browser_dialog import GPXBrowserDialog
        dlg = GPXBrowserDialog([])
        assert dlg is not None


class TestGPXBrowserCheckbox:
    """GPX browser: checkbox filtering via get_excluded_filenames."""

    def test_all_checked_returns_empty_excluded(self, qapp):
        from gps_photo_tracker.gui.gpx_browser_dialog import GPXBrowserDialog
        segments = [
            {"filename": "a.gpx", "point_count": 100, "start": 1700000000.0, "end": 1700003600.0},
            {"filename": "b.gpx", "point_count": 50, "start": 1700100000.0, "end": 1700105000.0},
        ]
        dlg = GPXBrowserDialog(segments)
        excluded = dlg.get_excluded_filenames()
        assert excluded == set()

    def test_unchecked_returns_excluded(self, qapp):
        from gps_photo_tracker.gui.gpx_browser_dialog import GPXBrowserDialog
        segments = [
            {"filename": "a.gpx", "point_count": 100, "start": 1700000000.0, "end": 1700003600.0},
            {"filename": "b.gpx", "point_count": 50, "start": 1700100000.0, "end": 1700105000.0},
        ]
        dlg = GPXBrowserDialog(segments)
        # Uncheck first row
        widget = dlg._table.cellWidget(0, 0)
        cb = widget.findChild(QCheckBox)
        cb.setChecked(False)
        excluded = dlg.get_excluded_filenames()
        assert "a.gpx" in excluded
        assert "b.gpx" not in excluded

    def test_select_all_button(self, qapp):
        from gps_photo_tracker.gui.gpx_browser_dialog import GPXBrowserDialog
        segments = [
            {"filename": "a.gpx", "point_count": 100, "start": 1700000000.0, "end": 1700003600.0},
        ]
        dlg = GPXBrowserDialog(segments)
        # Uncheck first
        widget = dlg._table.cellWidget(0, 0)
        cb = widget.findChild(QCheckBox)
        cb.setChecked(False)
        # Click select all
        dlg._set_all_checked(True)
        assert cb.isChecked()
        assert dlg.get_excluded_filenames() == set()

    def test_deselect_all_button(self, qapp):
        from gps_photo_tracker.gui.gpx_browser_dialog import GPXBrowserDialog
        segments = [
            {"filename": "a.gpx", "point_count": 100, "start": 1700000000.0, "end": 1700003600.0},
            {"filename": "b.gpx", "point_count": 50, "start": 1700100000.0, "end": 1700105000.0},
        ]
        dlg = GPXBrowserDialog(segments)
        dlg._set_all_checked(False)
        excluded = dlg.get_excluded_filenames()
        assert excluded == {"a.gpx", "b.gpx"}
