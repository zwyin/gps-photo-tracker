"""Tests for GPSMatcher with linear interpolation."""

import pytest

from gps_photo_tracker.core.gps_matcher import GPSMatcher
from gps_photo_tracker.core.models import GPXSegment, MatcherConfig, RejectReason

from conftest import utc, make_point, make_segment, make_photo


# ── Fixtures ───────────────────────────────────────────────

@pytest.fixture
def default_matcher():
    return GPSMatcher(MatcherConfig())


def _uniform_segment():
    """GPS points every 60s, tightly spaced so distance < 200m between consecutive."""
    points = []
    for i in range(11):
        t = utc(8, i)  # 08:00, 08:01, ..., 08:10
        lat = 25.0 + i * 0.0001  # ~11m per step, ~110m total → well within 200m
        lon = 100.0 + i * 0.0001
        alt = 1000.0 + i * 10.0
        points.append(make_point(lat, lon, t, alt))
    return make_segment(points)


def _middle_photo():
    """Photo at 08:05 — exactly midpoint of uniform segment."""
    return make_photo("mid.jpg", utc(8, 5))


# ── Interpolation tests ────────────────────────────────────

class TestInterpolation:

    def test_basic_interpolation(self, default_matcher):
        seg = _uniform_segment()
        photo = _middle_photo()
        # Neighbors in context_window (300s)
        photos = [
            make_photo("p0.jpg", utc(8, 3)),
            photo,
            make_photo("p2.jpg", utc(8, 7)),
        ]
        results = default_matcher.match(photos, [seg])
        mid_result = results[1]
        assert mid_result.success
        assert mid_result.method == "interpolated"
        assert mid_result.gps is not None

    def test_interpolation_accuracy(self, default_matcher):
        """Interpolation at midpoint should be within 1m of analytical solution."""
        seg = _uniform_segment()
        photo = _middle_photo()
        photos = [
            make_photo("prev.jpg", utc(8, 2)),
            photo,
            make_photo("next.jpg", utc(8, 8)),
        ]
        results = default_matcher.match(photos, [seg])
        gps = results[1].gps
        assert gps is not None
        # At 08:05, index=5, lat=25.005, lon=100.005, alt=1050.0
        assert abs(gps.latitude - 25.0005) < 0.0001
        assert abs(gps.longitude - 100.0005) < 0.0001
        assert abs(gps.altitude - 1050.0) < 1.0

    def test_interpolation_context_fields(self, default_matcher):
        seg = _uniform_segment()
        photo = _middle_photo()
        photos = [
            make_photo("prev.jpg", utc(8, 2)),
            photo,
            make_photo("next.jpg", utc(8, 8)),
        ]
        results = default_matcher.match(photos, [seg])
        r = results[1]
        assert r.interpolation_prev is not None
        assert r.interpolation_next is not None
        assert r.interpolation_distance is not None
        assert r.interpolation_distance > 0
        assert r.interpolation_ratio is not None
        assert 0.0 < r.interpolation_ratio < 1.0

    def test_nearest_match_has_no_interpolation_fields(self, default_matcher):
        """nearest match should have None interpolation fields."""
        # Extend segment range so photo falls within seg.start <= ts <= seg.end
        seg = make_segment([make_point(25.0, 100.0, utc(8, 0)), make_point(25.0, 100.0, utc(8, 3))])
        photos = [make_photo("iso.jpg", utc(8, 1))]  # 60s away, within segment range
        results = default_matcher.match(photos, [seg])
        assert results[0].success
        assert results[0].method == "nearest"
        assert results[0].interpolation_prev is None
        assert results[0].interpolation_next is None


# ── Nearest match tests ────────────────────────────────────

