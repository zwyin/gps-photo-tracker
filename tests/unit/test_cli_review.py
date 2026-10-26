"""Tests for CLI interactive review (--review): non-tty degrade, review loop,
apply_review integration, write path, abort/Ctrl-C handling."""
import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from gps_photo_tracker.cli import main
from gps_photo_tracker.core.models import (
    BatchResult,
    GPSInfo,
    GPXSegment,
    MatcherConfig,
    MatchResult,
    PhotoInfo,
    ProcessMode,
    ReviewAction,
    TrackPoint,
)
from gps_photo_tracker.service.tagging_service import GPSTaggingService


# ── Fixtures ────────────────────────────────────────────────

def _seg():
    """Segment with points at 1470/1500/1560 (photo ok=1500 is a match)."""
    return GPXSegment(filename="ride.gpx", start=1400.0, end=1600.0,
                      points=[
                          TrackPoint(timestamp=1470.0, latitude=34.99, longitude=138.99, altitude=100),
                          TrackPoint(timestamp=1500.0, latitude=35.0, longitude=139.0, altitude=110),
                          TrackPoint(timestamp=1560.0, latitude=35.001, longitude=139.001, altitude=120),
                      ])


def _photo(name, ts):
    return PhotoInfo(path=Path(f"/tmp/{name}.jpg"), filename=f"{name}.jpg",
                     timestamp=ts, has_gps=False)


def _failed_batch():
    """1 matched (ok, ts=1500) + 2 failed (f1 ts=1560, f2 ts=1440)."""
    r_ok = MatchResult(photo=_photo("ok", 1500.0), success=True,
                       gps=GPSInfo(35.0, 139.0), method="nearest", time_diff=5.0)
    r_f1 = MatchResult(photo=_photo("f1", 1560.0), success=False,
                       reject_reason="time_diff")
    r_f2 = MatchResult(photo=_photo("f2", 1440.0), success=False,
                       reject_reason="no_gps_coverage")
    return BatchResult(total=3, matched=1, skipped=0, failed=2, overwritten=0,
                       success_rate=1 / 3, results=[r_ok, r_f1, r_f2],
                       reject_groups={}, concurrent_workers=1)


def _matched_batch():
    r = MatchResult(photo=_photo("ok", 1500.0), success=True,
                    gps=GPSInfo(35.0, 139.0), method="nearest")
    return BatchResult(total=1, matched=1, skipped=0, failed=0, overwritten=0,
                       success_rate=1.0, results=[r], reject_groups={},
                       concurrent_workers=1)


class FakeTty(io.StringIO):
    """stdin stub that claims to be a tty (drives the interactive loop)."""
    def isatty(self):
        return True


_ORIG_APPLY = GPSTaggingService.apply_review


def _real_apply(results, state):
    """Invoke the real apply_review via a throwaway service instance (pre-patch ref)."""
    return _ORIG_APPLY(GPSTaggingService(), results, state)


class _ApplySpyRecorder:
    """Patch target for GPSTaggingService.apply_review: record + delegate."""
    def __init__(self):
        self.calls = []

    def __call__(self, results, state):
        self.calls.append((results, state))
        return _real_apply(results, state)


def _patched_scan(batch):
    """Class-level patches: scan+preview mocked, prepare/apply/write real."""
    return [
        patch.object(GPSTaggingService, "scan_gpx", return_value=[_seg()]),
        patch.object(GPSTaggingService, "scan_photos", return_value=[_photo("ok", 1500.0)]),
        patch.object(GPSTaggingService, "preview", return_value=batch),
    ]


def _run_review_main(monkeypatch, stdin_text, argv, batch=None, spy_apply=None):
    """Run cli.main with mocked scan/preview and (optionally fake) stdin."""
    batch = batch if batch is not None else _failed_batch()
    for p in _patched_scan(batch):
        p.start()
    try:
        if stdin_text is not None:
            monkeypatch.setattr(sys, "stdin", FakeTty(stdin_text))
        if spy_apply is not None:
            patch.object(GPSTaggingService, "apply_review", spy_apply).start()
        return main(argv)
    finally:
        patch.stopall()


