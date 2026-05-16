# Drag-and-Drop File Support Design

**Date:** 2026-05-16
**Status:** Approved
**Version:** v0.10.0

## Goal

Allow users to drag GPS track files/folders and photo folders directly onto the main window, eliminating the need to manually browse for directories.

## Architecture

Enable `setAcceptDrops(True)` on `MainWindow`. Implement `dragEnterEvent`, `dragMoveEvent`, `dropEvent`, and a `_classify_drop` helper to determine content type from dropped URLs.

Only `main_window.py` is modified. No new files or module changes needed.

## File Type Classification (`_classify_drop`)

Input: list of QUrl from drop event.

Logic:

1. **Single GPX/KML/TCX file** → use its parent directory as GPS directory
2. **Directory scan**: check for track files (`.gpx`, `.kml`, `.tcx`) and image files (`.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff`)
   - Only track files → GPS directory
   - Only image files → Photo directory
   - Both → Ask user via QMessageBox to choose
   - Neither → Show "unsupported content" warning
3. **Multiple items**: first GPS-like → GPS dir, first photo-like → Photo dir

## Event Handlers

### `dragEnterEvent`
- Accept if any URL is a local file/dir (scheme == "file")
- Show copy cursor

### `dragMoveEvent`
- Accept (required for drop to work)

### `dropEvent`
- Extract URLs → call `_classify_drop` → get `(gps_dir: Path | None, photo_dir: Path | None)`
- If `gps_dir`: set `_gps_dir_edit`, add history, call `_auto_scan_gpx`
- If `photo_dir`: set `_photo_dir_edit`, add history, call `_auto_scan_photos`
- If ambiguous: show QMessageBox with "作为GPS目录 / 作为照片目录 / 取消"

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Drop empty folder | Show warning "目录为空" |
| Drop single image file | Use parent directory as photo dir |
| Drop mix of track + image files | Ask user to choose |
| Drop non-local URL | Reject silently |
| Drop while processing | Ignore (start button disabled state) |

## Testing

- Unit test `_classify_drop` logic with mock QUrls (pure logic, no GUI)
- Integration test drag events on MainWindow (requires qtbot)
- Test edge cases: empty folder, single file, mixed content

## Scope

- Only modifies `gui/main_window.py`
- Reuses existing `_auto_scan_gpx`, `_auto_scan_photos`, `_add_path_history`
- ~60 lines of new code
