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
    """Stash the exit code for pytest_unconfigure (see hook below)."""
    session.config._gpspt_exit_code = int(exitstatus)


def pytest_unconfigure(config):
    """Exit hard at unconfigure on POSIX — before any teardown stage can
    crash. NOT on Windows: see the platform gate below.

    Closed-but-alive QWidgets (the main_window fixture closes windows but
    never deletes them) accumulate across the suite; on headless CI
    runners the post-summary teardown stages crashed the process: plain
    interpreter finalization segfaulted (Linux) / aborted (macOS 'Pure
    virtual function called'). Destroying widgets or the QApplication
    from hooks was not a fix either — deletion order is platform/
    plugin-state dependent (segfaulted on every CI runner while passing
    locally).

    Windows is the opposite case: hookless it exits cleanly (its round-1
    failure was 3 real test bugs, since fixed), while every hard-exit
    variant crashed it — atexit ran too late (a later-registered unload
    step died with exit 1 first) and os._exit itself crashed with Qt
    background threads alive. Hence: skip the hard exit on win32.

    By unconfigure time the terminal summary and pytest-cov report have
    been printed (they run in sessionfinish), and conftest's unconfigure
    runs BEFORE plugin unconfigure steps — so exiting here preserves all
    output and skips every later teardown, where the POSIX crash lives.
    """
    import os
    import sys

    if sys.platform == "win32":
        return
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(getattr(config, "_gpspt_exit_code", 0))


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
