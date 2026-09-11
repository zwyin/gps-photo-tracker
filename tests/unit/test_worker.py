"""Tests for gui.worker.Worker — InputSelection + photo_root contract."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from gps_photo_tracker.core.models import (
    GPXSegment,
    InputSelection,
    MatcherConfig,
    ProcessMode,
    ProcessOptions,
    TrackPoint,
)
from gps_photo_tracker.gui.worker import Worker


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_worker_holds_selections_and_photo_root(tmp_path, qapp):
    """Worker stores the InputSelection objects and photo_root verbatim."""
    g = InputSelection.of([tmp_path / "a.gpx"])
    p = InputSelection.of([tmp_path / "x.jpg"])
    w = Worker(g, p, config=MatcherConfig(), options=ProcessOptions(mode=ProcessMode.PREVIEW),
               photo_root=tmp_path)
    assert w._gps_selection is g
    assert w._photo_selection is p
    assert w._photo_root == tmp_path


def test_worker_photo_root_defaults_none(qapp):
    """photo_root defaults to None when not supplied."""
    g = InputSelection.of([Path("/tmp/a.gpx")])
    p = InputSelection.of([Path("/tmp/x.jpg")])
    w = Worker(g, p, config=MatcherConfig(), options=ProcessOptions(mode=ProcessMode.PREVIEW))
    assert w._photo_root is None


def test_segment_summary_includes_points_for_map(qapp):
    """scan_done segment dicts carry track points (map panel polyline source)."""
    from gps_photo_tracker.gui.worker import _segment_summary

    seg = GPXSegment(
        filename="t.gpx",
        start=100.0,
        end=200.0,
        points=[TrackPoint(timestamp=100.0, latitude=31.1, longitude=121.1),
                TrackPoint(timestamp=200.0, latitude=31.2, longitude=121.2)],
    )
    d = _segment_summary(seg)
    assert d["filename"] == "t.gpx"
    assert d["start"] == 100.0 and d["end"] == 200.0
    assert d["point_count"] == 2
    assert d["points"] == [
        {"latitude": 31.1, "longitude": 121.1},
        {"latitude": 31.2, "longitude": 121.2},
    ]
