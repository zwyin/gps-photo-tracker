# GPS Photo Tracker

[中文文档](docs/README_zh.md)

Batch geotag photos using GPS tracks (GPX/KML/TCX) — automatically write EXIF GPS coordinates for camera photos without built-in GPS.

## Why This Tool

Most cameras (unlike phones and drones) don't record GPS. Without geotags, photo apps (Apple Photos, Lightroom, Google Photos) can't organize or recommend photos by location. Manual tagging is impractical for hundreds of photos.

**Typical workflow**: shoot with a camera, record GPS track on your phone or smartwatch (Apple Watch, Garmin, etc.), then use this tool to batch-match and geotag.

Existing tools with linear interpolation achieve **30-50% coverage** — many photos remain unmatched. GPS Photo Tracker adds a **two-pass neighbor-following** algorithm that recovers unmatched photos by following their nearest successful neighbor, boosting coverage to **~90%**. Parameters are adjustable to balance accuracy vs. coverage.

**Target users**: Travelers shooting with a camera + tracking GPS on phone/watch. Photographers needing location-based organization. Field researchers geotagging survey photos.

**Keywords**: geotag, GPS tag, EXIF, photo geotagging, GPX, GPS photo, geocoding photos, photo location tag, camera GPS

## Comparison with Other Tools

| Feature | GPS Photo Tracker | GeoSetter | HoudahGeo | Lightroom Classic | ExifTool | PicMeta PhotoTracker |
|---------|:-:|:-:|:-:|:-:|:-:|:-:|
| Price | **Free / OSS** | Free | $39 | $20/mo | Free | Free |
| Platform | Win/Mac/Linux | Win only | Mac only | Win/Mac | CLI (all) | Win only |
| Open source | **Yes (GPLv3)** | No | No | No | Yes (Artistic) | No |
| Chinese UI | **Yes** | Yes | No | Yes | Partial | No |
| GPS track formats | GPX<br>KML<br>TCX | GPX<br>NMEA<br>KML<br>+3 | GPX<br>NMEA<br>FIT<br>+1 | GPX | GPX<br>NMEA<br>KML<br>+3 | GPX |
| Linear interpolation | **Yes** | Yes | Yes | Yes | Yes | No |
| Two-pass neighbor follow | **Yes** | No | No | No | No | No |
| GPS coverage (typical) | **~90%** | ~50-70% | ~60-80% | ~50-70% | ~50-70% | ~30-40% |
| Interactive review | **Yes** | Limited | Yes | Limited | No (CLI) | No |
| Parameter tuning | **Yes** | Yes | Yes | Time offset only | Yes | Limited |
| WYSIWYG workflow | **Yes** | No | No | No | No | No |
| Arrow-key quick follow | **Yes** | No | No | No | No | No |
| Batch processing | **Yes** | Yes | Yes | Yes | Yes | Yes |
| Write status tracking | **Yes** | No | No | No | No | No |
| Last update | 2026 | 2019 | 2025 | 2026 | 2026 | 2022 |

> **Coverage**: All tools achieve high coverage with dense tracks (1 fix/sec). The gap widens with sparse tracks or GPS signal gaps — GPS Photo Tracker's neighbor following recovers photos that others leave unmatched.

## Features

### Core Matching

- **Multi-format GPS track support** — GPX, KML (Google Earth), TCX (Garmin) with auto-detection
- **Linear interpolation matching** — Accurately interpolates positions between GPS track points
- **Two-pass neighbor following** — Unmatched photos follow nearest successful neighbor; existing-GPS photos excluded from propagation
- **Smart parameter tuning** — Auto-recommends parameters based on track density; all thresholds adjustable

### Interactive Workflow

- **WYSIWYG workflow** — Step-based guided flow: preview → review → execute. All edits carry forward to write
- **Interactive review** — Review failed GPS matches, manually assign coordinates or pick nearby track points
- **Arrow-key GPS follow** — Use ← → keys to quickly assign GPS from adjacent matched photos
- **Esc undo** — Press Esc to restore any photo to its original matched state
- **Source column context menu** — Double-click for quick access to follow/protect/undo actions
- **GPS overwrite protection** — Skips photos that already have GPS data by default
- **GPS coverage stats** — Real-time pre/post coverage rate and success rate display

### Safety & Performance

