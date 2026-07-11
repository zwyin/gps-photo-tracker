"""Tests for __main__.py entry point."""

import sys
import builtins
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from gps_photo_tracker.__main__ import (
    _crash_log_path,
    _write_crash_log,
    _show_error_dialog,
    _check_dependencies,
    main,
    _run,
)


class TestCrashLogPath:
    def test_frozen_returns_executable_dir(self):
        with patch.object(sys, "frozen", True, create=True):
            with patch.object(sys, "executable", "/fake/app"):
                path = _crash_log_path()
                assert path == Path("/fake") / "GPS_Photo_Tracker_crash.log"

    def test_non_frozen_returns_home_dir(self):
        with patch.object(sys, "frozen", False, create=True):
            path = _crash_log_path()
            assert path == Path.home() / "GPS_Photo_Tracker_crash.log"


class TestWriteCrashLog:
    def test_writes_log_file(self):
        log_file = Path.home() / "test_crash_tmp.log"
        try:
            with patch("gps_photo_tracker.__main__._crash_log_path", return_value=log_file):
                result = _write_crash_log("Test error occurred")
            assert result == log_file
            content = log_file.read_text(encoding="utf-8")
            assert "GPS Photo Tracker crashed" in content
            assert "Test error occurred" in content
        finally:
            log_file.unlink(missing_ok=True)

    def test_write_failure_returns_none(self):
        with patch("gps_photo_tracker.__main__._crash_log_path",
                   return_value=Path("/nonexistent_dir_bad/crash.log")):
            result = _write_crash_log("error")
        assert result is None


class TestShowErrorDialog:
    def test_tkinter_dialog(self):
        """Shows error via tkinter when available."""
        mock_root = MagicMock()
        with patch("tkinter.Tk", return_value=mock_root), \
             patch("tkinter.messagebox.showerror") as mock_show:
            _show_error_dialog("Title", "Message")
            mock_show.assert_called_once_with("Title", "Message")
            mock_root.destroy.assert_called_once()

    def test_tkinter_fails_falls_back_to_print(self):
        """When tkinter fails, falls back to stderr print."""
        with patch("tkinter.Tk", side_effect=ImportError("no tk")):
            with patch.dict("sys.modules", {"PySide6.QtWidgets": None}):
                _show_error_dialog("Error", "Something broke")

    def test_pyside6_fallback(self):
        """When tkinter fails but PySide6 works, uses QMessageBox."""
        mock_box = MagicMock()
        with patch("tkinter.Tk", side_effect=ImportError("no tk")), \
             patch("PySide6.QtWidgets.QApplication") as MockApp, \
             patch("PySide6.QtWidgets.QMessageBox", return_value=mock_box):
            MockApp.instance.return_value = MagicMock()
            _show_error_dialog("P6 Error", "PySide6 message")
            mock_box.exec.assert_called_once()


class TestCheckDependencies:
    def test_all_present(self):
        result = _check_dependencies()
        assert result == {}

    def test_missing_dependency(self):
        """When a dependency is missing, returns it."""
        real_import = builtins.__import__

        def fake_import(name, *a, **kw):
            if name == "geopy":
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *a, **kw)

        with patch("builtins.__import__", side_effect=fake_import):
            result = _check_dependencies()
            assert "geopy" in result

    def test_multiple_missing(self):
        real_import = builtins.__import__

        def fake_import(name, *a, **kw):
            if name in ("geopy", "tenacity"):
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *a, **kw)

        with patch("builtins.__import__", side_effect=fake_import):
            result = _check_dependencies()
            assert "geopy" in result
            assert "tenacity" in result

    def test_pillow_not_checked_even_if_missing(self):
        """Pillow must NOT be treated as a required dependency. It is never
        imported by the app (thumbnails use PySide6 QPixmap; EXIF uses piexif,
        which is standalone). Requiring it crashed the Windows build, where
        PyInstaller dropped the unused library and this check then failed with
        "Missing dependencies: Pillow". Regression guard: even if PIL were
        uninstallable, it must not be flagged as missing.
        """
        real_import = builtins.__import__

        def fake_import(name, *a, **kw):
            if name == "PIL":
                raise ImportError("No module named 'PIL'")
            return real_import(name, *a, **kw)

        with patch("builtins.__import__", side_effect=fake_import):
            result = _check_dependencies()
        assert "PIL" not in result

    def test_pillow_is_test_only_dependency(self):
        """Pillow is a TEST-only dependency (the suite imports PIL.Image to
        build JPEG fixtures), NOT a runtime dependency. The production app
        never imports PIL (thumbnails use PySide6 QPixmap; EXIF uses piexif).
        Keeping Pillow out of runtime deps fixed the Windows packaged-build
        crash where the startup check demanded a library PyInstaller never
        bundled. It must stay in the dev extra so tests can import PIL.
        """
        import tomllib
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        runtime = data["project"]["dependencies"]
        dev = data["project"]["optional-dependencies"]["dev"]
        assert not any("Pillow" in d for d in runtime), \
            "Pillow must not be a runtime dependency"
        assert any("Pillow" in d for d in dev), \
            "Pillow must remain in dev/test deps for JPEG fixtures"


class TestMain:
    def test_main_catches_exception(self):
        with patch("gps_photo_tracker.__main__._run", side_effect=RuntimeError("boom")), \
             patch("gps_photo_tracker.__main__._write_crash_log", return_value=Path("/tmp/crash.log")), \
             patch("gps_photo_tracker.__main__._show_error_dialog"), \
             pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_main_crash_log_none(self):
        """main() handles _write_crash_log returning None."""
        with patch("gps_photo_tracker.__main__._run", side_effect=RuntimeError("boom")), \
             patch("gps_photo_tracker.__main__._write_crash_log", return_value=None), \
             patch("gps_photo_tracker.__main__._show_error_dialog"), \
             pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_main_success(self):
        with patch("gps_photo_tracker.__main__._run") as mock_run:
            main()
            mock_run.assert_called_once()


class TestRun:
    def test_missing_deps_exits(self):
        with patch("gps_photo_tracker.__main__._check_dependencies",
                   return_value={"fake": "fake>=1.0"}), \
             patch("gps_photo_tracker.__main__._write_crash_log"), \
             patch("gps_photo_tracker.__main__._show_error_dialog"), \
             pytest.raises(SystemExit) as exc_info:
            _run()
        assert exc_info.value.code == 1

    def test_run_calls_run_app(self):
        with patch("gps_photo_tracker.__main__._check_dependencies", return_value={}), \
             patch("gps_photo_tracker.gui.run_app") as mock_run_app:
            _run()
            mock_run_app.assert_called_once()
