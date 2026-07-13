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
        return [GPXSegment(
            filename=path.name,
            start=points[0].timestamp,
            end=points[-1].timestamp,
            points=points,
        )]

    @staticmethod
    def _has_valid_position(record: dict) -> bool:
        lat = record.get("position_lat")
        lon = record.get("position_long")
        if lat is None or lon is None:
            return False
        return -90.0 <= float(lat) <= 90.0 and -180.0 <= float(lon) <= 180.0

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
            latitude=record["position_lat"],
            longitude=record["position_long"],
            altitude=alt,
        )
