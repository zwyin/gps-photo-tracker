"""Tests for FITParser (Garmin FIT, read-only GPS-only)."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from gps_photo_tracker.core.fit_parser import FITParser
from gps_photo_tracker.core.models import GPXParseError, GPXSegment, TrackPoint

# Fixture: tests/fixtures/garmin-fenix-5-run.fit is a real Garmin fenix 5 run
# recording, sourced from python-fitparse (MIT License,
# https://github.com/dtcooper/python-fitparse) — MIT-compatible with this
# GPL-3.0-or-later project. garmin-fit-sdk's own samples are NOT used (no
# license file). See TestFITParserIntegration for end-to-end coverage.


def _rec(lat, lon, ts_iso, alt=None):
    """Build a record dict with position in DEGREES (float)."""
    rec = {
        "position_lat": lat,
        "position_long": lon,
        "timestamp": datetime.fromisoformat(ts_iso.replace("Z", "+00:00")),
    }
    if alt is not None:
        rec["enhanced_altitude"] = alt
    return rec


def _rec_semicircles(lat_sc, lon_sc, ts_iso, alt=None):
    """Build a record dict with position in SEMICIRCLES (int) — matches actual
    garmin_fit_sdk output (apply_scale_and_offset does NOT convert
    position_lat/position_long; they stay sint32 semicircles)."""
    rec = {
        "position_lat": lat_sc,
        "position_long": lon_sc,
        "timestamp": datetime.fromisoformat(ts_iso.replace("Z", "+00:00")),
    }
    if alt is not None:
        rec["enhanced_altitude"] = alt
    return rec


class TestFITParserHappy:
    def test_single_record_returns_one_segment(self, tmp_path):
        f = tmp_path / "run.fit"
        f.write_bytes(b"fake")
        msgs = {"record_mesgs": [_rec(35.0, 139.0, "2026-01-01T08:00:00Z", 50.0)]}
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = (msgs, [])
            segs = FITParser().parse_file(f)
        assert len(segs) == 1
        assert len(segs[0].points) == 1
        p = segs[0].points[0]
        assert p.latitude == 35.0
        assert p.longitude == 139.0
        assert p.altitude == 50.0
        assert isinstance(p.timestamp, float)
        assert segs[0].filename == "run.fit"
        assert segs[0].start == segs[0].end == p.timestamp

    def test_multi_records_sorted_by_timestamp(self, tmp_path):
        f = tmp_path / "multi.fit"
        f.write_bytes(b"fake")
        msgs = {"record_mesgs": [
            _rec(36.0, 140.0, "2026-01-01T09:00:00Z"),
            _rec(35.0, 139.0, "2026-01-01T08:00:00Z"),
            _rec(35.5, 139.5, "2026-01-01T08:30:00Z"),
        ]}
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = (msgs, [])
            segs = FITParser().parse_file(f)
        pts = segs[0].points
        assert len(pts) == 3
        for i in range(1, len(pts)):
            assert pts[i].timestamp >= pts[i - 1].timestamp
        assert segs[0].start < segs[0].end

    def test_altitude_none_when_missing(self, tmp_path):
        f = tmp_path / "noalt.fit"
        f.write_bytes(b"fake")
        msgs = {"record_mesgs": [_rec(35.0, 139.0, "2026-01-01T08:00:00Z")]}
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = (msgs, [])
            segs = FITParser().parse_file(f)
        assert segs[0].points[0].altitude is None

    def test_multi_session_file_merges_into_one_segment(self, tmp_path):
        f = tmp_path / "tri.fit"
        f.write_bytes(b"fake")
        msgs = {"record_mesgs": [
            _rec(35.0, 139.0, "2026-01-01T08:00:00Z"),
            _rec(36.0, 140.0, "2026-01-01T11:00:00Z"),
            _rec(37.0, 141.0, "2026-01-01T13:00:00Z"),
        ]}
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = (msgs, [])
            segs = FITParser().parse_file(f)
        assert len(segs) == 1
        assert len(segs[0].points) == 3


class TestFITParserFiltering:
    def test_record_without_position_skipped(self, tmp_path):
        f = tmp_path / "indoor.fit"
        f.write_bytes(b"fake")
        msgs = {"record_mesgs": [
            {"timestamp": datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)},
            _rec(35.0, 139.0, "2026-01-01T08:00:10Z"),
        ]}
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = (msgs, [])
            segs = FITParser().parse_file(f)
        assert len(segs) == 1
        assert len(segs[0].points) == 1

    def test_position_none_sentinel_skipped(self, tmp_path):
        f = tmp_path / "sentinel.fit"
        f.write_bytes(b"fake")
        msgs = {"record_mesgs": [
            {"position_lat": None, "position_long": None,
             "timestamp": datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)},
            _rec(35.0, 139.0, "2026-01-01T08:00:10Z"),
        ]}
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = (msgs, [])
            segs = FITParser().parse_file(f)
        assert len(segs[0].points) == 1

    def test_out_of_range_position_skipped(self, tmp_path):
        f = tmp_path / "bad.fit"
        f.write_bytes(b"fake")
        msgs = {"record_mesgs": [
            {"position_lat": 999.0, "position_long": 0.0,
             "timestamp": datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)},
            _rec(35.0, 139.0, "2026-01-01T08:00:10Z"),
        ]}
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = (msgs, [])
            segs = FITParser().parse_file(f)
        assert len(segs[0].points) == 1

    def test_empty_record_mesgs_returns_empty(self, tmp_path):
        f = tmp_path / "empty.fit"
        f.write_bytes(b"fake")
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = ({"record_mesgs": []}, [])
            segs = FITParser().parse_file(f)
        assert segs == []

    def test_all_records_without_gps_returns_empty(self, tmp_path):
        f = tmp_path / "hr.fit"
        f.write_bytes(b"fake")
        msgs = {"record_mesgs": [
            {"timestamp": datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc), "heart_rate": 120},
            {"timestamp": datetime(2026, 1, 1, 8, 0, 10, tzinfo=timezone.utc), "heart_rate": 125},
        ]}
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = (msgs, [])
            segs = FITParser().parse_file(f)
        assert segs == []


class TestFITParserErrors:
    def test_non_fatal_errors_logged_but_returns_points(self, tmp_path):
        f = tmp_path / "warn.fit"
        f.write_bytes(b"fake")
        msgs = {"record_mesgs": [_rec(35.0, 139.0, "2026-01-01T08:00:00Z")]}
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = (msgs, ["unknown field X"])
            segs = FITParser().parse_file(f)
        assert len(segs) == 1
        assert len(segs[0].points) == 1

    def test_stream_failure_raises_gpxparseerror(self, tmp_path):
        f = tmp_path / "nope.fit"
        f.write_bytes(b"fake")
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS:
            MS.from_file.side_effect = OSError("io err")
            with pytest.raises(GPXParseError, match="Failed to open FIT"):
                FITParser().parse_file(f)

    def test_decoder_exception_raises_gpxparseerror(self, tmp_path):
        f = tmp_path / "corrupt.fit"
        f.write_bytes(b"fake")
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.side_effect = RuntimeError("decode boom")
            with pytest.raises(GPXParseError, match="Failed to decode FIT"):
                FITParser().parse_file(f)

    def test_record_missing_timestamp_raises_gpxparseerror(self, tmp_path):
        f = tmp_path / "nots.fit"
        f.write_bytes(b"fake")
        msgs = {"record_mesgs": [
            {"position_lat": 35.0, "position_long": 139.0},  # 有 position 缺 timestamp
        ]}
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = (msgs, [])
            with pytest.raises(GPXParseError, match="missing timestamp"):
                FITParser().parse_file(f)


class TestFITParserContract:
    def test_returns_gpxsegment_type(self, tmp_path):
        f = tmp_path / "run.fit"
        f.write_bytes(b"fake")
        msgs = {"record_mesgs": [_rec(35.0, 139.0, "2026-01-01T08:00:00Z")]}
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = (msgs, [])
            segs = FITParser().parse_file(f)
        assert isinstance(segs[0], GPXSegment)
        assert isinstance(segs[0].points[0], TrackPoint)

    def test_timestamp_is_utc_posix_float(self, tmp_path):
        f = tmp_path / "tz.fit"
        f.write_bytes(b"fake")
        msgs = {"record_mesgs": [_rec(35.0, 139.0, "2026-01-01T08:00:00Z")]}
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = (msgs, [])
            segs = FITParser().parse_file(f)
        assert abs(segs[0].points[0].timestamp - 1767254400.0) < 1.0

    def test_naive_datetime_defended_as_utc(self, tmp_path):
        f = tmp_path / "naive.fit"
        f.write_bytes(b"fake")
        msgs = {"record_mesgs": [{
            "position_lat": 35.0, "position_long": 139.0,
            "timestamp": datetime(2026, 1, 1, 8, 0),
        }]}
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = (msgs, [])
            segs = FITParser().parse_file(f)
        assert abs(segs[0].points[0].timestamp - 1767254400.0) < 1.0


class TestFITParserPerformance:
    """Quantified baseline — avoid 'a few MB' hand-waving (spec § 7.3)."""

    def test_50k_records_under_2_seconds(self, tmp_path):
        import time
        f = tmp_path / "big.fit"
        f.write_bytes(b"fake")
        # 50k records ~ a 14-hour 1Hz activity (ultra-endurance edge case)
        base = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
        records = [
            {"position_lat": 35.0 + i * 1e-6,
             "position_long": 139.0 + i * 1e-6,
             "timestamp": datetime.fromtimestamp(base.timestamp() + i, tz=timezone.utc)}
            for i in range(50000)
        ]
        msgs = {"record_mesgs": records}
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = (msgs, [])
            t0 = time.perf_counter()
            segs = FITParser().parse_file(f)
            elapsed = time.perf_counter() - t0
        assert len(segs[0].points) == 50000
        assert elapsed < 2.0, f"50k records took {elapsed:.2f}s (budget 2s)"


class TestFITParserSemicircles:
    """SDK's apply_scale_and_offset does NOT convert position_lat/position_long
    (they stay sint32 semicircles). FITParser must convert to degrees itself:
    degrees = semicircles * 180 / 2^31."""

    def test_semicircles_converted_to_degrees(self, tmp_path):
        f = tmp_path / "semicircles.fit"
        f.write_bytes(b"fake")
        # 456099168 semicircles = 38.22979° ; -1463077146 semicircles = -122.63370°
        msgs = {"record_mesgs": [_rec_semicircles(456099168, -1463077146, "2026-01-01T08:00:00Z", 50.0)]}
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = (msgs, [])
            segs = FITParser().parse_file(f)
        assert len(segs) == 1
        p = segs[0].points[0]
        assert abs(p.latitude - 38.22979) < 0.001
        assert abs(p.longitude - (-122.63370)) < 0.001
        assert p.altitude == 50.0

    def test_semicircles_with_invalid_sentinel_filtered(self, tmp_path):
        """A record whose semicircles convert to an out-of-range degree value
        (e.g. extreme lat) must be filtered out."""
        f = tmp_path / "bad.fit"
        f.write_bytes(b"fake")
        # 2_000_000_000 semicircles -> ~167° lat, out of [-90,90] -> filtered
        msgs = {"record_mesgs": [
            _rec_semicircles(2_000_000_000, -1463077146, "2026-01-01T08:00:00Z"),
            _rec_semicircles(456099168, -1463077146, "2026-01-01T08:00:10Z"),
        ]}
        with patch("gps_photo_tracker.core.fit_parser.Stream") as MS, \
             patch("gps_photo_tracker.core.fit_parser.Decoder") as MD:
            MS.from_file.return_value = object()
            MD.return_value.read.return_value = (msgs, [])
            segs = FITParser().parse_file(f)
        assert len(segs[0].points) == 1


_FIXTURE = Path(__file__).parent.parent / "fixtures" / "garmin-fenix-5-run.fit"


@pytest.mark.skipif(not _FIXTURE.exists(), reason="no MIT-licensed .fit fixture")
class TestFITParserIntegration:
    """End-to-end with a real Garmin fenix 5 .fit (MIT, from python-fitparse)."""

    def test_real_fit_parses_to_nonempty_segment(self):
        segs = FITParser().parse_file(_FIXTURE)
        assert len(segs) == 1
        assert len(segs[0].points) > 0
        for p in segs[0].points:
            assert -90 <= p.latitude <= 90
            assert -180 <= p.longitude <= 180

    def test_real_fit_coords_in_expected_range(self):
        """garmin-fenix-5-run.fit is a California run (~38.2°N, ~-122.6°W)."""
        segs = FITParser().parse_file(_FIXTURE)
        p = segs[0].points[0]
        assert 38.0 < p.latitude < 38.5
        assert -123.0 < p.longitude < -122.0
