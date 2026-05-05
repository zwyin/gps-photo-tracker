"""Main window for GPS Photo Tracker."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QRadioButton,
    QButtonGroup,
    QProgressBar,
    QSplitter,
)

from gps_photo_tracker.core.models import MatcherConfig, ProcessMode, ProcessOptions
from gps_photo_tracker.gui.detail_dialog import DetailDialog
from gps_photo_tracker.gui.gpx_browser_dialog import GPXBrowserDialog
from gps_photo_tracker.gui.settings_dialog import SettingsDialog, load_settings
from gps_photo_tracker.gui.worker import Worker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GPS Photo Tracker")
        self.setMinimumSize(1000, 600)

        self._worker: Worker | None = None
        self._result_details: list[dict] = []
        self._cached_segments = []

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # Left panel
        left = self._build_left_panel()
        splitter.addWidget(left)

        # Right panel
        right = self._build_right_panel()
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self.statusBar().showMessage("就绪")

        # Menu bar
        menu = self.menuBar()
        file_menu = menu.addMenu("文件")
        settings_action = file_menu.addAction("设置")
        settings_action.triggered.connect(self._open_settings)

        # Load saved settings
        self._apply_saved_settings()

    # ── Left panel ──────────────────────────────────────────

    def _build_left_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # File selection
        layout.addWidget(self._build_file_group())
        # Parameters
        layout.addWidget(self._build_params_group())
        # Process mode
        layout.addWidget(self._build_mode_group())
        # Buttons
        layout.addWidget(self._build_buttons())
        # Progress
        layout.addWidget(self._build_progress_group())

        layout.addStretch()
        return widget

    def _build_file_group(self) -> QGroupBox:
        group = QGroupBox("文件选择")
        layout = QVBoxLayout(group)

        # GPS directory
        row1 = QHBoxLayout()
        self._gps_dir_edit = QLineEdit()
        self._gps_dir_edit.setPlaceholderText("GPS 轨迹目录...")
        btn_gps = QPushButton("浏览")
        btn_gps.clicked.connect(self._browse_gps_dir)
        row1.addWidget(QLabel("GPS:"))
        row1.addWidget(self._gps_dir_edit)
        row1.addWidget(btn_gps)
        layout.addLayout(row1)

        # Photo directory
        row2 = QHBoxLayout()
        self._photo_dir_edit = QLineEdit()
        self._photo_dir_edit.setPlaceholderText("照片目录...")
        btn_photo = QPushButton("浏览")
        btn_photo.clicked.connect(self._browse_photo_dir)
        row2.addWidget(QLabel("照片:"))
        row2.addWidget(self._photo_dir_edit)
        row2.addWidget(btn_photo)
        layout.addLayout(row2)

        # Output directory
        row3 = QHBoxLayout()
        self._output_dir_edit = QLineEdit()
        self._output_dir_edit.setPlaceholderText("输出目录（拷贝模式）...")
        btn_output = QPushButton("浏览")
        btn_output.clicked.connect(self._browse_output_dir)
        row3.addWidget(QLabel("输出:"))
        row3.addWidget(self._output_dir_edit)
        row3.addWidget(btn_output)
        layout.addLayout(row3)

        # Scan summary (clickable to browse GPX)
        self._scan_summary = QLabel("GPS: — | 照片: —")
        self._scan_summary.setStyleSheet(
            "padding: 4px; background: #e8e8e8; border-radius: 3px; cursor: pointer;"
        )
        self._scan_summary.mousePressEvent = lambda e: self._open_gpx_browser()
        layout.addWidget(self._scan_summary)

        return group

    def _build_params_group(self) -> QGroupBox:
        group = QGroupBox("参数配置")
        layout = QVBoxLayout(group)

        # Isolated window
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("孤立窗口:"))
        self._isolated_spin = QSpinBox()
        self._isolated_spin.setRange(30, 7200)
        self._isolated_spin.setValue(300)
        self._isolated_spin.setSuffix(" 秒")
        row1.addWidget(self._isolated_spin)
        layout.addLayout(row1)

        # Middle time window
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("中间窗口:"))
        self._middle_spin = QSpinBox()
        self._middle_spin.setRange(60, 14400)
        self._middle_spin.setValue(3600)
        self._middle_spin.setSuffix(" 秒")
        row2.addWidget(self._middle_spin)
        layout.addLayout(row2)

        # Context window
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("上下文窗口:"))
        self._context_spin = QSpinBox()
        self._context_spin.setRange(30, 3600)
        self._context_spin.setValue(300)
        self._context_spin.setSuffix(" 秒")
        row3.addWidget(self._context_spin)
        layout.addLayout(row3)

        # Max distance
        row4 = QHBoxLayout()
        row4.addWidget(QLabel("距离阈值:"))
        self._distance_spin = QSpinBox()
        self._distance_spin.setRange(50, 5000)
        self._distance_spin.setValue(200)
        self._distance_spin.setSuffix(" 米")
        row4.addWidget(self._distance_spin)
        layout.addLayout(row4)

        # Checkboxes
        self._match_tail_cb = QCheckBox("匹配首尾孤立照片")
        self._match_tail_cb.setChecked(True)
        layout.addWidget(self._match_tail_cb)

        self._overwrite_gps_cb = QCheckBox("覆盖已有 GPS")
        self._overwrite_gps_cb.setChecked(False)
        layout.addWidget(self._overwrite_gps_cb)

        # Time offset
        row5 = QHBoxLayout()
        row5.addWidget(QLabel("时间偏移:"))
        self._offset_spin = QSpinBox()
        self._offset_spin.setRange(-3600, 3600)
        self._offset_spin.setValue(0)
        self._offset_spin.setSuffix(" 秒")
        row5.addWidget(self._offset_spin)
        layout.addLayout(row5)

        return group

    def _build_mode_group(self) -> QGroupBox:
        group = QGroupBox("处理模式")
        layout = QHBoxLayout(group)

        self._mode_group = QButtonGroup(self)
        self._preview_rb = QRadioButton("预览")
        self._copy_rb = QRadioButton("拷贝")
        self._overwrite_rb = QRadioButton("覆盖")
        self._preview_rb.setChecked(True)

        self._mode_group.addButton(self._preview_rb, 0)
        self._mode_group.addButton(self._copy_rb, 1)
        self._mode_group.addButton(self._overwrite_rb, 2)

        layout.addWidget(self._preview_rb)
        layout.addWidget(self._copy_rb)
        layout.addWidget(self._overwrite_rb)
        return group

    def _build_buttons(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self._start_btn = QPushButton("开始处理")
        self._start_btn.clicked.connect(self._on_start)
        layout.addWidget(self._start_btn)

        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self._cancel_btn)

        return widget

    def _build_progress_group(self) -> QGroupBox:
        group = QGroupBox("进度")
        layout = QVBoxLayout(group)

        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(0)
        layout.addWidget(self._progress_bar)

        self._progress_label = QLabel("就绪")
        layout.addWidget(self._progress_label)

        self._elapsed_label = QLabel("")
        layout.addWidget(self._elapsed_label)

        return group

    # ── Right panel ─────────────────────────────────────────

    def _build_right_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Stats card
        self._stats_label = QLabel("匹配结果将在此显示")
        self._stats_label.setStyleSheet("padding: 8px; background: #f0f0f0; border-radius: 4px;")
        layout.addWidget(self._stats_label)

        # Results table
        self._results_table = QTableWidget(0, 5)
        self._results_table.setHorizontalHeaderLabels(["文件名", "GPS(前)", "GPS(后)", "方式", "状态"])
        self._results_table.horizontalHeader().setStretchLastSection(True)
        self._results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._results_table.doubleClicked.connect(self._on_table_double_click)
        layout.addWidget(self._results_table)

        return widget

    # ── Actions ─────────────────────────────────────────────

    def _browse_gps_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择 GPS 轨迹目录")
        if path:
            self._gps_dir_edit.setText(path)

    def _browse_photo_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择照片目录")
        if path:
            self._photo_dir_edit.setText(path)

    def _browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self._output_dir_edit.setText(path)

    def _get_matcher_config(self) -> MatcherConfig:
        return MatcherConfig(
            isolated_window=self._isolated_spin.value(),
            middle_time_window=self._middle_spin.value(),
            context_window=self._context_spin.value(),
            max_gps_distance=self._distance_spin.value(),
            match_tail=self._match_tail_cb.isChecked(),
            time_offset=self._offset_spin.value(),
        )

    def _get_process_options(self) -> ProcessOptions:
        mode_id = self._mode_group.checkedId()
        mode = [ProcessMode.PREVIEW, ProcessMode.COPY, ProcessMode.OVERWRITE][mode_id]
        output_dir = Path(self._output_dir_edit.text()) if self._output_dir_edit.text() else None
        return ProcessOptions(
            mode=mode,
            output_dir=output_dir,
            overwrite_gps=self._overwrite_gps_cb.isChecked(),
        )

    def _on_start(self):
        gps_dir = self._gps_dir_edit.text()
        photo_dir = self._photo_dir_edit.text()
        if not gps_dir or not photo_dir:
            QMessageBox.warning(self, "提示", "请先选择 GPS 轨迹目录和照片目录")
            return

        mode_id = self._mode_group.checkedId()
        if mode_id == 1 and not self._output_dir_edit.text():
            QMessageBox.warning(self, "提示", "拷贝模式需要指定输出目录")
            return

        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._progress_bar.setValue(0)
        self._progress_label.setText("扫描中...")
        self._results_table.setRowCount(0)
        self._result_details.clear()

        config = self._get_matcher_config()
        options = self._get_process_options()

        self._worker = Worker(
            gps_dir=Path(gps_dir),
            photo_dir=Path(photo_dir),
            config=config,
            options=options,
        )
        self._worker.progress_signal.connect(self._on_progress)
        self._worker.photo_signal.connect(self._on_photo_processed)
        self._worker.done_signal.connect(self._on_done)
        self._worker.scan_done_signal.connect(self._on_scan_done)
        self._worker.start()

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()
            self._progress_label.setText("正在取消...")

    def _on_progress(self, phase: str, current: int, total: int, filename: str, elapsed: float):
        if total > 0:
            self._progress_bar.setMaximum(total)
            self._progress_bar.setValue(current)
        self._progress_label.setText(f"当前: {filename}")
        if elapsed > 0:
            self._elapsed_label.setText(f"已用: {elapsed:.0f}s")

    def _on_photo_processed(self, result_dict: dict):
        row = self._results_table.rowCount()
        self._results_table.insertRow(row)

        filename = result_dict.get("filename", "")
        self._results_table.setItem(row, 0, QTableWidgetItem(filename))

        # GPS before — check if photo had existing GPS
        has_existing = result_dict.get("has_gps", False)
        self._results_table.setItem(row, 1, QTableWidgetItem("有" if has_existing else "无"))

        # GPS after
        lat = result_dict.get("latitude")
        lon = result_dict.get("longitude")
        if lat is not None and lon is not None:
            gps_text = f"{lat:.4f}, {lon:.4f}"
        else:
            gps_text = "—"
        self._results_table.setItem(row, 2, QTableWidgetItem(gps_text))

        # Method
        method = result_dict.get("method", "")
        method_text = {"interpolated": "插值", "nearest": "就近"}.get(method, "")
        self._results_table.setItem(row, 3, QTableWidgetItem(method_text))

        # Status
        success = result_dict.get("success", False)
        if success:
            status = "成功"
        else:
            reason = result_dict.get("reject_reason", "失败")
            status = {"no_gps_coverage": "无GPS覆盖", "time_diff": "时差过大",
                      "gps_distance": "距离过大", "tail_isolated": "孤立",
                      "no_track_points": "无轨迹点"}.get(reason, reason)
        self._results_table.setItem(row, 4, QTableWidgetItem(status))

        self._results_table.scrollToBottom()
        self._result_details.append(result_dict)

    def _on_done(self, result_dict: dict):
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)

        total = result_dict.get("total", 0)
        matched = result_dict.get("matched", 0)
        failed = result_dict.get("failed", 0)
        skipped = result_dict.get("skipped", 0)
        rate = result_dict.get("success_rate", 0)

        self._stats_label.setText(
            f"总数: {total} | 成功: {matched} | 跳过: {skipped} | 失败: {failed} | 成功率: {rate:.1%}"
        )
        self._progress_label.setText("完成")
        self.statusBar().showMessage(f"处理完成: {matched}/{total} 成功")

    def _on_scan_done(self, segments: list[dict]):
        self._cached_segments = segments
        gpx_count = len(segments)
        total_pts = sum(s.get("point_count", 0) for s in segments)
        self._scan_summary.setText(f"GPS: {gpx_count} 段, {total_pts} 点 (点击查看)")

    def _on_table_double_click(self, index):
        row = index.row()
        if 0 <= row < len(self._result_details):
            dialog = DetailDialog(self._result_details[row], self)
            dialog.exec()

    def _open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            self._apply_saved_settings()

    def _apply_saved_settings(self):
        s = load_settings()
        self._isolated_spin.setValue(int(s.get("isolated_window", 300)))
        self._middle_spin.setValue(int(s.get("middle_time_window", 3600)))
        self._context_spin.setValue(int(s.get("context_window", 300)))
        self._distance_spin.setValue(int(s.get("max_gps_distance", 200)))
        self._offset_spin.setValue(int(s.get("time_offset", 0)))
        self._match_tail_cb.setChecked(bool(s.get("match_tail", True)))
        self._overwrite_gps_cb.setChecked(bool(s.get("overwrite_gps", False)))

    def _open_gpx_browser(self):
        if self._cached_segments:
            dialog = GPXBrowserDialog(self._cached_segments, self)
            dialog.exec()

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        event.accept()
