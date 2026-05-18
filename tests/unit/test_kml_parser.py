"""Tests for EF-08 KMLParser."""
from pathlib import Path

from gps_photo_tracker.core.kml_parser import KMLParser
from gps_photo_tracker.core.models import GPXSegment, GPXParseError


KML_GX_TRACK = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"
     xmlns:gx="http://www.google.com/kml/ext/2.2">
  <Document>
    <Placemark>
      <gx:Track>
        <when>2026-01-01T08:00:00Z</when>
        <when>2026-01-01T08:05:00Z</when>
        <when>2026-01-01T08:10:00Z</when>
        <gx:coord>139.6917 35.6895 50</gx:coord>
        <gx:coord>139.7000 35.6900 55</gx:coord>
        <gx:coord>139.7100 35.6910 60</gx:coord>
      </gx:Track>
    </Placemark>
  </Document>
</kml>"""


KML_LINESTRING = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <LineString>
        <coordinates>
          139.6917,35.6895,50
          139.7000,35.6900,55
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""


class TestKMLParser:
    def test_parse_gx_track(self, tmp_path):
        kml_file = tmp_path / "test.kml"
        kml_file.write_text(KML_GX_TRACK, encoding="utf-8")
        segments = KMLParser().parse_file(kml_file)
        assert len(segments) == 1
        assert len(segments[0].points) == 3
        assert abs(segments[0].points[0].latitude - 35.6895) < 0.001
        assert abs(segments[0].points[0].longitude - 139.6917) < 0.001
        assert segments[0].points[0].altitude == 50.0

    def test_parse_linestring(self, tmp_path):
        kml_file = tmp_path / "test.kml"
        kml_file.write_text(KML_LINESTRING, encoding="utf-8")
        segments = KMLParser().parse_file(kml_file)
        assert len(segments) == 1
        assert len(segments[0].points) == 2
        assert segments[0].points[0].timestamp == 0.0

    def test_parse_empty_kml(self, tmp_path):
        kml_file = tmp_path / "empty.kml"
        kml_file.write_text(
            '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>',
            encoding="utf-8",
        )
        segments = KMLParser().parse_file(kml_file)
        assert segments == []

    def test_parse_invalid_raises(self, tmp_path):
        bad = tmp_path / "bad.kml"
        bad.write_text("not xml", encoding="utf-8")
        try:
            KMLParser().parse_file(bad)
            assert False, "Should raise GPXParseError"
        except GPXParseError:
            pass

    def test_gx_track_segment_timestamps(self, tmp_path):
        kml_file = tmp_path / "test.kml"
        kml_file.write_text(KML_GX_TRACK, encoding="utf-8")
        segments = KMLParser().parse_file(kml_file)
        seg = segments[0]
        assert seg.start < seg.end
        assert seg.points[0].timestamp > 0

    def test_returns_gpx_segment_type(self, tmp_path):
        kml_file = tmp_path / "test.kml"
        kml_file.write_text(KML_GX_TRACK, encoding="utf-8")
        segments = KMLParser().parse_file(kml_file)
        assert isinstance(segments[0], GPXSegment)

    def test_missing_altitude_defaults_zero(self, tmp_path):
        kml_no_alt = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"
     xmlns:gx="http://www.google.com/kml/ext/2.2">
  <Document>
    <Placemark>
      <gx:Track>
        <when>2026-01-01T08:00:00Z</when>
        <gx:coord>139.6917 35.6895</gx:coord>
      </gx:Track>
    </Placemark>
  </Document>
</kml>"""
        kml_file = tmp_path / "noalt.kml"
        kml_file.write_text(kml_no_alt, encoding="utf-8")
        segments = KMLParser().parse_file(kml_file)
        assert segments[0].points[0].altitude == 0.0


class TestKMLParserEdgeCases:
    """Cover uncovered branches: empty tracks, malformed coords, empty LineStrings."""

    def test_gx_track_coord_too_few_parts(self, tmp_path):
        """Coord with < 2 parts should be skipped."""
        kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"
     xmlns:gx="http://www.google.com/kml/ext/2.2">
  <Document>
    <Placemark>
      <gx:Track>
        <when>2026-01-01T08:00:00Z</when>
        <gx:coord>139.6917</gx:coord>
        <when>2026-01-01T08:05:00Z</when>
        <gx:coord>139.7000 35.6900 55</gx:coord>
      </gx:Track>
    </Placemark>
  </Document>
</kml>"""
        kml_file = tmp_path / "short.kml"
        kml_file.write_text(kml, encoding="utf-8")
        segments = KMLParser().parse_file(kml_file)
        assert len(segments) == 1
        assert len(segments[0].points) == 1  # only the valid coord

    def test_gx_track_empty_returns_none(self, tmp_path):
        """gx:Track with no valid coords returns no segment."""
        kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"
     xmlns:gx="http://www.google.com/kml/ext/2.2">
  <Document>
    <Placemark>
      <gx:Track>
        <gx:coord>onlyone</gx:coord>
      </gx:Track>
    </Placemark>
  </Document>
</kml>"""
        kml_file = tmp_path / "empty_track.kml"
        kml_file.write_text(kml, encoding="utf-8")
        segments = KMLParser().parse_file(kml_file)
        assert segments == []

    def test_linestring_empty_coordinates(self, tmp_path):
        """LineString with empty coordinates text returns no segment."""
        kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <LineString>
        <coordinates></coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""
        kml_file = tmp_path / "empty_ls.kml"
        kml_file.write_text(kml, encoding="utf-8")
        segments = KMLParser().parse_file(kml_file)
        assert segments == []

    def test_linestring_blank_lines_skipped(self, tmp_path):
        """Blank lines in coordinates should be skipped."""
        kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <LineString>
        <coordinates>
          139.6917,35.6895,50

          139.7000,35.6900,55
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""
        kml_file = tmp_path / "blanks.kml"
        kml_file.write_text(kml, encoding="utf-8")
        segments = KMLParser().parse_file(kml_file)
        assert len(segments) == 1
        assert len(segments[0].points) == 2

    def test_linestring_malformed_coord_skipped(self, tmp_path):
        """LineString coord with < 2 comma-separated parts is skipped."""
        kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <LineString>
        <coordinates>
          139.6917
          139.7000,35.6900,55
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""
        kml_file = tmp_path / "malformed.kml"
        kml_file.write_text(kml, encoding="utf-8")
        segments = KMLParser().parse_file(kml_file)
        assert len(segments) == 1
        assert len(segments[0].points) == 1

    def test_linestring_all_invalid_returns_none(self, tmp_path):
        """LineString where all coords are invalid returns no segment."""
        kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <LineString>
        <coordinates>
          justone
          alsoinvalid
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""
        kml_file = tmp_path / "all_invalid.kml"
        kml_file.write_text(kml, encoding="utf-8")
        segments = KMLParser().parse_file(kml_file)
        assert segments == []

    def test_no_linestring_element(self, tmp_path):
        """Placemark without LineString or gx:Track returns no segment."""
        kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>no geometry</name>
    </Placemark>
  </Document>
</kml>"""
        kml_file = tmp_path / "no_geom.kml"
        kml_file.write_text(kml, encoding="utf-8")
        segments = KMLParser().parse_file(kml_file)
        assert segments == []
