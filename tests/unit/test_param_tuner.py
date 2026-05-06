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

    def test_match_tail_always_true(self):
        segments = _make_segments(10, 50)
        photos = _make_photos(10, 30)
        config = ParamTuner.recommend(segments, photos)
        assert config.match_tail is True

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
