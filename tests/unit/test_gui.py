"""Tests for GUI components."""

import pytest
from pathlib import Path

from PySide6.QtWidgets import QApplication
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
