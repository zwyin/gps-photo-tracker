# GPS Photo Tracker

[中文文档](docs/README_zh.md)

Batch process photos with GPS tracks (GPX/KML/TCX) to automatically write EXIF GPS tags. Built for photographers and travelers who need to geotag photos from cameras without built-in GPS.

## Features

- **Multi-format GPS track support** — GPX, KML (Google Earth), TCX (Garmin) with auto-detection
- **Linear interpolation matching** — Accurately interpolates positions between GPS track points
- **Safe copy mode** — Copies photos before writing, never modifies originals
- **GPS overwrite protection** — Skips photos that already have GPS data by default
- **Batch processing** — Handles thousands of photos with progress tracking and cancellation
- **Smart parameter tuning** — Auto-recommends matching parameters based on track density
- **HTML report** — Self-contained report with inline charts showing match results
- **Resume capability** — Checkpoint system for copy mode, can resume interrupted batches
- **Parallel write** — Multi-threaded EXIF writing for faster processing
- **EXIF orientation** — Correctly displays thumbnails with orientation transforms
- **Interactive review** — Review failed GPS matches after preview, manually assign coordinates or pick nearby track points

## Quick Start

### Option A: Download Pre-built Package (Recommended)

Download from [GitHub Actions](../../actions/workflows/build.yml) → click the latest successful run → scroll down to **Artifacts**:

| Platform | File |
|----------|------|
| macOS | `GPS-Photo-Tracker-v0.9.0-macos.zip` |
| Windows | `GPS-Photo-Tracker-v0.9.0-windows.zip` |
| Linux | `GPS-Photo-Tracker-v0.9.0-linux.tar.gz` |

Download, unzip, and double-click to run. No Python or any other software needed.

### Option B: Run from Source

**Step 1 — Check Python version**

```bash
python --version
```

Need **Python 3.11 or higher**. If you see a lower version, download from [python.org](https://www.python.org/downloads/).

**Step 2 — Download source code**

```bash
git clone https://github.com/zwyin/gps-photo-tracker-claude.git
cd gps-photo-tracker-claude
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

1. Select a directory containing GPS track files (GPX/KML/TCX)
2. Select a directory containing photos (JPEG)
3. Adjust matching parameters or use "Smart Recommend"
4. Preview results, then run in copy or overwrite mode

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
| Core (algorithm/IO) | >= 85% | ~90% |
| Service | >= 80% | ~81% |
| Overall | >= 75% | ~86% |

### Project Structure

```
src/gps_photo_tracker/
├── core/           # Algorithms: GPS matching, parsers, EXIF, checkpoint
├── service/        # Business logic: tagging pipeline, cancellation
├── gui/            # PySide6 GUI: main window, panels, dialogs
└── logging_/       # Structured logging
tests/
├── unit/           # 334 unit tests
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
