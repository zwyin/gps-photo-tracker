"""Tests for CLI mode (gps-photo-tracker-cli)."""
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from gps_photo_tracker.core.models import BatchResult, GPXSegment, PhotoInfo, TrackPoint
from gps_photo_tracker.cli import main


def _seg():
    return GPXSegment(filename="ride.gpx", start=1000.0, end=2000.0,
                      points=[TrackPoint(timestamp=1500.0, latitude=35.0, longitude=139.0)])


def _photo():
    return PhotoInfo(path=Path("/tmp/x.jpg"), filename="x.jpg", timestamp=1500.0, has_gps=False)


def _result(failed=0, total=1, matched=1):
    return BatchResult(total=total, matched=matched, skipped=0, failed=failed,
                       overwritten=0, success_rate=1.0 if failed == 0 else 0.0,
                       results=[], reject_groups={}, concurrent_workers=1)


class TestCliArgParsing:
    def test_missing_track_exits_1(self, capsys):
        """argparse error (missing -t) → exit 1 (overridden, not default 2)."""
        with pytest.raises(SystemExit) as ei:
            main(["./photos/"])
        assert ei.value.code == 1
        err = capsys.readouterr().err
        assert "track" in err.lower() or "required" in err.lower()

    def test_missing_photos_exits_1(self, capsys):
        with pytest.raises(SystemExit) as ei:
            main(["-t", "ride.gpx"])
        assert ei.value.code == 1

    def test_version_exits_0(self, capsys):
        with pytest.raises(SystemExit) as ei:
            main(["--version"])
        assert ei.value.code == 0


class TestCliDryRun:
    def test_dry_run_default_calls_preview(self, tmp_path):
        (tmp_path / "p.jpg").write_bytes(b"x")
        with patch("gps_photo_tracker.cli.GPSTaggingService") as MockSvc:
            inst = MockSvc.return_value
            inst.scan_gpx.return_value = [_seg()]
            inst.scan_photos.return_value = [_photo()]
            inst.preview.return_value = _result()
            code = main(["-t", "ride.gpx", str(tmp_path)])
        assert code == 0
        inst.preview.assert_called_once()
        inst.process.assert_not_called()

    def test_dry_run_explicit_n_flag(self, tmp_path):
        (tmp_path / "p.jpg").write_bytes(b"x")
        with patch("gps_photo_tracker.cli.GPSTaggingService") as MockSvc:
            inst = MockSvc.return_value
            inst.scan_gpx.return_value = [_seg()]
            inst.scan_photos.return_value = [_photo()]
            inst.preview.return_value = _result()
            code = main(["-t", "ride.gpx", "-n", str(tmp_path)])
        assert code == 0


class TestCliExitCodes:
    def test_partial_failure_exits_2(self, tmp_path):
        (tmp_path / "p.jpg").write_bytes(b"x")
        with patch("gps_photo_tracker.cli.GPSTaggingService") as MockSvc:
            inst = MockSvc.return_value
            inst.scan_gpx.return_value = [_seg()]
            inst.scan_photos.return_value = [_photo()]
            inst.preview.return_value = _result(failed=2, total=5, matched=3)
            code = main(["-t", "ride.gpx", str(tmp_path)])
        assert code == 2

    def test_empty_segments_exits_1(self, tmp_path, capsys):
        """scan_gpx swallows parse errors → returns [] → CLI must detect & exit 1."""
        (tmp_path / "p.jpg").write_bytes(b"x")
        with patch("gps_photo_tracker.cli.GPSTaggingService") as MockSvc:
            inst = MockSvc.return_value
            inst.scan_gpx.return_value = []  # swallowed parse failure
            inst.scan_photos.return_value = [_photo()]
            code = main(["-t", "bad.gpx", str(tmp_path)])
        assert code == 1
        assert "no track" in capsys.readouterr().err.lower()

    def test_empty_photos_exits_1(self, tmp_path, capsys):
        """_expand silently skips missing paths → [] → CLI must detect & exit 1."""
        with patch("gps_photo_tracker.cli.GPSTaggingService") as MockSvc:
            inst = MockSvc.return_value
            inst.scan_gpx.return_value = [_seg()]
            inst.scan_photos.return_value = []  # silently skipped
            code = main(["-t", "ride.gpx", str(tmp_path)])
        assert code == 1
        assert "no photos" in capsys.readouterr().err.lower()
