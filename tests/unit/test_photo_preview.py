"""Tests for PhotoPreview widget."""

from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPixmapCache
from PySide6.QtWidgets import QApplication

from gps_photo_tracker.gui.photo_preview import PhotoPreview


@pytest.fixture
def app(qtbot):
    return QApplication.instance() or QApplication([])


@pytest.fixture
def preview(app, qtbot):
    w = PhotoPreview()
    qtbot.addWidget(w)
    return w


class TestPhotoPreview:

    def test_clear_resets_labels(self, preview):
        preview.clear()
        assert preview._thumb_label.text() == ""
        assert preview._info_label.text() == "选中照片查看预览"

    def test_show_photo_updates_info(self, preview):
        preview.show_photo("/some/path.jpg", "Test info text")
        assert preview._info_label.text() == "Test info text"

    def test_show_photo_empty_path_clears_thumb(self, preview):
        preview._thumb_label.setText("existing")
        preview.show_photo("", "No photo")
        assert preview._thumb_label.text() == ""

    def test_show_photo_cached_pixmap(self, preview):
        cache_key = "thumb:/cached/photo.jpg"
        pm = QPixmap(100, 100)
        pm.fill(Qt.GlobalColor.red)
        QPixmapCache.insert(cache_key, pm)
        preview.show_photo("/cached/photo.jpg", "Cached")
        # Should have set the pixmap (not "加载中...")
        assert preview._thumb_label.pixmap() is not None

    def test_show_photo_async_triggers_timer(self, preview):
        with patch.object(PhotoPreview, "_load_thumbnail"):
            preview.show_photo("/nonexistent.jpg", "Loading test")
            assert preview._pending_thumb_path == "/nonexistent.jpg"
            assert preview._thumb_label.text() == "加载中..."

    def test_load_thumbnail_null_pixmap_clears(self, preview):
        preview._pending_thumb_path = "/nonexistent_file.jpg"
        preview._load_thumbnail()
        assert preview._thumb_label.text() == ""

    def test_load_thumbnail_valid_image(self, preview, tmp_path):
        from PIL import Image
        img = Image.new("RGB", (10, 10))
        img.save(tmp_path / "test.jpg", "JPEG")
        preview._pending_thumb_path = str(tmp_path / "test.jpg")
        preview._load_thumbnail()
        assert preview._thumb_label.pixmap() is not None

    def test_load_thumbnail_empty_path_returns_early(self, preview):
        preview._pending_thumb_path = ""
        preview._load_thumbnail()
        # Should not crash, just return

    def test_load_thumbnail_caches_result(self, preview, tmp_path):
        from PIL import Image
        img = Image.new("RGB", (10, 10))
        img.save(tmp_path / "test.jpg", "JPEG")
        path = str(tmp_path / "test.jpg")
        QPixmapCache.clear()
        preview._pending_thumb_path = path
        preview._load_thumbnail()
        cached = QPixmapCache.find(f"thumb:{path}")
        assert cached is not None
