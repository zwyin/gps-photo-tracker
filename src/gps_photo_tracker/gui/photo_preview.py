"""Photo preview widget: adaptive image + info text in a draggable splitter."""

from PySide6.QtCore import Qt, QTimer, QSettings
from PySide6.QtGui import QImageReader, QPixmap, QPixmapCache
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSplitter, QWidget

# Longest side of the cached preview pixmap. Decoded ONCE via QImageReader's
# native JPEG downscale (setScaledSize) — far faster on Windows than
# decode-full-then-scale. Cached so repeated views never touch disk.
# (v0.22.0 fixed cache-HIT lag; v0.23.1 fixed cache-MISS speed; v0.24.0 made
# the preview adaptive: image + info in a draggable splitter, image fills its
# slot on both width and height — no more 30% fixed-width cap.)
_PREVIEW_MAX_PX = 1024
_SETTINGS_ORG = "GPSPhotoTracker"
_SETTINGS_APP = "GPSPhotoTracker"
_SPLITTER_STATE_KEY = "preview_splitter_state"


class PhotoPreview(QWidget):
    """Image preview + info text in a horizontal QSplitter.

    Drag the splitter handle to resize the image vs the info text. The image
    fills its slot (adaptive width AND height — v0.24.0 removed the 30%
    fixed-width cap). Splitter state persists across runs via QSettings.

    Cache key `preview:{path}` is namespaced vs PhotoBrowserDialog's `thumb:`
    (QPixmapCache is process-global — v0.22.0 review).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(4)
        self._splitter.setStyleSheet(
            "QSplitter::handle { background: #c0c0c0; }"
            "QSplitter::handle:hover { background: #4a9eff; }"
        )
        outer.addWidget(self._splitter)

        self._thumb_label = QLabel()
        self._thumb_label.setMinimumSize(80, 80)
        self._thumb_label.setStyleSheet("background: #e8e8e8; border: 1px solid #ccc;")
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._splitter.addWidget(self._thumb_label)

        self._info_label = QLabel("选中照片查看预览")
        self._info_label.setWordWrap(True)
        self._info_label.setMinimumWidth(200)
        self._info_label.setMaximumWidth(360)
        self._splitter.addWidget(self._info_label)

        # Image expands; info keeps a fixed-ish width.
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)

        self._splitter.splitterMoved.connect(self._on_splitter_moved)

        self._pending_thumb_path: str = ""
        self._full_pixmap: QPixmap | None = None

        # Restore saved splitter proportions (image-vs-info widths).
        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        state = settings.value(_SPLITTER_STATE_KEY)
        if state:
            self._splitter.restoreState(state)

    def _on_splitter_moved(self, *_):
        """Re-scale the image to the new thumb-slot size and persist state."""
        self._rescale()
        QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue(
            _SPLITTER_STATE_KEY, self._splitter.saveState()
        )

    def show_photo(self, photo_path: str, info_text: str):
        """Update info immediately, load thumbnail asynchronously."""
        self._info_label.setText(info_text)
        if not photo_path:
            self._thumb_label.clear()
            self._full_pixmap = None
            return
        cache_key = f"preview:{photo_path}"
        cached = QPixmapCache.find(cache_key)
        if cached is not None and not cached.isNull():
            # Cache hit: reuse the already-decoded preview pixmap.
            self._full_pixmap = cached
            self._rescale()
        else:
            # Cache miss: keep showing the current photo until the new one is
            # ready (no "加载中..." flash). Schedule the async decode.
            self._pending_thumb_path = photo_path
            QTimer.singleShot(10, self._load_thumbnail)

    def clear(self):
        self._thumb_label.clear()
        self._full_pixmap = None
        self._info_label.setText("选中照片查看预览")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._full_pixmap and not self._full_pixmap.isNull():
            self._rescale()

    def _rescale(self):
        """Scale _full_pixmap to the thumb label's current size (KeepAspectRatio).

        Falls back to the label's minimum size when it hasn't been laid out yet
        (e.g. in tests / before first show), so a cache-hit show_photo still
        produces a visible pixmap.
        """
        if not self._full_pixmap or self._full_pixmap.isNull():
            return
        tw = self._thumb_label.width()
        th = self._thumb_label.height()
        if tw <= 0:
            tw = self._thumb_label.minimumWidth()
        if th <= 0:
            th = self._thumb_label.minimumHeight()
        if tw <= 0 or th <= 0:
            return
        scaled = self._full_pixmap.scaled(
            tw, th,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._thumb_label.setPixmap(scaled)

    def _decode_preview(self, path: str) -> QPixmap | None:
        """Decode JPEG directly to ≤ _PREVIEW_MAX_PX via QImageReader's native
        downscale, apply EXIF orientation. Native downscale is far faster than
        decode-full-then-scale, especially on Windows (libjpeg DCT scaling)."""
        reader = QImageReader(str(path))
        if not reader.canRead():
            return None
        orig = reader.size()
        if orig.width() > _PREVIEW_MAX_PX or orig.height() > _PREVIEW_MAX_PX:
            target = orig.scaled(
                _PREVIEW_MAX_PX, _PREVIEW_MAX_PX,
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            reader.setScaledSize(target)
        img = reader.read()
        if img.isNull():
            return None
        pixmap = QPixmap.fromImage(img)
        from pathlib import Path
        from gps_photo_tracker.core.orientation import OrientationReader
        orientation = OrientationReader.get_orientation(Path(path))
        if orientation and orientation != 1:
            pixmap = OrientationReader.apply_orientation(pixmap, orientation)
        return pixmap

    def preload_photos(self, paths: list[str]):
        """Load thumbnails into cache without displaying them."""
        for i, path in enumerate(paths):
            if not path:
                continue
            if QPixmapCache.find(f"preview:{path}"):
                continue
            QTimer.singleShot(50 + i * 30, lambda p=path: self._preload_one(p))

    def _preload_one(self, path: str):
        if QPixmapCache.find(f"preview:{path}"):
            return
        pixmap = self._decode_preview(path)
        if pixmap is not None:
            QPixmapCache.insert(f"preview:{path}", pixmap)

    def _load_thumbnail(self):
        path = self._pending_thumb_path
        if not path:
            return
        # Dedupe rapid navigation: if another scheduled timer already decoded &
        # cached this path, skip the redundant decode.
        cached = QPixmapCache.find(f"preview:{path}")
        if cached is not None and not cached.isNull():
            return
        pixmap = self._decode_preview(path)
        if pixmap is None:
            self._full_pixmap = None
            self._thumb_label.clear()
            return
        QPixmapCache.insert(f"preview:{path}", pixmap)
        self._full_pixmap = pixmap
        self._rescale()
