# EF-07: Interactive Review — Design Spec

**Date:** 2026-05-15
**Status:** Approved
**Affects versions:** 0.9.0

## Summary

Insert a mandatory review step between GPS matching and EXIF writing. When Preview detects failed matches, a list-driven review dialog pops up automatically. Users can skip, manually select a nearby GPS track point, or enter coordinates for failed photos before proceeding to COPY/OVERWRITE.

## User Workflow

```
Select files → Preview → Match complete
  → Has failed items? → YES → Auto-popup ReviewDialog
    → User reviews (skip / manual GPS / manual coord)
    → Confirm → Write phase (COPY/OVERWRITE)
  → NO → Directly to Write phase or show results
```

## 1. Data Model

New types in `core/models.py`:

```python
class ReviewAction(Enum):
    KEEP_SKIP = "keep_skip"        # Default, do nothing
    MANUAL_GPS = "manual_gps"      # User selected a track point
    MANUAL_COORD = "manual_coord"  # User entered lat/lon
    SKIP = "skip"                  # User explicitly skipped

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
```

`MatchResult` gets a new optional field:

```python
review_gps: GPSInfo | None = None  # Set by apply_review if user assigns GPS
```

## 2. Service Layer Split

Split the monolithic `_run_pipeline` into three phases:

### Phase 1: Match (existing, unchanged)
- `scan_gpx()` → `scan_photos()` → `GPSMatcher.match()`
- Returns `list[MatchResult]`

### Phase 2: Review (new)
- `prepare_review(results, segments)` — extract failed items into `ReviewState`
- GUI shows `ReviewDialog`, user makes decisions
- `apply_review(results, state)` — merge decisions back into `MatchResult`:
  - `MANUAL_GPS`: build `GPSInfo` from selected `TrackPoint`, set `match_result.review_gps` and `success=True`
  - `MANUAL_COORD`: build `GPSInfo` from lat/lon, set `match_result.review_gps` and `success=True`
  - `KEEP_SKIP` / `SKIP`: no change, `success` stays `False`, write phase skips

### Phase 3: Write (existing, unchanged)
- Iterate `MatchResult`, write GPS for `success=True` items
- `review_gps` takes precedence over `gps` if set

### New public methods on GPSTaggingService

```python
def prepare_review(self, results: list[MatchResult], segments: list[GPXSegment]) -> ReviewState
def apply_review(self, results: list[MatchResult], state: ReviewState) -> list[MatchResult]
def write_phase(self, results: list[MatchResult], options: ProcessOptions) -> BatchResult
```

### Worker changes

- Preview mode: match complete → emit `review_ready(state)` → MainWindow opens ReviewDialog → review done → emit `write_start(modified_results)` → Worker runs write phase
- COPY/OVERWRITE: same flow, write phase behavior differs
- No failed items → skip review, go directly to write or show results

## 3. GUI Components

### 3.1 ReviewDialog (`gui/review_dialog.py`)

List-driven `QDialog` layout:

```
┌─────────────────────────────────────────────────────────┐
│ 审核失败项 — 共 23 张                            [全部跳过] │
├────────────────────────────────┬────────────────────────┤
│ ☑ 全选   筛选: [全部失败 ▾]     │                        │
├────────────────────────────────┤  Photo Preview          │
│ ☑ 📷 IMG_0421  14:32:15       │  ┌────────────────┐    │
│   时间差过大 (42min)            │  │  thumbnail     │    │
│   Action: [选操作 ▾]           │  └────────────────┘    │
├────────────────────────────────┤                        │
│ ☐ 📷 IMG_0422  14:33:01       │  Time: 14:32:15        │
│   无 GPS 覆盖                  │  Reason: time_gap      │
│   Action: [选操作 ▾]           │  Nearest: 14:50 @ ...  │
├────────────────────────────────┤                        │
│ ...                            │  ── Batch (3 selected) ─│
│                                │  [Skip] [Pick GPS]     │
│                                │  [Enter Coord]         │
├────────────────────────────────┴────────────────────────┤
│ Progress: 15/23  Skipped: 12  Manual: 3          [确认] │
└─────────────────────────────────────────────────────────┘
```

**Interactions:**
1. Table defaults to all rows selected, action column = "pending"
2. Click row → right panel shows thumbnail + details
3. Single action: inline dropdown per row (skip / manual GPS / enter coord)
4. Batch action: checkbox multiple rows → batch buttons in right panel
5. "Manual GPS" → opens `GPSPointPicker` sub-dialog
6. "Enter Coord" → opens small dialog for lat/lon input
7. Bottom bar shows real-time progress
8. "Confirm" closes dialog, returns `ReviewState`
9. "Skip All" sets all to SKIP, closes immediately
10. Close (X) = treat as "Skip All"

### 3.2 GPSPointPicker (`gui/gps_point_picker.py`)

Sub-dialog showing track points near photo time (±30 min):

- List sorted by time, each row: timestamp, coordinates, time delta from photo
- Click to select, confirm returns `TrackPoint`

### 3.3 MainWindow integration

- `_on_done` checks for `review_state` in result
- Has state + has failed items → create `ReviewDialog(state)` → on confirm → `service.apply_review()` → notify Worker to continue write phase
- No failed items → skip review, show results directly

## 4. Edge Cases

| Case | Behavior |
|------|----------|
| Zero failures | Skip review dialog entirely |
| User closes dialog (X) | Treat as "Skip All" |
| Invalid coordinates | Reject with inline validation (-90~90, -180~180) |
| No nearby GPS points | Disable "Manual GPS" button for that photo, show "no points nearby" |
| Large failure count (500+) | Table uses virtual scroll or pagination |

## 5. File Changes

| File | Change |
|------|--------|
| `core/models.py` | Add `ReviewAction`, `ReviewDecision`, `ReviewState`; add `review_gps` field to `MatchResult` |
| `service/tagging_service.py` | Add `prepare_review()`, `apply_review()`, `write_phase()`; split `_run_pipeline` |
| `gui/review_dialog.py` | **New** — ReviewDialog |
| `gui/gps_point_picker.py` | **New** — GPSPointPicker sub-dialog |
| `gui/main_window.py` | `_on_done` review interception |
| `gui/worker.py` | Phase-based signal emission |
| `tests/unit/test_review.py` | **New** — ReviewState, apply_review unit tests |
| `tests/unit/test_review_dialog.py` | **New** — ReviewDialog GUI tests |

## 6. Testing

- `prepare_review()` / `apply_review()`: unit tests covering all `ReviewAction` branches
- Coordinate validation: reject out-of-range, accept boundary values
- Zero failures: returns empty `ReviewState`, MainWindow skips review
- GUI tests: button clicks, dropdown selections, batch operations signal flow

## 7. Future Iteration

- Card-driven layout (option B from brainstorming) as alternative interaction mode
- User preference to choose list vs card mode in Settings
- Review results persistence (save/load review state across sessions)
