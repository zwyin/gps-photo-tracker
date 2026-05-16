"""Review dialog for failed GPS matches — list-driven layout."""

from gps_photo_tracker.gui.settings_dialog import format_timestamp

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QComboBox, QHeaderView, QGroupBox, QCheckBox,
    QSplitter, QMessageBox, QDialogButtonBox, QWidget, QInputDialog,
)

from gps_photo_tracker.core.models import (
    ReviewAction, ReviewDecision, ReviewState, TrackPoint,
)
from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker

_REASON_LABELS = {
    "no_gps_coverage": "无 GPS 覆盖",
    "time_diff": "时间差过大",
    "gps_distance": "距离过大",
    "tail_isolated": "孤立照片",
    "no_track_points": "无轨迹点",
}


class ReviewDialog(QDialog):
    """Review failed GPS matches and assign manual GPS or skip."""

    def __init__(self, state: ReviewState, parent=None):
        super().__init__(parent)
        self._state = state
        self._action_combos: list[QComboBox] = []
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle(f"审核失败项 — 共 {len(self._state.failed_results)} 张")
        self.setMinimumSize(900, 500)
        main_layout = QVBoxLayout(self)

        # Top bar
        top_bar = QHBoxLayout()
        self._select_all_cb = QCheckBox("全选")
        self._select_all_cb.setChecked(True)
        self._select_all_cb.stateChanged.connect(self._on_select_all)
        top_bar.addWidget(self._select_all_cb)
        top_bar.addStretch()
        skip_all_btn = QPushButton("全部跳过")
        skip_all_btn.clicked.connect(self._skip_all)
        top_bar.addWidget(skip_all_btn)
        main_layout.addLayout(top_bar)

        # Splitter: table | detail panel
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: table
        self._table = QTableWidget(len(self._state.failed_results), 5)
        self._table.setHorizontalHeaderLabels(["☑", "文件名", "拍摄时间", "失败原因", "操作"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        for row, result in enumerate(self._state.failed_results):
            check_item = QTableWidgetItem()
            check_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            check_item.setCheckState(Qt.CheckState.Checked)
            check_item.setData(Qt.ItemDataRole.UserRole, row)
            self._table.setItem(row, 0, check_item)

            fn_item = QTableWidgetItem(result.photo.filename)
            fn_item.setData(Qt.ItemDataRole.UserRole, row)
            self._table.setItem(row, 1, fn_item)
            self._table.setItem(row, 2, QTableWidgetItem(self._format_time(result.photo.timestamp)))
            reason = result.reject_reason or "unknown"
            self._table.setItem(row, 3, QTableWidgetItem(
                _REASON_LABELS.get(reason, reason)
            ))

            combo = QComboBox()
            combo.addItems(["待定", "跳过", "手动选 GPS", "输入坐标"])
            combo.currentIndexChanged.connect(lambda idx, r=row: self._on_action_changed(r, idx))
            self._table.setCellWidget(row, 4, combo)
            self._action_combos.append(combo)

        self._table.setSortingEnabled(True)
        self._table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        self._reassign_combo_widgets()

        self._table.horizontalHeader().sortIndicatorChanged.connect(
            lambda col, order: self._reassign_combo_widgets()
        )
        self._table.currentCellChanged.connect(
            lambda cr, cc, pr, pc: self._on_row_clicked(cr, cc)
        )

        splitter.addWidget(self._table)

        # Right: detail panel
        detail_panel = QVBoxLayout()
        self._preview_label = QLabel("点击左侧照片查看预览")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumSize(180, 140)
        detail_panel.addWidget(self._preview_label)

        self._info_label = QLabel("")
        self._info_label.setWordWrap(True)
        detail_panel.addWidget(self._info_label)

        batch_group = QGroupBox("批量操作（已选照片）")
        batch_layout = QHBoxLayout(batch_group)
        batch_skip_btn = QPushButton("跳过")
        batch_skip_btn.clicked.connect(lambda: self._batch_action(1))
        batch_layout.addWidget(batch_skip_btn)
        batch_gps_btn = QPushButton("手动选 GPS")
        batch_gps_btn.clicked.connect(lambda: self._batch_action(2))
        batch_layout.addWidget(batch_gps_btn)
        batch_coord_btn = QPushButton("输入坐标")
        batch_coord_btn.clicked.connect(lambda: self._batch_action(3))
        batch_layout.addWidget(batch_coord_btn)
        detail_panel.addWidget(batch_group)
        detail_panel.addStretch()

        right_widget = QWidget()
        right_widget.setLayout(detail_panel)
        splitter.addWidget(right_widget)
        splitter.setSizes([600, 300])
        main_layout.addWidget(splitter)

        # Bottom bar
        bottom_bar = QHBoxLayout()
        self._progress_label = QLabel(f"已处理 0/{len(self._state.failed_results)}")
        bottom_bar.addWidget(self._progress_label)
        bottom_bar.addStretch()
        confirm_btn = QPushButton("确认")
        confirm_btn.clicked.connect(self._confirm)
        bottom_bar.addWidget(confirm_btn)
        main_layout.addLayout(bottom_bar)

    def get_state(self) -> ReviewState:
        return self._state

    def closeEvent(self, event):
        """Treat X button as 'Skip All' per spec."""
        self._skip_all()
        event.accept()

    def _skip_all(self):
        for result in self._state.failed_results:
            path_str = str(result.photo.path)
            self._state.decisions[path_str] = ReviewDecision(
                photo_path=path_str, action=ReviewAction.SKIP,
            )
        self.accept()

    def _confirm(self):
        for row, result in enumerate(self._state.failed_results):
            path_str = str(result.photo.path)
            if path_str in self._state.decisions:
                continue
            self._state.decisions[path_str] = ReviewDecision(
                photo_path=path_str, action=ReviewAction.SKIP,
            )
        self.accept()

    def _on_row_clicked(self, row, col):
        if row < 0 or row >= self._table.rowCount():
            return
        data_row = self._get_data_row(row)
        result = self._state.failed_results[data_row]
        reason = result.reject_reason or "未知"
        info = f"<b>文件:</b> {result.photo.filename}<br>"
        info += f"<b>拍摄时间:</b> {self._format_time(result.photo.timestamp)}<br>"
        info += f"<b>失败原因:</b> {_REASON_LABELS.get(reason, reason)}<br>"
        if result.time_diff is not None:
            info += f"<b>时间差:</b> {result.time_diff:.0f}s"
        self._info_label.setText(info)
        try:
            pixmap = QPixmap(str(result.photo.path))
            if not pixmap.isNull():
                self._preview_label.setPixmap(
                    pixmap.scaled(180, 140, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
                )
        except Exception:
            self._preview_label.setText("无法加载预览")

    def _on_action_changed(self, row: int, combo_idx: int):
        result = self._state.failed_results[row]
        path_str = str(result.photo.path)
        if combo_idx == 1:
            self._state.decisions[path_str] = ReviewDecision(
                photo_path=path_str, action=ReviewAction.SKIP,
            )
        elif combo_idx == 2:
            self._open_gps_picker(row)
        elif combo_idx == 3:
            self._open_coord_input(row)
        self._update_progress()

    def _open_gps_picker(self, row: int):
        result = self._state.failed_results[row]
        nearby = self._get_nearby_points(result.photo.timestamp or 0, window=1800)
        if not nearby:
            QMessageBox.information(self, "无轨迹点", "拍摄时间附近 30 分钟内无 GPS 轨迹点")
            self._action_combos[row].setCurrentIndex(0)
            return
        picker = GPSPointPicker(nearby, result.photo.timestamp or 0, self)
        if picker.exec() == QDialog.DialogCode.Accepted:
            pt = picker.get_selected_point()
            if pt:
                path_str = str(result.photo.path)
                self._state.decisions[path_str] = ReviewDecision(
                    photo_path=path_str,
                    action=ReviewAction.MANUAL_GPS,
                    selected_point=pt,
                )
        else:
            self._action_combos[row].setCurrentIndex(0)

    def _open_coord_input(self, row: int):
        result = self._state.failed_results[row]
        lat_str, ok1 = QInputDialog.getText(self, "输入纬度", "纬度 (-90 ~ 90):")
        if not ok1:
            self._action_combos[row].setCurrentIndex(0)
            return
        lon_str, ok2 = QInputDialog.getText(self, "输入经度", "经度 (-180 ~ 180):")
        if not ok2:
            self._action_combos[row].setCurrentIndex(0)
            return
        try:
            lat = float(lat_str)
            lon = float(lon_str)
        except ValueError:
            QMessageBox.warning(self, "格式错误", "请输入有效的数字")
            self._action_combos[row].setCurrentIndex(0)
            return
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            QMessageBox.warning(self, "范围错误", "纬度 -90~90，经度 -180~180")
            self._action_combos[row].setCurrentIndex(0)
            return
        path_str = str(result.photo.path)
        self._state.decisions[path_str] = ReviewDecision(
            photo_path=path_str,
            action=ReviewAction.MANUAL_COORD,
            manual_lat=lat,
            manual_lon=lon,
        )

    def _batch_action(self, combo_idx: int):
        for row in range(self._table.rowCount()):
            check_item = self._table.item(row, 0)
            if check_item and check_item.checkState() == Qt.CheckState.Checked:
                data_row = self._get_data_row(row)
                self._action_combos[data_row].setCurrentIndex(combo_idx)
        self._update_progress()

    def _on_select_all(self, state):
        checked = state == Qt.CheckState.Checked.value
        for row in range(self._table.rowCount()):
            check_item = self._table.item(row, 0)
            if check_item:
                check_item.setCheckState(
                    Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                )

    def _get_nearby_points(self, photo_ts: float, window: float = 1800) -> list[TrackPoint]:
        points = []
        for seg in self._state.gps_segments:
            for pt in seg.points:
                if abs(pt.timestamp - photo_ts) <= window:
                    points.append(pt)
        points.sort(key=lambda p: abs(p.timestamp - photo_ts))
        return points

    def _update_progress(self):
        total = len(self._state.failed_results)
        decided = len(self._state.decisions)
        self._progress_label.setText(f"已处理 {decided}/{total}")

    def _get_data_row(self, visual_row: int) -> int:
        item = self._table.item(visual_row, 1)
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        return data if data is not None else visual_row

    def _reassign_combo_widgets(self):
        for visual_row in range(self._table.rowCount()):
            data_row = self._get_data_row(visual_row)
            self._table.setCellWidget(visual_row, 4, self._action_combos[data_row])

    @staticmethod
    def _format_time(ts: float | None) -> str:
        if ts is None:
            return "—"
        return format_timestamp(ts)
