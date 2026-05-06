#!/usr/bin/env python3
"""Build GPS Photo Tracker for current platform.

Usage:
    python scripts/build.py          # Build for current platform
    python scripts/build.py --clean  # Clean build
    python scripts/build.py --onefile  # Single file (no .app bundle)
"""

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = ROOT / "gps-photo-tracker.spec"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"


def check_pyinstaller():
    try:
        import PyInstaller
        print(f"PyInstaller {PyInstaller.__version__} found")
    except ImportError:
        print("PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def clean():
    for d in [DIST_DIR, BUILD_DIR]:
        if d.exists():
            shutil.rmtree(d)
            print(f"Removed {d}")


def build(clean_first=False, onefile=False):
    check_pyinstaller()

    if clean_first:
        clean()

    cmd = [sys.executable, "-m", "PyInstaller", str(SPEC_FILE), "--noconfirm"]

    if onefile:
        cmd.append("--onefile")

    print(f"Building on {platform.system()} {platform.release()}")
    print(f"Command: {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print(f"Build FAILED with exit code {result.returncode}")
        sys.exit(result.returncode)

    system = platform.system()
    if system == "Darwin":
        app_path = DIST_DIR / "GPS Photo Tracker.app"
        if app_path.exists():
            print(f"\nBuilt: {app_path}")
            print(f"Size: {sum(f.stat().st_size for f in app_path.rglob('*')) / 1024 / 1024:.1f} MB")
    elif system == "Windows":
        exe_path = DIST_DIR / "GPS Photo Tracker.exe"
        if exe_path.exists():
            print(f"\nBuilt: {exe_path}")
    elif system == "Linux":
        exe_path = DIST_DIR / "GPS Photo Tracker"
        if exe_path.exists():
            print(f"\nBuilt: {exe_path}")
            # Make executable
            exe_path.chmod(0o755)

    print("\nDone!")


def main():
    parser = argparse.ArgumentParser(description="Build GPS Photo Tracker")
    parser.add_argument("--clean", action="store_true", help="Clean before building")
    parser.add_argument("--onefile", action="store_true", help="Build single file (no .app)")
    args = parser.parse_args()
    build(clean_first=args.clean, onefile=args.onefile)


if __name__ == "__main__":
    main()