class TestNearestMatch:

    def test_nearest_match_single_side(self, default_matcher):
        """Middle photo but only prev GPS point → nearest."""
        # Photo at exact last GPS point time → prev_point exists, next_point=None
        points = [make_point(25.0, 100.0, utc(8, 0)), make_point(25.001, 100.001, utc(8, 4))]
        seg = make_segment(points)
        photos = [
            make_photo("p0.jpg", utc(8, 2)),    # prev_photo, within context_window
            make_photo("mid.jpg", utc(8, 4)),    # matches last GPS point, no next GPS
            make_photo("p2.jpg", utc(8, 6)),     # next_photo, within context_window
        ]
        results = default_matcher.match(photos, [seg])
        # mid.jpg: prev exists, next doesn't → nearest with prev
        mid = results[1]
        assert mid.success
        assert mid.method == "nearest"

    def test_isolated_match_enabled(self):
        matcher = GPSMatcher(MatcherConfig(match_isolated=True, isolated_window=300))
        seg = make_segment([make_point(25.0, 100.0, utc(8, 0)), make_point(25.0, 100.0, utc(8, 5))])
        photos = [make_photo("iso.jpg", utc(8, 1))]  # 60s away
        results = matcher.match(photos, [seg])
        assert results[0].success
        assert results[0].method == "nearest"

    def test_isolated_reject_tail_false(self):
        matcher = GPSMatcher(MatcherConfig(match_isolated=False))
        seg = make_segment([make_point(25.0, 100.0, utc(8, 0)), make_point(25.0, 100.0, utc(8, 5))])
        photos = [make_photo("iso.jpg", utc(8, 1))]
        results = matcher.match(photos, [seg])
        assert not results[0].success
        assert results[0].reject_reason == RejectReason.ISOLATED_DISABLED

    def test_head_isolated_within_tolerance(self):
        """Photo before segment start but within isolated_window → matched as isolated."""
        matcher = GPSMatcher(MatcherConfig(match_isolated=True, isolated_window=300, context_window=60))
        seg = make_segment([make_point(25.0, 100.0, utc(8, 5)), make_point(25.0, 100.0, utc(8, 10))])
        photos = [make_photo("head.jpg", utc(8, 3))]  # 120s before segment start
        results = matcher.match(photos, [seg])
        assert results[0].success
        assert results[0].method == "nearest"

    def test_tail_isolated_within_tolerance(self):
        """Photo after segment end but within isolated_window → matched as isolated."""
        matcher = GPSMatcher(MatcherConfig(match_isolated=True, isolated_window=300, context_window=60))
        seg = make_segment([make_point(25.0, 100.0, utc(8, 0)), make_point(25.0, 100.0, utc(8, 5))])
        photos = [make_photo("tail.jpg", utc(8, 7))]  # 120s after segment end
        results = matcher.match(photos, [seg])
        assert results[0].success
        assert results[0].method == "nearest"

    def test_head_isolated_beyond_tolerance(self):
        """Photo before segment start and beyond isolated_window → NO_GPS_COVERAGE."""
        matcher = GPSMatcher(MatcherConfig(match_isolated=True, isolated_window=300))
        seg = make_segment([make_point(25.0, 100.0, utc(8, 5)), make_point(25.0, 100.0, utc(8, 10))])
        photos = [make_photo("far_head.jpg", utc(7, 59))]  # 361s before, beyond tolerance
        results = matcher.match(photos, [seg])
        assert not results[0].success
        assert results[0].reject_reason == RejectReason.NO_GPS_COVERAGE

    def test_middle_isolated_still_works(self):
        """Photo within segment range but neighbors far apart → isolated match."""
        matcher = GPSMatcher(MatcherConfig(match_isolated=True, isolated_window=300, context_window=60))
        seg = make_segment([make_point(25.0, 100.0, utc(8, 0)), make_point(25.0, 100.0, utc(8, 5))])
        # Single photo in segment → no neighbors → isolated
        photos = [make_photo("middle_iso.jpg", utc(8, 2))]
        results = matcher.match(photos, [seg])
        assert results[0].success
        assert results[0].method == "nearest"

    def test_head_tail_middle_isolated_consistency(self):
        """All three isolated types should produce the same result when match_isolated=True."""
        matcher = GPSMatcher(MatcherConfig(match_isolated=True, isolated_window=300, context_window=60))
        seg = make_segment([make_point(25.0, 100.0, utc(8, 5)), make_point(25.0, 100.0, utc(8, 10))])
        # Head: 60s before start, middle: at 8:07, tail: 60s after end
        photos = [
            make_photo("head.jpg", utc(8, 4)),    # 60s before seg.start
            make_photo("middle.jpg", utc(8, 7)),   # within segment
            make_photo("tail.jpg", utc(8, 11)),    # 60s after seg.end
        ]
        results = matcher.match(photos, [seg])
        for r in results:
            assert r.success, f"{r.photo.filename} should succeed"
            assert r.method == "nearest"

    def test_all_isolated_rejected_when_disabled(self):
        """All three isolated types rejected when match_isolated=False."""
        matcher = GPSMatcher(MatcherConfig(match_isolated=False, isolated_window=300, context_window=60))
        seg = make_segment([make_point(25.0, 100.0, utc(8, 5)), make_point(25.0, 100.0, utc(8, 10))])
        photos = [
            make_photo("head.jpg", utc(8, 4)),
            make_photo("middle.jpg", utc(8, 7)),
            make_photo("tail.jpg", utc(8, 11)),
        ]
        results = matcher.match(photos, [seg])
        for r in results:
            assert not r.success, f"{r.photo.filename} should fail"
            # Head/tail fail at _find_segment → NO_GPS_COVERAGE
            # Middle fails at isolated check → ISOLATED_DISABLED
            assert r.reject_reason in (RejectReason.NO_GPS_COVERAGE, RejectReason.ISOLATED_DISABLED)


# ── Rejection tests ────────────────────────────────────────

