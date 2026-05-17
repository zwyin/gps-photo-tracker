"""EF-05: Smart parameter recommendation based on GPX and photo density."""
import math

from gps_photo_tracker.core.models import GPXSegment, MatcherConfig, PhotoInfo


class ParamTuner:
    """Recommend optimal MatcherConfig from track and photo data."""

    @staticmethod
    def recommend(segments: list[GPXSegment], photos: list[PhotoInfo]) -> MatcherConfig:
        if len(photos) < 5 or not segments:
            return MatcherConfig()

        gpx_avg_gap = ParamTuner._gpx_avg_gap(segments)
        speed_median = ParamTuner._speed_median(segments)

        isolated = max(300, ParamTuner._clamp(int(gpx_avg_gap * 3), 60, 3600))
        middle = max(3600, ParamTuner._clamp(int(gpx_avg_gap * 10), 600, 7200))
        context = max(300, ParamTuner._clamp(int(gpx_avg_gap * 2), 60, 1800))

        if speed_median < 3:
            distance = 200
        elif speed_median < 8:
            distance = 400
        else:
            distance = 500

        return MatcherConfig(
            isolated_window=isolated,
            middle_time_window=middle,
            context_window=context,
            max_gps_distance=distance,
            match_isolated=True,
            time_offset=0,
        )

    @staticmethod
    def _gpx_avg_gap(segments: list[GPXSegment]) -> float:
        gaps = []
        for seg in segments:
            pts = seg.points
            for i in range(1, len(pts)):
                gaps.append(pts[i].timestamp - pts[i - 1].timestamp)
        return sum(gaps) / len(gaps) if gaps else 300.0

    @staticmethod
    def _speed_median(segments: list[GPXSegment]) -> float:
        speeds = []
        for seg in segments:
            pts = seg.points
            for i in range(1, len(pts)):
                dt = pts[i].timestamp - pts[i - 1].timestamp
                if dt <= 0:
                    continue
                dlat = math.radians(pts[i].latitude - pts[i - 1].latitude)
                dlon = math.radians(pts[i].longitude - pts[i - 1].longitude)
                lat1 = math.radians(pts[i - 1].latitude)
                a = (math.sin(dlat / 2) ** 2
                     + math.cos(lat1) * math.cos(lat1) * math.sin(dlon / 2) ** 2)
                dist = 6371000 * 2 * math.asin(math.sqrt(a))
                speeds.append(dist / dt)
        if not speeds:
            return 1.5
        speeds.sort()
        return speeds[len(speeds) // 2]

    @staticmethod
    def _clamp(value: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, value))
