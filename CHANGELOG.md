# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-05-08

### Added

- PySide6 GUI with main window, config panel, progress panel, result table, and settings dialog
- Photo browser with thumbnail preview and EXIF orientation support
- GPX track browser with file grouping and time coverage overview
- Detail dialog with GPS comparison and interpolation reference points
- GPS matching algorithm with linear interpolation for middle photos
- Multi-format track support: GPX, KML (Google Earth), TCX (Garmin)
- Smart parameter tuning based on track density and photo distribution
- Copy mode with GPS tag writing and overwrite protection
- Preview mode for dry-run matching without file changes
- Batch processor with ThreadPoolExecutor for parallel EXIF writing
- Checkpoint system for resume capability in copy mode
- HTML report generation with inline SVG charts
- Structured logging with operation, match, write, and error log categories
- Path history with persistent QComboBox (last 10 entries)
- GitHub Actions CI workflow for cross-platform testing

### Tested

- 334 unit tests, 86%+ code coverage
- End-to-end validation with 1,832 real photos, 83%+ match success rate
- GPS coordinate write verification with 0.001 degree precision

## [0.8.0] - 2026-05-07

### Added

- EF-03: BatchProcessor for concurrent EXIF write phase
- EF-04: CheckpointManager for resume after interruption (copy mode)
- EF-05: ParamTuner for automatic parameter recommendation
- EF-08: Multi-format GPS support (GPX/KML/TCX via TrackParser)
- EF-09: HTML report builder with inline SVG charts
- EF-10: OrientationReader for EXIF orientation display transforms
- PyInstaller build configuration for macOS .app bundle
- Six rounds of code review with critical bug fixes

### Changed

- Service layer integrated all v0.8 modules
- GUI integrated smart recommend, workers, resume, and report controls
- BatchProcessor uses ThreadPoolExecutor (not ProcessPoolExecutor)