# ── Non-tty degradation ─────────────────────────────────────

class TestReviewNonTty:
    """stdin not a tty → no prompt/hang, print suggestion, exit normally."""

    def test_non_tty_skips_review_and_suggests(self, tmp_path, capsys):
        (tmp_path / "p.jpg").write_bytes(b"x")
        spy = _ApplySpyRecorder()
        code = _run_review_main(None, None,  # stdin untouched → pytest non-tty stub
                                ["-t", "ride.gpx", "--review", str(tmp_path)],
                                spy_apply=spy)
        assert code == 2  # failures still exist, review skipped
        err = capsys.readouterr().err
        assert "terminal" in err.lower()
        assert spy.calls == []  # apply_review never called

    def test_non_tty_write_mode_does_not_write(self, tmp_path, capsys):
        (tmp_path / "p.jpg").write_bytes(b"x")
        out = tmp_path / "out"
        code = _run_review_main(None, None,
                                ["-t", "ride.gpx", "--review", "-o", str(out), str(tmp_path)])
        assert code == 2
        assert not out.exists()  # nothing written without review
        err = capsys.readouterr().err
        assert "terminal" in err.lower()

    def test_no_failures_skips_review_and_writes(self, tmp_path, monkeypatch, capsys):
        """--review with zero failures → note + normal write path (write_phase)."""
        (tmp_path / "p.jpg").write_bytes(b"x")
        out = tmp_path / "out"
        captured = {}

        def fake_write_phase(self_, results, options, photo_dir=None, on_progress=None,
                             on_photo_processed=None, cancel=None):
            captured["results"] = results
            captured["options"] = options
            return _matched_batch()

        batch = _matched_batch()
        for p in _patched_scan(batch):
            p.start()
        try:
            patch.object(GPSTaggingService, "write_phase", fake_write_phase).start()
            monkeypatch.setattr(sys, "stdin", FakeTty("\n"))  # tty available but unused
            code = main(["-t", "ride.gpx", "--review", "-o", str(out), str(tmp_path)])
        finally:
            patch.stopall()
        assert code == 0
        assert captured["options"].mode == ProcessMode.COPY
        assert len(captured["results"]) == 1
        out_text = capsys.readouterr().out
        assert "nothing to review" in out_text


# ── Interactive loop ────────────────────────────────────────

