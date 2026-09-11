"""Camera clock auto-correction (task #12).

Detects a systematic camera-clock offset from match results + track segments by
scanning the coverage(offset) function for a peak, formulated as an interval
max-overlap problem.

Key insight (docs/superpowers/specs/2026-09-11-clock-autocorrect.md §3):
successful matches' ``time_diff`` carries NO offset information — the matcher
anchors purely on time, so a clock error δ simply relocates each photo to the
track position at t+δ with ``time_diff`` staying at sampling noise. The
detectable signal is instead the number of photos falling inside track time
coverage as a function of a candidate offset.
"""

from __future__ import annotations

from dataclasses import dataclass

from gps_photo_tracker.core.models import GPXSegment, MatchResult

# Exit events are placed 1 ms after the interval end so that the interval
# [start-t, end-t] stays closed (photo covered at offset == end - t exactly).
_EPS_S = 0.001


@dataclass(frozen=True)
class ClockCorrection:
    """Suggested camera clock correction.

    ``offset_s`` is the REPLACEMENT value for ``MatcherConfig.time_offset``
    (total, not a delta on top of the current setting).
    """

    offset_s: int
    support: int  # photos inside track coverage at the suggested offset
    total: int  # photos considered (timestamp known, not skipped)
    confidence: float  # support / total
    gain: int  # photos rescued relative to the current offset
    plateau_start_s: float  # offset range achieving this coverage (diagnostics)
    plateau_end_s: float


def _covered_mask(timestamps: list[float], segments: list[GPXSegment],
                  offset: float) -> int:
    """Bitmask of photos whose (t + offset) falls inside any segment."""
    mask = 0
    for j, t in enumerate(timestamps):
        x = t + offset
        for seg in segments:
            if seg.start <= x <= seg.end:
                mask |= 1 << j
                break
    return mask


def detect_offset(
    results: list[MatchResult],
    segments: list[GPXSegment],
    *,
    tolerance_s: float = 30.0,
    min_support: int = 3,
    current_offset_s: int = 0,
) -> ClockCorrection | None:
    """Detect camera clock offset from match results; None when not confident.

    Sweeps candidate offsets via interval max-overlap: photo j is covered by
    segment i iff offset ∈ [start_i - t_j, end_i - t_j]. Returns a suggestion
    only when ALL guards pass (better to stay silent than mislead):

    - net gain: more photos covered than at the current offset;
    - no-loss: every currently-covered photo stays covered (never sacrifice
      healthy photos to rescue failed ones);
    - support >= min_support and gain >= min_support (enough votes);
    - the correction magnitude >= tolerance_s (sub-tolerance is noise).

    The suggested value is the centre of the best coverage plateau (maximin
    slack; recovers δ exactly when the shooting window is bounded by the
    track), expressed as a replacement ``time_offset`` total.
    """
    considered = [
        r for r in results
        if r.photo.timestamp is not None and r.method != "skipped"
    ]
    if not considered or not segments:
        return None
    timestamps = [r.photo.timestamp + current_offset_s for r in considered]

    now_mask = _covered_mask(timestamps, segments, 0.0)
    now_count = now_mask.bit_count()

    # Event sweep: photo j covered by segment i iff offset ∈ [start-t, end-t].
    events: list[tuple[float, int, int]] = []  # (value, delta, photo_index)
    for j, t in enumerate(timestamps):
        for seg in segments:
            events.append((seg.start - t, 1, j))
            events.append((seg.end - t + _EPS_S, -1, j))
    events.sort(key=lambda e: (e[0], -e[1]))

    counts = [0] * len(timestamps)
    mask = 0
    regions: list[tuple[float, float, int]] = []  # (lo, hi, mask)
    prev = None
    idx = 0
    while idx < len(events):
        value = events[idx][0]
        if prev is not None:
            regions.append((prev, value, mask))
        prev = value
        while idx < len(events) and events[idx][0] == value:
            _, delta, j = events[idx]
            if delta == 1 and counts[j] == 0:
                mask |= 1 << j
            counts[j] += delta
            if delta == -1 and counts[j] == 0:
                mask &= ~(1 << j)
            idx += 1

    # Guards, then best coverage plateau.
    candidates: list[tuple[float, float]] = []
    best_count = -1
    for lo, hi, m in regions:
        count = m.bit_count()
        if count <= now_count:  # no net gain
            continue
        if now_mask & ~m:  # would drop a currently-covered photo
            continue
        if count < min_support or count - now_count < min_support:
            continue
        if count > best_count:
            best_count = count
            candidates = [(lo, hi)]
        elif count == best_count:
            candidates.append((lo, hi))
    if not candidates:
        return None

    # Merge adjacent runs, pick the one closest to the current offset.
    runs: list[tuple[float, float]] = []
    for lo, hi in candidates:
        if runs and runs[-1][1] == lo:
            runs[-1] = (runs[-1][0], hi)
        else:
            runs.append((lo, hi))
    lo, hi = min(runs, key=lambda r: abs((r[0] + r[1]) / 2))

    delta_s = int(round((lo + hi) / 2))
    if abs(delta_s) < tolerance_s:
        return None

    support = best_count
    total = len(timestamps)
    return ClockCorrection(
        offset_s=delta_s + current_offset_s,
        support=support,
        total=total,
        confidence=support / total,
        gain=support - now_count,
        plateau_start_s=lo + current_offset_s,
        plateau_end_s=hi + current_offset_s,
    )
