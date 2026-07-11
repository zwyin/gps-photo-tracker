# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for GPS Photo Tracker v0.9.0."""

import os
import sys
from pathlib import Path

block_cipher = None

# Project root
ROOT = Path(SPECPATH)
SRC = ROOT / "src"

a = Analysis(
    [str(SRC / "gps_photo_tracker" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "gps_photo_tracker",
        "gps_photo_tracker.core",
        "gps_photo_tracker.core.exif_writer",
        "gps_photo_tracker.core.file_provider",
        "gps_photo_tracker.core.gps_matcher",
        "gps_photo_tracker.core.gpx_parser",
        "gps_photo_tracker.core.kml_parser",
        "gps_photo_tracker.core.tcx_parser",
        "gps_photo_tracker.core.track_parser",
        "gps_photo_tracker.core.checkpoint",
        "gps_photo_tracker.core.concurrency",
        "gps_photo_tracker.core.orientation",
        "gps_photo_tracker.core.param_tuner",
        "gps_photo_tracker.core.report_builder",
        "gps_photo_tracker.core.models",
        "gps_photo_tracker.gui",
        "gps_photo_tracker.gui.main_window",
        "gps_photo_tracker.gui.config_panel",
        "gps_photo_tracker.gui.detail_dialog",
        "gps_photo_tracker.gui.gpx_browser_dialog",
        "gps_photo_tracker.gui.photo_browser_dialog",
        "gps_photo_tracker.gui.photo_preview",
        "gps_photo_tracker.gui.progress_panel",
        "gps_photo_tracker.gui.result_table",
        "gps_photo_tracker.gui.settings_dialog",
        "gps_photo_tracker.gui.worker",
        "gps_photo_tracker.service",
        "gps_photo_tracker.service.tagging_service",
        "gps_photo_tracker.service.cancel_token",
        "gps_photo_tracker.logging_",
        "gps_photo_tracker.logging_.logger",
        # Third-party deps that PyInstaller may miss
        "piexif",
        "gpxpy",
        "geopy",
        "geopy.distance",
        "tenacity",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "scipy",
        "pytest",
        "coverage",
    ],
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GPS Photo Tracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    # Use the PySide6 default window icon — no custom icon yet
    # icon="assets/icon.icns",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GPS Photo Tracker",
)

# macOS .app bundle
app = BUNDLE(
    coll,
    name="GPS Photo Tracker.app",
    icon=None,
    bundle_identifier="com.gps-photo-tracker.app",
    info_plist={
        "CFBundleName": "GPS Photo Tracker",
        "CFBundleShortVersionString": "0.22.0",
        "CFBundleVersion": "0.22.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "GPX Track",
                "CFBundleTypeExtensions": ["gpx"],
                "CFBundleTypeRole": "Viewer",
            },
        ],
    },
)
