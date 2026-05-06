"""EF-08: KML track file parser."""
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from gps_photo_tracker.core.models import GPXParseError, GPXSegment, TrackPoint

KML_NS = "http://www.opengis.net/kml/2.2"
GX_NS = "http://www.google.com/kml/ext/2.2"


class KMLParser:
    """Parse KML files with gx:Track or LineString into GPXSegments."""

    def parse_file(self, path: Path) -> list[GPXSegment]:
        try:
            tree = ET.parse(str(path))
        except ET.ParseError as e:
            raise GPXParseError(f"Failed to parse KML file {path}: {e}") from e

        root = tree.getroot()
        segments: list[GPXSegment] = []
        filename = path.name

        for pm in root.iter(f"{{{KML_NS}}}Placemark"):
            seg = self._parse_gx_track(pm, filename)
            if seg:
                segments.append(seg)
                continue
            seg = self._parse_linestring(pm, filename)
            if seg:
                segments.append(seg)

        return segments

    def _parse_gx_track(self, placemark: ET.Element, filename: str) -> GPXSegment | None:
        track = placemark.find(f".//{{{GX_NS}}}Track")
        if track is None:
            return None

        whens = track.findall(f"{{{KML_NS}}}when")
        coords = track.findall(f"{{{GX_NS}}}coord")

        points: list[TrackPoint] = []
        for i, coord_el in enumerate(coords):
            parts = coord_el.text.strip().split()
            if len(parts) < 2:
                continue
            lon, lat = float(parts[0]), float(parts[1])
            alt = float(parts[2]) if len(parts) > 2 else 0.0

            ts = 0.0
            if i < len(whens) and whens[i].text:
                dt = datetime.fromisoformat(whens[i].text.strip().replace("Z", "+00:00"))
                ts = dt.timestamp()

            points.append(TrackPoint(timestamp=ts, latitude=lat, longitude=lon, altitude=alt))

        if not points:
            return None
        points.sort(key=lambda p: p.timestamp)
        return GPXSegment(
            filename=filename,
            start=points[0].timestamp,
            end=points[-1].timestamp,
            points=points,
        )

    def _parse_linestring(self, placemark: ET.Element, filename: str) -> GPXSegment | None:
        ls = placemark.find(f".//{{{KML_NS}}}LineString")
        if ls is None:
            return None
        coords_el = ls.find(f"{{{KML_NS}}}coordinates")
        if coords_el is None or not coords_el.text:
            return None

        points: list[TrackPoint] = []
        for line in coords_el.text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 2:
                continue
            lon, lat = float(parts[0]), float(parts[1])
            alt = float(parts[2]) if len(parts) > 2 else 0.0
            ts = float(len(points))
            points.append(TrackPoint(timestamp=ts, latitude=lat, longitude=lon, altitude=alt))

        if not points:
            return None
        return GPXSegment(
            filename=filename,
            start=points[0].timestamp,
            end=points[-1].timestamp,
            points=points,
        )
