"""Tests for new model fields added in v0.8.0."""
from pathlib import Path

from gps_photo_tracker.core.models import (
    BatchResult, PhotoInfo, ProcessOptions,
    ProcessMode,
)


class TestReviewModels:

    def test_review_action_values(self):
        from gps_photo_tracker.core.models import ReviewAction
        assert ReviewAction.KEEP_SKIP.value == "keep_skip"
        assert ReviewAction.MANUAL_GPS.value == "manual_gps"
        assert ReviewAction.MANUAL_COORD.value == "manual_coord"
        assert ReviewAction.SKIP.value == "skip"

    def test_review_decision_defaults(self):
        from gps_photo_tracker.core.models import ReviewDecision, ReviewAction
        d = ReviewDecision(photo_path="/tmp/test.jpg", action=ReviewAction.SKIP)
        assert d.selected_point is None
        assert d.manual_lat is None
        assert d.manual_lon is None

    def test_review_state_defaults(self):
        from gps_photo_tracker.core.models import ReviewState
        state = ReviewState(failed_results=[])
        assert state.decisions == {}
        assert state.gps_segments == []

    def test_match_result_has_review_gps(self):
        from gps_photo_tracker.core.models import MatchResult, PhotoInfo
        photo = PhotoInfo(path=Path("/tmp/test.jpg"), filename="test.jpg",
                          timestamp=1000.0, has_gps=False)
        result = MatchResult(photo=photo, success=True)
        assert result.review_gps is None


def test_process_options_new_defaults():
    opts = ProcessOptions(mode=ProcessMode.PREVIEW)
    assert opts.resume is False
    assert opts.generate_report is False
    assert opts.workers == 1


def test_batch_result_concurrent_workers():
    r = BatchResult(total=10, matched=5, skipped=2, failed=3,
                    overwritten=0, success_rate=0.5, concurrent_workers=4)
    assert r.concurrent_workers == 4


def test_batch_result_default_workers():
    r = BatchResult(total=0, matched=0, skipped=0, failed=0,
                    overwritten=0, success_rate=0.0)
    assert r.concurrent_workers == 1


def test_photo_info_orientation_default():
    p = PhotoInfo(path=Path("/x.jpg"), filename="x.jpg",
                  timestamp=1.0, has_gps=False)
    assert p.orientation is None


def test_photo_info_orientation_set():
    p = PhotoInfo(path=Path("/x.jpg"), filename="x.jpg",
                  timestamp=1.0, has_gps=False, orientation=6)
    assert p.orientation == 6
