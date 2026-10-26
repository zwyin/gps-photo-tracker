"""Test fixtures and data factories."""

import gc
from datetime import datetime, timezone
from pathlib import Path

import pytest

from gps_photo_tracker.core.models import (
    GPXSegment,
    GPSInfo,
    MatcherConfig,
    PhotoInfo,
    TrackPoint,
)


def pytest_sessionfinish(session, exitstatus):
    """Controlled Qt teardown BEFORE interpreter shutdown.

    Closed-but-alive QWidgets (the main_window fixture closes windows but
    never deletes them) accumulate across the suite; on headless CI runners
    they were destroyed only after the platform plugin tore down, crashing
    at process exit AFTER the summary line ('libc++abi: Pure virtual
    function called!' on macOS, segfault on Linux) — turning green runs
    into red. Destroy them here while everything is still alive.
    """
    try:
        from PySide6.QtWidgets import QApplication
        from shiboken6 import delete as shiboken_delete
    except ImportError:
        return  # PySide6 not installed (pure-core test environments)
    app = QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        w.close()
    app.processEvents()
    gc.collect()
    # Delete the QApplication itself; Qt then destroys the remaining
    # (closed-but-alive) widgets through its own ordered parent-child
    # teardown. Per-widget shiboken_delete is NOT safe here: the snapshot
    # list goes stale as parent deletions cascade into children.
    try:
        shiboken_delete(app)
    except RuntimeError:
        pass


def utc(h: int, m: int = 0, s: int = 0, day: int = 17, month: int = 2, year: int = 2026) -> float:
    """UTC timestamp factory."""
    return datetime(year, month, day, h, m, s, tzinfo=timezone.utc).timestamp()


def make_point(lat: float, lon: float, ts: float, alt: float | None = None) -> TrackPoint:
    return TrackPoint(timestamp=ts, latitude=lat, longitude=lon, altitude=alt)


def make_segment(points: list[TrackPoint], filename: str = "test.gpx") -> GPXSegment:
    pts = sorted(points, key=lambda p: p.timestamp)
    return GPXSegment(
        filename=filename,
        start=pts[0].timestamp,
        end=pts[-1].timestamp,
        points=pts,
    )


def make_photo(filename: str, ts: float, has_gps: bool = False,
               lat: float | None = None, lon: float | None = None,
               alt: float | None = None) -> PhotoInfo:
    existing_gps = None
    if has_gps and lat is not None and lon is not None:
        existing_gps = GPSInfo(latitude=lat, longitude=lon, altitude=alt)
    return PhotoInfo(
        path=Path(f"/photos/{filename}"),
        filename=filename,
        timestamp=ts,
        has_gps=has_gps,
        existing_gps=existing_gps,
    )


@pytest.fixture
def default_config() -> MatcherConfig:
    return MatcherConfig()
