"""Tests for SelectionListDialog."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from gps_photo_tracker.gui.selection_list_dialog import SelectionListDialog


@pytest.fixture
def app(qtbot):
    return QApplication.instance() or QApplication([])


@pytest.fixture
def paths():
    return [
        Path("/photos/IMG_001.jpg"),
        Path("/photos/IMG_002.jpg"),
        Path("/tracks/morning.gpx"),
]


@pytest.fixture
def dialog(app, qtbot, paths):
    d = SelectionListDialog(paths)
    qtbot.addWidget(d)
    return d


class TestSelectionListDialog:

    def test_lists_all_paths(self, dialog, paths):
        text = dialog._list.toPlainText()
        for p in paths:
            assert str(p) in text

    def test_count_label_shows_total(self, dialog, paths):
        assert str(len(paths)) in dialog._count_label.text()

    def test_window_title_default(self, dialog):
        assert dialog.windowTitle() == "已选清单"

    def test_custom_title(self, app, qtbot, paths):
        d = SelectionListDialog(paths, title="自定义标题")
        qtbot.addWidget(d)
        assert d.windowTitle() == "自定义标题"

    def test_text_edit_is_read_only(self, dialog):
        assert dialog._list.isReadOnly() is True

    def test_close_button_triggers_accept(self, dialog, qtbot):
        buttons = dialog.findChildren(QPushButton)
        close_btn = next(b for b in buttons if b.text() == "关闭")
        with qtbot.waitSignal(dialog.accepted, timeout=1000):
            close_btn.click()

    def test_empty_paths(self, app, qtbot):
        d = SelectionListDialog([])
        qtbot.addWidget(d)
        assert d._list.toPlainText() == ""
        assert "0" in d._count_label.text()
