"""Entry point for python -m gps_photo_tracker."""

import sys
import traceback
from datetime import datetime
from pathlib import Path


def _crash_log_path():
    """Return path for crash log, next to the executable or in home dir."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path.home()
    return base / "GPS_Photo_Tracker_crash.log"


def _write_crash_log(error_msg):
    """Append crash info to log file."""
    log_path = _crash_log_path()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 60}\n")
            f.write(f"[{timestamp}] GPS Photo Tracker crashed\n\n")
            f.write(error_msg)
            f.write(f"\n\nLog file: {log_path}\n")
        return log_path
    except Exception:
        return None


def _show_error_dialog(title, message):
    """Try to show a graphical error dialog. Works even without PySide6."""
    # Try tkinter first (bundled with Python, lighter than PySide6)
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
        return
    except Exception:
        pass

    # Try PySide6
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        _app = QApplication.instance() or QApplication(sys.argv)
        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle(title)
        box.setText(message)
        box.exec()
        return
    except Exception:
        pass

    # Last resort: print (only visible if console is available)
    print(f"\n{'=' * 50}", file=sys.stderr)
    print(f"{title}", file=sys.stderr)
    print(f"{'=' * 50}", file=sys.stderr)
    print(message, file=sys.stderr)


def _check_dependencies():
    """Check all required dependencies and return missing ones."""
    required = {
        "PySide6": "PySide6>=6.6",
        "piexif": "piexif>=1.1.3",
        "gpxpy": "gpxpy>=1.6.0",
        "geopy": "geopy>=2.4.0",
        "tenacity": "tenacity>=8.0.0",
    }
    missing = {}
    for module, pip_name in required.items():
        try:
            __import__(module)
        except ImportError:
            missing[module] = pip_name
    return missing


def main():
    try:
        _run()
    except Exception:
        error_msg = traceback.format_exc()
        log_path = _write_crash_log(error_msg)

        display = error_msg.strip().split("\n")[-1]
        log_info = f"\n\nCrash log: {_crash_log_path()}" if log_path else ""
        _show_error_dialog(
            "GPS Photo Tracker - Startup Error",
            f"Program failed to start:\n\n{display}{log_info}",
        )
        sys.exit(1)


def _run():
    missing = _check_dependencies()
    if missing:
        deps = "\n".join(f"  - {pip}" for pip in missing.values())
        _write_crash_log(f"Missing dependencies:\n{deps}")
        _show_error_dialog(
            "GPS Photo Tracker - Missing Dependencies",
            f"Missing:\n{deps}\n\nRun: pip install -e .",
        )
        sys.exit(1)

    from gps_photo_tracker.gui import run_app
    run_app()


if __name__ == "__main__":
    main()