class TestRejection:

    def test_no_gps_coverage(self, default_matcher):
        seg = make_segment([make_point(25.0, 100.0, utc(8, 0))])
        photos = [make_photo("out.jpg", utc(10, 0))]  # far outside segment
        results = default_matcher.match(photos, [seg])
        assert not results[0].success
        assert results[0].reject_reason == RejectReason.NO_GPS_COVERAGE

    def test_gps_distance_degrades_to_nearest(self):
        """prev and next GPS points > max_gps_distance → degrade to nearest-point."""
        matcher = GPSMatcher(MatcherConfig(max_gps_distance=200))
        points = [
            make_point(25.0, 100.0, utc(8, 0)),
            make_point(25.0, 100.0, utc(8, 5)),  # same location as first
            make_point(26.0, 101.0, utc(8, 10)),  # ~157km away!
        ]
        seg = make_segment(points)
        photos = [
            make_photo("p0.jpg", utc(8, 1)),
            make_photo("mid.jpg", utc(8, 5)),  # between close and far point
            make_photo("p2.jpg", utc(8, 9)),
        ]
        results = matcher.match(photos, [seg])
        # mid at 08:05: prev=08:00 (300s), next=08:10 (300s) → picks prev (<=)
        # distance too large → degrade to nearest
        mid = results[1]
        assert mid.success
        assert mid.method == "nearest"
        assert mid.time_diff == 300

    def test_time_diff_exceeded_middle(self):
        matcher = GPSMatcher(MatcherConfig(middle_time_window=60))
        points = [make_point(25.0, 100.0, utc(8, 0)), make_point(25.001, 100.001, utc(8, 30))]
        seg = make_segment(points)
        photos = [
            make_photo("p0.jpg", utc(8, 0, 30)),
            make_photo("mid.jpg", utc(8, 10)),
            make_photo("p2.jpg", utc(8, 10, 30)),
        ]
        results = matcher.match(photos, [seg])
        mid = results[1]
        assert not mid.success
        assert mid.reject_reason == RejectReason.TIME_DIFF

    def test_time_diff_exceeded_isolated(self):
        matcher = GPSMatcher(MatcherConfig(isolated_window=30))
        seg = make_segment([make_point(25.0, 100.0, utc(8, 0)), make_point(25.0, 100.0, utc(8, 5))])
        photos = [make_photo("iso.jpg", utc(8, 1))]  # 60s > 30s
        results = matcher.match(photos, [seg])
        assert not results[0].success
        assert results[0].reject_reason == RejectReason.TIME_DIFF

    def test_middle_degradation_nearest_too_far(self):
        """Distance too large + nearest point also beyond middle_time_window → TIME_DIFF, second pass also blocked."""
        matcher = GPSMatcher(MatcherConfig(max_gps_distance=200, middle_time_window=60, isolated_window=60))
        points = [
            make_point(25.0, 100.0, utc(8, 0)),
            make_point(26.0, 101.0, utc(8, 10)),  # ~157km, 600s away
        ]
        seg = make_segment(points)
        photos = [
            make_photo("p0.jpg", utc(8, 1)),
            make_photo("mid.jpg", utc(8, 5)),  # prev_td=300s, next_td=300s, both > 60s
            make_photo("p2.jpg", utc(8, 9)),
        ]
        results = matcher.match(photos, [seg])
        mid = results[1]
        assert not mid.success
        assert mid.reject_reason == RejectReason.TIME_DIFF

    def test_middle_degradation_picks_closer_point(self):
        """Distance too large → picks the closer GPS point by time_diff."""
        matcher = GPSMatcher(MatcherConfig(max_gps_distance=200, middle_time_window=3600))
        points = [
            make_point(25.0, 100.0, utc(8, 0)),
            make_point(26.0, 101.0, utc(8, 10)),
        ]
        seg = make_segment(points)
        photos = [
            make_photo("p0.jpg", utc(8, 1)),
            make_photo("mid.jpg", utc(8, 2)),  # prev_td=120s, next_td=480s → picks prev
            make_photo("p2.jpg", utc(8, 3)),
        ]
        results = matcher.match(photos, [seg])
        mid = results[1]
        assert mid.success
        assert mid.method == "nearest"
        assert mid.time_diff == 120
        assert mid.gps.latitude == 25.0
        assert mid.gps.longitude == 100.0

    def test_no_track_points(self, default_matcher):
        seg = GPXSegment(filename="empty.gpx", start=utc(8, 0), end=utc(8, 10), points=[])
        photos = [make_photo("x.jpg", utc(8, 5))]
        results = default_matcher.match(photos, [seg])
        assert not results[0].success
        assert results[0].reject_reason == RejectReason.NO_TRACK_POINTS


# ── Parameter effect tests ─────────────────────────────────

