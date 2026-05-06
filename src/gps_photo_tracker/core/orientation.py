"""EF-10: EXIF Orientation reader and QTransform mapper."""
from pathlib import Path

import piexif


class OrientationReader:
    """Read EXIF Orientation and compute display transforms."""

    @staticmethod
    def get_orientation(path: Path) -> int | None:
        """Read EXIF Orientation tag (1-8). Returns None if missing or unreadable."""
        try:
            exif_dict = piexif.load(str(path))
            return exif_dict.get("0th", {}).get(piexif.ImageIFD.Orientation)
        except Exception:
            return None

    @staticmethod
    def transform_matrix(orientation: int):
        """Map EXIF Orientation value 1-8 to QTransform.

        Returns QTransform. Must be called within a QApplication context.
        """
        from PySide6.QtGui import QTransform
        t = QTransform()
        if orientation == 2:
            t.scale(-1, 1)
        elif orientation == 3:
            t.rotate(180)
        elif orientation == 4:
            t.scale(1, -1)
        elif orientation == 5:
            t.scale(-1, 1)
            t.rotate(90)
        elif orientation == 6:
            t.rotate(90)
        elif orientation == 7:
            t.scale(-1, 1)
            t.rotate(-90)
        elif orientation == 8:
            t.rotate(-90)
        return t

    @staticmethod
    def apply_orientation(qpixmap, orientation: int):
        """Apply orientation transform to QPixmap. Returns new pixmap."""
        if orientation is None or orientation <= 1:
            return qpixmap
        t = OrientationReader.transform_matrix(orientation)
        return qpixmap.transformed(t)
