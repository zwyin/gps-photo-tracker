"""Tests for review phase: prepare_review, apply_review."""

from pathlib import Path

from gps_photo_tracker.core.models import (
    GPSInfo,
    GPXSegment,
    MatcherConfig,
    MatchResult,
    PhotoInfo,
    ProcessMode,
    ProcessOptions,
    ReviewAction,
    ReviewDecision,
    ReviewState,
    TrackPoint,
)
from gps_photo_tracker.service.tagging_service import GPSTaggingService


def _make_photo(filename: str, timestamp: float = 1000.0) -> PhotoInfo:
    return PhotoInfo(path=Path(f"/tmp/{filename}"), filename=filename,
                     timestamp=timestamp, has_gps=False)


def _make_failed_result(filename: str, reason: str = "time_diff") -> MatchResult:
    return MatchResult(photo=_make_photo(filename), success=False,
                       reject_reason=reason)


def _make_success_result(filename: str) -> MatchResult:
    return MatchResult(photo=_make_photo(filename), success=True,
                       gps=GPSInfo(latitude=25.0, longitude=100.0))


def _make_segment() -> GPXSegment:
    return GPXSegment(
        filename="track.gpx",
        start=900.0, end=1100.0,
        points=[
            TrackPoint(timestamp=950.0, latitude=25.0, longitude=100.0, altitude=100),
            TrackPoint(timestamp=1000.0, latitude=25.001, longitude=100.001, altitude=110),
            TrackPoint(timestamp=1050.0, latitude=25.002, longitude=100.002, altitude=120),
        ],
    )


class TestPrepareReview:

    def test_extracts_failed_results(self):
        service = GPSTaggingService()
        results = [_make_success_result("ok.jpg"), _make_failed_result("fail.jpg")]
        state = service.prepare_review(results, [_make_segment()])
        assert len(state.failed_results) == 1
        assert state.failed_results[0].photo.filename == "fail.jpg"

    def test_includes_gps_segments(self):
        service = GPSTaggingService()
        seg = _make_segment()
        state = service.prepare_review([], [seg])
        assert len(state.gps_segments) == 1

    def test_empty_when_all_succeed(self):
        service = GPSTaggingService()
        results = [_make_success_result("a.jpg"), _make_success_result("b.jpg")]
        state = service.prepare_review(results, [])
        assert len(state.failed_results) == 0


class TestApplyReview:

    def test_manual_gps_sets_review_gps_and_success(self):
        service = GPSTaggingService()
        seg = _make_segment()
        results = [_make_failed_result("fail.jpg")]
        state = ReviewState(
            failed_results=results,
            gps_segments=[seg],
        )
        state.decisions["/tmp/fail.jpg"] = ReviewDecision(
            photo_path="/tmp/fail.jpg",
            action=ReviewAction.MANUAL_GPS,
            selected_point=TrackPoint(timestamp=1000.0, latitude=25.001, longitude=100.001),
        )
        modified = service.apply_review(results, state)
        assert modified[0].success is True
        assert modified[0].review_gps is not None
        assert modified[0].review_gps.latitude == 25.001
        assert modified[0].review_gps.longitude == 100.001

    def test_manual_coord_sets_review_gps(self):
        service = GPSTaggingService()
        results = [_make_failed_result("fail.jpg")]
        state = ReviewState(failed_results=results)
        state.decisions["/tmp/fail.jpg"] = ReviewDecision(
            photo_path="/tmp/fail.jpg",
            action=ReviewAction.MANUAL_COORD,
            manual_lat=30.0,
            manual_lon=120.0,
        )
        modified = service.apply_review(results, state)
        assert modified[0].success is True
        assert modified[0].review_gps == GPSInfo(latitude=30.0, longitude=120.0)

    def test_skip_keeps_failure(self):
        service = GPSTaggingService()
        results = [_make_failed_result("fail.jpg")]
        state = ReviewState(failed_results=results)
        state.decisions["/tmp/fail.jpg"] = ReviewDecision(
            photo_path="/tmp/fail.jpg",
            action=ReviewAction.SKIP,
        )
        modified = service.apply_review(results, state)
        assert modified[0].success is False
        assert modified[0].review_gps is None

    def test_keep_skip_does_nothing(self):
        service = GPSTaggingService()
        results = [_make_failed_result("fail.jpg")]
        state = ReviewState(failed_results=results)
        state.decisions["/tmp/fail.jpg"] = ReviewDecision(
            photo_path="/tmp/fail.jpg",
            action=ReviewAction.KEEP_SKIP,
        )
        modified = service.apply_review(results, state)
        assert modified[0].success is False
        assert modified[0].review_gps is None

    def test_no_decision_for_photo_keeps_failure(self):
        service = GPSTaggingService()
        results = [_make_failed_result("fail.jpg")]
        state = ReviewState(failed_results=results)
        modified = service.apply_review(results, state)
        assert modified[0].success is False

    def test_manual_gps_includes_altitude(self):
        service = GPSTaggingService()
        results = [_make_failed_result("fail.jpg")]
        state = ReviewState(failed_results=results)
        state.decisions["/tmp/fail.jpg"] = ReviewDecision(
            photo_path="/tmp/fail.jpg",
            action=ReviewAction.MANUAL_GPS,
            selected_point=TrackPoint(timestamp=1000.0, latitude=25.0, longitude=100.0, altitude=500.0),
        )
        modified = service.apply_review(results, state)
        assert modified[0].review_gps.altitude == 500.0


