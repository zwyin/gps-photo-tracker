"""Tests for GPSPointPicker and ReviewDialog GUI components."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gps_photo_tracker.core.models import (
    GPSInfo, GPXSegment, MatchResult, PhotoInfo,
    ReviewAction, ReviewDecision, ReviewState, TrackPoint,
)


@pytest.fixture
def app(qtbot):
    return QApplication.instance() or QApplication([])


class TestGPSPointPicker:

    def test_populates_track_points(self, app, qtbot):
        from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker
        points = [
            TrackPoint(timestamp=1000.0, latitude=25.0, longitude=100.0, altitude=100),
            TrackPoint(timestamp=1050.0, latitude=25.001, longitude=100.001, altitude=110),
        ]
        picker = GPSPointPicker(points, photo_timestamp=1025.0)
        qtbot.addWidget(picker)
        assert picker._table.rowCount() == 2

    def test_confirm_returns_selected_point(self, app, qtbot):
        from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker
        points = [
            TrackPoint(timestamp=1000.0, latitude=25.0, longitude=100.0, altitude=100),
            TrackPoint(timestamp=1050.0, latitude=25.001, longitude=100.001, altitude=110),
        ]
        picker = GPSPointPicker(points, photo_timestamp=1025.0)
        qtbot.addWidget(picker)
        picker._table.selectRow(0)
        result = picker.get_selected_point()
        assert result is not None
        assert result.latitude == 25.0

    def test_no_selection_returns_none(self, app, qtbot):
        from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker
        points = [
            TrackPoint(timestamp=1000.0, latitude=25.0, longitude=100.0),
        ]
        picker = GPSPointPicker(points, photo_timestamp=1000.0)
        qtbot.addWidget(picker)
        picker._table.clearSelection()
        assert picker.get_selected_point() is None

    def test_empty_points_disables_confirm(self, app, qtbot):
        from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker
        picker = GPSPointPicker([], photo_timestamp=1000.0)
        qtbot.addWidget(picker)
        assert not picker._confirm_btn.isEnabled()


def _make_failed_result(filename: str, reason: str = "time_diff") -> MatchResult:
    return MatchResult(
        photo=PhotoInfo(path=Path(f"/tmp/{filename}"), filename=filename,
                        timestamp=1000.0, has_gps=False),
        success=False, reject_reason=reason,
    )


def _make_review_state():
    seg = GPXSegment(
        filename="track.gpx", start=900.0, end=1100.0,
        points=[
            TrackPoint(timestamp=950.0, latitude=25.0, longitude=100.0, altitude=100),
            TrackPoint(timestamp=1000.0, latitude=25.001, longitude=100.001, altitude=110),
        ],
    )
    return ReviewState(
        failed_results=[_make_failed_result("fail1.jpg"), _make_failed_result("fail2.jpg")],
        gps_segments=[seg],
    )


class TestReviewDialog:

    def test_table_shows_all_failures(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        assert dialog._table.rowCount() == 2

    def test_skip_all_sets_skip_decisions(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._skip_all()
        assert len(dialog._state.decisions) == 2
        for d in dialog._state.decisions.values():
            assert d.action == ReviewAction.SKIP

    def test_confirm_with_no_decisions_treated_as_skip(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._confirm()
        for d in dialog._state.decisions.values():
            assert d.action == ReviewAction.SKIP

    def test_get_state_returns_review_state(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        assert dialog.get_state() is state
