"""Photo preview widget with async thumbnail loading."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImageReader, QPixmap, QPixmapCache
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

# Longest side of the cached preview pixmap. Large enough for the preview pane
# (~30% of window width, incl. high-DPI). Decoded ONCE via QImageReader's
# *native* JPEG downscale (setScaledSize) — the decoder produces the target
# size directly instead of decoding full-res then scaling, which is far faster
# on Windows (libjpeg). Result is cached so repeated views never touch disk.
#
# v0.22.0 fixed cache-HIT lag but the cache-MISS path still did a full decode
# + scale on Windows → "加载中" flash + slowness on forward browse. v0.23.1
# switches to QImageReader native downscale (fast miss) and drops the "加载中"
# flash (keep showing the previous photo until the new one is ready).
#
# Cache key `preview:{path}` is namespaced vs PhotoBrowserDialog's `thumb:`
# (QPixmapCache is process-global — v0.22.0 review).
_PREVIEW_MAX_PX = 1024


class PhotoPreview(QWidget):
    """Thumbnail preview + info label, with QPixmapCache async loading and dynamic resize."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # QPixmapCache size limit is set ONCE at app startup (run_app), not here
        # — it's process-global (v0.22.0 review, M2).
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._thumb_label = QLabel()
        self._thumb_label.setMinimumSize(80, 80)
        self._thumb_label.setStyleSheet("background: #e8e8e8; border: 1px solid #ccc;")
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._thumb_label)

        self._info_label = QLabel("选中照片查看预览")
        self._info_label.setWordWrap(True)
        layout.addWidget(self._info_label, stretch=1)

        self._pending_thumb_path: str = ""
        self._full_pixmap: QPixmap | None = None

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
            # Cache hit: reuse the already-decoded preview pixmap. MUST NOT
            # re-decode the full JPEG here — that was the browse-lag root cause.
            self._full_pixmap = cached
            self._rescale()
        else:
            # Cache miss: keep showing the CURRENT photo until the new one is
            # ready (don't flash "加载中..." — it clears the image and feels
            # janky/slow). Just schedule the async decode; it swaps in when done.
            self._pending_thumb_path = photo_path
            QTimer.singleShot(10, self._load_thumbnail)

    def clear(self):
        self._thumb_label.clear()
        self._full_pixmap = None
        self._info_label.setText("选中照片查看预览")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        thumb_w = max(int(self.width() * 0.3), 80)
        self._thumb_label.setFixedWidth(thumb_w)
        if self._full_pixmap and not self._full_pixmap.isNull():
            self._rescale()

    def _rescale(self):
        if not self._full_pixmap or self._full_pixmap.isNull():
            return
        thumb_w = max(int(self.width() * 0.3), 80)
        h = self.height()
        scaled = self._full_pixmap.scaled(
            thumb_w, h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._thumb_label.setPixmap(scaled)

    def _decode_preview(self, path: str) -> QPixmap | None:
        """Decode JPEG directly to ≤ _PREVIEW_MAX_PX via QImageReader's native
        downscale (setScaledSize), apply EXIF orientation. Runs once per photo;
        the result is cached. Native downscale is dramatically faster than
        decode-full-res-then-scale, especially on Windows (libjpeg DCT scaling).
        """
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
            # Stagger loads so the immediately-adjacent photo loads first
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
        # cached this path, skip the redundant decode. Null-pixmap guard mirrors
        # show_photo so a stray NULL entry can't pin the UI.
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
