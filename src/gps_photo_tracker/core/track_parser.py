"""EF-08: Unified track file parser — dispatches by extension."""
from pathlib import Path

from gps_photo_tracker.core.gpx_parser import GPXParser
from gps_photo_tracker.core.kml_parser import KMLParser
from gps_photo_tracker.core.models import GPXParseError, GPXSegment
from gps_photo_tracker.core.tcx_parser import TCXParser

_TRACK_EXTENSIONS = {".gpx", ".kml", ".tcx"}


class TrackParser:
    """Parse track files (GPX, KML, TCX) with auto-detection."""

    def __init__(self):
        self._gpx = GPXParser()
        self._kml = KMLParser()
        self._tcx = TCXParser()

    def parse_file(self, path: Path) -> list[GPXSegment]:
        ext = path.suffix.lower()
        if ext == ".gpx":
            return self._gpx.parse_file(path)
        elif ext == ".kml":
            return self._kml.parse_file(path)
        elif ext == ".tcx":
            return self._tcx.parse_file(path)
        else:
            raise GPXParseError(f"Unsupported track format: {ext}")

    def parse_directory(self, directory: Path) -> list[GPXSegment]:
        all_segments: list[GPXSegment] = []
        if not directory.exists():
            raise GPXParseError(f"Directory not found: {directory}")
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix.lower() in _TRACK_EXTENSIONS:
                try:
                    segments = self.parse_file(path)
                    all_segments.extend(segments)
                except Exception:
                    pass
        return all_segments
