"""Tests for GPSPointPicker and ReviewDialog GUI components."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gps_photo_tracker.core.models import TrackPoint


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
