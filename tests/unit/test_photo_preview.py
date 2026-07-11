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
        cache_key = "preview:/cached/photo.jpg"
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
        cached = QPixmapCache.find(f"preview:{path}")
        assert cached is not None

    def test_show_photo_cache_hit_does_not_redecode(self, preview, tmp_path, qtbot):
        """Regression (v0.22.0): browsing back to a previously-viewed photo must
        NOT re-decode the JPEG from disk. The old cache-hit branch re-called
        QPixmap(path) on every selection change, causing ~0.5s/photo lag on
        Windows (libjpeg) while macOS (ImageIO) hid the cost."""
        from PIL import Image
        import gps_photo_tracker.gui.photo_preview as ppmod

        img = Image.new("RGB", (60, 40))
        photo = tmp_path / "photo.jpg"
        img.save(photo, "JPEG")
        path = str(photo)
        QPixmapCache.clear()

        real_qpix = ppmod.QPixmap
        decodes: list[str] = []

        def counting_qpix(*args, **kwargs):
            # Only a path-string argument means "decode from disk".
            if args and isinstance(args[0], str):
                decodes.append(args[0])
            return real_qpix(*args, **kwargs)

        with patch.object(ppmod, "QPixmap", counting_qpix):
            preview.show_photo(path, "first view")
            # Let the async _load_thumbnail (QTimer.singleShot) run and populate cache.
            qtbot.waitUntil(lambda: QPixmapCache.find(f"preview:{path}") is not None, timeout=2000)
            after_first = len(decodes)
            assert after_first >= 1  # cache populated via at least one decode

            # Second view is a cache hit — must NOT decode from disk again.
            preview.show_photo(path, "second view")
            assert len(decodes) == after_first

    def test_caches_under_preview_namespace(self, preview, tmp_path):
        """PhotoPreview must cache under the `preview:` namespace, NOT `thumb:`
        (owned by PhotoBrowserDialog's 150x150 thumbnails). QPixmapCache is
        process-global, so sharing the key would serve wrong-sized pixmaps across
        widgets (v0.22.0 review, M1)."""
        from PIL import Image
        img = Image.new("RGB", (40, 30))
        p = tmp_path / "ns.jpg"
        img.save(p, "JPEG")
        path = str(p)
        QPixmapCache.clear()
        preview._pending_thumb_path = path
        preview._load_thumbnail()
        assert QPixmapCache.find(f"preview:{path}") is not None
        assert QPixmapCache.find(f"thumb:{path}") is None