class TestReviewInteractive:

    def test_enter_default_keeps_failed(self, tmp_path, monkeypatch, capsys):
        """Enter on every item → no decisions, results unchanged, exit 2."""
        (tmp_path / "p.jpg").write_bytes(b"x")
        spy = _ApplySpyRecorder()
        batch = _failed_batch()
        code = _run_review_main(monkeypatch, "\n\n",
                                ["-t", "ride.gpx", "--review", str(tmp_path)],
                                batch=batch, spy_apply=spy)
        assert code == 2
        assert len(spy.calls) == 1
        _, state = spy.calls[0]
        assert state.decisions == {}
        out = capsys.readouterr().out
        assert "matched: 1" in out  # unchanged counts

    def test_pick_nearest_gps_point(self, tmp_path, monkeypatch, capsys):
        """'g' + '1' → MANUAL_GPS decision with nearest candidate (dt=0)."""
        (tmp_path / "p.jpg").write_bytes(b"x")
        spy = _ApplySpyRecorder()
        code = _run_review_main(monkeypatch, "g\n1\n\n",
                                ["-t", "ride.gpx", "--review", str(tmp_path)],
                                spy_apply=spy)
        assert code == 2  # f2 still failed
        _, state = spy.calls[0]
        dec = state.decisions["/tmp/f1.jpg"]
        assert dec.action == ReviewAction.MANUAL_GPS
        assert dec.selected_point.timestamp == 1560.0  # nearest to f1
        assert dec.selected_point.latitude == 35.001
        out = capsys.readouterr().out
        assert "matched: 2" in out  # f1 rescued via manual_gps

    def test_manual_coord(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "p.jpg").write_bytes(b"x")
        spy = _ApplySpyRecorder()
        code = _run_review_main(monkeypatch, "c\n35.5\n139.5\n\n",
                                ["-t", "ride.gpx", "--review", str(tmp_path)],
                                spy_apply=spy)
        assert code == 2
        _, state = spy.calls[0]
        dec = state.decisions["/tmp/f1.jpg"]
        assert dec.action == ReviewAction.MANUAL_COORD
        assert dec.manual_lat == 35.5
        assert dec.manual_lon == 139.5
        out = capsys.readouterr().out
        assert "matched: 2" in out

    def test_manual_coord_invalid_then_valid(self, tmp_path, monkeypatch, capsys):
        """Bad number / out-of-range → re-prompt until valid."""
        (tmp_path / "p.jpg").write_bytes(b"x")
        spy = _ApplySpyRecorder()
        code = _run_review_main(monkeypatch, "c\nabc\n35.5\n999\n139.5\n\n",
                                ["-t", "ride.gpx", "--review", str(tmp_path)],
                                spy_apply=spy)
        assert code == 2
        _, state = spy.calls[0]
        dec = state.decisions["/tmp/f1.jpg"]
        assert dec.action == ReviewAction.MANUAL_COORD
        assert dec.manual_lat == 35.5
        assert dec.manual_lon == 139.5

    def test_pick_gps_no_candidates(self, tmp_path, monkeypatch, capsys):
        """Photo far outside ±30min window → 'no track points' + re-prompt."""
        (tmp_path / "p.jpg").write_bytes(b"x")
        far = MatchResult(photo=_photo("far", 1500.0 + 7200.0), success=False,
                          reject_reason="time_diff")
        batch = _failed_batch()
        batch.results = [far]
        spy = _ApplySpyRecorder()
        code = _run_review_main(monkeypatch, "g\n\n",
                                ["-t", "ride.gpx", "--review", str(tmp_path)],
                                batch=batch, spy_apply=spy)
        assert code == 2
        _, state = spy.calls[0]
        assert state.decisions == {}  # 'g' found nothing, Enter kept
        out = capsys.readouterr().out
        assert "no track points" in out

    def test_follow_prev(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "p.jpg").write_bytes(b"x")
        batch = _failed_batch()
        code = _run_review_main(monkeypatch, "p\n\n",
                                ["-t", "ride.gpx", "--review", str(tmp_path)],
                                batch=batch)
        assert code == 2
        f1 = batch.results[1]
        assert f1.success is True
        assert f1.method == "follow_prev"
        assert f1.review_gps == GPSInfo(35.0, 139.0)  # copies neighbor's GPSInfo (no alt)
        assert "matched: 2" in capsys.readouterr().out

    def test_follow_next(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "p.jpg").write_bytes(b"x")
        batch = _failed_batch()
        code = _run_review_main(monkeypatch, "\nn\n",
                                ["-t", "ride.gpx", "--review", str(tmp_path)],
                                batch=batch)
        assert code == 2
        f2 = batch.results[2]  # ts=1440, next matched neighbor is ok@1500
        assert f2.success is True
        assert f2.method == "follow_next"
        assert f2.review_gps == GPSInfo(35.0, 139.0)

    def test_quit_aborts_without_apply(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "p.jpg").write_bytes(b"x")
        spy = _ApplySpyRecorder()
        code = _run_review_main(monkeypatch, "q",
                                ["-t", "ride.gpx", "--review", str(tmp_path)],
                                spy_apply=spy)
        assert code == 1
        assert spy.calls == []
        assert "aborted" in capsys.readouterr().err.lower()

    def test_eof_aborts_cleanly(self, tmp_path, monkeypatch, capsys):
        """Closed stdin (empty) → EOF treated as abort, exit 1, no hang."""
        (tmp_path / "p.jpg").write_bytes(b"x")
        spy = _ApplySpyRecorder()
        code = _run_review_main(monkeypatch, "",
                                ["-t", "ride.gpx", "--review", str(tmp_path)],
                                spy_apply=spy)
        assert code == 1
        assert spy.calls == []

    def test_ctrl_c_exits_cleanly(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "p.jpg").write_bytes(b"x")
        spy = _ApplySpyRecorder()

        def raise_ki(prompt=""):
            raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", raise_ki)
        code = _run_review_main(monkeypatch, "\n",  # stdin unused: input patched
                                ["-t", "ride.gpx", "--review", str(tmp_path)],
                                spy_apply=spy)
        assert code == 1
        assert spy.calls == []
        assert "aborted" in capsys.readouterr().err.lower()

    def test_unknown_action_reprompts(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "p.jpg").write_bytes(b"x")
        spy = _ApplySpyRecorder()
        code = _run_review_main(monkeypatch, "x\n\n\n",
                                ["-t", "ride.gpx", "--review", str(tmp_path)],
                                spy_apply=spy)
        assert code == 2
        out = capsys.readouterr().out
        assert "unknown action" in out
        _, state = spy.calls[0]
        assert state.decisions == {}


