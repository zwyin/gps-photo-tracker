"""Tests for core.clock_correction — camera clock auto-correction (task #12).

Synthetic scenarios per spec docs/superpowers/specs/2026-09-11-clock-autocorrect.md §6.
"""

import pytest

from gps_photo_tracker.core.clock_correction import ClockCorrection, detect_offset
from gps_photo_tracker.core.models import MatchResult

from conftest import make_photo, make_point, make_segment, utc


def make_result(ts, *, filename="p", method=None, success=False):
    """Build a MatchResult around a photo with the given EXIF timestamp."""
    photo = make_photo(f"{filename}.jpg", ts)
    return MatchResult(photo=photo, success=success, method=method)


def hike_segment(start_h=10, end_h=12, step_min=5, name="test.gpx"):
    """Track covering start_h..end_h with points every step_min minutes."""
    import math
    t0 = utc(start_h)
    t1 = utc(end_h)
    n = int((t1 - t0) / (step_min * 60))
    points = [
        make_point(46.0 + 0.001 * i, 7.0 + 0.001 * i, t0 + i * step_min * 60)
        for i in range(n + 1)
    ]
    return make_segment(points, filename=name)


def photo_stamps(first_h, first_min, last_h, last_min, step_min=10):
    """EXIF timestamps (floats) from first to last inclusive, every step_min."""
    t0 = utc(first_h, first_min)
    t1 = utc(last_h, last_min)
    n = int((t1 - t0) / (step_min * 60))
    return [t0 + i * step_min * 60 for i in range(n + 1)]


# ── 经典偏差场景：相机 +1h，建议恰为 −3600s ────────────────

class TestClassicOffset:

    def test_camera_one_hour_ahead_suggests_minus_3600(self):
        seg = hike_segment()  # 10:00–12:00
        # true 10:05–11:55, camera +1h → stamps 11:05–12:55
        results = [make_result(ts + 3600, filename=f"p{i}")
                   for i, ts in enumerate(photo_stamps(10, 5, 11, 55))]

        correction = detect_offset(results, [seg])

        assert correction is not None
        assert correction.offset_s == -3600
        assert correction.total == 12
        assert correction.support == 12
        assert correction.confidence == 1.0
        # offset=0 时仅 stamps ≤12:00 的 6 张在覆盖内 → 挽回 6 张
        assert correction.gain == 6

    def test_camera_one_hour_behind_suggests_plus_3600(self):
        seg = hike_segment()
        results = [make_result(ts - 3600, filename=f"p{i}")
                   for i, ts in enumerate(photo_stamps(10, 5, 11, 55))]

        correction = detect_offset(results, [seg])

        assert correction is not None
        assert correction.offset_s == 3600

    def test_symmetric_margins_recover_exact_delta(self):
        """Photos bounded by track start/end (5 min margins) → plateau centre = δ."""
        seg = hike_segment()  # 10:00–12:00
        # true 10:05–11:55 → stamps 11:05–12:55 with camera +90 min
        results = [make_result(ts + 5400, filename=f"p{i}")
                   for i, ts in enumerate(photo_stamps(10, 5, 11, 55))]

        correction = detect_offset(results, [seg])

        assert correction is not None
        assert correction.offset_s == -5400


# ── 无信号 / 不可检测场景 ─────────────────────────────────

