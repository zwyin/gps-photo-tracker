"""Entry point for python -m gps_photo_tracker."""

import sys


def _check_dependencies():
    """Check all required dependencies and return missing ones."""
    required = {
        "PySide6": "PySide6>=6.6",
        "piexif": "piexif>=1.1.3",
        "gpxpy": "gpxpy>=1.6.0",
        "PIL": "Pillow>=10.0.0",
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
    missing = _check_dependencies()
    if missing:
        print("=" * 50)
        print("GPS Photo Tracker - 缺少必要依赖 / Missing Dependencies")
        print("=" * 50)
        print()
        for module, pip_name in missing.items():
            print(f"  ✗ {pip_name}")
        print()
        print("安装方法 / Install with:")
        print(f"  pip install -e .")
        print()
        print("或单独安装 / Or install individually:")
        for pip_name in missing.values():
            print(f"  pip install \"{pip_name}\"")
        print()
        sys.exit(1)

    from gps_photo_tracker.gui import run_app
    run_app()


if __name__ == "__main__":
    main()
