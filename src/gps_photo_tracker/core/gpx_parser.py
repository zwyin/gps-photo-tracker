"""GPX file parser - extracts track segments with UTC timestamps."""

from datetime import timezone
from pathlib import Path

import gpxpy

from gps_photo_tracker.core.models import (
    GPXParseError,
    GPXSegment,
    TrackPoint,
)


class GPXParser:
    """Parse GPX files into GPXSegment list."""

    def parse_file(self, path: Path) -> list[GPXSegment]:
        """Parse a single GPX file. Raises GPXParseError on failure."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                gpx = gpxpy.parse(f)
        except Exception as e:
            raise GPXParseError(f"Failed to parse GPX file {path}: {e}") from e

        filename = path.name
        segments: list[GPXSegment] = []

        for track in gpx.tracks:
            for segment in track.segments:
                points: list[TrackPoint] = []
                for pt in segment.points:
                    if pt.time is None or pt.latitude is None or pt.longitude is None:
                        continue

                    utc_time = pt.time.replace(tzinfo=timezone.utc)
                    timestamp = utc_time.timestamp()
                    altitude = pt.elevation  # None when <ele> tag is missing

                    points.append(TrackPoint(
                        timestamp=timestamp,
                        latitude=pt.latitude,
                        longitude=pt.longitude,
                        altitude=altitude,
                    ))

                if not points:
                    continue

                points.sort(key=lambda p: p.timestamp)
                segments.append(GPXSegment(
                    filename=filename,
                    start=points[0].timestamp,
                    end=points[-1].timestamp,
                    points=points,
                ))

        return segments

    def parse_directory(self, dir: Path) -> list[GPXSegment]:
        """Parse all .gpx files in a directory (non-recursive). Raises GPXParseError."""
        if not dir.is_dir():
            raise GPXParseError(f"Not a directory: {dir}")

        segments: list[GPXSegment] = []
        errors: list[str] = []

        for path in sorted(dir.iterdir()):
            if path.suffix.lower() != ".gpx":
                continue
            try:
                segments.extend(self.parse_file(path))
            except GPXParseError as e:
                errors.append(str(e))

        if errors and not segments:
            raise GPXParseError(f"All GPX files failed: {'; '.join(errors)}")

        return segments
