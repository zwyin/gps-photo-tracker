"""Data structures, exceptions, and constants for GPS Photo Tracker.

All cross-module data uses dataclasses defined here. No bare dicts.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


# ── Exceptions ──────────────────────────────────────────────


class GPSTrackerError(Exception):
    """Base for all business exceptions."""


class GPXParseError(GPSTrackerError):
    """GPX file parse failure."""


class EXIFReadError(GPSTrackerError):
    """EXIF read failure."""


class EXIFWriteError(GPSTrackerError):
    """EXIF write failure."""


class MatchingError(GPSTrackerError):
    """Matching process error."""


class OperationCancelledError(GPSTrackerError):
    """User cancelled the operation."""


class FileAccessError(GPSTrackerError):
    """File access failure."""


class PermissionDeniedError(FileAccessError):
    """Permission denied."""


class DiskFullError(FileAccessError):
    """Disk full."""


class NetworkTimeoutError(FileAccessError):
    """Network disk timeout."""


# ── Enums & Constants ───────────────────────────────────────


class ProcessMode(Enum):
    PREVIEW = "preview"
    COPY = "copy"
    OVERWRITE = "overwrite"


class ProgressPhase(Enum):
    SCANNING_GPX = "scanning_gpx"
    SCANNING_PHOTOS = "scanning_photos"
    MATCHING = "matching"
    WRITING = "writing"


class RejectReason:
    NO_GPS_COVERAGE = "no_gps_coverage"
    GPS_DISTANCE = "gps_distance"
    TAIL_ISOLATED = "tail_isolated"  # legacy alias
    ISOLATED_DISABLED = "isolated_disabled"
    TIME_DIFF = "time_diff"
    NO_TRACK_POINTS = "no_track_points"


class ReviewAction(Enum):
    KEEP_SKIP = "keep_skip"
    MANUAL_GPS = "manual_gps"
    MANUAL_COORD = "manual_coord"
    SKIP = "skip"
    FOLLOW_PREV = "follow_prev"
    FOLLOW_NEXT = "follow_next"


# ── Data structures ─────────────────────────────────────────


@dataclass
class TrackPoint:
    timestamp: float  # UTC timestamp
    latitude: float
    longitude: float
    altitude: float | None = None  # None = no <ele> tag in GPX


@dataclass
class GPXSegment:
    filename: str  # source GPX filename
    start: float  # UTC timestamp
    end: float  # UTC timestamp
    points: list[TrackPoint] = field(default_factory=list)


@dataclass
class GPSInfo:
    latitude: float
    longitude: float
    altitude: float | None = None  # None = skip altitude tags


@dataclass
class PhotoInfo:
    path: Path
    filename: str
    timestamp: float | None  # UTC timestamp (from EXIF capture time), None if unreadable
    has_gps: bool
    existing_gps: GPSInfo | None = None
    orientation: int | None = None  # EXIF Orientation 1-8, None if unreadable


@dataclass
class MatchResult:
    photo: PhotoInfo
    success: bool
    gps: GPSInfo | None = None
    method: str | None = None  # "interpolated" | "nearest"
    time_diff: float | None = None  # seconds
    reject_reason: str | None = None  # RejectReason constant
    interpolation_prev: TrackPoint | None = None  # for GUI detail dialog
    interpolation_next: TrackPoint | None = None
    interpolation_distance: float | None = None  # meters
    interpolation_ratio: float | None = None
    review_gps: GPSInfo | None = None  # GPS assigned during interactive review


@dataclass
class ReviewDecision:
    photo_path: str
    action: ReviewAction
    selected_point: TrackPoint | None = None
    manual_lat: float | None = None
    manual_lon: float | None = None


@dataclass
class ReviewState:
    failed_results: list[MatchResult]
    decisions: dict[str, ReviewDecision] = field(default_factory=dict)
    gps_segments: list[GPXSegment] = field(default_factory=list)
    all_results: list[MatchResult] = field(default_factory=list)


@dataclass
class BatchResult:
    total: int
    matched: int
    skipped: int  # already has GPS, not overwritten
    failed: int  # match failed
    overwritten: int  # overwrote existing GPS
    success_rate: float
    results: list[MatchResult] = field(default_factory=list)
    reject_groups: dict[str, list[str]] = field(default_factory=dict)
    concurrent_workers: int = 1


@dataclass
class MatcherConfig:
    isolated_window: int = 300  # seconds
    middle_time_window: int = 3600  # seconds
    context_window: int = 300  # seconds
    max_gps_distance: int = 200  # meters
    match_tail: bool = True  # legacy alias
    match_isolated: bool = True
    overwrite_gps: bool = False
    time_offset: int = 0  # seconds, positive = photo time + offset


@dataclass
class ProcessOptions:
    mode: ProcessMode
    output_dir: Path | None = None  # required for COPY mode
    keep_structure: bool = True
    overwrite_gps: bool = False
    resume: bool = False
    generate_report: bool = False
    workers: int = 1


@dataclass
class ProgressUpdate:
    phase: ProgressPhase
    current: int
    total: int
    current_file: str
    elapsed_seconds: float


@dataclass(frozen=True)
class InputSelection:
    paths: tuple[Path, ...] = ()

    @property
    def is_empty(self) -> bool:
        return len(self.paths) == 0

    @classmethod
    def of(cls, paths) -> "InputSelection":
        seen = set()
        norm = []
        for p in paths:
            pp = Path(p)
            if pp == Path():
                continue
            if pp not in seen:
                seen.add(pp)
                norm.append(pp)
        return cls(paths=tuple(norm))