# ── Write mode + CSV ────────────────────────────────────────

class TestReviewWriteMode:

    def _fake_write_phase(self, captured):
        def fake(self_, results, options, photo_dir=None, on_progress=None,
                 on_photo_processed=None, cancel=None):
            captured["results"] = results
            captured["options"] = options
            captured["photo_dir"] = photo_dir
            matched = sum(1 for r in results if r.success)
            return BatchResult(total=len(results), matched=matched,
                               skipped=0, failed=len(results) - matched,
                               overwritten=0, success_rate=matched / len(results),
                               results=results, reject_groups={},
                               concurrent_workers=1)
        return fake

    def test_review_then_write_phase(self, tmp_path, monkeypatch, capsys):
        """Dry review decisions reach write_phase: f1 manual_gps, COPY options."""
        (tmp_path / "p.jpg").write_bytes(b"x")
        out = tmp_path / "out"
        captured = {}
        batch = _failed_batch()
        for p in _patched_scan(batch):
            p.start()
        try:
            patch.object(GPSTaggingService, "write_phase",
                         self._fake_write_phase(captured)).start()
            monkeypatch.setattr(sys, "stdin", FakeTty("g\n1\n\n"))
            code = main(["-t", "ride.gpx", "--review", "-o", str(out), str(tmp_path)])
        finally:
            patch.stopall()
        assert code == 2  # f2 still failed after review
        results = captured["results"]
        f1 = results[1]
        assert f1.success is True
        assert f1.method == "manual_gps"
        assert f1.review_gps == GPSInfo(35.001, 139.001, 120.0)
        assert captured["options"].mode == ProcessMode.COPY
        assert captured["photo_dir"] == Path(str(tmp_path))

    def test_write_mode_html_report_parity(self, tmp_path, monkeypatch, capsys):
        """--report in review write mode also emits HTML (like non-review path)."""
        (tmp_path / "p.jpg").write_bytes(b"x")
        out = tmp_path / "out"
        captured = {}
        batch = _failed_batch()
        for p in _patched_scan(batch):
            p.start()
        try:
            patch.object(GPSTaggingService, "write_phase",
                         self._fake_write_phase(captured)).start()
            monkeypatch.setattr(sys, "stdin", FakeTty("g\n1\n\n"))
            code = main(["-t", "ride.gpx", "--review", "-o", str(out),
                         "--report", str(tmp_path)])
        finally:
            patch.stopall()
        assert code == 2  # f2 still failed
        assert (out / "report.html").exists()
        assert (out / "report.csv").exists()

    def test_csv_reflects_review_gps_dry_run(self, tmp_path, monkeypatch, capsys):
        """Dry-run --report CSV contains the reviewed method/coords."""
        (tmp_path / "p.jpg").write_bytes(b"x")
        monkeypatch.chdir(tmp_path)
        code = _run_review_main(monkeypatch, "g\n1\n\n",
                                ["-t", "ride.gpx", "--review", "--report", str(tmp_path)])
        assert code == 2
        csv_path = tmp_path / "report.csv"
        assert csv_path.exists()
        content = csv_path.read_text(encoding="utf-8")
        assert "manual_gps" in content
        assert "35.001" in content
