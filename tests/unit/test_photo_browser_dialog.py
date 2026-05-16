"""Tests for PhotoBrowserDialog."""

from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPixmapCache
from PySide6.QtWidgets import QApplication

from gps_photo_tracker.gui.photo_browser_dialog import PhotoBrowserDialog


@pytest.fixture
def app(qtbot):
    return QApplication.instance() or QApplication([])


def _make_photos():
    return [
        {"filename": "gps1.jpg", "path": "/photos/gps1.jpg", "timestamp": 1000.0,
         "has_gps": True, "latitude": 25.0, "longitude": 100.0, "altitude": 50},
        {"filename": "nogps.jpg", "path": "/photos/nogps.jpg", "timestamp": 2000.0,
         "has_gps": False},
        {"filename": "gps2.jpg", "path": "/photos/gps2.jpg", "timestamp": 1500.0,
         "has_gps": True, "latitude": 26.0, "longitude": 101.0, "altitude": None},
    ]


@pytest.fixture
def dialog(app, qtbot):
    d = PhotoBrowserDialog(_make_photos())
    qtbot.addWidget(d)
    return d


class TestPhotoBrowserDialog:

    def test_initial_populate_shows_all(self, dialog):
        assert dialog._table.rowCount() == 3

    def test_summary_text(self, dialog):
        assert "共 3" in dialog._summary.text()
        assert "2" in dialog._summary.text()  # 2 with GPS

    def test_filter_has_gps(self, dialog):
        dialog._filter_cb.setCurrentIndex(1)  # "有GPS"
        assert dialog._table.rowCount() == 2

    def test_filter_no_gps(self, dialog):
        dialog._filter_cb.setCurrentIndex(2)  # "无GPS"
        assert dialog._table.rowCount() == 1

    def test_filter_all(self, dialog):
        dialog._filter_cb.setCurrentIndex(0)
        assert dialog._table.rowCount() == 3

    def test_search_filter(self, dialog):
        dialog._search_edit.setText("nogps")
        assert dialog._table.rowCount() == 1

    def test_search_case_insensitive(self, dialog):
        dialog._search_edit.setText("NOGPS")
        assert dialog._table.rowCount() == 1

    def test_search_empty_shows_all(self, dialog):
        dialog._search_edit.setText("")
        assert dialog._table.rowCount() == 3

    def test_sort_by_filename(self, dialog):
        dialog._sort_cb.setCurrentIndex(0)
        first = dialog._table.item(0, 0).text()
        assert first == "gps1.jpg"

    def test_sort_by_timestamp(self, dialog):
        dialog._sort_cb.setCurrentIndex(1)
        first = dialog._table.item(0, 0).text()
        assert first == "gps1.jpg"  # timestamp 1000 < 1500 < 2000

    def test_on_selection_updates_info(self, dialog):
        dialog._table.selectRow(0)
        info = dialog._info_label.text()
        assert "gps1.jpg" in info
        assert "25.0000" in info

    def test_on_selection_no_gps_shows_dash(self, dialog):
        # Filter to show only no-gps
        dialog._filter_cb.setCurrentIndex(2)
        dialog._table.selectRow(0)
        info = dialog._info_label.text()
        assert "—" in info

    def test_on_selection_clears_when_deselected(self, dialog):
        dialog._table.selectRow(0)
        dialog._table.clearSelection()
        assert "选中照片查看详情" in dialog._info_label.text()

    def test_load_thumbnail_null_path_clears(self, dialog):
        dialog._pending_thumb_path = "/nonexistent_file_xyz.jpg"
        dialog._load_thumbnail()
        assert dialog._thumb_label.pixmap() is None or dialog._thumb_label.text() == ""

    def test_load_thumbnail_valid_image(self, dialog, tmp_path):
        from PIL import Image
        img_path = tmp_path / "test_thumb.jpg"
        Image.new("RGB", (100, 100), color="green").save(str(img_path))
        dialog._pending_thumb_path = str(img_path)
        dialog._load_thumbnail()
        assert dialog._thumb_label.pixmap() is not None

    def test_load_thumbnail_empty_path_returns(self, dialog):
        dialog._pending_thumb_path = ""
        dialog._load_thumbnail()  # should not crash

    def test_fmt_time_valid(self):
        result = PhotoBrowserDialog._fmt_time(1000.0)
        assert "1970" in result

    def test_fmt_time_invalid(self):
        result = PhotoBrowserDialog._fmt_time(float("nan"))
        assert result == "—"

    def test_selection_with_cached_pixmap(self, dialog):
        cache_key = "thumb:/photos/gps1.jpg"
        pm = QPixmap(100, 100)
        pm.fill(Qt.GlobalColor.red)
        QPixmapCache.insert(cache_key, pm)
        dialog._table.selectRow(0)
        assert dialog._thumb_label.pixmap() is not None