class TestNoSignal:

    def test_healthy_camera_returns_none(self):
        seg = hike_segment()
        results = [make_result(ts, filename=f"p{i}")
                   for i, ts in enumerate(photo_stamps(10, 5, 11, 55))]

        assert detect_offset(results, [seg]) is None

    def test_silent_error_long_track_returns_none(self):
        """Camera off but all stamps still inside a much longer track → None
        (documented limitation: no failure signal to detect)."""
        seg = hike_segment(9, 17)  # 09:00–17:00
        # true 10:00–16:00, camera +1h → stamps 11:00–17:00, all covered
        results = [make_result(ts + 3600, filename=f"p{i}")
                   for i, ts in enumerate(photo_stamps(10, 0, 16, 0, step_min=30))]

        assert detect_offset(results, [seg]) is None

    def test_lunch_photos_do_not_trigger_harmful_suggestion(self):
        """Healthy in-track photos + a few after-track photos clustered:
        guards must reject any offset sacrificing covered photos."""
        seg = hike_segment()  # 10:00–12:00
        in_track = [make_result(ts, filename=f"h{i}")
                    for i, ts in enumerate(photo_stamps(10, 10, 11, 0))]
        lunch = [make_result(utc(12, 30), filename="l1"),
                 make_result(utc(12, 40), filename="l2"),
                 make_result(utc(12, 50), filename="l3")]

        assert detect_offset(in_track + lunch, [seg]) is None

    def test_no_loss_guard_blocks_sacrifice_even_with_majority_gain(self):
        """4 healthy in-track + 9 after-track photos: a −80 min shift covers
        9 by dropping the 4 healthy (net coverage up, gain ≥ min_support) —
        the no-loss guard alone must reject this."""
        seg = hike_segment()  # 10:00–12:00
        in_track = [make_result(ts, filename=f"h{i}")
                    for i, ts in enumerate(photo_stamps(10, 10, 11, 0))]  # 4
        after = [make_result(utc(12, 30) + i * 300, filename=f"a{i}")
                 for i in range(9)]  # 12:30–13:10

        assert detect_offset(in_track + after, [seg]) is None


# ── 守卫条件 ──────────────────────────────────────────────

class TestGuards:

    def test_min_support_blocks_weak_evidence(self):
        seg = hike_segment()
        # only 2 photos, both shifted out of coverage
        results = [make_result(utc(13, 0), filename="a"),
                   make_result(utc(13, 10), filename="b")]

        assert detect_offset(results, [seg], min_support=3) is None
        assert detect_offset(results, [seg], min_support=2) is not None

    def test_sub_tolerance_correction_is_noise(self):
        """Photos spanning the whole track shifted −10s → point plateau at
        +10s: a real but meaningless correction, suppressed by tolerance
        (min_support=1 isolates the tolerance guard from the gain guard)."""
        seg = hike_segment()  # 10:00–12:00
        # camera −10s: true 10:00/10:30/11:00/12:00 → last stamp still inside
        stamps = [utc(9, 59, 50), utc(10, 29, 50), utc(10, 59, 50), utc(11, 59, 50)]
        results = [make_result(ts, filename=f"p{i}") for i, ts in enumerate(stamps)]

        # plateau collapses to [+10, +10]: suggestion +10s < 30s tolerance
        assert detect_offset(results, [seg], min_support=1) is None
        # same scene with a 5s tolerance does suggest the 10s correction
        c = detect_offset(results, [seg], min_support=1, tolerance_s=5.0)
        assert c is not None
        assert c.offset_s == 10

    def test_current_offset_baseline(self):
        """results produced with current_offset_s=600 already carry +600s in the
        matcher's frame; suggestion is the REPLACEMENT total, not a delta."""
        seg = hike_segment()
        true_delta = 3600
        # user already applied +600; residual error = true_delta − 600
        results = [make_result(ts + true_delta, filename=f"p{i}")
                   for i, ts in enumerate(photo_stamps(10, 5, 11, 55))]

        correction = detect_offset(results, [seg], current_offset_s=600)

        # timestamps re-based by current_offset_s → suggestion is full −3600
        assert correction is not None
        assert correction.offset_s == -3600

    def test_insufficient_gain_returns_none(self):
        """Coverage at best offset equals current coverage → no gain → None."""
        seg = hike_segment()
        # half in, half out, but the out-half spreads so wide that no single
        # offset rescues more than it must drop
        stamps = photo_stamps(10, 30, 11, 30) + [utc(20, 0), utc(20, 10)]
        results = [make_result(ts, filename=f"p{i}") for i, ts in enumerate(stamps)]

        assert detect_offset(results, [seg]) is None


# ── 输入边界 ──────────────────────────────────────────────

