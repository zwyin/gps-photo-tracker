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

    def test_gps_distance_exceeded(self):
        """prev and next GPS points > 200m apart → GPS_DISTANCE."""
        matcher = GPSMatcher(MatcherConfig(max_gps_distance=200))
        points = [
            make_point(25.0, 100.0, utc(8, 0)),
            make_point(25.0, 100.0, utc(8, 5)),  # same location, same segment
            make_point(26.0, 101.0, utc(8, 10)),  # ~157km away!
        ]
        seg = make_segment(points)
        photos = [
            make_photo("p0.jpg", utc(8, 1)),
            make_photo("mid.jpg", utc(8, 5)),  # between close and far point
            make_photo("p2.jpg", utc(8, 9)),
        ]
        results = matcher.match(photos, [seg])
        # mid at 08:05: prev=08:05 point, next=08:10 point → huge distance
        mid = results[1]
        assert not mid.success
        assert mid.reject_reason == RejectReason.GPS_DISTANCE

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
        m_narrow = GPSMatcher(MatcherConfig(middle_time_window=60))

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

        assert m_wide.match(photos, [seg])[1].success
        assert not m_narrow.match(photos, [seg])[1].success


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
        matcher = GPSMatcher(MatcherConfig())
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
