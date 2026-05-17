"""GPS matcher with linear interpolation.

Matches photos to GPS track points using time-based correlation.
Supports interpolated matching (middle photos) and nearest-point matching (isolated).
"""

import logging

from geopy.distance import geodesic

logger = logging.getLogger(__name__)

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
        # Filter out photos with no timestamp (spec: PhotoInfo.timestamp can be None)
        valid_photos = [p for p in photos if p.timestamp is not None]
        sorted_photos = sorted(valid_photos, key=lambda p: p.timestamp)
        results: list[MatchResult] = []
        for i, photo in enumerate(sorted_photos):
            if photo.has_gps and not self.config.overwrite_gps:
                results.append(MatchResult(
                    photo=photo, success=True, method="skipped",
                    gps=None,
                ))
            else:
                results.append(self._match_one(photo, sorted_photos, i, segments))

        # Second pass: neighbor follow for failed photos
        self._second_pass_neighbor_follow(results)

        return results

    def _second_pass_neighbor_follow(self, results: list[MatchResult]):
        """Second pass: failed photos try to follow nearest successful neighbor.

        Scans results on each iteration so newly-rescued photos cascade
        to their neighbors (fixes chain-breaking bug where pre-built list
        missed photos rescued earlier in the same pass).
        """
        for i, result in enumerate(results):
            if result.success or result.photo.timestamp is None:
                continue

            target_ts = result.photo.timestamp

            # Scan results directly (includes photos rescued earlier in this loop)
            prev_neighbor = None
            next_neighbor = None
            prev_diff = float("inf")
            next_diff = float("inf")

            for sr in results:
                if not sr.success or sr.gps is None or sr.photo.timestamp is None:
                    continue
                if sr.method == "skipped":
                    continue  # existing GPS may be unreliable — don't propagate
                diff = sr.photo.timestamp - target_ts
                if diff < 0 and abs(diff) < prev_diff:
                    prev_diff = abs(diff)
                    prev_neighbor = sr
                elif diff > 0 and abs(diff) < next_diff:
                    next_diff = abs(diff)
                    next_neighbor = sr

            # Pick the closer one
            if prev_neighbor and prev_diff <= next_diff:
                chosen, chosen_diff = prev_neighbor, prev_diff
                method = "auto_follow_prev"
            elif next_neighbor:
                chosen, chosen_diff = next_neighbor, next_diff
                method = "auto_follow_next"
            else:
                continue

            if chosen_diff <= self.config.isolated_window:
                logger.debug("  → 第二回合跟随 | %s → %s diff=%.0fs",
                             result.photo.filename, method, chosen_diff)
                result.success = True
                result.gps = GPSInfo(
                    latitude=chosen.gps.latitude,
                    longitude=chosen.gps.longitude,
                    altitude=chosen.gps.altitude,
                )
                result.method = method
                result.time_diff = chosen_diff
                result.reject_reason = None

    def _match_one(
        self,
        photo: PhotoInfo,
        all_photos: list[PhotoInfo],
        index: int,
        segments: list[GPXSegment],
    ) -> MatchResult:
        adjusted_time = photo.timestamp + self.config.time_offset
        logger.debug("匹配 %s | timestamp=%s offset=%s adjusted=%s",
                     photo.filename, photo.timestamp, self.config.time_offset, adjusted_time)

        # Step 1: find covering segment
        segment = self._find_segment(adjusted_time, segments)
        if segment is None:
            logger.debug("  → 无覆盖段 | adjusted=%s, %d段可用", adjusted_time, len(segments))
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
            and (photo.timestamp - prev_photo.timestamp) <= self.config.context_window
            and (next_photo.timestamp - photo.timestamp) <= self.config.context_window
        )

        # Step 3: find prev/next GPS points
        prev_point = self._find_prev_point(adjusted_time, segment)
        next_point = self._find_next_point(adjusted_time, segment)

        if prev_point is None and next_point is None:
            logger.debug("  → 无轨迹点 | segment=%s", segment.filename)
            return MatchResult(
                photo=photo, success=False,
                reject_reason=RejectReason.NO_TRACK_POINTS,
            )

        # Step 4a: middle + both points → try interpolation, fallback to nearest
        if is_middle and prev_point is not None and next_point is not None:
            distance = geodesic(
                (prev_point.latitude, prev_point.longitude),
                (next_point.latitude, next_point.longitude),
            ).meters
            time_diff = abs(next_point.timestamp - prev_point.timestamp)

            can_interpolate = (
                distance <= self.config.max_gps_distance
                and time_diff <= self.config.middle_time_window
            )

            if can_interpolate:
                # Linear interpolation
                span = next_point.timestamp - prev_point.timestamp
                logger.debug("  → 插值 | span=%.1fs dist=%.0fm ratio=%.3f", span, distance,
                             (adjusted_time - prev_point.timestamp) / span if span else 0.5)
                if span == 0:
                    # Same timestamp — use midpoint
                    lat = (prev_point.latitude + next_point.latitude) / 2
                    lon = (prev_point.longitude + next_point.longitude) / 2
                    prev_alt = prev_point.altitude if prev_point.altitude is not None else 0.0
                    next_alt = next_point.altitude if next_point.altitude is not None else 0.0
                    alt = None if (prev_point.altitude is None and next_point.altitude is None) else (prev_alt + next_alt) / 2
                    seg_distance = geodesic(
                        (prev_point.latitude, prev_point.longitude),
                        (next_point.latitude, next_point.longitude),
                    ).meters
                    return MatchResult(
                        photo=photo, success=True,
                        gps=GPSInfo(latitude=lat, longitude=lon, altitude=alt),
                        method="interpolated",
                        time_diff=time_diff,
                        interpolation_prev=prev_point,
                        interpolation_next=next_point,
                        interpolation_distance=seg_distance,
                        interpolation_ratio=0.5,
                    )
                ratio = (adjusted_time - prev_point.timestamp) / span
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

            # Fallback: distance/time_diff too large → degrade to nearest point
            prev_td = abs(prev_point.timestamp - adjusted_time)
            next_td = abs(next_point.timestamp - adjusted_time)
            if prev_td <= next_td:
                nearest, nearest_td = prev_point, prev_td
            else:
                nearest, nearest_td = next_point, next_td
            logger.debug("  → 插值降级就近 | dist=%.0fm time_diff=%.1fs nearest_td=%.1fs",
                         distance, time_diff, nearest_td)
            if nearest_td > self.config.middle_time_window:
                return MatchResult(
                    photo=photo, success=False,
                    reject_reason=RejectReason.TIME_DIFF,
                    time_diff=nearest_td,
                )
            return MatchResult(
                photo=photo, success=True,
                gps=GPSInfo(latitude=nearest.latitude, longitude=nearest.longitude,
                            altitude=nearest.altitude),
                method="nearest",
                time_diff=nearest_td,
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
        if not self.config.match_isolated:
            return MatchResult(
                photo=photo, success=False,
                reject_reason=RejectReason.ISOLATED_DISABLED,
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
        # Level 1: exact match (photo time within segment range)
        for seg in segments:
            if seg.start <= ts <= seg.end:
                return seg
        # Level 2: tolerance match (photo time within isolated_window of nearest segment)
        best_seg = None
        best_diff = float("inf")
        for seg in segments:
            if ts < seg.start:
                diff = seg.start - ts
            elif ts > seg.end:
                diff = ts - seg.end
            else:
                continue
            if diff < best_diff:
                best_diff = diff
                best_seg = seg
        if best_seg is not None and best_diff <= self.config.isolated_window:
            return best_seg
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
