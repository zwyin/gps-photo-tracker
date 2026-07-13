"""Tests for EF-08 TrackParser (unified dispatcher)."""
from pathlib import Path
from unittest.mock import patch

import pytest
from gps_photo_tracker.core.models import GPXSegment, GPXParseError, TrackPoint
from gps_photo_tracker.core.track_parser import TrackParser


class TestTrackParser:
    def test_dispatches_gpx(self, tmp_path):
        gpx_file = tmp_path / "test.gpx"
        gpx_file.write_text("fake", encoding="utf-8")
        with patch("gps_photo_tracker.core.track_parser.GPXParser") as MockParser:
            mock_seg = GPXSegment(filename="test.gpx", start=0, end=1,
                                  points=[TrackPoint(timestamp=0, latitude=0, longitude=0)])
            MockParser.return_value.parse_file.return_value = [mock_seg]
            segments = TrackParser().parse_file(gpx_file)
            MockParser.return_value.parse_file.assert_called_once_with(gpx_file)
            assert len(segments) == 1

    def test_dispatches_kml(self, tmp_path):
        kml_file = tmp_path / "test.kml"
        kml_file.write_text("fake", encoding="utf-8")
        with patch("gps_photo_tracker.core.track_parser.KMLParser") as MockParser:
            MockParser.return_value.parse_file.return_value = []
            TrackParser().parse_file(kml_file)
            MockParser.return_value.parse_file.assert_called_once()

    def test_dispatches_tcx(self, tmp_path):
        tcx_file = tmp_path / "test.tcx"
        tcx_file.write_text("fake", encoding="utf-8")
        with patch("gps_photo_tracker.core.track_parser.TCXParser") as MockParser:
            MockParser.return_value.parse_file.return_value = []
            TrackParser().parse_file(tcx_file)
            MockParser.return_value.parse_file.assert_called_once()

    def test_dispatches_fit(self, tmp_path):
        fit_file = tmp_path / "test.fit"
        fit_file.write_bytes(b"fake")
        with patch("gps_photo_tracker.core.track_parser.FITParser") as MockParser:
            mock_seg = GPXSegment(filename="test.fit", start=0, end=1,
                                  points=[TrackPoint(timestamp=0, latitude=0, longitude=0)])
            MockParser.return_value.parse_file.return_value = [mock_seg]
            segments = TrackParser().parse_file(fit_file)
            MockParser.return_value.parse_file.assert_called_once_with(fit_file)
            assert len(segments) == 1

    def test_unknown_extension_raises(self, tmp_path):
        f = tmp_path / "test.xyz"
        f.write_text("fake", encoding="utf-8")
        try:
            TrackParser().parse_file(f)
            assert False, "Should raise"
        except GPXParseError:
            pass

    def test_parse_directory(self, tmp_path):
        (tmp_path / "a.gpx").write_text("fake", encoding="utf-8")
        (tmp_path / "b.kml").write_text("fake", encoding="utf-8")
        (tmp_path / "c.txt").write_text("fake", encoding="utf-8")
        with patch("gps_photo_tracker.core.track_parser.GPXParser") as MockGPX, \
             patch("gps_photo_tracker.core.track_parser.KMLParser") as MockKML:
            MockGPX.return_value.parse_file.return_value = []
            MockKML.return_value.parse_file.return_value = []
            TrackParser().parse_directory(tmp_path)
            MockGPX.return_value.parse_file.assert_called_once()
            MockKML.return_value.parse_file.assert_called_once()

    def test_parse_directory_not_found(self):
        with pytest.raises(GPXParseError, match="not found"):
            TrackParser().parse_directory(Path("/nonexistent/dir"))

    def test_parse_directory_skips_bad_files(self, tmp_path):
        (tmp_path / "bad.gpx").write_text("not xml", encoding="utf-8")
        with patch("gps_photo_tracker.core.track_parser.GPXParser") as MockGPX:
            MockGPX.return_value.parse_file.side_effect = Exception("corrupt")
            segments = TrackParser().parse_directory(tmp_path)
            assert segments == []
