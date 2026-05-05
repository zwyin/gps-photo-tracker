"""GPS matcher with linear interpolation.

Matches photos to GPS track points using time-based correlation.
Supports interpolated matching (middle photos) and nearest-point matching (isolated).
"""

from geopy.distance import geodesic

from gps_photo_tracker.core.models import (
    GPSInfo,
    GPXSegment,
    MatcherConfig,
    MatchResult,
    PhotoInfo,
    RejectReason,
    TrackPoint,
)


class GPSMatcher:
    """Match photos to GPS track segments."""

    def __init__(self, config: MatcherConfig):
        self.config = config

    def match(
        self,
        photos: list[PhotoInfo],
        segments: list[GPXSegment],
    ) -> list[MatchResult]:
        sorted_photos = sorted(photos, key=lambda p: p.timestamp)
        results: list[MatchResult] = []
        for i, photo in enumerate(sorted_photos):
            results.append(self._match_one(photo, sorted_photos, i, segments))
        return results

    def _match_one(
        self,
        photo: PhotoInfo,
        all_photos: list[PhotoInfo],
        index: int,
        segments: list[GPXSegment],
    ) -> MatchResult:
        adjusted_time = photo.timestamp + self.config.time_offset

        # Step 1: find covering segment
        segment = self._find_segment(adjusted_time, segments)
        if segment is None:
            return MatchResult(
                photo=photo, success=False,
                reject_reason=RejectReason.NO_GPS_COVERAGE,
            )

        # Step 2: determine context (middle vs isolated)
        prev_photo = all_photos[index - 1] if index > 0 else None
        next_photo = all_photos[index + 1] if index < len(all_photos) - 1 else None
        is_middle = (
            prev_photo is not None
            and next_photo is not None
            and (adjusted_time - prev_photo.timestamp) <= self.config.context_window
            and (next_photo.timestamp - adjusted_time) <= self.config.context_window
        )

        # Step 3: find prev/next GPS points
        prev_point = self._find_prev_point(adjusted_time, segment)
        next_point = self._find_next_point(adjusted_time, segment)

        if prev_point is None and next_point is None:
            return MatchResult(
                photo=photo, success=False,
                reject_reason=RejectReason.NO_TRACK_POINTS,
            )

        # Step 4a: middle + both points → try interpolation
        if is_middle and prev_point is not None and next_point is not None:
            distance = geodesic(
                (prev_point.latitude, prev_point.longitude),
                (next_point.latitude, next_point.longitude),
            ).meters

            if distance > self.config.max_gps_distance:
                return MatchResult(
                    photo=photo, success=False,
                    reject_reason=RejectReason.GPS_DISTANCE,
                )

            time_diff = abs(next_point.timestamp - prev_point.timestamp)
            if time_diff > self.config.middle_time_window:
                return MatchResult(
                    photo=photo, success=False,
                    reject_reason=RejectReason.TIME_DIFF,
                    time_diff=time_diff,
                )

            # Linear interpolation
            ratio = (adjusted_time - prev_point.timestamp) / (next_point.timestamp - prev_point.timestamp)
            lat = prev_point.latitude + ratio * (next_point.latitude - prev_point.latitude)
            lon = prev_point.longitude + ratio * (next_point.longitude - prev_point.longitude)

            # Altitude: None treated as 0 for calculation; both None → result None
            prev_alt = prev_point.altitude if prev_point.altitude is not None else 0.0
            next_alt = next_point.altitude if next_point.altitude is not None else 0.0
            if prev_point.altitude is None and next_point.altitude is None:
                alt = None
            else:
                alt = prev_alt + ratio * (next_alt - prev_alt)

            return MatchResult(
                photo=photo, success=True,
                gps=GPSInfo(latitude=lat, longitude=lon, altitude=alt),
                method="interpolated",
                time_diff=time_diff,
                interpolation_prev=prev_point,
                interpolation_next=next_point,
                interpolation_distance=distance,
                interpolation_ratio=ratio,
            )

        # Step 4b: middle but single-sided → nearest
        if is_middle:
            point = prev_point if prev_point is not None else next_point
            assert point is not None
            time_diff = abs(point.timestamp - adjusted_time)
            if time_diff > self.config.middle_time_window:
                return MatchResult(
                    photo=photo, success=False,
                    reject_reason=RejectReason.TIME_DIFF,
                    time_diff=time_diff,
                )
            return MatchResult(
                photo=photo, success=True,
                gps=GPSInfo(latitude=point.latitude, longitude=point.longitude, altitude=point.altitude),
                method="nearest",
                time_diff=time_diff,
            )

        # Step 4c: isolated
        if not self.config.match_tail:
            return MatchResult(
                photo=photo, success=False,
                reject_reason=RejectReason.TAIL_ISOLATED,
            )

        # Find nearest point
        nearest = prev_point if prev_point is not None else next_point
        if prev_point is not None and next_point is not None:
            prev_diff = abs(prev_point.timestamp - adjusted_time)
            next_diff = abs(next_point.timestamp - adjusted_time)
            nearest = prev_point if prev_diff <= next_diff else next_point

        time_diff = abs(nearest.timestamp - adjusted_time)
        if time_diff > self.config.isolated_window:
            return MatchResult(
                photo=photo, success=False,
                reject_reason=RejectReason.TIME_DIFF,
                time_diff=time_diff,
            )

        return MatchResult(
            photo=photo, success=True,
            gps=GPSInfo(latitude=nearest.latitude, longitude=nearest.longitude, altitude=nearest.altitude),
            method="nearest",
            time_diff=time_diff,
        )

    def _find_segment(self, ts: float, segments: list[GPXSegment]) -> GPXSegment | None:
        for seg in segments:
            if seg.start <= ts <= seg.end:
                return seg
        return None

    def _find_prev_point(self, ts: float, segment: GPXSegment) -> TrackPoint | None:
        result = None
        for pt in segment.points:
            if pt.timestamp < ts:
                result = pt
            else:
                break
        return result

    def _find_next_point(self, ts: float, segment: GPXSegment) -> TrackPoint | None:
        for pt in segment.points:
            if pt.timestamp > ts:
                return pt
        return None
