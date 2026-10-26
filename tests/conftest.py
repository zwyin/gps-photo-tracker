"""Test fixtures and data factories."""

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
    """Skip interpreter finalization on Qt builds: exit hard via atexit.

    Closed-but-alive QWidgets (the main_window fixture closes windows but
    never deletes them) accumulate across the suite; on headless CI runners
    interpreter-finalization teardown crashed at process exit AFTER the
    summary line ('libc++abi: Pure virtual function called!' on macOS,
    segfault on Linux/Windows), turning green runs red. Deleting widgets
    or the QApplication from THIS hook was not a fix either — deletion
    order differs per platform and segfaulted on every CI runner while
    passing locally. Instead, schedule os._exit as the LAST atexit
    handler (atexit is LIFO and this registers before pytest's terminal
    summary / pytest-cov report run in their own sessionfinish hooks):
    everything still prints and flushes, then the process dies before
    the finalization stage where the crash lives.
    """
    import atexit
    import os

    atexit.register(lambda: os._exit(exitstatus))


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
