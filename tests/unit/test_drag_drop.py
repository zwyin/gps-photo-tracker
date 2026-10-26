"""Tests for drag-and-drop: DropZone widget + drop path classification."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QMimeData, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent
from PySide6.QtWidgets import QApplication

from gps_photo_tracker.gui.drop_zone import (
    IMAGE_EXTS,
    MIXED_GPS,
    MIXED_PHOTO,
    TRACK_EXTS,
    DropZone,
    classify_paths,
)
from gps_photo_tracker.gui.main_window import MainWindow


@pytest.fixture
def app(qtbot):
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    return w


def _make_mime(urls: list[str]) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(u) for u in urls])
    return mime


def _make_drag_event(mime: QMimeData, action=Qt.DropAction.CopyAction):
    """Create a minimal drag enter event for testing."""
    event = MagicMock(spec=QDragEnterEvent)
    event.mimeData.return_value = mime
    event.setDropAction = MagicMock()
    event.accept = MagicMock()
    event.ignore = MagicMock()
    return event


def _make_move_event(mime: QMimeData):
    event = MagicMock(spec=QDragMoveEvent)
    event.mimeData.return_value = mime
    event.setDropAction = MagicMock()
    event.accept = MagicMock()
    event.ignore = MagicMock()
    return event


def _make_drop_event(mime: QMimeData):
    event = MagicMock()
    event.mimeData.return_value = mime
    event.setDropAction = MagicMock()
    event.accept = MagicMock()
    event.ignore = MagicMock()
    return event


# ── Pure classification logic (no Qt event plumbing) ───────

class TestClassifyPaths:

    def test_multiple_track_files_merged(self, tmp_path):
        """Multi-file merge: track files from different dirs all land in
        the track list, order preserved (exact file selection, not parent)."""
        a = tmp_path / "a.gpx"
        a.write_text("<gpx></gpx>")
        sub = tmp_path / "sub"
        sub.mkdir()
        b = sub / "b.kml"
        b.write_text("<kml></kml>")
        tracks, photos = classify_paths([a, b])
        assert tracks == [a, b]
        assert photos == []

    def test_multiple_image_files_merged(self, tmp_path):
        a = tmp_path / "1.jpg"
        a.write_bytes(b"\xff\xd8\xff\xe0")
        b = tmp_path / "2.png"
        b.write_bytes(b"\x89PNG")
        tracks, photos = classify_paths([a, b])
        assert tracks == []
        assert photos == [a, b]

    def test_mixed_drop_fills_both(self, tmp_path):
        gpx = tmp_path / "track.gpx"
        gpx.write_text("<gpx></gpx>")
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0")
        tracks, photos = classify_paths([gpx, img])
        assert tracks == [gpx]
        assert photos == [img]

    @pytest.mark.parametrize("ext", sorted(TRACK_EXTS))
    def test_all_track_extensions(self, tmp_path, ext):
        f = tmp_path / f"track{ext}"
        f.write_text("x")
        tracks, _ = classify_paths([f])
        assert tracks == [f]

    @pytest.mark.parametrize("ext", sorted(IMAGE_EXTS))
    def test_all_image_extensions(self, tmp_path, ext):
        f = tmp_path / f"img{ext}"
        f.write_bytes(b"x")
        _, photos = classify_paths([f])
        assert photos == [f]

    def test_unknown_extension_ignored(self, tmp_path):
        txt = tmp_path / "notes.txt"
        txt.write_text("hello")
        tracks, photos = classify_paths([txt])
        assert tracks == []
        assert photos == []

    def test_track_directory_sniffed(self, tmp_path):
        d = tmp_path / "tracks"
        d.mkdir()
        (d / "track.gpx").write_text("<gpx></gpx>")
        tracks, photos = classify_paths([d])
        assert tracks == [d]
        assert photos == []

    def test_image_directory_sniffed(self, tmp_path):
        d = tmp_path / "photos"
        d.mkdir()
        (d / "img.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        tracks, photos = classify_paths([d])
        assert tracks == []
        assert photos == [d]

    def test_empty_directory_ignored(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        tracks, photos = classify_paths([empty])
        assert tracks == []
        assert photos == []

    def test_nonexistent_path_ignored(self):
        tracks, photos = classify_paths([Path("/nonexistent/path/file.gpx")])
        assert tracks == []
        assert photos == []

    def test_duplicates_deduplicated(self, tmp_path):
        gpx = tmp_path / "track.gpx"
        gpx.write_text("<gpx></gpx>")
        tracks, _ = classify_paths([gpx, gpx, gpx])
        assert tracks == [gpx]

    def test_directory_sniff_non_recursive(self, tmp_path):
        """A track hidden in a subdirectory does not classify the parent
        (matches FileProvider.resolve_tracks non-recursive scan)."""
        nested = tmp_path / "outer" / "inner"
        nested.mkdir(parents=True)
        (nested / "track.gpx").write_text("<gpx></gpx>")
        tracks, photos = classify_paths([tmp_path / "outer"])
        assert tracks == []
        assert photos == []

    def test_mixed_directory_chooser_gps(self, tmp_path):
        mixed = tmp_path / "mixed"
        mixed.mkdir()
        (mixed / "track.gpx").write_text("<gpx></gpx>")
        (mixed / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        tracks, photos = classify_paths([mixed], mixed_dir_chooser=lambda d: MIXED_GPS)
        assert tracks == [mixed]
        assert photos == []

    def test_mixed_directory_chooser_photo(self, tmp_path):
        mixed = tmp_path / "mixed"
        mixed.mkdir()
        (mixed / "track.gpx").write_text("<gpx></gpx>")
        (mixed / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        tracks, photos = classify_paths([mixed], mixed_dir_chooser=lambda d: MIXED_PHOTO)
        assert tracks == []
        assert photos == [mixed]

    def test_mixed_directory_chooser_cancel(self, tmp_path):
        mixed = tmp_path / "mixed"
        mixed.mkdir()
        (mixed / "track.gpx").write_text("<gpx></gpx>")
        (mixed / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        tracks, photos = classify_paths([mixed], mixed_dir_chooser=lambda d: None)
        assert tracks == []
        assert photos == []

    def test_mixed_directory_without_chooser_ignored(self, tmp_path):
        mixed = tmp_path / "mixed"
        mixed.mkdir()
        (mixed / "track.gpx").write_text("<gpx></gpx>")
        (mixed / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        tracks, photos = classify_paths([mixed])
        assert tracks == []
        assert photos == []


# ── DropZone widget ────────────────────────────────────────

class TestDropZoneWidget:

    def test_zone_exists_in_main_window(self, window):
        assert isinstance(window._drop_zone, DropZone)
        assert window._drop_zone.acceptDrops()

    def test_drag_enter_accepts_and_highlights(self, window, qtbot, tmp_path):
        gpx = tmp_path / "track.gpx"
        gpx.write_text("<gpx></gpx>")
        event = _make_drag_event(_make_mime([str(gpx)]))
        window._drop_zone.dragEnterEvent(event)
        event.accept.assert_called_once()
        event.ignore.assert_not_called()
        assert window._drop_zone.is_highlighted()

    def test_drag_enter_rejects_unknown_extension(self, window, tmp_path):
        txt = tmp_path / "notes.txt"
        txt.write_text("hello")
        event = _make_drag_event(_make_mime([str(txt)]))
        window._drop_zone.dragEnterEvent(event)
        event.ignore.assert_called_once()
        event.accept.assert_not_called()
        assert not window._drop_zone.is_highlighted()

    def test_drag_enter_rejects_remote_urls(self, window):
        mime = QMimeData()
        mime.setUrls([QUrl("https://example.com/file.gpx")])
        event = _make_drag_event(mime)
        window._drop_zone.dragEnterEvent(event)
        event.ignore.assert_called_once()
        assert not window._drop_zone.is_highlighted()

    def test_drag_move_accepts(self, window, tmp_path):
        gpx = tmp_path / "track.gpx"
        gpx.write_text("<gpx></gpx>")
        event = _make_move_event(_make_mime([str(gpx)]))
        window._drop_zone.dragMoveEvent(event)
        event.accept.assert_called_once()
        event.ignore.assert_not_called()

    def test_drag_leave_clears_highlight(self, window, tmp_path):
        gpx = tmp_path / "track.gpx"
        gpx.write_text("<gpx></gpx>")
        zone = window._drop_zone
        zone.dragEnterEvent(_make_drag_event(_make_mime([str(gpx)])))
        assert zone.is_highlighted()
        zone.dragLeaveEvent(MagicMock())
        assert not zone.is_highlighted()

    def test_drop_emits_paths_and_clears_highlight(self, window, qtbot, tmp_path):
        gpx = tmp_path / "track.gpx"
        gpx.write_text("<gpx></gpx>")
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0")
        zone = window._drop_zone
        with qtbot.waitSignal(zone.pathsDropped) as blocker:
            zone.dropEvent(_make_drop_event(_make_mime([str(gpx), str(img)])))
        event = blocker.args[0]
        assert event == [gpx, img]
        assert all(isinstance(p, Path) for p in event)
        assert not zone.is_highlighted()

    def test_drop_ignores_remote_urls(self, window, qtbot):
        mime = QMimeData()
        mime.setUrls([QUrl("https://example.com")])
        zone = window._drop_zone
        with qtbot.assertNotEmitted(zone.pathsDropped):
            zone.dropEvent(_make_drop_event(mime))


# ── MainWindow window-level drag events (unchanged contract) ──

class TestWindowDragEvents:

    def test_accept_local_file(self, window):
        event = _make_drag_event(_make_mime(["/tmp/test.gpx"]))
        window.dragEnterEvent(event)
        event.accept.assert_called_once()
        event.ignore.assert_not_called()

    def test_reject_non_local(self, window):
        mime = QMimeData()
        mime.setUrls([QUrl("https://example.com/file.gpx")])
        event = _make_drag_event(mime)
        window.dragEnterEvent(event)
        event.ignore.assert_called_once()
        event.accept.assert_not_called()

    def test_reject_no_urls(self, window):
        event = _make_drag_event(QMimeData())
        window.dragEnterEvent(event)
        event.ignore.assert_called_once()

    def test_drag_move_accepts_with_urls(self, window):
        event = _make_move_event(_make_mime(["/tmp/test.gpx"]))
        window.dragMoveEvent(event)
        event.accept.assert_called_once()

    def test_drag_move_rejects_without_urls(self, window):
        event = _make_move_event(QMimeData())
        window.dragMoveEvent(event)
        event.ignore.assert_called_once()


# ── MainWindow integration: drops reach the selections ─────

class TestMainWindowDropIntegration:

    def test_dropped_track_files_merge_into_gps_selection(self, window, tmp_path):
        a = tmp_path / "a.gpx"
        a.write_text("<gpx></gpx>")
        b = tmp_path / "b.gpx"
        b.write_text("<gpx></gpx>")
        with patch.object(window, "_auto_scan_gpx"), \
             patch.object(window, "_add_path_history"):
            window._on_dropped_paths([a, b])
        assert list(window._gps_selection.paths) == [a, b]
        assert window._gps_dir_edit.currentText() == f"\U0001F4C4 2 个文件"

    def test_dropped_images_merge_into_photo_selection(self, window, tmp_path):
        a = tmp_path / "1.jpg"
        a.write_bytes(b"\xff\xd8\xff\xe0")
        b = tmp_path / "2.png"
        b.write_bytes(b"\x89PNG")
        with patch.object(window, "_auto_scan_photos"), \
             patch.object(window, "_clear_results"):
            window._on_dropped_paths([a, b])
        assert list(window._photo_selection.paths) == [a, b]
        assert window._photo_dir_edit.currentText() == f"\U0001F4C4 2 个文件"

    def test_dropped_mixed_content_fills_both_selections(self, window, tmp_path):
        gpx = tmp_path / "track.gpx"
        gpx.write_text("<gpx></gpx>")
        d = tmp_path / "photos"
        d.mkdir()
        (d / "img.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        with patch.object(window, "_auto_scan_gpx"), \
             patch.object(window, "_auto_scan_photos"), \
             patch.object(window, "_clear_results"), \
             patch.object(window, "_add_path_history"):
            window._on_dropped_paths([gpx, d])
        assert list(window._gps_selection.paths) == [gpx]
        assert list(window._photo_selection.paths) == [d]

    def test_dropped_nothing_recognized_shows_message(self, window, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with patch("gps_photo_tracker.gui.main_window.QMessageBox.information") as msg:
            window._on_dropped_paths([empty])
        msg.assert_called_once()

    def test_window_drop_event_routes_to_handler(self, window, tmp_path):
        gpx = tmp_path / "track.gpx"
        gpx.write_text("<gpx></gpx>")
        with patch.object(window, "_auto_scan_gpx"), \
             patch.object(window, "_add_path_history"):
            window.dropEvent(_make_drop_event(_make_mime([str(gpx)])))
        assert list(window._gps_selection.paths) == [gpx]

    def test_drop_zone_signal_updates_selection(self, window, qtbot, tmp_path):
        gpx = tmp_path / "track.gpx"
        gpx.write_text("<gpx></gpx>")
        with patch.object(window, "_auto_scan_gpx"), \
             patch.object(window, "_add_path_history"):
            window._drop_zone.pathsDropped.emit([gpx])
        assert list(window._gps_selection.paths) == [gpx]

    def test_mixed_dir_dialog_routes_answer(self, window, tmp_path):
        """MainWindow._classify_drop consults _choose_mixed_dir for a
        directory holding both tracks and photos."""
        mixed = tmp_path / "mixed"
        mixed.mkdir()
        (mixed / "track.gpx").write_text("<gpx></gpx>")
        (mixed / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        with patch.object(window, "_choose_mixed_dir", return_value=MIXED_GPS) as chooser:
            tracks, photos = window._classify_drop([mixed])
        chooser.assert_called_once_with(mixed)
        assert tracks == [mixed]
        assert photos == []

    def test_drop_no_local_files_ignored(self, window):
        mime = QMimeData()
        mime.setUrls([QUrl("https://example.com")])
        event = _make_drop_event(mime)
        # Should silently return without error
        window.dropEvent(event)
