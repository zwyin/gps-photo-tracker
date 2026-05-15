"""GPS track point picker dialog for manual GPS assignment."""

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QDialogButtonBox,
)

from gps_photo_tracker.core.models import TrackPoint


class GPSPointPicker(QDialog):
    """Dialog to pick a GPS track point near a photo's capture time."""

    def __init__(self, points: list[TrackPoint], photo_timestamp: float, parent=None):
        super().__init__(parent)
        self._points = points
        self._photo_timestamp = photo_timestamp
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("选择 GPS 轨迹点")
        self.setMinimumSize(500, 350)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            f"拍摄时间: {self._format_time(self._photo_timestamp)}  |  "
            f"共 {len(self._points)} 个附近轨迹点"
        ))

        self._table = QTableWidget(len(self._points), 4)
        self._table.setHorizontalHeaderLabels(["时间", "纬度", "经度", "时间差"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        for row, pt in enumerate(self._points):
            self._table.setItem(row, 0, QTableWidgetItem(self._format_time(pt.timestamp)))
            self._table.setItem(row, 1, QTableWidgetItem(f"{pt.latitude:.6f}"))
            self._table.setItem(row, 2, QTableWidgetItem(f"{pt.longitude:.6f}"))
            diff = abs(pt.timestamp - self._photo_timestamp)
            mins, secs = divmod(int(diff), 60)
            self._table.setItem(row, 3, QTableWidgetItem(
                f"{mins}m{secs:02d}s" if mins > 0 else f"{secs}s"
            ))

        self._table.selectRow(0)
        layout.addWidget(self._table)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._confirm_btn = btn_box.button(QDialogButtonBox.StandardButton.Ok)
        self._confirm_btn.setText("确认选择")
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self._confirm_btn.setEnabled(len(self._points) > 0)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_selected_point(self) -> TrackPoint | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._points[rows[0].row()]

    @staticmethod
    def _format_time(ts: float) -> str:
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")
        except (OSError, ValueError):
            return str(ts)