class TestParameterEffects:

    def test_time_offset_positive(self):
        seg = _uniform_segment()
        photo = make_photo("p.jpg", utc(8, 5))
        photos = [make_photo("prev.jpg", utc(8, 2)), photo, make_photo("next.jpg", utc(8, 8))]

        m0 = GPSMatcher(MatcherConfig(time_offset=0))
        m60 = GPSMatcher(MatcherConfig(time_offset=60))  # shifts to 08:06

        r0 = m0.match(photos, [seg])[1]
        r60 = m60.match(photos, [seg])[1]

        assert r0.success
        assert r60.success
        # offset=60 → matches GPS at ~08:06 instead of 08:05
        assert r60.gps.latitude > r0.gps.latitude

    def test_time_offset_negative(self):
        seg = _uniform_segment()
        photo = make_photo("p.jpg", utc(8, 5))
        photos = [make_photo("prev.jpg", utc(8, 2)), photo, make_photo("next.jpg", utc(8, 8))]

        m0 = GPSMatcher(MatcherConfig(time_offset=0))
        mneg = GPSMatcher(MatcherConfig(time_offset=-60))

        r0 = m0.match(photos, [seg])[1]
        rneg = mneg.match(photos, [seg])[1]

        assert r0.success
        assert rneg.success
        assert rneg.gps.latitude < r0.gps.latitude

    def test_time_offset_shifts_match_target(self):
        """time_offset=+60 should match GPS at original_time + 60s."""
        seg = _uniform_segment()
        photo = make_photo("p.jpg", utc(8, 5))
        photos = [make_photo("prev.jpg", utc(8, 2)), photo, make_photo("next.jpg", utc(8, 8))]

        m60 = GPSMatcher(MatcherConfig(time_offset=60))
        result = m60.match(photos, [seg])[1]
        assert result.success
        # At 08:06 → lat=25.006, lon=100.006
        assert abs(result.gps.latitude - 25.0006) < 0.0001

    def test_context_window_effect(self):
        """Narrow context_window → photos become isolated."""
        seg = _uniform_segment()
        photos = [
            make_photo("p0.jpg", utc(8, 0)),
            make_photo("mid.jpg", utc(8, 5)),  # 300s from p0
            make_photo("p2.jpg", utc(8, 10)),  # 300s from mid
        ]

        # Wide window: mid is "middle"
        m_wide = GPSMatcher(MatcherConfig(context_window=400))
        r_wide = m_wide.match(photos, [seg])[1]
        assert r_wide.method == "interpolated"

        # Narrow window: mid is "isolated"
        m_narrow = GPSMatcher(MatcherConfig(context_window=60))
        r_narrow = m_narrow.match(photos, [seg])[1]
        assert r_narrow.method == "nearest"

    def test_middle_time_window_effect(self):
        points = [make_point(25.0, 100.0, utc(8, 0)), make_point(25.001, 100.001, utc(8, 5))]
        seg = make_segment(points)
        photos = [
            make_photo("p0.jpg", utc(8, 0, 30)),
            make_photo("mid.jpg", utc(8, 2, 30)),
            make_photo("p2.jpg", utc(8, 4, 30)),
        ]

        # Time span between prev and next GPS points = 300s
        m_wide = GPSMatcher(MatcherConfig(middle_time_window=400))
        m_narrow = GPSMatcher(MatcherConfig(middle_time_window=60, isolated_window=60))

        assert m_wide.match(photos, [seg])[1].success
        assert not m_narrow.match(photos, [seg])[1].success

    def test_isolated_window_effect(self):
        seg = make_segment([make_point(25.0, 100.0, utc(8, 0)), make_point(25.0, 100.0, utc(8, 5))])
        photos = [make_photo("iso.jpg", utc(8, 2))]  # 120s from nearest point

        m_wide = GPSMatcher(MatcherConfig(isolated_window=300))
        m_narrow = GPSMatcher(MatcherConfig(isolated_window=60))

        assert m_wide.match(photos, [seg])[0].success
        assert not m_narrow.match(photos, [seg])[0].success

    def test_max_gps_distance_effect(self):
        points = [
            make_point(25.0, 100.0, utc(8, 0)),
            make_point(25.01, 100.01, utc(8, 10)),  # ~1.5km away
        ]
        seg = make_segment(points)
        photos = [
            make_photo("p0.jpg", utc(8, 2)),
            make_photo("mid.jpg", utc(8, 5)),
            make_photo("p2.jpg", utc(8, 8)),
        ]

        m_wide = GPSMatcher(MatcherConfig(max_gps_distance=2000))
        m_narrow = GPSMatcher(MatcherConfig(max_gps_distance=200))

        wide_result = m_wide.match(photos, [seg])[1]
        narrow_result = m_narrow.match(photos, [seg])[1]
        # wide: distance OK → interpolated
        assert wide_result.success
        assert wide_result.method == "interpolated"
        # narrow: distance too large → degrade to nearest (300s < middle_time_window)
        assert narrow_result.success
        assert narrow_result.method == "nearest"


# ── Altitude edge cases ────────────────────────────────────

