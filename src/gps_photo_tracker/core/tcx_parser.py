"""EF-08: TCX (Garmin Training Center) track file parser."""
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from gps_photo_tracker.core.models import GPXParseError, GPXSegment, TrackPoint

TCX_NS = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"


class TCXParser:
    """Parse TCX files into GPXSegments."""

    def parse_file(self, path: Path) -> list[GPXSegment]:
        try:
            tree = ET.parse(str(path))
        except ET.ParseError as e:
            raise GPXParseError(f"Failed to parse TCX file {path}: {e}") from e

        root = tree.getroot()
        segments: list[GPXSegment] = []
        filename = path.name

        for lap in root.iter(f"{{{TCX_NS}}}Lap"):
            points: list[TrackPoint] = []
            for tp in lap.iter(f"{{{TCX_NS}}}Trackpoint"):
                time_el = tp.find(f"{{{TCX_NS}}}Time")
                pos = tp.find(f"{{{TCX_NS}}}Position")
                if time_el is None or pos is None:
                    continue

                lat_el = pos.find(f"{{{TCX_NS}}}LatitudeDegrees")
                lon_el = pos.find(f"{{{TCX_NS}}}LongitudeDegrees")
                if lat_el is None or lon_el is None:
                    continue

                ts_text = time_el.text.strip()
                dt = datetime.fromisoformat(ts_text.replace("Z", "+00:00"))
                lat = float(lat_el.text)
                lon = float(lon_el.text)

                alt_el = tp.find(f"{{{TCX_NS}}}AltitudeMeters")
                if alt_el is None:
                    alt_el = pos.find(f"{{{TCX_NS}}}AltitudeMeters")
                alt = float(alt_el.text) if alt_el is not None else None

                points.append(TrackPoint(
                    timestamp=dt.timestamp(),
                    latitude=lat,
                    longitude=lon,
                    altitude=alt,
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
