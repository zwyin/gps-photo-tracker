"""Photo preview widget with async thumbnail loading."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QPixmapCache
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class PhotoPreview(QWidget):
    """Thumbnail preview + info label, with QPixmapCache async loading and dynamic resize."""

    def __init__(self, parent=None):
        super().__init__(parent)
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
            return

        cache_key = f"thumb:{photo_path}"
        cached = QPixmapCache.find(cache_key)
        if cached:
            # Reload full pixmap for dynamic rescaling
            full = QPixmap(photo_path)
            if not full.isNull():
                from pathlib import Path
                from gps_photo_tracker.core.orientation import OrientationReader
                orientation = OrientationReader.get_orientation(Path(photo_path))
                if orientation and orientation != 1:
                    full = OrientationReader.apply_orientation(full, orientation)
                self._full_pixmap = full
            else:
                self._full_pixmap = None
            self._rescale()
        else:
            self._thumb_label.setText("加载中...")
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

    def preload_photos(self, paths: list[str]):
        """Load thumbnails into cache without displaying them."""
        for i, path in enumerate(paths):
            if not path:
                continue
            cache_key = f"thumb:{path}"
            if QPixmapCache.find(cache_key):
                continue
            # Stagger loads so current photo loads first
            QTimer.singleShot(50 + i * 30, lambda p=path: self._preload_one(p))

    def _preload_one(self, path: str):
        cache_key = f"thumb:{path}"
        if QPixmapCache.find(cache_key):
            return
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            from pathlib import Path
            from gps_photo_tracker.core.orientation import OrientationReader
            orientation = OrientationReader.get_orientation(Path(path))
            if orientation and orientation != 1:
                pixmap = OrientationReader.apply_orientation(pixmap, orientation)
            scaled = pixmap.scaled(
                200, 200,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            QPixmapCache.insert(cache_key, scaled)

    def _load_thumbnail(self):
        path = self._pending_thumb_path
        if not path:
            return
        cache_key = f"thumb:{path}"
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            # Apply EXIF orientation transform
            from pathlib import Path
            from gps_photo_tracker.core.orientation import OrientationReader
            orientation = OrientationReader.get_orientation(Path(path))
            if orientation and orientation != 1:
                pixmap = OrientationReader.apply_orientation(pixmap, orientation)
            self._full_pixmap = pixmap
            # Cache a standard thumbnail for preload use
            cached = pixmap.scaled(
                200, 200,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            QPixmapCache.insert(cache_key, cached)
            if path == self._pending_thumb_path:
                self._rescale()
        else:
            self._full_pixmap = None
            self._thumb_label.clear()