class TestAltitudeEdgeCases:

    def test_altitude_none_in_interpolation(self):
        """One GPS point has altitude=None → interpolation uses 0 for that side."""
        points = [
            make_point(25.0, 100.0, utc(8, 0), alt=1000.0),
            make_point(25.01, 100.01, utc(8, 10), alt=None),
        ]
        seg = make_segment(points)
        photos = [
            make_photo("p0.jpg", utc(8, 2)),
            make_photo("mid.jpg", utc(8, 5)),  # ratio=0.5
            make_photo("p2.jpg", utc(8, 8)),
        ]
        matcher = GPSMatcher(MatcherConfig(max_gps_distance=2000))
        result = matcher.match(photos, [seg])[1]
        assert result.success
        assert result.gps.altitude is not None
        # 0.5 * 1000 + 0.5 * 0 = 500.0
        assert abs(result.gps.altitude - 500.0) < 1.0

    def test_altitude_both_none_in_interpolation(self):
        """Both GPS points have altitude=None → result altitude=None."""
        points = [
            make_point(25.0, 100.0, utc(8, 0), alt=None),
            make_point(25.001, 100.001, utc(8, 10), alt=None),
        ]
        seg = make_segment(points)
        photos = [
            make_photo("p0.jpg", utc(8, 2)),
            make_photo("mid.jpg", utc(8, 5)),
            make_photo("p2.jpg", utc(8, 8)),
        ]
        matcher = GPSMatcher(MatcherConfig())
        result = matcher.match(photos, [seg])[1]
        assert result.success
        assert result.gps.altitude is None


# ── Boundary tests (prev/next=None) ────────────────────────

class TestBoundaryConditions:

    def test_first_photo_prev_none(self, default_matcher):
        """First photo has prev=None → should be isolated."""
        seg = _uniform_segment()
        photos = [
            make_photo("first.jpg", utc(8, 5)),  # first, no prev
            make_photo("second.jpg", utc(8, 6)),
            make_photo("third.jpg", utc(8, 7)),
        ]
        results = default_matcher.match(photos, [seg])
        # first.jpg: prev=None → isolated (context_window check fails for prev)
        first = results[0]
        assert first.success  # match_isolated=True by default
        assert first.method == "nearest"  # isolated → nearest

    def test_last_photo_next_none(self, default_matcher):
        seg = _uniform_segment()
        photos = [
            make_photo("first.jpg", utc(8, 3)),
            make_photo("second.jpg", utc(8, 4)),
            make_photo("last.jpg", utc(8, 9)),  # last, no next
        ]
        results = default_matcher.match(photos, [seg])
        last = results[2]
        assert last.success
        assert last.method == "nearest"

    def test_single_photo_no_neighbors(self, default_matcher):
        seg = _uniform_segment()
        photos = [make_photo("only.jpg", utc(8, 5))]
        results = default_matcher.match(photos, [seg])
        assert results[0].success
        assert results[0].method == "nearest"


# ── Output contract tests ──────────────────────────────────

class TestOutputContract:

    def test_returns_equal_length(self, default_matcher):
        seg = _uniform_segment()
        photos = [make_photo(f"p{i}.jpg", utc(8, i)) for i in range(11)]
        results = default_matcher.match(photos, [seg])
        assert len(results) == len(photos)

    def test_batch_mixed_results(self, default_matcher):
        """Mix of matched, failed, and different methods."""
        points = [
            make_point(25.0, 100.0, utc(8, 0)),
            make_point(25.001, 100.001, utc(8, 1)),
            make_point(25.002, 100.002, utc(8, 2)),
        ]
        seg = make_segment(points)
        photos = [
            make_photo("in1.jpg", utc(8, 0, 30)),  # interpolated
            make_photo("in2.jpg", utc(8, 1, 30)),  # interpolated
            make_photo("out.jpg", utc(12, 0)),      # NO_GPS_COVERAGE
        ]
        results = default_matcher.match(photos, [seg])
        assert len(results) == 3
        assert results[0].success
        assert results[1].success
        assert not results[2].success
        assert results[2].reject_reason == RejectReason.NO_GPS_COVERAGE


class TestDivisionByZeroProtection:
    """Photo between two GPS points with same timestamp should not crash."""

    def test_same_timestamp_points(self, default_matcher):
        pts = [
            make_point(25.0, 100.0, utc(8, 0, 0)),
            make_point(25.001, 100.001, utc(8, 10, 0)),
        ]
        seg = make_segment(pts)
        photo = make_photo("p.jpg", utc(8, 5, 0))

        results = default_matcher.match([photo], [seg])
        assert len(results) == 1
        assert results[0].success


class TestNoneTimestampFiltering:
    """Photos with timestamp=None should be filtered out by match()."""

    def test_none_timestamp_photos_excluded(self, default_matcher):
        """match() should skip photos with timestamp=None (no crash)."""
        seg = _uniform_segment()
        from pathlib import Path
        from gps_photo_tracker.core.models import PhotoInfo
        photo_none = PhotoInfo(path=Path("/x.jpg"), filename="none.jpg",
                               timestamp=None, has_gps=False)
        photo_valid = make_photo("valid.jpg", utc(8, 5))
        results = default_matcher.match([photo_none, photo_valid], [seg])
        # Only valid photo should be in results
        assert len(results) == 1
        assert results[0].photo.filename == "valid.jpg"

    def test_all_none_timestamp_returns_empty(self, default_matcher):
        seg = _uniform_segment()
        from pathlib import Path
        from gps_photo_tracker.core.models import PhotoInfo
        photos = [
            PhotoInfo(path=Path("/a.jpg"), filename="a.jpg", timestamp=None, has_gps=False),
            PhotoInfo(path=Path("/b.jpg"), filename="b.jpg", timestamp=None, has_gps=False),
        ]
        results = default_matcher.match(photos, [seg])
        assert len(results) == 0


