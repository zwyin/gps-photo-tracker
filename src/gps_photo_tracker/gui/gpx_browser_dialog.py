"""GPX track browser dialog."""

from datetime import datetime, timezone
from collections import defaultdict

from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class GPXBrowserDialog(QDialog):
    """Browse loaded GPX segments grouped by source file.

    Accepts either list[GPXSegment] or list[dict] (from Worker scan_done_signal).
    """

    def __init__(self, segments, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GPX 轨迹详情")
        self.setMinimumSize(700, 500)
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

        # Group by source file
        files = defaultdict(list)
        for row in rows:
            files[row["filename"]].append(row)

        # All segments table
        table = QTableWidget(len(rows), 5)
        table.setHorizontalHeaderLabels(["来源文件", "Track段", "点数", "开始时间", "结束时间"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSortingEnabled(True)

        for i, row in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(row["filename"]))
            table.setItem(i, 1, QTableWidgetItem(f"Segment {row['index'] + 1}"))
            table.setItem(i, 2, QTableWidgetItem(str(row["point_count"])))
            table.setItem(i, 3, QTableWidgetItem(self._fmt_time(row["start"])))
            table.setItem(i, 4, QTableWidgetItem(self._fmt_time(row["end"])))

        layout.addWidget(table)

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
        if rows:
            coverage_group = QGroupBox("时间覆盖总览")
            coverage_layout = QVBoxLayout(coverage_group)
            all_earliest = min(r["start"] for r in rows)
            all_latest = max(r["end"] for r in rows)
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
        total_points = sum(r["point_count"] for r in rows)
        summary = QLabel(f"共 {len(files)} 个文件, {len(rows)} 个轨迹段, {total_points} 个 GPS 点")
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

    @staticmethod
    def _fmt_date(ts: float) -> str:
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt.strftime("%m/%d")
        except (OSError, ValueError):
            return "—"
