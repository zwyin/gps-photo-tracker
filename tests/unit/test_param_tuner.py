"""Tests for EF-05 ParamTuner."""
from pathlib import Path

from gps_photo_tracker.core.models import GPXSegment, MatcherConfig, PhotoInfo, TrackPoint
from gps_photo_tracker.core.param_tuner import ParamTuner


def _make_segments(gap_seconds: float, count: int) -> list[GPXSegment]:
    points = [
        TrackPoint(timestamp=i * gap_seconds, latitude=0.0, longitude=0.0)
        for i in range(count)
    ]
    return [GPXSegment(filename="test.gpx", start=0.0,
                       end=(count - 1) * gap_seconds, points=points)]


def _make_photos(count: int, gap_seconds: float) -> list[PhotoInfo]:
    return [
        PhotoInfo(path=Path(f"/p{i}.jpg"), filename=f"p{i}.jpg",
                  timestamp=i * gap_seconds, has_gps=False)
        for i in range(count)
    ]


class TestParamTuner:
    def test_insufficient_photos_returns_defaults(self):
        segments = _make_segments(10, 20)
        photos = _make_photos(3, 30)
        config = ParamTuner.recommend(segments, photos)
        assert config.isolated_window == 300
        assert config.middle_time_window == 3600

    def test_no_segments_returns_defaults(self):
        photos = _make_photos(10, 30)
        config = ParamTuner.recommend([], photos)
        assert config.isolated_window == 300

    def test_dense_gpx_adjusts_windows(self):
        segments = _make_segments(5, 100)
        photos = _make_photos(20, 10)
        config = ParamTuner.recommend(segments, photos)
        assert config.isolated_window >= 300
        assert config.context_window >= 300

    def test_sparse_gpx_widens_windows(self):
        segments = _make_segments(300, 20)
        photos = _make_photos(20, 600)
        config = ParamTuner.recommend(segments, photos)
        assert config.isolated_window >= 900

    def test_time_offset_never_changed(self):
        segments = _make_segments(10, 50)
        photos = _make_photos(10, 30)
        config = ParamTuner.recommend(segments, photos)
        assert config.time_offset == 0

    def test_match_isolated_always_true(self):
        segments = _make_segments(10, 50)
        photos = _make_photos(10, 30)
        config = ParamTuner.recommend(segments, photos)
        assert config.match_isolated is True

    def test_returns_matcher_config_type(self):
        segments = _make_segments(10, 50)
        photos = _make_photos(10, 30)
        config = ParamTuner.recommend(segments, photos)
        assert isinstance(config, MatcherConfig)

    def test_max_gps_distance_reasonable(self):
        segments = _make_segments(10, 50)
        photos = _make_photos(10, 30)
        config = ParamTuner.recommend(segments, photos)
        assert 50 <= config.max_gps_distance <= 1000

    def test_params_within_bf01_ranges(self):
        segments = _make_segments(60, 50)
        photos = _make_photos(20, 120)
        config = ParamTuner.recommend(segments, photos)
        assert 60 <= config.isolated_window <= 3600
        assert 600 <= config.middle_time_window <= 7200
        assert 60 <= config.context_window <= 1800
        assert 50 <= config.max_gps_distance <= 1000


class TestParamTunerSpeedBranches:
    """Cover speed_median branches: slow (<3), medium (<8), fast (>=8)."""

    def _make_moving_segments(self, lat_step: float, gap: float, count: int) -> list[GPXSegment]:
        """Segments with configurable lat_step to control speed."""
        points = [
            TrackPoint(timestamp=i * gap, latitude=i * lat_step, longitude=0.0)
            for i in range(count)
        ]
        return [GPXSegment(filename="test.gpx", start=0.0,
                           end=(count - 1) * gap, points=points)]

    def test_slow_speed_distance_200(self):
        """speed_median < 3 m/s → distance = 200."""
        # ~0.0001° per 60s ≈ 0.3 m/s (walking)
        segments = self._make_moving_segments(0.0001, 60, 50)
        photos = _make_photos(10, 30)
        config = ParamTuner.recommend(segments, photos)
        assert config.max_gps_distance == 200

    def test_medium_speed_distance_400(self):
        """3 ≤ speed_median < 8 m/s → distance = 400."""
        # ~0.0005° per 10s ≈ 5.5 m/s (cycling)
        segments = self._make_moving_segments(0.0005, 10, 50)
        photos = _make_photos(10, 30)
        config = ParamTuner.recommend(segments, photos)
        assert config.max_gps_distance == 400

    def test_fast_speed_distance_500(self):
        """speed_median ≥ 8 m/s → distance = 500."""
        # ~0.001° per 5s ≈ 25 m/s (driving)
        segments = self._make_moving_segments(0.001, 5, 50)
        photos = _make_photos(10, 30)
        config = ParamTuner.recommend(segments, photos)
        assert config.max_gps_distance == 500

    def test_zero_time_gap_skipped(self):
        """Points with dt=0 should be skipped in speed calculation."""
        points = [
            TrackPoint(timestamp=0.0, latitude=0.0, longitude=0.0),
            TrackPoint(timestamp=0.0, latitude=1.0, longitude=1.0),  # dt=0, skip
            TrackPoint(timestamp=10.0, latitude=0.001, longitude=0.0),
        ]
        seg = GPXSegment(filename="dup.gpx", start=0.0, end=10.0, points=points)
        photos = _make_photos(10, 30)
        config = ParamTuner.recommend([seg], photos)
        assert isinstance(config, MatcherConfig)

    def test_single_point_returns_default_speed(self):
        """Single-point segment → no speed pairs → returns default 1.5."""
        seg = GPXSegment(filename="single.gpx", start=0.0, end=0.0,
                         points=[TrackPoint(timestamp=0.0, latitude=0.0, longitude=0.0)])
        photos = _make_photos(10, 30)
        config = ParamTuner.recommend([seg], photos)
        # speed 1.5 < 3 → distance = 200
        assert config.max_gps_distance == 200