class TestZeroSpanInterpolationDistance:
    """Zero-span edge case should compute distance correctly (bug fix).

    When prev and next GPS points have the same timestamp but the photo falls
    between them (photo time == GPS time), both _find_prev_point and _find_next_point
    return None because they use strict < / >. In this case the photo correctly gets
    NO_TRACK_POINTS. The real zero-span bug we're fixing is when prev.timestamp ==
    next.timestamp but the photo time is exactly at that same timestamp -- the code
    used to crash with AttributeError from self._distance() which didn't exist.
    Now it correctly returns NO_TRACK_POINTS without crashing.
    """

    def test_zero_span_no_crash(self):
        """Two GPS points with same timestamp should not crash the matcher."""
        matcher = GPSMatcher(MatcherConfig(isolated_window=60))
        pts = [
            make_point(25.0, 100.0, utc(8, 5)),
            make_point(25.001, 100.001, utc(8, 5)),  # same timestamp
        ]
        seg = make_segment(pts)
        photos = [
            make_photo("prev.jpg", utc(8, 3)),
            make_photo("mid.jpg", utc(8, 5)),
            make_photo("next.jpg", utc(8, 7)),
        ]
        # Should not crash — used to crash with AttributeError: self._distance
        results = matcher.match(photos, [seg])
        assert len(results) == 3
        # The mid photo at exact GPS time gets NO_TRACK_POINTS (prev/next are strict)
        mid = results[1]
        assert not mid.success
        assert mid.reject_reason == RejectReason.NO_TRACK_POINTS

    def test_interpolation_with_very_close_timestamps(self):
        """GPS points 1 second apart should interpolate correctly."""
        matcher = GPSMatcher(MatcherConfig())
        pts = [
            make_point(25.0, 100.0, utc(8, 5, 0)),
            make_point(25.001, 100.001, utc(8, 5, 1)),  # 1 second apart
        ]
        seg = make_segment(pts)
        photos = [
            make_photo("prev.jpg", utc(8, 3)),
            make_photo("mid.jpg", utc(8, 5, 0)),  # exact same time as first point
            make_photo("next.jpg", utc(8, 7)),
        ]
        results = matcher.match(photos, [seg])
        mid = results[1]
        # Photo at same time as first GPS point: prev=None (strict <), next exists
        # This gives single-sided nearest match, not interpolation
        assert mid.success
        assert mid.method == "nearest"


# ── BUG-5: Skip photos with existing GPS when overwrite disabled ──


class TestSkipExistingGPS:
    """Photos with existing GPS should be skipped when overwrite_gps=False."""

    def test_skip_gps_photo_default_config(self):
        """Default config (overwrite_gps=False): GPS photo is skipped."""
        matcher = GPSMatcher(MatcherConfig())
        seg = _uniform_segment()
        photo = make_photo("gps.jpg", utc(8, 5), has_gps=True, lat=25.0, lon=100.0)
        results = matcher.match([photo], [seg])
        assert len(results) == 1
        r = results[0]
        assert r.success
        assert r.method == "skipped"
        assert r.gps is not None
        assert r.gps.latitude == 25.0
        assert r.gps.longitude == 100.0

    def test_skip_gps_photo_mixed_batch(self):
        """Mixed batch: GPS photos skipped, non-GPS photos matched normally."""
        matcher = GPSMatcher(MatcherConfig())
        seg = _uniform_segment()
        photos = [
            make_photo("gps1.jpg", utc(8, 2), has_gps=True, lat=25.0, lon=100.0),
            make_photo("no_gps.jpg", utc(8, 5)),
            make_photo("gps2.jpg", utc(8, 8), has_gps=True, lat=26.0, lon=101.0),
        ]
        results = matcher.match(photos, [seg])
        assert results[0].method == "skipped"
        assert results[0].success
        assert results[1].method == "interpolated"
        assert results[1].success
        assert results[2].method == "skipped"
        assert results[2].success

    def test_overwrite_gps_photos_when_enabled(self):
        """overwrite_gps=True: GPS photos go through normal matching."""
        config = MatcherConfig(overwrite_gps=True)
        matcher = GPSMatcher(config)
        seg = _uniform_segment()
        photos = [
            make_photo("prev.jpg", utc(8, 3)),
            make_photo("gps.jpg", utc(8, 5), has_gps=True, lat=25.0, lon=100.0),
            make_photo("next.jpg", utc(8, 7)),
        ]
        results = matcher.match(photos, [seg])
        r = results[1]
        assert r.success
        assert r.method == "interpolated"
        # GPS should be interpolated, not the original
        assert r.gps is not None
        assert r.gps.latitude != 25.0 or r.gps.longitude != 100.0

    def test_skip_preserves_existing_gps(self):
        """Skipped photos keep their original GPS coordinates."""
        matcher = GPSMatcher(MatcherConfig())
        seg = _uniform_segment()
        photo = make_photo("gps.jpg", utc(8, 5), has_gps=True, lat=30.5, lon=120.3, alt=500.0)
        results = matcher.match([photo], [seg])
        r = results[0]
        assert r.gps.latitude == 30.5
        assert r.gps.longitude == 120.3
        assert r.gps.altitude == 500.0

    def test_no_timestamp_photo_filtered_out(self):
        """Photos without timestamp are excluded from matching entirely."""
        from pathlib import Path
        from gps_photo_tracker.core.models import PhotoInfo
        matcher = GPSMatcher(MatcherConfig())
        seg = _uniform_segment()
        photo = PhotoInfo(
            path=Path("/photos/no_ts.jpg"),
            filename="no_ts.jpg",
            timestamp=None,
            has_gps=False,
        )
        results = matcher.match([photo], [seg])
        assert len(results) == 0


