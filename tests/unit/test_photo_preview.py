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


class TestPreviewSplitter:
    """v0.24.0: QSplitter layout, adaptive _rescale, state persistence."""

    def test_layout_is_splitter_with_thumb_and_info(self, preview):
        """PhotoPreview uses a QSplitter: thumb (left, expanding) + info (right)."""
        from PySide6.QtWidgets import QSplitter
        sp = preview.findChild(QSplitter)
        assert sp is preview._splitter
        assert sp.widget(0) is preview._thumb_label
        assert sp.widget(1) is preview._info_label
        assert preview._info_label.minimumWidth() >= 200
        assert preview._info_label.maximumWidth() <= 360

    def test_rescale_uses_label_size_not_30_percent(self, preview):
        """_rescale scales to _thumb_label's actual size (not 30% of widget)."""
        pm = QPixmap(200, 100)
        pm.fill(Qt.GlobalColor.red)
        preview._full_pixmap = pm
        preview._thumb_label.resize(160, 120)
        preview._rescale()
        shown = preview._thumb_label.pixmap()
        assert shown is not None
        # 200x100 (2:1) in 160x120 → width-bound → 160x80
        assert shown.width() == 160
        assert shown.height() == 80

    def test_rescale_falls_back_to_minimum_when_width_zero(self, preview, monkeypatch):
        """When _thumb_label.width() is 0 (not laid out), fall back to minimumWidth."""
        pm = QPixmap(100, 100)
        pm.fill(Qt.GlobalColor.red)
        preview._full_pixmap = pm
        monkeypatch.setattr(preview._thumb_label, "width", lambda: 0)
        monkeypatch.setattr(preview._thumb_label, "height", lambda: 100)
        preview._rescale()
        shown = preview._thumb_label.pixmap()
        assert shown is not None
        # Fell back to minimumWidth 80 → 100x100 in (80,100) → 80x80
        assert shown.width() == 80

    def test_rescale_noop_without_pixmap(self, preview):
        """_rescale early-returns when there is no _full_pixmap."""
        preview._full_pixmap = None
        existing = QPixmap(50, 50)
        existing.fill(Qt.GlobalColor.blue)
        preview._thumb_label.setPixmap(existing)
        preview._rescale()
        assert preview._thumb_label.pixmap().width() == 50  # unchanged

    def test_splitter_moved_persists_state(self, preview, monkeypatch):
        """Dragging the splitter saves its state via QSettings."""
        saved = {}
        class _FakeSettings:
            def __init__(self, *a, **k): pass
            def value(self, k, d=None, t=None):
                return saved.get(k)
            def setValue(self, k, v):
                saved[k] = v
        monkeypatch.setattr(
            "gps_photo_tracker.gui.photo_preview.QSettings", _FakeSettings)
        preview._on_splitter_moved()
        assert "preview_splitter_state" in saved

    def test_splitter_state_restored_on_init(self, monkeypatch, qtbot):
        """A new PhotoPreview restores the saved splitter proportions."""
        state_box = [None]
        class _FakeSettings:
            def __init__(self, *a, **k): pass
            def value(self, k, d=None, t=None):
                return state_box[0]
            def setValue(self, k, v):
                state_box[0] = v
        monkeypatch.setattr(
            "gps_photo_tracker.gui.photo_preview.QSettings", _FakeSettings)
        p1 = PhotoPreview()
        qtbot.addWidget(p1)
        p1._splitter.setSizes([500, 200])
        p1._on_splitter_moved()           # persists → state_box[0] = state
        assert state_box[0] is not None
        p2 = PhotoPreview()               # restores from state_box[0]
        qtbot.addWidget(p2)
        # Info width restored exactly (200); thumb width may be clamped to the
        # widget's actual width (not shown in test → smaller than 500).
        assert p2._splitter.sizes()[1] == 200

    def test_resize_event_rescales_when_pixmap_present(self, preview):
        """resizeEvent calls _rescale when a pixmap is loaded."""
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QResizeEvent
        pm = QPixmap(200, 100)
        pm.fill(Qt.GlobalColor.green)
        preview._full_pixmap = pm
        preview._thumb_label.resize(120, 120)
        preview.resizeEvent(QResizeEvent(QSize(400, 300), QSize(100, 100)))
        shown = preview._thumb_label.pixmap()
        assert shown is not None  # _rescale ran on resize

    def test_no_fixed_width_30_percent(self, preview):
        """The old setFixedWidth(self.width()*0.3) is gone — _thumb_label has
        no fixed width policy; it expands via the splitter stretch factor."""
        # _thumb_label should NOT have a fixed width (the old cap is removed).
        from PySide6.QtWidgets import QSizePolicy
        sp = preview._thumb_label.sizePolicy()
        assert sp.horizontalPolicy() != QSizePolicy.Policy.Fixed


