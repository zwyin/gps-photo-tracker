"""Tests for drag-and-drop file support in MainWindow."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QMimeData

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


class TestDragEnterEvent:

    def test_accept_local_file(self, window):
        mime = _make_mime(["/tmp/test.gpx"])
        event = _make_drag_event(mime)
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
        mime = QMimeData()
        event = _make_drag_event(mime)
        window.dragEnterEvent(event)
        event.ignore.assert_called_once()


class TestDragMoveEvent:

    def test_accept_with_urls(self, window):
        mime = _make_mime(["/tmp/test.gpx"])
        event = MagicMock(spec=QDragMoveEvent)
        event.mimeData.return_value = mime
        event.setDropAction = MagicMock()
        event.accept = MagicMock()
        event.ignore = MagicMock()
        window.dragMoveEvent(event)
        event.accept.assert_called_once()

    def test_reject_without_urls(self, window):
        mime = QMimeData()
        event = MagicMock(spec=QDragMoveEvent)
        event.mimeData.return_value = mime
        event.setDropAction = MagicMock()
        event.accept = MagicMock()
        event.ignore = MagicMock()
        window.dragMoveEvent(event)
        event.ignore.assert_called_once()


class TestClassifyDrop:

    def test_single_gpx_file(self, window, tmp_path):
        gpx = tmp_path / "track.gpx"
        gpx.write_text("<gpx></gpx>")
        urls = [QUrl.fromLocalFile(str(gpx))]
        gps_dir, photo_dir = window._classify_drop(urls)
        assert gps_dir == tmp_path
        assert photo_dir is None

    def test_single_image_file(self, window, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0")
        urls = [QUrl.fromLocalFile(str(img))]
        gps_dir, photo_dir = window._classify_drop(urls)
        assert photo_dir == tmp_path
        assert gps_dir is None

    def test_track_directory(self, window, tmp_path):
        gpx = tmp_path / "track.gpx"
        gpx.write_text("<gpx></gpx>")
        urls = [QUrl.fromLocalFile(str(tmp_path))]
        gps_dir, photo_dir = window._classify_drop(urls)
        assert gps_dir == tmp_path
        assert photo_dir is None

    def test_image_directory(self, window, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0")
        urls = [QUrl.fromLocalFile(str(tmp_path))]
        gps_dir, photo_dir = window._classify_drop(urls)
        assert photo_dir == tmp_path
        assert gps_dir is None

    def test_empty_directory(self, window, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        urls = [QUrl.fromLocalFile(str(empty))]
        gps_dir, photo_dir = window._classify_drop(urls)
        assert gps_dir is None
        assert photo_dir is None

    def test_nonexistent_path(self, window):
        urls = [QUrl.fromLocalFile("/nonexistent/path/file.gpx")]
        gps_dir, photo_dir = window._classify_drop(urls)
        assert gps_dir is None
        assert photo_dir is None

    def test_multiple_files_gps_and_photo(self, window, tmp_path):
        gps_dir = tmp_path / "gps"
        gps_dir.mkdir()
        (gps_dir / "track.gpx").write_text("<gpx></gpx>")
        photo_dir = tmp_path / "photos"
        photo_dir.mkdir()
        (photo_dir / "img.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        urls = [
            QUrl.fromLocalFile(str(gps_dir / "track.gpx")),
            QUrl.fromLocalFile(str(photo_dir / "img.jpg")),
        ]
        result_gps, result_photo = window._classify_drop(urls)
        assert result_gps == gps_dir
        assert result_photo == photo_dir

    def test_mixed_directory_choose_gps(self, window, tmp_path):
        mixed = tmp_path / "mixed"
        mixed.mkdir()
        (mixed / "track.gpx").write_text("<gpx></gpx>")
        (mixed / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        urls = [QUrl.fromLocalFile(str(mixed))]
        with patch("gps_photo_tracker.gui.main_window.QMessageBox") as MockMsgBox:
            mock_msg = MagicMock()
            mock_msg.clickedButton.return_value = mock_msg  # GPS button
            MockMsgBox.return_value = mock_msg
            # addButton returns different objects; make gps_btn match clickedButton
            mock_msg.addButton.side_effect = [mock_msg, MagicMock(), MagicMock()]
            gps_dir, photo_dir = window._classify_drop(urls)
            assert gps_dir == mixed
            assert photo_dir is None

    def test_mixed_directory_choose_photo(self, window, tmp_path):
        mixed = tmp_path / "mixed"
        mixed.mkdir()
        (mixed / "track.gpx").write_text("<gpx></gpx>")
        (mixed / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        urls = [QUrl.fromLocalFile(str(mixed))]
        with patch("gps_photo_tracker.gui.main_window.QMessageBox") as MockMsgBox:
            mock_msg = MagicMock()
            photo_btn = MagicMock()
            mock_msg.addButton.side_effect = [MagicMock(), photo_btn, MagicMock()]
            mock_msg.clickedButton.return_value = photo_btn
            MockMsgBox.return_value = mock_msg
            gps_dir, photo_dir = window._classify_drop(urls)
            assert gps_dir is None
            assert photo_dir == mixed

    def test_mixed_directory_cancel(self, window, tmp_path):
        mixed = tmp_path / "mixed"
        mixed.mkdir()
        (mixed / "track.gpx").write_text("<gpx></gpx>")
        (mixed / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        urls = [QUrl.fromLocalFile(str(mixed))]
        with patch("gps_photo_tracker.gui.main_window.QMessageBox") as MockMsgBox:
            mock_msg = MagicMock()
            cancel_btn = MagicMock()
            mock_msg.addButton.side_effect = [MagicMock(), MagicMock(), cancel_btn]
            mock_msg.clickedButton.return_value = cancel_btn
            MockMsgBox.return_value = mock_msg
            gps_dir, photo_dir = window._classify_drop(urls)
            assert gps_dir is None
            assert photo_dir is None

    def test_kml_file_recognized(self, window, tmp_path):
        kml = tmp_path / "track.kml"
        kml.write_text("<kml></kml>")
        urls = [QUrl.fromLocalFile(str(kml))]
        gps_dir, _ = window._classify_drop(urls)
        assert gps_dir == tmp_path

    def test_tcx_file_recognized(self, window, tmp_path):
        tcx = tmp_path / "track.tcx"
        tcx.write_text("<TrainingCenterDatabase></TrainingCenterDatabase>")
        urls = [QUrl.fromLocalFile(str(tcx))]
        gps_dir, _ = window._classify_drop(urls)
        assert gps_dir == tmp_path

    def test_png_image_recognized(self, window, tmp_path):
        img = tmp_path / "photo.png"
        img.write_bytes(b"\x89PNG")
        urls = [QUrl.fromLocalFile(str(img))]
        _, photo_dir = window._classify_drop(urls)
        assert photo_dir == tmp_path

    def test_tiff_image_recognized(self, window, tmp_path):
        img = tmp_path / "photo.tiff"
        img.write_bytes(b"II")
        urls = [QUrl.fromLocalFile(str(img))]
        _, photo_dir = window._classify_drop(urls)
        assert photo_dir == tmp_path


class TestDropEvent:

    def test_drop_sets_gps_dir(self, window, tmp_path):
        gpx = tmp_path / "track.gpx"
        gpx.write_text("<gpx></gpx>")
        mime = _make_mime([str(gpx)])
        event = MagicMock()
        event.mimeData.return_value = mime
        with patch.object(window, "_auto_scan_gpx") as mock_scan, \
             patch.object(window, "_add_path_history"):
            window.dropEvent(event)
            mock_scan.assert_called_once()
            assert window._gps_dir_edit.currentText() == str(tmp_path)

    def test_drop_sets_photo_dir(self, window, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0")
        mime = _make_mime([str(img)])
        event = MagicMock()
        event.mimeData.return_value = mime
        with patch.object(window, "_auto_scan_photos") as mock_scan, \
             patch.object(window, "_add_path_history"):
            window.dropEvent(event)
            mock_scan.assert_called_once()
            assert window._photo_dir_edit.currentText() == str(tmp_path)

    def test_drop_unknown_shows_message(self, window, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        mime = _make_mime([str(empty)])
        event = MagicMock()
        event.mimeData.return_value = mime
        with patch("gps_photo_tracker.gui.main_window.QMessageBox.information") as mock_msg:
            window.dropEvent(event)
            mock_msg.assert_called_once()

    def test_drop_no_local_files(self, window):
        mime = QMimeData()
        mime.setUrls([QUrl("https://example.com")])
        event = MagicMock()
        event.mimeData.return_value = mime
        # Should silently return without error
        window.dropEvent(event)