class TestWritePhaseWithReviewGPS:

    def test_write_phase_uses_review_gps(self, tmp_path):
        """write_phase should use review_gps when set, overriding gps."""
        from PIL import Image
        service = GPSTaggingService()
        img = Image.new("RGB", (10, 10))
        img.save(tmp_path / "test.jpg", "JPEG")

        result = MatchResult(
            photo=PhotoInfo(path=tmp_path / "test.jpg", filename="test.jpg",
                            timestamp=1000.0, has_gps=False),
            success=True,
            gps=GPSInfo(latitude=0.0, longitude=0.0),
            review_gps=GPSInfo(latitude=39.9, longitude=116.4),
            method="manual_coord",
        )
        options = ProcessOptions(mode=ProcessMode.OVERWRITE)
        batch = service.write_phase([result], options)
        assert batch.matched == 1
        from gps_photo_tracker.core.exif_writer import EXIFWriter
        written = EXIFWriter.read_gps(tmp_path / "test.jpg")
        assert written is not None
        assert abs(written.latitude - 39.9) < 0.01
        assert abs(written.longitude - 116.4) < 0.01

    def test_write_phase_skips_failed(self, tmp_path):
        service = GPSTaggingService()
        result = _make_failed_result("fail.jpg")
        options = ProcessOptions(mode=ProcessMode.OVERWRITE)
        batch = service.write_phase([result], options)
        assert batch.matched == 0
        assert batch.failed == 1


class TestWorkerReviewSignal:

    def test_worker_emits_review_ready_on_failure(self, qtbot, tmp_path):
        """Worker should emit review_ready when preview finds failures."""
        import textwrap
        from gps_photo_tracker.gui.worker import Worker
        from gps_photo_tracker.core.models import ProcessMode, ProcessOptions, MatcherConfig
        from PIL import Image
        import piexif

        gpx = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>
            <trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:05:00Z</time></trkpt>
          </trkseg></trk>
        </gpx>
        """)
        (tmp_path / "track.gpx").write_text(gpx)

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 20:00:00"}}
        img.save(tmp_path / "photo.jpg", "JPEG", exif=piexif.dump(exif))

        options = ProcessOptions(mode=ProcessMode.PREVIEW)
        config = MatcherConfig()
        worker = Worker(
            gps_dir=tmp_path, photo_dir=tmp_path,
            config=config, options=options,
        )

        signals = []
        worker.review_ready_signal.connect(lambda s: signals.append(s))

        with qtbot.waitSignal(worker.review_ready_signal, timeout=10000):
            worker.run()

        assert len(signals) == 1
        assert len(signals[0]["failed_results"]) > 0