class TestInputEdges:

    def test_empty_inputs(self):
        assert detect_offset([], [hike_segment()]) is None
        assert detect_offset([make_result(utc(10, 0))], []) is None
        assert detect_offset([], []) is None

    def test_photos_without_timestamp_excluded(self):
        seg = hike_segment()
        photo = make_photo("no_ts.jpg", None)
        results = [MatchResult(photo=photo, success=False, reject_reason="no_gps_coverage")]
        assert detect_offset(results, [seg]) is None

    def test_skipped_photos_excluded(self):
        """skipped (already has GPS) photos never participate in matching."""
        seg = hike_segment()
        skipped = [MatchResult(photo=make_photo(f"s{i}.jpg", utc(13, i * 10)),
                               success=True, method="skipped")
                   for i in range(5)]
        live = [make_result(ts + 3600, filename=f"p{i}")
                for i, ts in enumerate(photo_stamps(10, 5, 11, 55))]

        correction = detect_offset(skipped + live, [seg])

        assert correction is not None
        assert correction.total == 12  # skipped excluded from denominator
        assert correction.offset_s == -3600

    def test_multi_segment_union(self):
        """Photo covered by either of two disjoint segments counts once."""
        seg_a = hike_segment(10, 11, name="a.gpx")
        seg_b = hike_segment(14, 15, name="b.gpx")
        # true 10:05–10:55 camera +1h → stamps 11:05–11:55 (beyond seg_a end)
        results = [make_result(ts + 3600, filename=f"p{i}")
                   for i, ts in enumerate(photo_stamps(10, 5, 10, 55))]

        correction = detect_offset(results, [seg_a, seg_b])

        assert correction is not None
        assert correction.offset_s == -3600


# ── 数据语义 ──────────────────────────────────────────────

class TestClockCorrectionDataclass:

    def test_fields_consistent(self):
        seg = hike_segment()
        results = [make_result(ts + 3600, filename=f"p{i}")
                   for i, ts in enumerate(photo_stamps(10, 5, 11, 55))]
        c = detect_offset(results, [seg])

        assert isinstance(c, ClockCorrection)
        assert c.support == int(c.confidence * c.total)
        assert c.plateau_start_s <= c.offset_s <= c.plateau_end_s
        assert c.gain > 0

    def test_tie_break_picks_nearest_run(self):
        """Two disjoint offset ranges each cover 3 photos (before-start group
        vs after-end group): the run closest to the current offset wins."""
        seg = hike_segment()  # 10:00–12:00
        before = [utc(9, 58), utc(9, 59), utc(9, 59, 30)]   # needs ≈ +1h
        after = [utc(13, 0), utc(13, 5), utc(13, 10)]       # needs ≈ −1h…−3h
        results = [make_result(ts, filename=f"p{i}")
                   for i, ts in enumerate(before + after)]

        c = detect_offset(results, [seg])

        assert c is not None
        # runs: [120, 7230] (center +3675) vs [−11400, −4200] (center −7800)
        assert c.offset_s == 3675

    def test_boundary_overlap_point_peak(self):
        """Closed-interval boundary coincidence: one photo's coverage starts
        exactly where another's ends → a point peak covering BOTH (4 photos
        for a single offset instant) beats the 3-photo plateaus."""
        seg = make_segment([make_point(46.0, 7.0, 500.0),
                            make_point(46.1, 7.1, 1500.0)])  # [500, 1500]
        stamps = [-2000.0, -1990.0, -1980.0, -1000.0, -990.0, -980.0]
        results = [make_result(ts, filename=f"p{i}")
                   for i, ts in enumerate(stamps)]

        c = detect_offset(results, [seg])

        assert c is not None
        assert c.offset_s == 2480
        assert c.support == 4  # instantaneous 4-photo overlap at exactly 2480
        assert c.confidence == pytest.approx(4 / 6)

    def test_adjacent_equal_coverage_regions_merge(self):
        """Enter/exit events at the SAME value (engineered 1 ms apart in photo
        time) swap photos without a point peak: two adjacent max-coverage
        regions must merge into one plateau."""
        seg = make_segment([make_point(46.0, 7.0, 500.0),
                            make_point(46.1, 7.1, 1500.0)])  # [500, 1500]
        # C's interval ends at 2480(+ε exit); D's interval starts at 2480.001:
        # exit(C) and enter(D) coincide → coverage stays 3 across the swap.
        stamps = [-1000.0, -990.0, -980.0, -1980.001]
        results = [make_result(ts, filename=f"p{i}")
                   for i, ts in enumerate(stamps)]

        c = detect_offset(results, [seg])

        assert c is not None
        assert c.support == 3
        assert c.plateau_start_s == 1500.0
        assert c.plateau_end_s == pytest.approx(2490.001, abs=1e-3)
        assert c.offset_s == 1995
