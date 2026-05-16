"""Photo preview widget with async thumbnail loading."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QPixmapCache
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class PhotoPreview(QWidget):
    """Thumbnail preview (200x200) + info label, with QPixmapCache async loading."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._thumb_label = QLabel()
        self._thumb_label.setFixedSize(200, 200)
        self._thumb_label.setStyleSheet("background: #e8e8e8; border: 1px solid #ccc;")
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._thumb_label)

        self._info_label = QLabel("选中照片查看预览")
        self._info_label.setWordWrap(True)
        layout.addWidget(self._info_label, stretch=1)

        self._pending_thumb_path: str = ""

    def show_photo(self, photo_path: str, info_text: str):
        """Update info immediately, load thumbnail asynchronously."""
        self._info_label.setText(info_text)

        if not photo_path:
            self._thumb_label.clear()
            return

        cache_key = f"thumb:{photo_path}"
        cached = QPixmapCache.find(cache_key)
        if cached:
            self._thumb_label.setPixmap(cached)
        else:
            self._thumb_label.setText("加载中...")
            self._pending_thumb_path = photo_path
            QTimer.singleShot(10, self._load_thumbnail)

    def clear(self):
        self._thumb_label.clear()
        self._info_label.setText("选中照片查看预览")

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
            scaled = pixmap.scaled(
                200, 200,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            QPixmapCache.insert(cache_key, scaled)
            if path == self._pending_thumb_path:
                self._thumb_label.setPixmap(scaled)
        else:
            self._thumb_label.clear()