# ── Second pass neighbor follow ──────────────────────────────

class TestSecondPassNeighborFollow:

    def test_auto_follow_prev_within_window(self):
        """Failed photo follows prev successful neighbor within isolated_window."""
        # seg at 08:00, p0 at 08:01:40 (100s from seg → matches), fail at 08:02 (120s → fails)
        matcher = GPSMatcher(MatcherConfig(isolated_window=100, match_isolated=True))
        seg = make_segment([make_point(25.0, 100.0, utc(8, 0))])
        photos = [
            make_photo("p0.jpg", utc(8, 1, 40)),
            make_photo("fail.jpg", utc(8, 2)),
        ]
        results = matcher.match(photos, [seg])
        assert results[0].success
        assert results[1].success
        assert results[1].method == "auto_follow_prev"
        assert results[1].gps.latitude == 25.0

    def test_auto_follow_next_within_window(self):
        """Failed photo follows next successful neighbor within isolated_window."""
        # seg at 08:05, fail at 08:03 (120s from seg → fails), p1 at 08:03:20 (100s → matches)
        matcher = GPSMatcher(MatcherConfig(isolated_window=100, match_isolated=True))
        seg = make_segment([make_point(25.0, 100.0, utc(8, 5))])
        photos = [
            make_photo("fail.jpg", utc(8, 3)),
            make_photo("p1.jpg", utc(8, 3, 20)),
        ]
        results = matcher.match(photos, [seg])
        assert results[0].success
        assert results[0].method == "auto_follow_next"

    def test_auto_follow_next_closer_than_prev(self):
        """Both neighbors within window, next is closer → follows next."""
        # seg_a at 08:00, seg_b at 08:05, isolated_window=100
        matcher = GPSMatcher(MatcherConfig(isolated_window=100, match_isolated=True))
        seg_a = make_segment([make_point(25.0, 100.0, utc(8, 0))])
        seg_b = make_segment([make_point(25.005, 100.005, utc(8, 5))])
        photos = [
            make_photo("prev.jpg", utc(8, 1, 30)),   # 90s from seg_a → matches
            make_photo("fail.jpg", utc(8, 2, 50)),    # 170s from seg_a, 130s from seg_b → fails
            make_photo("next.jpg", utc(8, 3, 50)),    # 70s from seg_b → matches
        ]
        results = matcher.match(photos, [seg_a, seg_b])
        # prev=80s, next=60s → next closer → auto_follow_next
        assert results[1].success
        assert results[1].method == "auto_follow_next"

    def test_auto_follow_blocked_by_window(self):
        """Both neighbors too far in time → second pass still fails."""
        matcher = GPSMatcher(MatcherConfig(isolated_window=60, match_isolated=True))
        seg = make_segment([make_point(25.0, 100.0, utc(8, 0))])
        photos = [
            make_photo("p0.jpg", utc(8, 0, 30)),   # matches (30s from seg)
            make_photo("fail.jpg", utc(8, 3)),       # 180s from seg → NO_GPS_COVERAGE
        ]
        results = matcher.match(photos, [seg])
        assert not results[1].success  # 150s from p0 > 60

    def test_case_00975_far_neighbors(self):
        """v0.16.0 case: 00975 far from both neighbors → second pass rejects."""
        matcher = GPSMatcher(MatcherConfig(isolated_window=300, match_isolated=True))
        seg_a = make_segment([make_point(23.6190, 102.8299, utc(9, 19))])
        seg_b = make_segment([make_point(23.0873, 102.8166, utc(15, 15))])
        photos = [
            make_photo("00973.jpg", utc(9, 19, 30)),
            make_photo("00975.jpg", utc(14, 9)),
            make_photo("00984.jpg", utc(15, 14, 30)),
        ]
        results = matcher.match(photos, [seg_a, seg_b])
        assert results[0].success
        assert not results[1].success
        assert results[2].success


