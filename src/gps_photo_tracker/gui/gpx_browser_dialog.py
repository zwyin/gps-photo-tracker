"""GPX track browser dialog."""

from datetime import datetime, timezone

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class GPXBrowserDialog(QDialog):
    """Browse loaded GPX segments with details.

    Accepts either list[GPXSegment] or list[dict] (from Worker scan_done_signal).
    """

    def __init__(self, segments, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GPX 轨迹详情")
        self.setMinimumSize(600, 400)
        self._build_ui(segments)

    def _build_ui(self, segments):
        layout = QVBoxLayout(self)

        # Normalize to list of dicts
        rows = []
        for i, seg in enumerate(segments):
            if isinstance(seg, dict):
                rows.append({
                    "filename": seg.get("filename", "—"),
                    "index": i,
                    "point_count": seg.get("point_count", 0),
                    "start": seg.get("start", 0),
                    "end": seg.get("end", 0),
                })
            else:
                rows.append({
                    "filename": seg.filename,
                    "index": i,
                    "point_count": len(seg.points),
                    "start": seg.start,
                    "end": seg.end,
                })

        # Segment table
        table = QTableWidget(len(rows), 5)
        table.setHorizontalHeaderLabels(["来源文件", "Track段", "点数", "开始时间", "结束时间"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        for i, row in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(row["filename"]))
            table.setItem(i, 1, QTableWidgetItem(f"Segment {row['index'] + 1}"))
            table.setItem(i, 2, QTableWidgetItem(str(row["point_count"])))
            table.setItem(i, 3, QTableWidgetItem(self._fmt_time(row["start"])))
            table.setItem(i, 4, QTableWidgetItem(self._fmt_time(row["end"])))

        layout.addWidget(table)

        # Summary
        total_points = sum(r["point_count"] for r in rows)
        summary = QLabel(f"共 {len(rows)} 个轨迹段, {total_points} 个 GPS 点")
        summary.setStyleSheet("padding: 6px; background: #f0f0f0; border-radius: 4px;")
        layout.addWidget(summary)

        # Close button
        btn_layout = QHBoxLayout()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    @staticmethod
    def _fmt_time(ts: float) -> str:
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            return "—"