class TestDecodePreviewBranches:
    """Branch coverage for _decode_preview, preload_photos, _preload_one."""

    def test_decode_large_image_uses_native_downscale(self, tmp_path):
        """Images > _PREVIEW_MAX_PX are decoded at reduced size (setScaledSize)."""
        from PIL import Image
        big = tmp_path / "big.jpg"
        Image.new("RGB", (2000, 1500)).save(str(big), "JPEG")
        from gps_photo_tracker.gui.photo_preview import _PREVIEW_MAX_PX
        pixmap = PhotoPreview()._decode_preview(str(big))
        assert pixmap is not None and not pixmap.isNull()
        assert max(pixmap.width(), pixmap.height()) <= _PREVIEW_MAX_PX

    def test_decode_non_image_returns_none(self, tmp_path):
        """A non-image file → QImageReader.canRead() False → None."""
        bad = tmp_path / "notimage.jpg"
        bad.write_bytes(b"this is not a JPEG")
        assert PhotoPreview()._decode_preview(str(bad)) is None

    def test_decode_truncated_jpeg_returns_none(self, tmp_path):
        """A truncated JPEG → QImageReader.read() isNull → None."""
        corrupt = tmp_path / "corrupt.jpg"
        corrupt.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x02\x00\x00")
        assert PhotoPreview()._decode_preview(str(corrupt)) is None

    def test_decode_applies_exif_orientation(self, tmp_path):
        """An image with EXIF orientation != 1 gets the transform applied."""
        import piexif
        from PIL import Image
        p = tmp_path / "portrait.jpg"
        Image.new("RGB", (100, 200)).save(str(p), "JPEG")
        exif = {"0th": {piexif.ImageIFD.Orientation: 6}}  # rotate 90°
        piexif.insert(piexif.dump(exif), str(p))
        pixmap = PhotoPreview()._decode_preview(str(p))
        assert pixmap is not None
        # Original 100×200, rotated 90° → 200×100
        assert pixmap.width() == 200 and pixmap.height() == 100

    def test_preload_photos_caches(self, preview, tmp_path, qtbot):
        """preload_photos schedules async decodes that populate the cache."""
        from PIL import Image
        f1 = tmp_path / "a.jpg"
        f2 = tmp_path / "b.jpg"
        Image.new("RGB", (60, 40)).save(str(f1), "JPEG")
        Image.new("RGB", (60, 40)).save(str(f2), "JPEG")
        QPixmapCache.clear()
        preview.preload_photos([str(f1), str(f2)])
        qtbot.waitUntil(
            lambda: QPixmapCache.find(f"preview:{str(f1)}") is not None
            and QPixmapCache.find(f"preview:{str(f2)}") is not None,
            timeout=2000)
        assert QPixmapCache.find(f"preview:{str(f1)}") is not None
        assert QPixmapCache.find(f"preview:{str(f2)}") is not None

    def test_preload_skips_empty_and_cached(self, preview, tmp_path, qtbot):
        """preload_photos skips empty paths and already-cached paths."""
        from PIL import Image
        f = tmp_path / "cached.jpg"
        Image.new("RGB", (60, 40)).save(str(f), "JPEG")
        QPixmapCache.clear()
        # Pre-populate the cache manually.
        from PySide6.QtGui import QPixmap
        QPixmapCache.insert(f"preview:{str(f)}", QPixmap(10, 10))
        preview.preload_photos(["", str(f)])
        qtbot.wait(200)  # let any stray timers fire
        cached = QPixmapCache.find(f"preview:{str(f)}")
        assert cached is not None and cached.width() == 10  # not re-decoded