class TestRealDataRegression:
    """Regression tests using coordinates and timestamps from actual user feedback."""

    def test_case_00463_00474_distance_degradation(self):
        """v0.15.0 real case: DSC00463-00474 between track points ~250m apart.

        Source: test-data/debug_input/照片 GPS 追踪记录（2026-02-07）.md
        Track has points near 25.05, 102.70 at ~13:30 and ~13:48.
        Photos at 13:38-13:42 are "middle" — interpolation rejected for distance
        (251m > 200m), but should degrade to nearest-point matching.

        Before fix: all failed with "距离过大"
        After fix: succeed via degradation to nearest-point

        Note: is_middle requires photo neighbors within context_window (300s).
        In the real run, DSC00458 (13:32) and DSC00477 (13:43) provided context.
        We add padding photos to replicate this.
        """
        matcher = GPSMatcher(MatcherConfig(
            max_gps_distance=200,
            middle_time_window=3600,
            isolated_window=300,
            match_isolated=True,
        ))
        # Real track points (simplified from actual GPX recording)
        points = [
            make_point(25.0519, 102.7052, utc(13, 30)),  # cluster before gap
            make_point(25.0521, 102.7027, utc(13, 48)),  # cluster after gap
        ]
        seg = make_segment(points)

        # Real photo timestamps, with padding photos for context_window
        photos = [
            make_photo("DSC00458.JPG", utc(13, 37, 30)),  # padding (138s before 00463)
            make_photo("DSC00463.JPG", utc(13, 38, 7)),
            make_photo("DSC00466.JPG", utc(13, 39, 55)),
            make_photo("DSC00474.JPG", utc(13, 42, 35)),
            make_photo("DSC00477.JPG", utc(13, 43, 5)),   # padding (30s after 00474)
        ]
        results = matcher.match(photos, [seg])

        # Find our target photos in results (sorted by timestamp)
        r463 = next(r for r in results if r.photo.filename == "DSC00463.JPG")
        r466 = next(r for r in results if r.photo.filename == "DSC00466.JPG")
        r474 = next(r for r in results if r.photo.filename == "DSC00474.JPG")

        # All should succeed via nearest-point degradation
        for label, r in [("00463", r463), ("00466", r466), ("00474", r474)]:
            assert r.success, f"{label} should succeed via degradation"
            assert r.method == "nearest", f"{label} should use nearest-point method"

        # 00463 (13:38:07): prev=13:30 (487s), next=13:48 (593s) → picks prev
        assert r463.time_diff == 487
        assert abs(r463.gps.latitude - 25.0519) < 0.0001

        # 00466 (13:39:55): prev=13:30 (595s), next=13:48 (485s) → picks next
        assert r466.time_diff == 485
        assert abs(r466.gps.latitude - 25.0521) < 0.0001

        # 00474 (13:42:35): prev=13:30 (755s), next=13:48 (325s) → picks next
        assert r474.time_diff == 325
        assert abs(r474.gps.latitude - 25.0521) < 0.0001

    def test_case_00975_auto_follow_next_direction(self):
        """v0.16.0 direction regression: auto_follow must pick next (not prev).

        Source: v0.16.0 BUG-1 feedback
        Real coordinates from 00973 (seg_a) and 00984 (seg_b).
        Bug was: GUI labeled "跟随下一个" but GPS came from prev neighbor (00973).
        This test validates the matcher correctly picks auto_follow_next
        and assigns next neighbor's GPS, not prev's.
        """
        matcher = GPSMatcher(MatcherConfig(isolated_window=600))
        seg_a = make_segment([make_point(23.6190, 102.8299, utc(9, 19))])
        seg_b = make_segment([make_point(23.0873, 102.8166, utc(14, 20))])

        photos = [
            make_photo("00973.jpg", utc(9, 19, 30)),
            make_photo("00975.jpg", utc(14, 9)),
            make_photo("00984.jpg", utc(14, 14, 30)),
        ]
        results = matcher.match(photos, [seg_a, seg_b])

        # 00973: nearest match from seg_a
        assert results[0].success
        assert abs(results[0].gps.latitude - 23.6190) < 0.0001

        # 00984: nearest match from seg_b (330s < 600s window)
        assert results[2].success
        assert abs(results[2].gps.latitude - 23.0873) < 0.0001

        # 00975: no direct GPS coverage → second-pass auto_follow
        # 00973 is 17410s away, 00984 is 330s away → picks 00984 (auto_follow_next)
        assert results[1].success
        assert results[1].method == "auto_follow_next"
        # CRITICAL: GPS must come from NEXT (00984), not PREV (00973)
        assert abs(results[1].gps.latitude - 23.0873) < 0.0001, \
            "auto_follow_next should give next neighbor's GPS, not prev's"
