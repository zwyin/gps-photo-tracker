# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.23.0] - 2026-07-12

### Added

- **文件或目录选择（平台自适应）**：GPS 轨迹和照片输入现在支持选择目录，或一个/多个文件。macOS 用原生 `NSOpenPanel`（一个对话框里选文件或目录，pyobjc），Windows/Linux 用"选择 ▾"小菜单 → 原生对话框，pyobjc 不可用时优雅降级。COPY 模式按所选照片的最低公共祖先（LCA）保留各自相对路径。

### Fixed

- **多目录同名照片碰撞**：checkpoint 与并行写入改按照片**全路径**做 key（原先按文件名），多目录选择下两个同名照片（如不同文件夹的 `IMG_001.jpg`）不再互相误标完成 / 并行字典互相覆盖 / 写失败时静默丢片。文件/混合/多目录选择强制保留目录结构，避免同名覆盖。

## [0.22.0] - 2026-07-11

### Fixed

- **Photo browsing lag on Windows (↑/↓ keys)**: Browsing photos in the result list was slow on Windows (~0.5s/photo; macOS felt smooth). Root cause: the photo preview re-decoded the full-resolution JPEG from disk on every selection change, discarding its own thumbnail cache. Fix: decode each photo once to a 1024px EXIF-orientation-corrected pixmap and reuse it on cache hit — repeated views are pure memory hits (no decode, no EXIF read, no disk/Defender scan). Adjacent-photo preload now populates the same cache, so forward browsing within ±3 is smooth too. Also namespaced the pixmap cache (`preview:` vs the photo browser's `thumb:`) and set the cache limit once at startup, since `QPixmapCache` is process-global.

## [0.21.0] - 2026-07-11

### Fixed

- **Windows crash on startup ("Missing dependencies: Pillow")**: Moved `Pillow` out of runtime dependencies into the `dev`/test extra. Pillow had been declared as a runtime dependency and checked at startup in `__main__.py`, but the production app never imports it — thumbnails use PySide6's `QPixmap` and EXIF writing uses `piexif` (standalone). Pillow is only used by the test suite to build JPEG fixtures (`PIL.Image`). On macOS the spec bundled it anyway; on Windows/Linux the build path bypasses the spec, so PyInstaller dropped the unused library and the startup check then failed, crashing the app. Moving it to dev-only fixes the Windows crash, keeps the test suite working, and shrinks every installer.

## [0.19.0] - 2026-05-18

### Added

- **Write status column**: New "写入状态" column in result table showing per-photo write outcome (已复制 / 已覆盖 / 跳过 / 失败 / 已取消)
- **Write signal separation**: Worker emits dedicated `write_signal` during write phase instead of reusing `photo_signal`, preventing duplicate rows after COPY/OVERWRITE

### Changed

- **Write mode tracking**: `MainWindow` stores the selected write mode (copy/overwrite) to correctly determine write status labels
- **Result table expanded**: 9 columns (was 8), export CSV/Markdown includes write status

### Fixed

- **Completion popup delay**: Write-phase completion notification no longer blocks or delays when user starts a new preview cycle; `_done_pending` flag prevents duplicate popups
- **Stats card protected counting**: Protected photos counted correctly in stats display
- **Removed dead `_METHOD_CODES` constant** that was superseded by `Qt.UserRole` storage

### Tested

- 859 tests passing, 99.55% overall coverage
- `__main__.py` entry point: 0→99% (crash log, error dialog, dependency check)
- `main_window.py`: 78→99% coverage (99 new test classes)
- Write status column verified in COPY and OVERWRITE modes
- Completion popup suppression tested with timer mock

## [0.18.0] - 2026-05-17

### Added

- **Esc undo mechanism**: Press Esc to restore a photo to its original matched state (undoes follow, protection, or any edit)
- **Source column double-click menu**: Double-click the "来源" column to open context menu with follow/protect/undo actions, dynamically generated based on current row state
- **Original state snapshot**: `_original_details` deep-copy preserved at preview completion for reliable undo

### Changed

- **Protection toggle refined**: `.` key still toggles protection, but Esc now serves as the ultimate undo — restores original match regardless of how many operations were applied
- **Shortcut hint updated**: `←→ 跟随GPS | . 保护/取消 | Esc 撤销 | ↑↓ 导航`

### Fixed

- **Protection toggle**: Unprotecting a photo now correctly restores the pre-protection GPS value (not the original match)

### Tested

- 506 tests passing
- Undo logic verified: follow→undo→restore, protect→undo→restore

## [0.17.0] - 2026-05-17

### Added

- **Source column redesign**: "方式" column renamed to "来源" with ①②③ step prefix labels (① 插值, ① 就近, ② 跟随, ③ 跟随, ③ 手动, —). Direction info (prev/next) moved to remark column
- **Protection mechanism**: `.` key now toggles per-photo protection (replaces old reset-to-original). Protected photos freeze current GPS(后), skip writing, and cannot be followed. Each row has independent snapshot for precise unprotect restore
- **Trusted record filtering**: All follow operations (auto_follow, review dialog, arrow keys) now consistently exclude skipped and protected photos as GPS sources
- **Protected filter**: New "已保护" filter option in result table dropdown
- **Stats card**: Shows "已保护" count separately when any photos are protected

### Changed

- **auto_follow API separation**: `GPSMatcher.auto_follow()` is now a public method called separately from `match()` in service layer, making the ①预览匹配 → ②自动跟随 pipeline explicit
- **Method internal codes stored in UserRole**: Table items store internal English codes (`interpolated`, `auto_follow_prev`, etc.) in `Qt.UserRole` for reliable WYSIWYG write path, eliminating display-label reverse-mapping
- **Remark column auto-generated**: Auto-follow photos automatically show direction ("跟随上一张"/"跟随下一张") in remark column

### Fixed

- Skipped photos (with existing GPS) no longer show a value in "计算GPS" column — `gps` field in `MatchResult` is now `None` for skipped photos
- Second-pass auto_follow excludes skipped photos — camera GPS may be unreliable and should not propagate to neighbors
- Cascade chain propagation in second-pass auto_follow — scans results dynamically, allowing rescued photos to cascade
- Export filename commit hash fallback — uses `git rev-parse` in dev mode when `__commit__` is empty
- Skipped photo counting in `process()` and `write_phase()` — correctly counted as "skipped"
- `_apply_follow` in tagging_service now excludes skipped/protected as follow sources

### Tested

- 506 tests passing
- 5 rounds of independent design review via sub-agents

## [0.16.0] - 2026-05-17

### Added

- Second-pass neighbor follow: unmatched photos automatically follow nearest successful neighbor within `isolated_window`
- Auto-follow methods: `auto_follow_prev` / `auto_follow_next` with distinct color coding
- Result table export: CSV (UTF-8 BOM) and Markdown (pipe-escaped) with auto-generated filename
- Reset defaults button in config panel: restores all parameters including checkboxes
- Smart export filename: `{photo_dir}_{timestamp}.{ext}`

### Fixed

- Arrow-key GPS follow direction: searches by timestamp (not visual row) for correct prev/next
- `_quick_follow_gps` altitude not copied to detail dict
- `_collect_table_results` missing `auto_follow_prev`/`auto_follow_next` in reverse method map
- Method label map extracted to class constants (`_METHOD_LABELS` / `_METHOD_CODES`) to prevent sync drift

### Changed

- Method label maps unified from 4 inline dictionaries to 2 class-level constants
- Photo preview uses `setFixedWidth` instead of `setFixedSize` for natural height in QSplitter

### Tested

- 501 tests passing, ~78% coverage
- Two independent code reviews + E2E analysis via sub-agents

## [0.15.0] - 2026-05-17

### Added

- Interpolation fallback to nearest-point: when middle photo interpolation fails due to distance/time, degrades to nearest GPS point instead of hard failure
- Result export functionality: export table to CSV or Markdown file with column-accurate output
- Export button in result table panel

### Fixed

- Middle photos (between two GPS points) that exceed `max_gps_distance` now degrade gracefully to nearest-point matching
- Time-diff exceeded cases also degrade to nearest-point when within `middle_time_window`

### Tested

- 495 tests passing
- Independent code review via sub-agent

## [0.13.0] - 2026-05-17

### Fixed

- Version number stuck at 0.9.0: synced `pyproject.toml` and `__init__.py` to match actual development version

## [0.14.0] - 2026-05-17

### Added

- WYSIWYG step-based workflow: ① 预览匹配 → ② 审核 → ③ 拷贝/覆盖
- `_collect_table_results()` reads GPS directly from table column (what you see is what gets written)
- `_original_details` deep copy enables true `.` key reset to original match
- Worker `pre_computed_results` parameter skips scan+match, writes directly
- COPY mode wraps flat photo directories with `photo_dir.name` subdirectory

### Changed

- Step buttons (① ② ③) replace mode radio buttons in config panel
- `_copy_destination()` adds `photo_dir.name` wrapper for flat directories
- `concurrency.py` parallel write path synced with same directory fix
- Removed dead code: `_review_decisions`, `_reviewed_results`

### Fixed

- Preview results (arrow follows, review edits, resets) now carry forward to execution
- Altitude preserved in WYSIWYG write path
- Skipped photos no longer counted as failures in write phase
- Parent directories created before EXIF write (sequential + parallel paths)

### Tested

- 487 tests passing, 78% coverage
- Independent E2E testing + code review via sub-agents

## [0.12.0] - 2026-05-17

### Added

- Review reopen button: re-open review dialog after closing
- Dot reset key: "." restores original GPS match, clears remarks
- Remarks column: 8th column tracks manual interventions (arrow follow, manual GPS, etc.)
- Arrow key GPS follow: ← → keys follow adjacent matched GPS

### Changed

- Arrow key handling: ← → trigger GPS follow instead of cell navigation
- Status/method/remarks three-column design for clearer result classification

### Fixed

- Arrow key interception by QTableWidget cell navigation
- Splitter handle visibility and hover color-coding

### Tested

- 430+ tests passing

## [0.11.0] - 2026-05-16

### Added

- Date/time column in results table
- Pre-processing overview: total photos, existing GPS, GPS coverage stats
- GPS coverage delta display (e.g., "45% → 78% (+33%)")
- Method column color coding for GPS interpolation types

### Fixed

- GPS column highlighting for review suggestions
- Splitter visibility with visual indicators
- Preview scaling on splitter resize
- Isolated photo matching (header/tail orphans)
- Existing GPS skip when overwrite disabled
- Statistics update after review corrections

### Tested

- 380+ tests passing

## [0.10.0] - 2026-05-16

### Added

- Drag-and-drop support for main window
- Configuration profiles (save/load multiple settings)
- Logging system with rolling rotation and GUI log viewer
- Thumbnail preloading (±3 rows cached)
- Column auto-sizing and default sort
- GPS color coding (overwritten vs. matched)
- Resizable splitters for panel adjustment
- Smart review suggestions

### Fixed

- File handler leaks (Windows compatibility)
- Timezone display consistency
- Result table: empty rows, sorting index, cursor warnings
- Review dialog: keyboard navigation, date-time display
- Cross-platform CI test failures
- Settings layout, preview display, splitter initialization

## [0.9.0] - 2026-05-16

### Added

- EF-07: Interactive review for failed GPS matches
  - ReviewAction enum, ReviewDecision and ReviewState data models
  - Service layer split: match → review → write phases
  - prepare_review() and apply_review() on GPSTaggingService
  - write_phase() supports review GPS precedence over matched GPS
  - Worker emits review_ready_signal for async review workflow
  - GPSPointPicker dialog for manual GPS track point selection
  - ReviewDialog with list-driven layout, batch actions, and inline dropdowns
  - MainWindow review integration with status bar summary
  - Coordinate input validation (-90~90 lat, -180~180 lon)

### Tested

- 360 unit/integration tests passing (26 new review tests)
- TDD-driven development for all new components

## [0.8.1] - 2026-05-11

### Fixed

- Startup crash handler: global try/catch writes crash log + shows error dialog
- Windows debug build (`--console`) for troubleshooting silent startup failures
- macOS .app bundle now packaged as .zip (preserves structure and permissions)
- Linux binary now packaged as .tar.gz (preserves executable bit)
- All platform artifacts include version number in filename
- Version alignment: pyproject.toml / __init__.py / spec / README all consistent

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

[0.17.0]: https://github.com/zwyin/gps-photo-tracker/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/zwyin/gps-photo-tracker/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/zwyin/gps-photo-tracker/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/zwyin/gps-photo-tracker/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/zwyin/gps-photo-tracker/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/zwyin/gps-photo-tracker/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/zwyin/gps-photo-tracker/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/zwyin/gps-photo-tracker/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/zwyin/gps-photo-tracker/releases/tag/v0.9.0
[0.8.1]: https://github.com/zwyin/gps-photo-tracker/releases/tag/v0.8.1
[1.0.0]: https://github.com/zwyin/gps-photo-tracker/releases/tag/v1.0.0
[0.8.0]: https://github.com/zwyin/gps-photo-tracker/releases/tag/v0.8.0
