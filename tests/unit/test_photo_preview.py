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
            # Cache miss no longer flashes "加载中..." — it keeps the previous
            # display and just schedules the async load (v0.23.1).
            assert preview._pending_thumb_path == "/nonexistent.jpg"

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
        """Regression: browsing back to a previously-viewed photo must NOT
        re-decode from disk — the cache-hit branch reuses the cached pixmap.
        v0.22.0 fixed the re-decode; v0.23.1 switched the decode to QImageReader
        native downscale, so this test patches the _decode_preview seam (agnostic
        to whether the decode uses QPixmap or QImageReader under the hood)."""
        from PIL import Image

        img = Image.new("RGB", (60, 40))
        photo = tmp_path / "photo.jpg"
        img.save(photo, "JPEG")
        path = str(photo)
        QPixmapCache.clear()

        with patch.object(PhotoPreview, "_decode_preview", wraps=preview._decode_preview) as mock_decode:
            preview.show_photo(path, "first view")
            # Let the async _load_thumbnail (QTimer.singleShot) run and populate cache.
            qtbot.waitUntil(lambda: QPixmapCache.find(f"preview:{path}") is not None, timeout=2000)
            qtbot.wait(80)  # let any pending timers (incl. ones leaked from other tests) settle
            after_first = mock_decode.call_count
            assert after_first >= 1  # cache populated via at least one decode

            # Second view is a cache hit — must NOT trigger a NEW decode.
            # (Relative check: robust to leaked-timer noise across the full suite.)
            preview.show_photo(path, "second view")
            qtbot.wait(80)
            assert mock_decode.call_count == after_first

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
