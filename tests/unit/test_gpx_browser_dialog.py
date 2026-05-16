"""Tests for GPXBrowserDialog."""

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox

from gps_photo_tracker.core.models import GPXSegment, TrackPoint
from gps_photo_tracker.gui.gpx_browser_dialog import GPXBrowserDialog


@pytest.fixture
def app(qtbot):
    return QApplication.instance() or QApplication([])


def _make_segments():
    return [
        GPXSegment(filename="track.gpx", start=1000.0, end=2000.0,
                   points=[TrackPoint(timestamp=1000.0, latitude=25.0, longitude=100.0),
                           TrackPoint(timestamp=1500.0, latitude=25.1, longitude=100.1)]),
        GPXSegment(filename="track.gpx", start=3000.0, end=4000.0,
                   points=[TrackPoint(timestamp=3000.0, latitude=26.0, longitude=101.0)]),
        GPXSegment(filename="other.gpx", start=5000.0, end=6000.0,
                   points=[TrackPoint(timestamp=5000.0, latitude=27.0, longitude=102.0),
                           TrackPoint(timestamp=5500.0, latitude=27.1, longitude=102.1),
                           TrackPoint(timestamp=6000.0, latitude=27.2, longitude=102.2)]),
    ]


def _make_dict_segments():
    return [
        {"filename": "a.gpx", "point_count": 5, "start": 100.0, "end": 200.0},
        {"filename": "b.gpx", "point_count": 3, "start": 300.0, "end": 400.0},
    ]


@pytest.fixture
def dialog(app, qtbot):
    d = GPXBrowserDialog(_make_segments())
    qtbot.addWidget(d)
    return d


class TestGPXBrowserDialog:

    def test_table_populated(self, dialog):
        assert dialog._table.rowCount() == 3

    def test_dict_segments(self, app, qtbot):
        d = GPXBrowserDialog(_make_dict_segments())
        qtbot.addWidget(d)
        assert d._table.rowCount() == 2

    def test_on_selection_shows_detail(self, dialog):
        dialog._table.selectRow(0)
        text = dialog._detail_label.text()
        assert "track.gpx" in text
        assert "段数" in text

    def test_on_selection_clears_when_deselected(self, dialog):
        dialog._table.selectRow(0)
        dialog._table.clearSelection()
        assert "点击" in dialog._detail_label.text()

    def test_set_all_checked(self, dialog):
        dialog._set_all_checked(False)
        for i in range(dialog._table.rowCount()):
            widget = dialog._table.cellWidget(i, 0)
            cb = widget.findChild(QCheckBox)
            assert not cb.isChecked()
        dialog._set_all_checked(True)
        for i in range(dialog._table.rowCount()):
            widget = dialog._table.cellWidget(i, 0)
            cb = widget.findChild(QCheckBox)
            assert cb.isChecked()

    def test_get_excluded_filenames_all_checked(self, dialog):
        assert dialog.get_excluded_filenames() == set()

    def test_get_excluded_filenames_unchecked(self, dialog):
        dialog._set_all_checked(False)
        excluded = dialog.get_excluded_filenames()
        assert "track.gpx" in excluded
        assert "other.gpx" in excluded

    def test_get_excluded_filenames_partial(self, dialog):
        # Uncheck just the first row
        widget = dialog._table.cellWidget(0, 0)
        cb = widget.findChild(QCheckBox)
        cb.setChecked(False)
        excluded = dialog.get_excluded_filenames()
        assert "track.gpx" in excluded
        assert "other.gpx" not in excluded

    def test_fmt_time_valid(self):
        result = GPXBrowserDialog._fmt_time(1000.0)
        assert "1970" in result

    def test_fmt_time_invalid(self):
        result = GPXBrowserDialog._fmt_time(float("nan"))
        assert result == "—"

    def test_fmt_date_valid(self):
        result = GPXBrowserDialog._fmt_date(1000.0)
        assert "01" in result

    def test_fmt_date_invalid(self):
        result = GPXBrowserDialog._fmt_date(float("nan"))
        assert result == "—"

    def test_empty_segments(self, app, qtbot):
        d = GPXBrowserDialog([])
        qtbot.addWidget(d)
        assert d._table.rowCount() == 0
