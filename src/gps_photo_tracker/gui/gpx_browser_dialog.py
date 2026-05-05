"""GPX track browser dialog with file selection checkboxes."""

from datetime import datetime, timezone
from collections import defaultdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class GPXBrowserDialog(QDialog):
    """Browse loaded GPX segments grouped by source file.

    Accepts either list[GPXSegment] or list[dict] (from Worker scan_done_signal).
    """

    def __init__(self, segments, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GPX 轨迹详情")
        self.setMinimumSize(700, 500)
        self._rows = []
        self._build_ui(segments)

    def _build_ui(self, segments):
        layout = QVBoxLayout(self)

        # Normalize to list of dicts
        for i, seg in enumerate(segments):
            if isinstance(seg, dict):
                self._rows.append({
                    "filename": seg.get("filename", "—"),
                    "index": i,
                    "point_count": seg.get("point_count", 0),
                    "start": seg.get("start", 0),
                    "end": seg.get("end", 0),
                })
            else:
                self._rows.append({
                    "filename": seg.filename,
                    "index": i,
                    "point_count": len(seg.points),
                    "start": seg.start,
                    "end": seg.end,
                })

        # Group by source file
        files = defaultdict(list)
        for row in self._rows:
            files[row["filename"]].append(row)

        # All segments table with checkbox column
        self._table = QTableWidget(len(self._rows), 6)
        self._table.setHorizontalHeaderLabels(["选择", "来源文件", "Track段", "点数", "开始时间", "结束时间"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)
        self._table.selectionModel().selectionChanged.connect(self._on_selection)

        for i, row in enumerate(self._rows):
            check_widget = QWidget()
            check_layout = QHBoxLayout(check_widget)
            check_layout.setContentsMargins(0, 0, 0, 0)
            check_layout.setAlignment(Qt.AlignCenter)
            cb = QCheckBox()
            cb.setChecked(True)
            check_layout.addWidget(cb)
            self._table.setCellWidget(i, 0, check_widget)
            self._table.setItem(i, 1, QTableWidgetItem(row["filename"]))
            self._table.setItem(i, 2, QTableWidgetItem(f"Segment {row['index'] + 1}"))
            self._table.setItem(i, 3, QTableWidgetItem(str(row["point_count"])))
            self._table.setItem(i, 4, QTableWidgetItem(self._fmt_time(row["start"])))
            self._table.setItem(i, 5, QTableWidgetItem(self._fmt_time(row["end"])))

        layout.addWidget(self._table)

        # File detail panel (updates on selection)
        self._detail_group = QGroupBox("选中文件详情")
        self._detail_layout = QVBoxLayout(self._detail_group)
        self._detail_label = QLabel("点击表格中的行查看文件详情")
        self._detail_label.setWordWrap(True)
        self._detail_layout.addWidget(self._detail_label)
        layout.addWidget(self._detail_group)

        # File summary group
        file_group = QGroupBox("文件统计")
        file_layout = QVBoxLayout(file_group)
        for filename, segs in sorted(files.items()):
            total_pts = sum(s["point_count"] for s in segs)
            earliest = min(s["start"] for s in segs)
            latest = max(s["end"] for s in segs)
            file_layout.addWidget(QLabel(
                f"{filename}: {len(segs)} 段, {total_pts} 点, "
                f"{self._fmt_time(earliest)} ~ {self._fmt_time(latest)}"
            ))
        layout.addWidget(file_group)

        # Time coverage overview
        if self._rows:
            coverage_group = QGroupBox("时间覆盖总览")
            coverage_layout = QVBoxLayout(coverage_group)
            all_earliest = min(r["start"] for r in self._rows)
            all_latest = max(r["end"] for r in self._rows)
            total_span = all_latest - all_earliest if all_latest > all_earliest else 1

            for filename, segs in sorted(files.items()):
                earliest = min(s["start"] for s in segs)
                latest = max(s["end"] for s in segs)
                bar_start = int((earliest - all_earliest) / total_span * 40)
                bar_end = int((latest - all_earliest) / total_span * 40)
                bar_len = max(bar_end - bar_start, 1)
                bar = "█" * bar_len + "░" * (40 - bar_len - bar_start)
                coverage_layout.addWidget(QLabel(
                    f"{self._fmt_date(earliest)} {bar} "
                    f"{self._fmt_time(earliest)}-{self._fmt_time(latest)}"
                ))
            layout.addWidget(coverage_group)

        # Summary
        total_points = sum(r["point_count"] for r in self._rows)
        summary = QLabel(f"共 {len(files)} 个文件, {len(self._rows)} 个轨迹段, {total_points} 个 GPS 点")
        summary.setStyleSheet("padding: 6px; background: #f0f0f0; border-radius: 4px;")
        layout.addWidget(summary)

        # Buttons
        btn_layout = QHBoxLayout()
        select_all_btn = QPushButton("全选")
        deselect_btn = QPushButton("取消全选")
        select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        deselect_btn.clicked.connect(lambda: self._set_all_checked(False))
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(select_all_btn)
        btn_layout.addWidget(deselect_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _set_all_checked(self, checked: bool):
        for i in range(self._table.rowCount()):
            widget = self._table.cellWidget(i, 0)
            if widget:
                cb = widget.findChild(QCheckBox)
                if cb:
                    cb.setChecked(checked)

    def _on_selection(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            self._detail_label.setText("点击表格中的行查看文件详情")
            return
        row = rows[0].row()
        if 0 <= row < len(self._rows):
            selected = self._rows[row]
            filename = selected["filename"]
            # Collect all segments for this file
            file_segs = [r for r in self._rows if r["filename"] == filename]
            total_pts = sum(s["point_count"] for s in file_segs)
            earliest = min(s["start"] for s in file_segs)
            latest = max(s["end"] for s in file_segs)
            duration_h = (latest - earliest) / 3600 if latest > earliest else 0

            lines = [
                f"文件: {filename}",
                f"段数: {len(file_segs)}  总点数: {total_pts}",
                f"时间: {self._fmt_time(earliest)} ~ {self._fmt_time(latest)}  (跨度 {duration_h:.1f} 小时)",
            ]
            for s in file_segs:
                lines.append(
                    f"  Segment {s['index'] + 1}: {s['point_count']} 点, "
                    f"{self._fmt_time(s['start'])} - {self._fmt_time(s['end'])}"
                )
            self._detail_label.setText("\n".join(lines))

    def get_excluded_filenames(self) -> set[str]:
        """Return set of filenames whose rows are unchecked."""
        excluded = set()
        for i in range(self._table.rowCount()):
            widget = self._table.cellWidget(i, 0)
            if widget:
                cb = widget.findChild(QCheckBox)
                filename = self._table.item(i, 1).text()
                if cb and not cb.isChecked():
                    excluded.add(filename)
        return excluded

    @staticmethod
    def _fmt_time(ts: float) -> str:
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            return "—"

    @staticmethod
    def _fmt_date(ts: float) -> str:
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt.strftime("%m/%d")
        except (OSError, ValueError):
            return "—"