- **Safe copy mode** — Copies photos before writing, never modifies originals
- **Batch processing** — Handles thousands of photos with progress tracking and cancellation
- **Parallel write** — Multi-threaded EXIF writing for faster processing
- **Resume capability** — Checkpoint system for copy mode, can resume interrupted batches
- **EXIF orientation** — Correctly displays thumbnails with orientation transforms
- **Write status tracking** — Per-photo write status column (copied / overwritten / skipped / failed / cancelled)

### Export & Reporting

- **Result export** — Export to CSV or Markdown with auto-generated filename
- **HTML report** — Self-contained report with inline charts showing match results

## Roadmap

- **Mobile support (iOS/Android)** — Geotag photos directly on your phone, no computer needed. One device for both GPS tracking and photo processing.

## Quick Start

### Option A: Download Pre-built Package (Recommended)

Download from [GitHub Actions](../../actions/workflows/build.yml) → click the latest successful run → scroll down to **Artifacts**:

| Platform | File |
|----------|------|
| macOS | `GPS-Photo-Tracker-v0.19.0-macos.zip` |
| Windows | `GPS-Photo-Tracker-v0.19.0-windows.zip` |
| Linux | `GPS-Photo-Tracker-v0.19.0-linux.tar.gz` |

Download, unzip, and double-click to run. No Python or any other software needed.

### Option B: Run from Source

**Step 1 — Check Python version**

```bash
python --version
```

Need **Python 3.11 or higher**. If you see a lower version, download from [python.org](https://www.python.org/downloads/).

**Step 2 — Download source code**

```bash
git clone https://github.com/zwyin/gps-photo-tracker.git
cd gps-photo-tracker
```

**Step 3 — Install dependencies**

```bash
pip install -e .
```

This automatically installs all required packages: PySide6, piexif, gpxpy, Pillow, geopy, tenacity.

**Step 4 — Launch**

```bash
python -m gps_photo_tracker
```

The program will automatically check dependencies on startup. If anything is missing, it shows a clear message telling you exactly what to install.

### Basic Workflow

The app uses a step-based guided workflow:

1. **① Preview** — Select GPS track and photo directories, auto-match photos to GPS positions
2. **② Review** — For unmatched photos, manually assign coordinates or pick nearby track points
3. **③ Execute** — Write GPS data to photos (copy to output or overwrite in-place)

What you see in the preview table is exactly what gets written — all manual corrections (arrow-key follows, review edits, resets) carry forward to execution.

## Development

### Setup

```bash
pip install -e ".[dev]"
```

### Run Tests

```bash
pytest                          # All tests
pytest --cov                    # With coverage report
pytest tests/unit/test_gps_matcher.py  # Single module
```

### Test Coverage

| Layer | Target | Current |
|-------|--------|---------|
| Core (algorithm/IO) | >= 85% | ~95% |
| Service | >= 80% | 86% |
| Overall | >= 75% | ~80% |

### Project Structure

```
src/gps_photo_tracker/
├── core/           # Algorithms: GPS matching, parsers, EXIF, checkpoint
├── service/        # Business logic: tagging pipeline, cancellation
├── gui/            # PySide6 GUI: main window, panels, dialogs
└── logging_/       # Structured logging
tests/
├── unit/           # 565+ unit tests
├── integration/    # End-to-end tests
└── batch/          # Large-scale batch tests
```

## Configuration

Matching parameters can be adjusted in the GUI or programmatically:

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `isolated_window` | 300s | 60-3600 | Max time diff for isolated photos |
| `middle_time_window` | 3600s | 600-7200 | Max time diff for interpolated photos |
| `context_window` | 300s | 60-1800 | Window to determine interpolation eligibility |
| `max_gps_distance` | 200m | 50-1000 | Max distance between consecutive GPS points |
| `match_tail` | True | — | Match photos at track boundaries |
| `time_offset` | 0s | -3600~3600 | Camera clock correction |

## Building

```bash
python scripts/build.py          # Build for current platform
python scripts/build.py --clean  # Clean build
```

Requires [PyInstaller](https://pyinstaller.org/). Produces a standalone `.app` (macOS), `.exe` (Windows), or binary (Linux).

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).

## Acknowledgments

- GPS matching algorithm validated against 1,832 real photos with 83%+ success rate
- Built with [PySide6](https://doc.qt.io/qtforpython-6/), [piexif](https://github.com/hMatoba/Piexif), [gpxpy](https://github.com/tkrajina/gpxpy), [Pillow](https://python-pillow.org/), and [geopy](https://github.com/geopy/geopy)
