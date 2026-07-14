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


from gps_photo_tracker.core.models import ProcessMode


class TestCliWriteModes:
    def test_copy_mode_calls_process_with_copy(self, tmp_path):
        (tmp_path / "p.jpg").write_bytes(b"x")
        out = tmp_path / "out"
        with patch("gps_photo_tracker.cli.GPSTaggingService") as MockSvc:
            inst = MockSvc.return_value
            inst.scan_gpx.return_value = [_seg()]
            inst.scan_photos.return_value = [_photo()]
            inst.process.return_value = _result()
            code = main(["-t", "ride.gpx", "-o", str(out), str(tmp_path)])
        assert code == 0
        inst.process.assert_called_once()
        call_args = inst.process.call_args
        options = call_args.kwargs.get("options") or call_args.args[3]
        assert options.mode == ProcessMode.COPY
        assert options.output_dir == out
        assert options.overwrite_gps is False
        # single photo source → photo_dir = that path, keep_structure=True
        assert call_args.kwargs.get("photo_dir") == Path(str(tmp_path))
        assert options.keep_structure is True

    def test_overwrite_sets_overwrite_gps_true(self, tmp_path):
        (tmp_path / "p.jpg").write_bytes(b"x")
        with patch("gps_photo_tracker.cli.GPSTaggingService") as MockSvc:
            inst = MockSvc.return_value
            inst.scan_gpx.return_value = [_seg()]
            inst.scan_photos.return_value = [_photo()]
            inst.process.return_value = _result()
            code = main(["-t", "ride.gpx", "--overwrite", str(tmp_path)])
        assert code == 0
        options = inst.process.call_args.kwargs["options"]
        assert options.mode == ProcessMode.OVERWRITE
        assert options.overwrite_gps is True  # CRITICAL: else existing-GPS photos skipped

    def test_multi_photo_sources_flat_no_keep_structure(self, tmp_path, capsys):
        d1 = tmp_path / "d1"; d1.mkdir(); (d1 / "p.jpg").write_bytes(b"x")
        d2 = tmp_path / "d2"; d2.mkdir(); (d2 / "p.jpg").write_bytes(b"x")
        out = tmp_path / "out"
        with patch("gps_photo_tracker.cli.GPSTaggingService") as MockSvc:
            inst = MockSvc.return_value
            inst.scan_gpx.return_value = [_seg()]
            inst.scan_photos.return_value = [_photo(), _photo()]
            inst.process.return_value = _result(total=2, matched=2)
            code = main(["-t", "ride.gpx", "-o", str(out), str(d1), str(d2)])
        assert code == 0
        call_kwargs = inst.process.call_args.kwargs
        assert call_kwargs["photo_dir"] is None  # multi-source → None
        assert call_kwargs["options"].keep_structure is False  # flat
        err = capsys.readouterr().err.lower()
        assert "flat" in err or "keep_structure" in err

    def test_time_offset_passed_to_config(self, tmp_path):
        (tmp_path / "p.jpg").write_bytes(b"x")
        with patch("gps_photo_tracker.cli.GPSTaggingService") as MockSvc:
            inst = MockSvc.return_value
            inst.scan_gpx.return_value = [_seg()]
            inst.scan_photos.return_value = [_photo()]
            inst.preview.return_value = _result()
            main(["-t", "ride.gpx", "--time-offset", "3600", str(tmp_path)])
        config = inst.preview.call_args.args[2]
        assert config.time_offset == 3600

    def test_workers_passed_to_options(self, tmp_path):
        (tmp_path / "p.jpg").write_bytes(b"x")
        out = tmp_path / "out"
        with patch("gps_photo_tracker.cli.GPSTaggingService") as MockSvc:
            inst = MockSvc.return_value
            inst.scan_gpx.return_value = [_seg()]
            inst.scan_photos.return_value = [_photo()]
            inst.process.return_value = _result()
            main(["-t", "ride.gpx", "-o", str(out), "-j", "4", str(tmp_path)])
        assert inst.process.call_args.kwargs["options"].workers == 4


class TestCliOutputSeparation:
    def test_progress_goes_to_stderr(self, tmp_path, capsys):
        (tmp_path / "p.jpg").write_bytes(b"x")
        from gps_photo_tracker.core.models import ProgressPhase, ProgressUpdate
        with patch("gps_photo_tracker.cli.GPSTaggingService") as MockSvc:
            inst = MockSvc.return_value
            inst.scan_gpx.return_value = [_seg()]
            inst.scan_photos.return_value = [_photo()]
            def preview(segs, phs, cfg, on_progress=None, **kw):
                if on_progress:
                    on_progress(ProgressUpdate(phase=ProgressPhase.MATCHING, current=1, total=1,
                                                current_file="x.jpg", elapsed_seconds=0.1))
                return _result()
            inst.preview.side_effect = preview
            main(["-t", "ride.gpx", str(tmp_path)])
        captured = capsys.readouterr()
        assert "1/1" in captured.err  # progress → stderr
        assert "1/1" not in captured.out  # not polluting stdout

    def test_verbose_one_line_per_photo_stdout(self, tmp_path, capsys):
        (tmp_path / "p.jpg").write_bytes(b"x")
        from gps_photo_tracker.core.models import MatchResult, GPSInfo
        mr = MatchResult(photo=_photo(), success=True, gps=GPSInfo(latitude=35, longitude=139), method="nearest")
        with patch("gps_photo_tracker.cli.GPSTaggingService") as MockSvc:
            inst = MockSvc.return_value
            inst.scan_gpx.return_value = [_seg()]
            inst.scan_photos.return_value = [_photo()]
            def preview(segs, phs, cfg, on_photo_processed=None, **kw):
                if on_photo_processed:
                    on_photo_processed(mr)
                return _result()
            inst.preview.side_effect = preview
            main(["-t", "ride.gpx", "-v", str(tmp_path)])
        captured = capsys.readouterr()
        assert "x.jpg" in captured.out  # verbose → stdout
        assert "ok" in captured.out

    def test_quiet_suppresses_verbose(self, tmp_path, capsys):
        (tmp_path / "p.jpg").write_bytes(b"x")
        from gps_photo_tracker.core.models import MatchResult
        mr = MatchResult(photo=_photo(), success=True, method="nearest")
        with patch("gps_photo_tracker.cli.GPSTaggingService") as MockSvc:
            inst = MockSvc.return_value
            inst.scan_gpx.return_value = [_seg()]
            inst.scan_photos.return_value = [_photo()]
            def preview(segs, phs, cfg, on_photo_processed=None, **kw):
                if on_photo_processed:
                    on_photo_processed(mr)
                return _result()
            inst.preview.side_effect = preview
            main(["-t", "ride.gpx", "-q", str(tmp_path)])
        captured = capsys.readouterr()
        assert "x.jpg" not in captured.out  # quiet suppresses per-photo
        assert "total:" in captured.out  # summary still printed
