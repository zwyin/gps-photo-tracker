"""Tests for GPXParser."""

import textwrap
from pathlib import Path

import pytest

from gps_photo_tracker.core.gpx_parser import GPXParser
from gps_photo_tracker.core.models import GPXParseError


# ── Helper: write a GPX file to tmp_path ──────────────────

def _write_gpx(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


SINGLE_SEGMENT = textwrap.dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <trkseg>
      <trkpt lat="25.953" lon="102.758"><time>2026-02-17T08:00:00Z</time><ele>1810.6</ele></trkpt>
      <trkpt lat="25.954" lon="102.759"><time>2026-02-17T08:10:00Z</time><ele>1815.0</ele></trkpt>
      <trkpt lat="25.955" lon="102.760"><time>2026-02-17T08:20:00Z</time><ele>1820.0</ele></trkpt>
    </trkseg>
  </trk>
</gpx>
""")

MULTI_SEGMENT = textwrap.dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <trkseg>
      <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time><ele>100.0</ele></trkpt>
      <trkpt lat="25.1" lon="100.1"><time>2026-02-17T08:10:00Z</time><ele>110.0</ele></trkpt>
    </trkseg>
    <trkseg>
      <trkpt lat="26.0" lon="101.0"><time>2026-02-17T13:00:00Z</time><ele>200.0</ele></trkpt>
      <trkpt lat="26.1" lon="101.1"><time>2026-02-17T13:10:00Z</time><ele>210.0</ele></trkpt>
    </trkseg>
  </trk>
</gpx>
""")

NO_ELEVATION = textwrap.dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>
    <trkpt lat="25.1" lon="100.1"><time>2026-02-17T08:10:00Z</time></trkpt>
  </trkseg></trk>
</gpx>
""")

EMPTY_TRACK = textwrap.dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg></trkseg></trk>
</gpx>
""")


class TestParseFile:

    def test_single_track_single_segment(self, tmp_path):
        path = _write_gpx(tmp_path, "test.gpx", SINGLE_SEGMENT)
        segments = GPXParser().parse_file(path)

        assert len(segments) == 1
        seg = segments[0]
        assert seg.filename == "test.gpx"
        assert len(seg.points) == 3
        assert seg.points[0].latitude == pytest.approx(25.953)
        assert seg.points[0].longitude == pytest.approx(102.758)
        assert seg.points[0].altitude == pytest.approx(1810.6)

    def test_multi_segment(self, tmp_path):
        path = _write_gpx(tmp_path, "multi.gpx", MULTI_SEGMENT)
        segments = GPXParser().parse_file(path)

        assert len(segments) == 2
        assert segments[0].points[0].latitude == pytest.approx(25.0)
        assert segments[1].points[0].latitude == pytest.approx(26.0)
        # different time ranges
        assert segments[0].end < segments[1].start

    def test_missing_elevation(self, tmp_path):
        path = _write_gpx(tmp_path, "noele.gpx", NO_ELEVATION)
        segments = GPXParser().parse_file(path)

        assert len(segments) == 1
        for pt in segments[0].points:
            assert pt.altitude is None

    def test_empty_gpx(self, tmp_path):
        path = _write_gpx(tmp_path, "empty.gpx", EMPTY_TRACK)
        segments = GPXParser().parse_file(path)
        assert segments == []

    def test_invalid_gpx_raises(self, tmp_path):
        path = _write_gpx(tmp_path, "bad.gpx", "this is not xml")
        with pytest.raises(GPXParseError):
            GPXParser().parse_file(path)

    def test_timestamp_is_utc(self, tmp_path):
        """Timestamp should be UTC regardless of local timezone."""
        path = _write_gpx(tmp_path, "ts.gpx", SINGLE_SEGMENT)
        segments = GPXParser().parse_file(path)

        from datetime import datetime, timezone
        # 2026-02-17T08:00:00Z → check timestamp matches
        expected = datetime(2026, 2, 17, 8, 0, 0, tzinfo=timezone.utc).timestamp()
        assert segments[0].points[0].timestamp == expected

    def test_points_sorted(self, tmp_path):
        """Points within a segment must be sorted by timestamp."""
        # Write GPX with out-of-order points
        out_of_order = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:20:00Z</time><ele>100</ele></trkpt>
            <trkpt lat="25.1" lon="100.1"><time>2026-02-17T08:00:00Z</time><ele>110</ele></trkpt>
            <trkpt lat="25.2" lon="100.2"><time>2026-02-17T08:10:00Z</time><ele>120</ele></trkpt>
          </trkseg></trk>
        </gpx>
        """)
        path = _write_gpx(tmp_path, "unsorted.gpx", out_of_order)
        segments = GPXParser().parse_file(path)

        timestamps = [p.timestamp for p in segments[0].points]
        assert timestamps == sorted(timestamps)


class TestParseDirectory:

    def test_parse_directory(self, tmp_path):
        _write_gpx(tmp_path, "a.gpx", SINGLE_SEGMENT)
        _write_gpx(tmp_path, "b.gpx", MULTI_SEGMENT)
        _write_gpx(tmp_path, "ignore.txt", "not a gpx")

        segments = GPXParser().parse_directory(tmp_path)
        # SINGLE_SEGMENT=1 seg + MULTI_SEGMENT=2 segs = 3 total
        assert len(segments) == 3

    def test_parse_directory_all_fail(self, tmp_path):
        _write_gpx(tmp_path, "bad.gpx", "not xml")
        with pytest.raises(GPXParseError):
            GPXParser().parse_directory(tmp_path)

    def test_parse_directory_partial_fail(self, tmp_path):
        _write_gpx(tmp_path, "good.gpx", SINGLE_SEGMENT)
        _write_gpx(tmp_path, "bad.gpx", "not xml")

        segments = GPXParser().parse_directory(tmp_path)
        assert len(segments) == 1  # good file's 1 segment

    def test_parse_directory_not_dir_raises(self):
        with pytest.raises(GPXParseError):
            GPXParser().parse_directory(Path("/nonexistent/path"))

    def test_parse_directory_empty(self, tmp_path):
        segments = GPXParser().parse_directory(tmp_path)
        assert segments == []

    def test_parse_directory_case_insensitive(self, tmp_path):
        _write_gpx(tmp_path, "upper.GPX", SINGLE_SEGMENT)
        segments = GPXParser().parse_directory(tmp_path)
        assert len(segments) == 1
