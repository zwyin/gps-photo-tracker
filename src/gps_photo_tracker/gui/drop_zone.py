"""Drag-and-drop zone for GPS tracks and photos.

Pure path-classification helpers live at module level so the drop
parsing logic (file classification / directory content sniffing /
multi-file merge) can be unit-tested without driving Qt drag events.
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

# Extensions recognized by the drop zone (mirror FileProvider / pickers).
TRACK_EXTS = frozenset({".gpx", ".kml", ".tcx", ".fit"})
IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff"})

# Answers a mixed-directory chooser callback may return.
MIXED_GPS = "gps"
MIXED_PHOTO = "photo"


def is_track_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in TRACK_EXTS


def is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTS


def classify_paths(paths, mixed_dir_chooser=None) -> tuple[list[Path], list[Path]]:
    """Split dropped paths into (track_paths, photo_paths).

    - Files are classified by extension; every recognized file is kept
      (multi-file merge — dropped files become exact selections).
    - Directories are sniffed non-recursively (iterdir, like
      FileProvider.resolve_tracks): track-only -> track list,
      image-only -> photo list, both -> ask ``mixed_dir_chooser(dir)``
      which must return MIXED_GPS / MIXED_PHOTO / None.
    - Unknown extensions, empty dirs and nonexistent paths are ignored.
    - Duplicates removed, order preserved.
    """
    tracks: list[Path] = []
    photos: list[Path] = []
    seen: set[Path] = set()

    def _add(bucket: list, p: Path):
        if p not in seen:
            seen.add(p)
            bucket.append(p)

    for raw in paths:
        p = Path(raw)
        if p in seen or not p.exists():
            continue
        if p.is_file():
            if p.suffix.lower() in TRACK_EXTS:
                _add(tracks, p)
            elif p.suffix.lower() in IMAGE_EXTS:
                _add(photos, p)
            continue
        if not p.is_dir():
            continue
        # Non-recursive sniff to avoid UI freeze on large directories.
        children = list(p.iterdir())
        has_track = any(f.suffix.lower() in TRACK_EXTS for f in children if f.is_file())
        has_image = any(f.suffix.lower() in IMAGE_EXTS for f in children if f.is_file())
        if has_track and has_image:
            if mixed_dir_chooser is None:
                continue
            answer = mixed_dir_chooser(p)
            if answer == MIXED_GPS:
                _add(tracks, p)
            elif answer == MIXED_PHOTO:
                _add(photos, p)
        elif has_track:
            _add(tracks, p)
        elif has_image:
            _add(photos, p)
    return tracks, photos


class DropZone(QFrame):
    """Visible drop target with drag-over highlight feedback.

    Emits ``pathsDropped`` (list[Path]) with every local path of a
    recognized drop; classification/GUI routing is the receiver's job
    (MainWindow._on_dropped_paths), so window-level drops and drop-zone
    drops share one code path.
    """

    pathsDropped = Signal(list)

    _NORMAL_STYLE = (
        "QFrame#dropZone { border: 2px dashed #b8b8b8; border-radius: 6px;"
        " background: #f7f7f7; }"
        " QFrame#dropZone QLabel { color: #8a8a8a; background: transparent; }"
    )
    _HIGHLIGHT_STYLE = (
        "QFrame#dropZone { border: 2px solid #4a9eff; border-radius: 6px;"
        " background: #e8f2ff; }"
        " QFrame#dropZone QLabel { color: #1a6dd4; background: transparent; }"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(44)
        self._highlighted = False

        self._label = QLabel("拖入 GPS 轨迹 / 照片（文件或目录，多选自动合并）", self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.addWidget(self._label)
        self._set_highlight(False)

    def _set_highlight(self, on: bool):
        self._highlighted = on
        self.setStyleSheet(self._HIGHLIGHT_STYLE if on else self._NORMAL_STYLE)

    def is_highlighted(self) -> bool:
        return self._highlighted

    @staticmethod
    def _local_paths(mime) -> list[Path]:
        return [Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()]

    @staticmethod
    def _recognizable(p: Path) -> bool:
        """Gate for drag-over feedback: track/image file, or any directory
        (content sniff happens at classification time)."""
        if p.is_dir():
            return True
        return p.suffix.lower() in TRACK_EXTS or p.suffix.lower() in IMAGE_EXTS

    def dragEnterEvent(self, event):
        paths = self._local_paths(event.mimeData())
        if paths and any(self._recognizable(p) for p in paths):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self._set_highlight(True)
            return
        event.ignore()

    def dragMoveEvent(self, event):
        paths = self._local_paths(event.mimeData())
        if paths and any(self._recognizable(p) for p in paths):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        event.ignore()

    def dragLeaveEvent(self, event):
        self._set_highlight(False)

    def dropEvent(self, event):
        self._set_highlight(False)
        paths = self._local_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.pathsDropped.emit(paths)
