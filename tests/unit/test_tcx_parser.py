"""Tests for EF-08 TCXParser."""
from pathlib import Path

from gps_photo_tracker.core.models import GPXSegment, GPXParseError
from gps_photo_tracker.core.tcx_parser import TCXParser


TCX_SINGLE_LAP = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Running">
      <Id>2026-01-01T08:00:00Z</Id>
      <Lap StartTime="2026-01-01T08:00:00Z">
        <Track>
          <Trackpoint>
            <Time>2026-01-01T08:00:00Z</Time>
            <Position>
              <LatitudeDegrees>35.6895</LatitudeDegrees>
              <LongitudeDegrees>139.6917</LongitudeDegrees>
              <AltitudeMeters>50</AltitudeMeters>
            </Position>
          </Trackpoint>
          <Trackpoint>
            <Time>2026-01-01T08:05:00Z</Time>
            <Position>
              <LatitudeDegrees>35.6900</LatitudeDegrees>
              <LongitudeDegrees>139.7000</LongitudeDegrees>
              <AltitudeMeters>55</AltitudeMeters>
            </Position>
          </Trackpoint>
        </Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>"""


TCX_MULTI_LAP = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Biking">
      <Id>2026-01-01T08:00:00Z</Id>
      <Lap StartTime="2026-01-01T08:00:00Z">
        <Track>
          <Trackpoint>
            <Time>2026-01-01T08:00:00Z</Time>
            <Position>
              <LatitudeDegrees>35.0</LatitudeDegrees>
              <LongitudeDegrees>139.0</LongitudeDegrees>
            </Position>
          </Trackpoint>
        </Track>
      </Lap>
      <Lap StartTime="2026-01-01T09:00:00Z">
        <Track>
          <Trackpoint>
            <Time>2026-01-01T09:00:00Z</Time>
            <Position>
              <LatitudeDegrees>36.0</LatitudeDegrees>
              <LongitudeDegrees>140.0</LongitudeDegrees>
              <AltitudeMeters>100</AltitudeMeters>
            </Position>
          </Trackpoint>
        </Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>"""


class TestTCXParser:
    def test_parse_single_lap(self, tmp_path):
        f = tmp_path / "run.tcx"
        f.write_text(TCX_SINGLE_LAP, encoding="utf-8")
        segments = TCXParser().parse_file(f)
        assert len(segments) == 1
        assert len(segments[0].points) == 2
        assert abs(segments[0].points[0].latitude - 35.6895) < 0.001
        assert segments[0].points[0].altitude == 50.0

    def test_parse_multi_lap(self, tmp_path):
        f = tmp_path / "bike.tcx"
        f.write_text(TCX_MULTI_LAP, encoding="utf-8")
        segments = TCXParser().parse_file(f)
        assert len(segments) == 2

    def test_missing_altitude_defaults_none(self, tmp_path):
        no_alt = TCX_SINGLE_LAP.replace("<AltitudeMeters>50</AltitudeMeters>", "").replace(
            "<AltitudeMeters>55</AltitudeMeters>", ""
        )
        f = tmp_path / "noalt.tcx"
        f.write_text(no_alt, encoding="utf-8")
        segments = TCXParser().parse_file(f)
        assert segments[0].points[0].altitude is None
        assert segments[0].points[1].altitude is None

    def test_empty_tcx(self, tmp_path):
        empty = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
</TrainingCenterDatabase>"""
        f = tmp_path / "empty.tcx"
        f.write_text(empty, encoding="utf-8")
        segments = TCXParser().parse_file(f)
        assert segments == []

    def test_invalid_xml_raises(self, tmp_path):
        f = tmp_path / "bad.tcx"
        f.write_text("not xml", encoding="utf-8")
        try:
            TCXParser().parse_file(f)
            assert False, "Should raise GPXParseError"
        except GPXParseError:
            pass

    def test_returns_gpx_segment_type(self, tmp_path):
        f = tmp_path / "run.tcx"
        f.write_text(TCX_SINGLE_LAP, encoding="utf-8")
        segments = TCXParser().parse_file(f)
        assert isinstance(segments[0], GPXSegment)

    def test_segment_timestamps_ordered(self, tmp_path):
        f = tmp_path / "run.tcx"
        f.write_text(TCX_SINGLE_LAP, encoding="utf-8")
        segments = TCXParser().parse_file(f)
        seg = segments[0]
        assert seg.start < seg.end
        for i in range(1, len(seg.points)):
            assert seg.points[i].timestamp >= seg.points[i - 1].timestamp
