"""Log viewer dialog for browsing and searching application logs."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

_LOG_FILES = {
    "操作记录": "operations.log",
    "匹配结果": "matches.log",
    "写入记录": "writes.log",
    "调试日志": "debug.log",
    "错误日志": "errors.log",
}


class LogViewerDialog(QDialog):
    """Browse and search application log files."""

    def __init__(self, log_dir: Path, parent=None):
        super().__init__(parent)
        self._log_dir = log_dir
        self.setWindowTitle("日志查看器")
        self.setMinimumSize(750, 500)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Toolbar: file selector + search + export
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("日志文件:"))
        self._file_cb = QComboBox()
        self._file_cb.addItems(_LOG_FILES.keys())
        self._file_cb.currentIndexChanged.connect(self._load_log)
        toolbar.addWidget(self._file_cb, stretch=1)

        toolbar.addWidget(QLabel("搜索:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("输入关键词过滤...")
        self._search_edit.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self._search_edit, stretch=1)

        export_btn = QPushButton("导出")
        export_btn.clicked.connect(self._export)
        toolbar.addWidget(export_btn)
        layout.addLayout(toolbar)

        # Log content
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(5000)
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self._text)

        # Bottom: summary + refresh
        bottom = QHBoxLayout()
        self._summary = QLabel("")
        bottom.addWidget(self._summary)
        bottom.addStretch()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._load_log)
        bottom.addWidget(refresh_btn)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

        # Initial load
        self._raw_lines: list[str] = []
        self._load_log()

    def _load_log(self):
        filename = _LOG_FILES.get(self._file_cb.currentText(), "")
        path = self._log_dir / filename
        self._raw_lines = []
        if path.exists():
            try:
                self._raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                self._raw_lines = [f"(无法读取: {path})"]
        else:
            self._raw_lines = [f"(日志文件不存在: {path})"]
        self._apply_filter()

    def _apply_filter(self):
        text = self._search_edit.text().lower()
        if text:
            lines = [l for l in self._raw_lines if text in l.lower()]
        else:
            lines = self._raw_lines
        self._text.setPlainText("\n".join(lines))
        self._summary.setText(f"共 {len(self._raw_lines)} 行, 筛选后 {len(lines)} 行")
        self._text.moveCursor(QTextCursor.MoveOperation.End)

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", f"{self._file_cb.currentText()}.txt", "文本文件 (*.txt)"
        )
        if path:
            Path(path).write_text(self._text.toPlainText(), encoding="utf-8")
