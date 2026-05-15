"""Tests for review phase: prepare_review, apply_review."""

from pathlib import Path

from gps_photo_tracker.core.models import (
    GPSInfo,
    GPXSegment,
    MatcherConfig,
    MatchResult,
    PhotoInfo,
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
