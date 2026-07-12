"""Read-only dialog listing currently-selected input paths."""

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class SelectionListDialog(QDialog):
    """Show the currently selected file/directory paths in a read-only list.

    Opened from the main window's "N 个文件（点击查看）" summary label
    to let the user review what is currently queued for processing.
    """

    def __init__(
        self,
        paths: Iterable[Path],
        title: str = "已选清单",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 360)
        self._paths = list(paths)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._count_label = QLabel(f"共 {len(self._paths)} 项：")
        layout.addWidget(self._count_label)

        self._list = QPlainTextEdit()
        self._list.setReadOnly(True)
        self._list.setPlainText("\n".join(str(p) for p in self._paths))
        layout.addWidget(self._list)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
