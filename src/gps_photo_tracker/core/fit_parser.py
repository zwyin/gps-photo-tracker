"""EF: FIT (Garmin) track file parser — read-only, GPS-only.

Uses garmin-fit-sdk to decode .fit binary files produced by sport
watches / bike computers (Garmin, Wahoo, Coros, Bryton, Suunto).
1 file → 1 GPXSegment (all records merged by time).
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

from garmin_fit_sdk import Decoder, Stream

from gps_photo_tracker.core.models import GPXParseError, GPXSegment, TrackPoint

logger = logging.getLogger("gps_tracker")


class FITParser:
    """Parse Garmin FIT files into a single GPXSegment (GPS-only, read-only)."""

    def parse_file(self, path: Path) -> list[GPXSegment]:
        try:
            stream = Stream.from_file(str(path))
        except Exception as e:
            raise GPXParseError(f"Failed to open FIT file {path}: {e}") from e

        try:
            messages, errors = Decoder(stream).read(
                apply_scale_and_offset=True,
                convert_datetimes_to_dates=True,
            )
        except Exception as e:
            raise GPXParseError(f"Failed to decode FIT file {path}: {e}") from e

        if errors:
            logger.warning("FIT 解析告警 %s: %s", path.name, errors[:3])

        records = messages.get("record_mesgs", []) or []
        points = [
            self._to_track_point(r)
            for r in records
            if self._has_valid_position(r)
        ]
        if not points:
            return []

        points.sort(key=lambda p: p.timestamp)

        boundaries = self._segment_boundaries(messages)
        if boundaries:
            return self._split_at(points, boundaries, path.name)
        return [GPXSegment(
            filename=path.name,
            start=points[0].timestamp,
            end=points[-1].timestamp,
            points=points,
        )]

    @staticmethod
    def _segment_boundaries(messages: dict) -> list[float]:
        """lap_mesg (preferred) / session_mesg timestamps → sorted POSIX boundaries.

        Multi-sport FIT files (triathlon) record one lap per sport; splitting
        segments at lap starts keeps the matcher's [start, end] routing honest
        during transitions (spec §14 high-priority followup).
        """
        for key in ("lap_mesgs", "session_mesgs"):
            mesgs = messages.get(key) or []
            stamps = []
            for m in mesgs:
                dt = m.get("timestamp") if isinstance(m, dict) else None
                if isinstance(dt, datetime):
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    stamps.append(dt.timestamp())
            if len(stamps) >= 2:  # single boundary == single segment, no split needed
                return sorted(set(stamps))
        return []

    @staticmethod
    def _split_at(points: list, boundaries: list[float], filename: str) -> list[GPXSegment]:
        """Split sorted points at boundary timestamps (point ts < b → earlier segment)."""
        groups: list[list] = [[]]
        b_iter = iter(boundaries)
        b = next(b_iter, None)
        for p in points:
            while b is not None and p.timestamp >= b:
                groups.append([])
                b = next(b_iter, None)
            groups[-1].append(p)
        segments = [
            GPXSegment(filename=filename, start=g[0].timestamp, end=g[-1].timestamp, points=g)
            for g in groups if g
        ]
        return segments

    # FIT position_lat/position_long are sint32 semicircles. garmin_fit_sdk's
    # apply_scale_and_offset does NOT convert them (only altitude/speed/etc),
    # so they arrive as raw int semicircles — convert to degrees here.
    _SEMICIRCLES_TO_DEGREES = 180.0 / 2**31

    @staticmethod
    def _to_degrees(value):
        """Convert semicircles (int) to degrees; pass through float degrees.

        SDK leaves position_lat/position_long as int semicircles even with
        apply_scale_and_offset=True. This is the FIT protocol's native unit
        (semicircles = degrees * 2^31 / 180).
        """
        if isinstance(value, int):
            return value * FITParser._SEMICIRCLES_TO_DEGREES
        return float(value)

    @staticmethod
    def _has_valid_position(record: dict) -> bool:
        lat = record.get("position_lat")
        lon = record.get("position_long")
        if lat is None or lon is None:
            return False
        lat = FITParser._to_degrees(lat)
        lon = FITParser._to_degrees(lon)
        return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0

    @staticmethod
    def _to_track_point(record: dict) -> TrackPoint:
        dt = record.get("timestamp")
        if dt is None:
            raise GPXParseError(f"FIT record missing timestamp: {record!r}")
        if isinstance(dt, datetime) and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ts = dt.timestamp() if isinstance(dt, datetime) else float(dt)
        alt = record.get("enhanced_altitude", record.get("altitude"))
        return TrackPoint(
            timestamp=ts,
            latitude=FITParser._to_degrees(record["position_lat"]),
            longitude=FITParser._to_degrees(record["position_long"]),
            altitude=alt,
        )
