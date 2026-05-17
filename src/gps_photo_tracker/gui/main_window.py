"""Main window for GPS Photo Tracker."""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QUrl
from PySide6.QtGui import QBrush, QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent

logger = logging.getLogger("gps_tracker")
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QComboBox,
    QSplitter,
)

from gps_photo_tracker.core.models import (
    GPXSegment,
    MatcherConfig,
    MatchResult,
    PhotoInfo,
    ProcessMode,
    ProcessOptions,
    ReviewAction,
    ReviewDecision,
    ReviewState,
    TrackPoint,
)
from gps_photo_tracker.gui.review_dialog import ReviewDialog
from gps_photo_tracker.gui.config_panel import build_params_group, build_mode_group
from gps_photo_tracker.gui.detail_dialog import DetailDialog
from gps_photo_tracker.gui.gpx_browser_dialog import GPXBrowserDialog
from gps_photo_tracker.gui.photo_browser_dialog import PhotoBrowserDialog
from gps_photo_tracker.gui.photo_preview import PhotoPreview
from gps_photo_tracker.gui.progress_panel import build_progress_group
from gps_photo_tracker.gui.result_table import build_result_panel
from gps_photo_tracker.gui.settings_dialog import SettingsDialog, load_settings
from gps_photo_tracker.gui.worker import Worker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GPS Photo Tracker")
        self.setMinimumSize(1000, 600)
        self.setAcceptDrops(True)

        self._worker: Worker | None = None
        self._result_details: list[dict] = []
        self._cached_segments = []
        self._cached_photos = []
        self._excluded_filenames: set[str] = set()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setHandleWidth(4)
        self._splitter.setStyleSheet(
            "QSplitter::handle { background: #c0c0c0; }"
            "QSplitter::handle:hover { background: #4a9eff; }"
        )
        layout.addWidget(self._splitter)

        # Left panel
        self._left_panel = self._build_left_panel()
        self._splitter.addWidget(self._left_panel)

        # Right panel
        right = self._build_right_panel()
        self._splitter.addWidget(right)

        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 2)
        self._splitter.setCollapsible(0, True)
        self._splitter.setSizes([300, 700])

        # Restore splitter state (only if previously saved)
        settings = QSettings("GPSPhotoTracker", "GPSPhotoTracker")
        splitter_state = settings.value("main_splitter_state")
        if splitter_state and isinstance(splitter_state, (bytes, bytearray)):
            self._splitter.restoreState(splitter_state)
        self._splitter.splitterMoved.connect(
            lambda: QSettings("GPSPhotoTracker", "GPSPhotoTracker").setValue(
                "main_splitter_state", self._splitter.saveState()
            )
        )

        self.statusBar().showMessage("就绪")

        # Menu bar
        menu = self.menuBar()
        file_menu = menu.addMenu("文件")
        settings_action = file_menu.addAction("设置")
        settings_action.triggered.connect(self._open_settings)

        view_menu = menu.addMenu("视图")
        self._toggle_panel_action = view_menu.addAction("配置面板")
        self._toggle_panel_action.setCheckable(True)
        self._toggle_panel_action.setChecked(True)
        self._toggle_panel_action.triggered.connect(self._toggle_left_panel)
        view_menu.addAction(self._toggle_panel_action)

        debug_menu = menu.addMenu("调试")
        log_action = debug_menu.addAction("查看日志")
        log_action.triggered.connect(self._open_log_viewer)

        self._review_decisions: dict = {}
        self._reviewed_results: list = []

        # Load saved settings
        self._apply_saved_settings()
        self._load_path_history()

    # ── Left panel ──────────────────────────────────────────

    def _build_left_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # File selection
        layout.addWidget(self._build_file_group())

        # Parameters (from config_panel)
        params_group, params_w = build_params_group()
        self._isolated_spin = params_w["isolated_spin"]
        self._middle_spin = params_w["middle_spin"]
        self._context_spin = params_w["context_spin"]
        self._distance_spin = params_w["distance_spin"]
        self._offset_spin = params_w["offset_spin"]
        self._match_tail_cb = params_w["match_tail_cb"]
        self._overwrite_gps_cb = params_w["overwrite_gps_cb"]
        self._keep_struct_cb = params_w["keep_struct_cb"]
        self._auto_tune_btn = params_w["auto_tune_btn"]
        self._workers_spin = params_w["workers_spin"]
        self._auto_tune_btn.clicked.connect(self._on_auto_tune)
        layout.addWidget(params_group)

        # Process mode (from config_panel)
        mode_group, mode_btn_group, mode_radios = build_mode_group()
        self._mode_group = mode_btn_group
        self._preview_rb = mode_radios["preview_rb"]
        self._copy_rb = mode_radios["copy_rb"]
        self._overwrite_rb = mode_radios["overwrite_rb"]
        layout.addWidget(mode_group)

        # Buttons
        layout.addWidget(self._build_buttons())

        # Progress (from progress_panel)
        progress_group, phase_bars, progress_label, elapsed_label = build_progress_group()
        self._phase_bars = phase_bars
        self._progress_label = progress_label
        self._elapsed_label = elapsed_label
        layout.addWidget(progress_group)

        layout.addStretch()
        return widget

    def _build_file_group(self) -> QGroupBox:
        group = QGroupBox("文件选择")
        layout = QVBoxLayout(group)

        # GPS directory
        row1 = QHBoxLayout()
        self._gps_dir_edit = QComboBox()
        self._gps_dir_edit.setEditable(True)
        self._gps_dir_edit.lineEdit().setPlaceholderText("GPS 轨迹目录 (GPX/KML/TCX)...")
        btn_gps = QPushButton("浏览")
        btn_gps.clicked.connect(self._browse_gps_dir)
        row1.addWidget(QLabel("GPS:"))
        row1.addWidget(self._gps_dir_edit)
        row1.addWidget(btn_gps)
        layout.addLayout(row1)

        # Photo directory
        row2 = QHBoxLayout()
        self._photo_dir_edit = QComboBox()
        self._photo_dir_edit.setEditable(True)
        self._photo_dir_edit.lineEdit().setPlaceholderText("照片目录...")
        btn_photo = QPushButton("浏览")
        btn_photo.clicked.connect(self._browse_photo_dir)
        row2.addWidget(QLabel("照片:"))
        row2.addWidget(self._photo_dir_edit)
        row2.addWidget(btn_photo)
        layout.addLayout(row2)

        # Output directory
        row3 = QHBoxLayout()
        self._output_dir_edit = QComboBox()
        self._output_dir_edit.setEditable(True)
        self._output_dir_edit.lineEdit().setPlaceholderText("输出目录（拷贝模式）...")
        btn_output = QPushButton("浏览")
        btn_output.clicked.connect(self._browse_output_dir)
        row3.addWidget(QLabel("输出:"))
        row3.addWidget(self._output_dir_edit)
        row3.addWidget(btn_output)
        layout.addLayout(row3)

        # Clickable labels for GPX and photo browsers
        browser_row = QHBoxLayout()
        self._gpx_browser_label = QLabel("GPS: —")
        self._gpx_browser_label.setStyleSheet(
            "padding: 4px; background: #e8e8e8; border-radius: 3px;"
        )
        self._gpx_browser_label.mousePressEvent = lambda e: self._open_gpx_browser()
        browser_row.addWidget(self._gpx_browser_label)

        self._photo_browser_label = QLabel("照片: —")
        self._photo_browser_label.setStyleSheet(
            "padding: 4px; background: #e8e8e8; border-radius: 3px;"
        )
        self._photo_browser_label.mousePressEvent = lambda e: self._open_photo_browser()
        browser_row.addWidget(self._photo_browser_label)
        layout.addLayout(browser_row)

        # Scan summary
        self._scan_summary = QLabel("GPS: — | 照片: —")
        self._scan_summary.setStyleSheet("padding: 4px; color: #666;")
        layout.addWidget(self._scan_summary)

        return group

    def _build_buttons(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self._start_btn = QPushButton("开始处理")
        self._start_btn.clicked.connect(self._on_start)
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self._start_btn)
        layout.addWidget(self._cancel_btn)
        return widget

    # ── Right panel ─────────────────────────────────────────

    def _build_right_panel(self) -> QWidget:
        # Result table (from result_table module)
        result_widget, self._pre_stats_label, self._stats_label, self._result_filter, self._results_table = build_result_panel()
        self._result_filter.currentIndexChanged.connect(self._apply_result_filter)
        self._results_table.doubleClicked.connect(self._on_table_double_click)
        self._results_table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        layout = result_widget.layout()

        # Move results_table into a vertical splitter with photo preview
        layout.removeWidget(self._results_table)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(4)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #c0c0c0; }"
            "QSplitter::handle:hover { background: #4a9eff; }"
        )
        splitter.addWidget(self._results_table)

        self._photo_preview = PhotoPreview()
        splitter.addWidget(self._photo_preview)
        splitter.setSizes([400, 200])

        # Restore saved splitter state
        settings = QSettings("GPSPhotoTracker", "GPSPhotoTracker")
        splitter_state = settings.value("right_splitter_state")
        if splitter_state:
            splitter.restoreState(splitter_state)
        splitter.splitterMoved.connect(
            lambda: QSettings("GPSPhotoTracker", "GPSPhotoTracker").setValue(
                "right_splitter_state", splitter.saveState()
            )
        )

        layout.addWidget(splitter, stretch=1)

        return result_widget

    # ── Actions ─────────────────────────────────────────────

    def _toggle_left_panel(self, checked: bool):
        sizes = self._splitter.sizes()
        if checked:
            self._splitter.setSizes([300, max(sizes[1], 400)])
        else:
            self._splitter.setSizes([0, sum(sizes)])

    def _browse_gps_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择 GPS 轨迹目录")
        if path:
            self._gps_dir_edit.setCurrentText(path)
            self._add_path_history("gps_dir_history", path, self._gps_dir_edit)
            self._auto_scan_gpx(Path(path))

    def _browse_photo_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择照片目录")
        if path:
            self._photo_dir_edit.setCurrentText(path)
            self._add_path_history("photo_dir_history", path, self._photo_dir_edit)
            self._clear_results()
            self._auto_scan_photos(Path(path))

    def _browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self._output_dir_edit.setCurrentText(path)
            self._add_path_history("output_dir_history", path, self._output_dir_edit)

    def _clear_results(self):
        self._results_table.setRowCount(0)
        self._result_details.clear()
        self._stats_label.setText("")
        self._photo_preview.clear()

    def _auto_scan_gpx(self, gps_dir: Path):
        from gps_photo_tracker.core.file_provider import FileProvider
        from gps_photo_tracker.core.track_parser import TrackParser
        provider = FileProvider()
        parser = TrackParser()
        track_files = provider.list_tracks(gps_dir)
        total_points = 0
        gpx_count = 0
        for f in track_files:
            try:
                segs = parser.parse_file(f)
                total_points += sum(len(s.points) for s in segs)
                gpx_count += len(segs)
            except Exception:
                logger.debug("跳过无法解析的轨迹文件: %s", f)
        if gpx_count > 0:
            self._gpx_browser_label.setText(f"GPS: {gpx_count} 段, {total_points} 点 (点击查看)")
            self._scan_summary.setText(f"GPS: {gpx_count} 段, {total_points} 点")

    def _auto_scan_photos(self, photo_dir: Path):
        from gps_photo_tracker.core.exif_writer import EXIFWriter
        from gps_photo_tracker.core.file_provider import FileProvider
        provider = FileProvider()
        photo_paths = provider.list_photos(photo_dir)
        has_gps = 0
        for p in photo_paths:
            try:
                gps = EXIFWriter.read_gps(p)
                if gps:
                    has_gps += 1
            except Exception:
                logger.debug("跳过无法读取GPS的照片: %s", p)
        total = len(photo_paths)
        self._photo_browser_label.setText(f"照片: {total}张 ({has_gps}有GPS) (点击查看)")
        prefix = self._scan_summary.text()
        self._scan_summary.setText(f"{prefix} | 照片: {total}张 ({has_gps}有GPS)")

    def _add_path_history(self, key: str, path: str, combo: QComboBox):
        settings = QSettings()
        history = settings.value(key, [])
        if isinstance(history, str):
            history = [history]
        if path in history:
            history.remove(path)
        history.insert(0, path)
        history = history[:10]
        settings.setValue(key, history)
        combo.clear()
        combo.addItems(history)
        combo.setCurrentText(path)

    def _load_path_history(self):
        settings = QSettings()
        for key, combo in [
            ("gps_dir_history", self._gps_dir_edit),
            ("photo_dir_history", self._photo_dir_edit),
            ("output_dir_history", self._output_dir_edit),
        ]:
            history = settings.value(key, [])
            if isinstance(history, str):
                history = [history]
            if history:
                combo.addItems(history)

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
        mode_id = max(0, self._mode_group.checkedId())
        mode = [ProcessMode.PREVIEW, ProcessMode.COPY, ProcessMode.OVERWRITE][mode_id]
        output_dir = Path(self._output_dir_edit.currentText()) if self._output_dir_edit.currentText() else None
        settings = QSettings()
        return ProcessOptions(
            mode=mode,
            output_dir=output_dir,
            overwrite_gps=self._overwrite_gps_cb.isChecked(),
            keep_structure=self._keep_struct_cb.isChecked(),
            resume=bool(settings.value("resume", False, type=bool)),
            generate_report=bool(settings.value("generate_report", False, type=bool)),
            workers=self._workers_spin.value(),
        )

    def _on_auto_tune(self):
        """Auto-tune parameters by re-scanning actual data."""
        gps_dir = self._gps_dir_edit.currentText()
        photo_dir = self._photo_dir_edit.currentText()
        if not gps_dir or not photo_dir:
            QMessageBox.information(self, "提示", "请先选择 GPS 轨迹目录和照片目录")
            return
        reply = QMessageBox.question(
            self, "智能推荐参数",
            "将根据已扫描的 GPS 轨迹和照片数据，自动分析并推荐最优匹配参数。\n\n"
            "当前参数值将被替换。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from gps_photo_tracker.service.tagging_service import GPSTaggingService
        service = GPSTaggingService()
        self.statusBar().showMessage("正在分析数据...")
        try:
            segments = service.scan_gpx(Path(gps_dir))
            photos = service.scan_photos(Path(photo_dir))
        except Exception as e:
            QMessageBox.warning(self, "错误", f"扫描失败: {e}")
            return
        config = service.auto_tune(segments, photos)
        self._isolated_spin.setValue(config.isolated_window)
        self._middle_spin.setValue(config.middle_time_window)
        self._context_spin.setValue(config.context_window)
        self._distance_spin.setValue(config.max_gps_distance)
        self._offset_spin.setValue(config.time_offset)
        self._match_tail_cb.setChecked(config.match_tail)
        self.statusBar().showMessage("参数已根据数据自动推荐")

    # ── Processing ──────────────────────────────────────────

    def _on_start(self):
        gps_dir = self._gps_dir_edit.currentText()
        photo_dir = self._photo_dir_edit.currentText()
        if not gps_dir or not photo_dir:
            QMessageBox.warning(self, "提示", "请先选择 GPS 轨迹目录和照片目录")
            return

        mode_id = self._mode_group.checkedId()
        if mode_id == 1 and not self._output_dir_edit.currentText():
            QMessageBox.warning(self, "提示", "拷贝模式需要指定输出目录")
            return

        # Overwrite mode confirmation (spec CF-05)
        if mode_id == 2:
            reply = QMessageBox.question(
                self, "确认覆盖",
                "覆盖模式将直接修改原始照片文件。\n\n"
                "建议先使用预览模式确认匹配结果，再使用拷贝模式。\n\n"
                "确定要使用覆盖模式吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        for bar in self._phase_bars:
            bar.setValue(0)
            bar.setMaximum(100)
        self._progress_label.setText("扫描中...")
        self._results_table.setRowCount(0)
        self._result_details.clear()

        config = self._get_matcher_config()
        options = self._get_process_options()

        settings = QSettings()
        log_dir_str = settings.value("log_dir", "")
        log_dir = Path(log_dir_str) if log_dir_str else None

        # Pass stored review decisions to Worker for COPY/OVERWRITE
        review_decisions = self._review_decisions if mode_id != 0 else None
        # Clear stale decisions when starting a new Preview run
        if mode_id == 0:
            self._review_decisions = {}

        self._worker = Worker(
            gps_dir=Path(gps_dir),
            photo_dir=Path(photo_dir),
            config=config,
            options=options,
            log_dir=log_dir,
            excluded_filenames=self._excluded_filenames,
            review_decisions=review_decisions,
        )
        self._worker.progress_signal.connect(self._on_progress)
        self._worker.photo_signal.connect(self._on_photo_processed)
        self._worker.done_signal.connect(self._on_done)
        self._worker.scan_done_signal.connect(self._on_scan_done)
        self._worker.photos_scanned_signal.connect(self._on_photos_scanned)
        self._worker.review_ready_signal.connect(self._on_review_ready)
        self._worker.start()

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()
            self._progress_label.setText("正在取消...")

    def _on_progress(self, phase: str, current: int, total: int, filename: str, elapsed: float):
        phase_map = {
            "scanning_gpx": 0,
            "scanning_photos": 1,
            "matching": 2,
            "writing": 3,
        }
        idx = phase_map.get(phase)
        if idx is not None and idx < len(self._phase_bars):
            bar = self._phase_bars[idx]
            if total > 0:
                bar.setMaximum(total)
                bar.setValue(current)
        self._progress_label.setText(f"当前: {filename}")
        if elapsed > 0:
            eta = (elapsed / current * (total - current)) if current > 0 and total > current else 0
            mins, secs = divmod(int(eta), 60)
            eta_str = f"{mins}m{secs:02d}s" if mins > 0 else f"{secs}s"
            self._elapsed_label.setText(f"已用: {elapsed:.0f}s  剩余: ~{eta_str}")

    def _on_photo_processed(self, result_dict: dict):
        # Disable sorting during row insertion to prevent row displacement
        sorting_was_enabled = self._results_table.isSortingEnabled()
        if sorting_was_enabled:
            self._results_table.setSortingEnabled(False)

        row = self._results_table.rowCount()
        self._results_table.insertRow(row)

        filename = result_dict.get("filename", "")
        data_idx = len(self._result_details)
        fn_item = QTableWidgetItem(filename)
        fn_item.setData(Qt.ItemDataRole.UserRole, data_idx)
        self._results_table.setItem(row, 0, fn_item)

        # 日期时间 — EXIF capture time
        datetime_text = result_dict.get("capture_time", "")
        self._results_table.setItem(row, 1, QTableWidgetItem(datetime_text))

        # GPS(前) — existing GPS before processing
        gps_before = result_dict.get("gps_before", "")
        before_text = gps_before if gps_before else "无"
        self._results_table.setItem(row, 2, QTableWidgetItem(before_text))

        # 计算GPS — computed GPS coordinates from matching
        lat = result_dict.get("latitude")
        lon = result_dict.get("longitude")
        if lat is not None and lon is not None:
            gps_text = f"{lat:.4f}, {lon:.4f}"
        else:
            gps_text = "—"
        self._results_table.setItem(row, 3, QTableWidgetItem(gps_text))

        # GPS(后) — what GPS will be after processing
        has_gps = result_dict.get("has_gps", False)
        will_overwrite = has_gps and self._overwrite_gps_cb.isChecked()
        if has_gps and not will_overwrite:
            after_text = before_text  # no change — keep existing GPS
        else:
            after_text = gps_text  # new match result
        self._results_table.setItem(row, 4, QTableWidgetItem(after_text))

        # Color-code matching GPS values
        same_brush = QBrush(QColor(220, 245, 220))  # light green
        if before_text not in ("无", "—") and before_text == after_text:
            self._results_table.item(row, 2).setBackground(same_brush)
            self._results_table.item(row, 4).setBackground(same_brush)
        if gps_text not in ("无", "—") and gps_text == after_text:
            self._results_table.item(row, 3).setBackground(same_brush)
            self._results_table.item(row, 4).setBackground(same_brush)

        method = result_dict.get("method", "")
        method_text = {"interpolated": "插值", "nearest": "就近"}.get(method, "")
        self._results_table.setItem(row, 5, QTableWidgetItem(method_text))

        success = result_dict.get("success", False)
        if success:
            status = "成功"
        else:
            reason = result_dict.get("reject_reason", "失败")
            status = {"no_gps_coverage": "无GPS覆盖", "time_diff": "时差过大",
                      "gps_distance": "距离过大", "tail_isolated": "孤立",
                      "no_track_points": "无轨迹点"}.get(reason, reason)
        self._results_table.setItem(row, 6, QTableWidgetItem(status))

        if sorting_was_enabled:
            self._results_table.setSortingEnabled(True)

        self._results_table.scrollToBottom()
        self._result_details.append(result_dict)
        self._apply_result_filter()
        self._update_stats_card()

    def _update_stats_card(self):
        details = self._result_details
        total = len(details)
        has_gps_total = sum(1 for d in details if d.get("has_gps"))
        new_matched = sum(1 for d in details if not d.get("has_gps") and d.get("success"))
        skipped_existing = sum(
            1 for d in details
            if d.get("has_gps") and d.get("success") and not d.get("overwritten")
        )
        overwritten = sum(1 for d in details if d.get("overwritten"))
        failed = sum(1 for d in details if not d.get("success"))
        matched = new_matched + skipped_existing + overwritten
        rate = matched / total if total > 0 else 0
        self._stats_label.setText(
            f"总数: {total} | 已有GPS: {has_gps_total} | "
            f"新匹配: {new_matched} | 跳过(已有): {skipped_existing} | "
            f"覆盖: {overwritten} | 失败: {failed} | 成功率: {rate:.1%}"
        )

    def _on_review_ready(self, review_data: dict):
        """Handle review_ready_signal: show ReviewDialog for failed matches."""
        failed_results = []
        for fr in review_data.get("failed_results", []):
            photo = PhotoInfo(
                path=Path(fr["photo_path"]),
                filename=fr["filename"],
                timestamp=fr.get("timestamp"),
                has_gps=False,
            )
            result = MatchResult(
                photo=photo, success=False,
                reject_reason=fr.get("reject_reason"),
                time_diff=fr.get("time_diff"),
            )
            failed_results.append(result)

        segments = []
        for sd in review_data.get("gps_segments", []):
            points = [
                TrackPoint(
                    timestamp=p["timestamp"],
                    latitude=p["latitude"],
                    longitude=p["longitude"],
                    altitude=p.get("altitude"),
                )
                for p in sd.get("points", [])
            ]
            segments.append(GPXSegment(
                filename=sd["filename"],
                start=sd["start"],
                end=sd["end"],
                points=points,
            ))

        state = ReviewState(failed_results=failed_results, gps_segments=segments)

        # Reconstruct all_results for neighbor lookup (follow-prev/next)
        all_results = []
        for ar in review_data.get("all_results", []):
            photo = PhotoInfo(
                path=Path(ar["photo_path"]),
                filename=ar["filename"],
                timestamp=ar.get("timestamp"),
                has_gps=ar.get("latitude") is not None,
            )
            gps = None
            if ar.get("latitude") is not None:
                from gps_photo_tracker.core.models import GPSInfo
                gps = GPSInfo(
                    latitude=ar["latitude"],
                    longitude=ar["longitude"],
                    altitude=ar.get("altitude"),
                )
            result = MatchResult(
                photo=photo, success=ar.get("success", False),
                gps=gps, method=ar.get("method"),
            )
            all_results.append(result)
        state.all_results = all_results
        dialog = ReviewDialog(state, self)
        dialog.exec()

        reviewed_state = dialog.get_state()
        if reviewed_state.decisions:
            # Store as serializable dict for Worker to consume on COPY/OVERWRITE
            self._review_decisions = {}
            for path_str, dec in reviewed_state.decisions.items():
                dec_data = {"action": dec.action.value}
                if dec.action == ReviewAction.MANUAL_GPS and dec.selected_point:
                    dec_data["point"] = {
                        "timestamp": dec.selected_point.timestamp,
                        "latitude": dec.selected_point.latitude,
                        "longitude": dec.selected_point.longitude,
                        "altitude": dec.selected_point.altitude,
                    }
                elif dec.action == ReviewAction.MANUAL_COORD:
                    dec_data["lat"] = dec.manual_lat
                    dec_data["lon"] = dec.manual_lon
                # FOLLOW_PREV/FOLLOW_NEXT: stored as action only, resolved at write time
                self._review_decisions[path_str] = dec_data

            # Write review decisions back into result table
            self._apply_review_to_table(reviewed_state, all_results)

            self._reviewed_results = failed_results
            manual_count = sum(
                1 for d in reviewed_state.decisions.values()
                if d.action in (ReviewAction.MANUAL_GPS, ReviewAction.MANUAL_COORD)
            )
            follow_count = sum(
                1 for d in reviewed_state.decisions.values()
                if d.action in (ReviewAction.FOLLOW_PREV, ReviewAction.FOLLOW_NEXT)
            )
            skip_count = sum(
                1 for d in reviewed_state.decisions.values()
                if d.action in (ReviewAction.SKIP, ReviewAction.KEEP_SKIP)
            )
            self.statusBar().showMessage(
                f"审核完成: {manual_count} 张手动指定, {follow_count} 张跟随, {skip_count} 张跳过。点 COPY/OVERWRITE 执行写入。"
            )
        else:
            self._review_decisions = {}

        # Manually trigger UI completion since Worker didn't emit done_signal
        total = review_data.get("total", 0)
        matched = review_data.get("matched", 0)
        failed = review_data.get("failed", 0)
        rate = matched / total if total > 0 else 0
        self._on_done({
            "total": total, "matched": matched, "failed": failed,
            "skipped": 0, "overwritten": 0, "success_rate": rate,
        })

    def _apply_review_to_table(self, reviewed_state: ReviewState, all_results: list):
        """Update result table rows with review decisions (GPS coords, method, status)."""
        from gps_photo_tracker.core.models import GPSInfo

        # Build time-ordered matched results for follow resolution
        ordered = sorted(
            [r for r in all_results if r.success and r.gps and r.photo.timestamp],
            key=lambda r: r.photo.timestamp or 0,
        )

        # Resolve follow-prev/next to actual GPS for each decision
        resolved_gps: dict[str, tuple[GPSInfo, str]] = {}  # path -> (gps, method_label)
        for path_str, dec in reviewed_state.decisions.items():
            if dec.action == ReviewAction.MANUAL_GPS and dec.selected_point:
                pt = dec.selected_point
                resolved_gps[path_str] = (GPSInfo(pt.latitude, pt.longitude, pt.altitude), "手动GPS")
            elif dec.action == ReviewAction.MANUAL_COORD and dec.manual_lat is not None and dec.manual_lon is not None:
                resolved_gps[path_str] = (GPSInfo(dec.manual_lat, dec.manual_lon), "手动坐标")
            elif dec.action in (ReviewAction.FOLLOW_PREV, ReviewAction.FOLLOW_NEXT):
                # Find the failed photo's timestamp in all_results
                target_ts = None
                for r in all_results:
                    if str(r.photo.path) == path_str and r.photo.timestamp:
                        target_ts = r.photo.timestamp
                        break
                if target_ts is None:
                    continue
                direction = -1 if dec.action == ReviewAction.FOLLOW_PREV else 1
                label = "跟随上一个" if dec.action == ReviewAction.FOLLOW_PREV else "跟随下一个"
                for j in range(len(ordered)):
                    idx = j if direction > 0 else len(ordered) - 1 - j
                    neighbor = ordered[idx]
                    if direction > 0 and neighbor.photo.timestamp > target_ts:
                        resolved_gps[path_str] = (neighbor.gps, label)
                        break
                    elif direction < 0 and neighbor.photo.timestamp < target_ts:
                        resolved_gps[path_str] = (neighbor.gps, label)
                        break

        # Update matching rows in the result table
        sorting_was_enabled = self._results_table.isSortingEnabled()
        if sorting_was_enabled:
            self._results_table.setSortingEnabled(False)

        for visual_row in range(self._results_table.rowCount()):
            item = self._results_table.item(visual_row, 0)
            if not item:
                continue
            data_row = item.data(Qt.ItemDataRole.UserRole)
            if data_row is None or data_row >= len(self._result_details):
                continue
            detail = self._result_details[data_row]
            path_str = detail.get("path", "")
            if path_str not in resolved_gps:
                continue

            gps, method_label = resolved_gps[path_str]
            gps_text = f"{gps.latitude:.4f}, {gps.longitude:.4f}"

            # Update GPS(后) column — show the review-assigned GPS
            self._results_table.setItem(visual_row, 4, QTableWidgetItem(gps_text))

            # Color-code: GPS(后) matching GPS(前) or 计算GPS
            same_brush = QBrush(QColor(220, 245, 220))
            before_item = self._results_table.item(visual_row, 2)
            calc_item = self._results_table.item(visual_row, 3)
            if before_item and before_item.text() not in ("无", "—") and before_item.text() == gps_text:
                self._results_table.item(visual_row, 4).setBackground(same_brush)
                before_item.setBackground(same_brush)
            elif calc_item and calc_item.text() not in ("无", "—") and calc_item.text() == gps_text:
                self._results_table.item(visual_row, 4).setBackground(same_brush)
                calc_item.setBackground(same_brush)
            else:
                review_brush = QBrush(QColor(200, 230, 255))  # light blue for review-assigned
                self._results_table.item(visual_row, 4).setBackground(review_brush)

            # Update method column
            self._results_table.setItem(visual_row, 5, QTableWidgetItem(method_label))

            # Update status column
            self._results_table.setItem(visual_row, 6, QTableWidgetItem("已审核"))

            # Also update the detail dict so double-click shows correct info
            detail["success"] = True
            detail["method"] = method_label
            detail["latitude"] = gps.latitude
            detail["longitude"] = gps.longitude
            detail["altitude"] = gps.altitude

        if sorting_was_enabled:
            self._results_table.setSortingEnabled(True)
        self._update_stats_card()

    def _on_done(self, result_dict: dict):
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)

        if result_dict.get("cancelled"):
            self._progress_label.setText("已取消")
            self.statusBar().showMessage("处理已取消")
            return

        if "error" in result_dict:
            QMessageBox.warning(self, "处理错误", f"处理失败：{result_dict['error']}")
            self._progress_label.setText("错误")
            self.statusBar().showMessage("处理失败")
            return

        total = result_dict.get("total", 0)
        matched = result_dict.get("matched", 0)
        failed = result_dict.get("failed", 0)
        skipped = result_dict.get("skipped", 0)
        rate = result_dict.get("success_rate", 0)

        self._stats_label.setText(
            f"总数: {total} | 成功: {matched} | 跳过: {skipped} | 失败: {failed} | 成功率: {rate:.1%}"
        )
        self._progress_label.setText("完成")
        self.statusBar().showMessage(
            f"处理完成: {matched}/{total} 成功 | 选中行后按 ← → 快速跟随相邻GPS"
        )

        QMessageBox.information(
            self, "处理完成",
            f"处理完成！\n\n总数: {total}\n成功: {matched}\n失败: {failed}\n跳过: {skipped}\n成功率: {rate:.1%}"
        )

    def _apply_result_filter(self):
        filter_idx = self._result_filter.currentIndex()
        for row in range(self._results_table.rowCount()):
            data_row = self._get_detail_row(row)
            if data_row < 0 or data_row >= len(self._result_details):
                self._results_table.setRowHidden(row, False)
                continue
            detail = self._result_details[data_row]
            success = detail.get("success", False)
            has_gps = detail.get("has_gps", False)
            if filter_idx == 0:
                self._results_table.setRowHidden(row, False)
            elif filter_idx == 1:
                self._results_table.setRowHidden(row, not success)
            elif filter_idx == 2:
                self._results_table.setRowHidden(row, success)
            elif filter_idx == 3:
                self._results_table.setRowHidden(row, not (has_gps and success))

    def _on_scan_done(self, segments: list[dict]):
        self._cached_segments = segments
        gpx_count = len(segments)
        total_pts = sum(s.get("point_count", 0) for s in segments)
        self._gpx_browser_label.setText(f"GPS: {gpx_count} 段, {total_pts} 点 (点击查看)")
        self._scan_summary.setText(f"GPS: {gpx_count} 段, {total_pts} 点")

    def _on_photos_scanned(self, photos: list[dict]):
        self._cached_photos = photos
        total = len(photos)
        with_gps = sum(1 for p in photos if p.get("has_gps"))
        self._photo_browser_label.setText(f"照片: {total}张 ({with_gps}有GPS) (点击查看)")
        self._scan_summary.setText(
            f"{self._scan_summary.text()} | 照片: {total}张 ({with_gps}有GPS)"
        )
        gps_ratio = with_gps / total if total > 0 else 0
        self._pre_stats_label.setText(
            f"处理前: {total}张照片 | {with_gps}张有GPS ({gps_ratio:.1%})"
        )

    def _open_photo_browser(self):
        if self._cached_photos:
            dialog = PhotoBrowserDialog(self._cached_photos, self)
            dialog.exec()

    def _on_table_double_click(self, index):
        data_row = self._get_detail_row(index.row())
        if 0 <= data_row < len(self._result_details):
            dialog = DetailDialog(self._result_details[data_row], self)
            dialog.exec()

    def _on_selection_changed(self):
        rows = self._results_table.selectionModel().selectedRows()
        if not rows:
            self._photo_preview.clear()
            return
        visual_row = rows[0].row()
        data_row = self._get_detail_row(visual_row)
        if 0 <= data_row < len(self._result_details):
            detail = self._result_details[data_row]
            photo_path = detail.get("path", "")
            lat = detail.get("latitude")
            lon = detail.get("longitude")
            method = detail.get("method", "")
            method_text = {"interpolated": "插值", "nearest": "就近"}.get(method, "—")
            gps_str = f"{lat:.4f}, {lon:.4f}" if lat is not None and lon is not None else "—"
            time_str = detail.get("capture_time") or "—"
            info = f"文件: {detail.get('filename', '—')}\n拍摄时间: {time_str}\nGPS: {gps_str}\n方式: {method_text}"
            self._photo_preview.show_photo(photo_path, info)

            # Preload adjacent thumbnails (3 before + 3 after)
            preload_paths = []
            for offset in range(1, 4):
                for delta in (offset, -offset):
                    adj_visual = visual_row + delta
                    if 0 <= adj_visual < self._results_table.rowCount():
                        adj_data = self._get_detail_row(adj_visual)
                        if 0 <= adj_data < len(self._result_details):
                            p = self._result_details[adj_data].get("path", "")
                            if p:
                                preload_paths.append(p)
            self._photo_preview.preload_photos(preload_paths)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Left, Qt.Key_Right):
            rows = self._results_table.selectionModel().selectedRows()
            if rows and self._results_table.rowCount() > 0:
                self._results_table.setFocus()
                self._quick_follow_gps(rows[0].row(), -1 if key == Qt.Key_Left else 1)
                return
        super().keyPressEvent(event)

    def _quick_follow_gps(self, visual_row: int, direction: int):
        """Assign GPS from nearest neighbor with GPS(后) in the given direction.

        direction: -1 = look upward (earlier in time), +1 = look downward (later in time).
        After assignment, auto-advance selection in the same direction.
        """
        data_row = self._get_detail_row(visual_row)
        if data_row < 0 or data_row >= len(self._result_details):
            return
        detail = self._result_details[data_row]

        # Only act on rows that lack GPS(后)
        gps_after_item = self._results_table.item(visual_row, 4)
        if gps_after_item and gps_after_item.text() not in ("无", "—", ""):
            # Already has GPS — just advance selection
            next_row = visual_row + direction
            if 0 <= next_row < self._results_table.rowCount():
                self._results_table.selectRow(next_row)
            return

        # Search for nearest row with GPS(后) in the given direction
        found_visual = -1
        found_gps_text = ""
        found_lat = None
        found_lon = None
        step = direction
        candidate = visual_row + step
        while 0 <= candidate < self._results_table.rowCount():
            cand_data = self._get_detail_row(candidate)
            if 0 <= cand_data < len(self._result_details):
                cand_detail = self._result_details[cand_data]
                cand_gps_item = self._results_table.item(candidate, 4)
                if cand_gps_item and cand_gps_item.text() not in ("无", "—", ""):
                    found_visual = candidate
                    found_gps_text = cand_gps_item.text()
                    found_lat = cand_detail.get("latitude")
                    found_lon = cand_detail.get("longitude")
                    break
            candidate += step

        if found_visual < 0:
            return

        # Apply GPS to current row
        method_label = "跟随上一个" if direction < 0 else "跟随下一个"
        sorting_was_enabled = self._results_table.isSortingEnabled()
        if sorting_was_enabled:
            self._results_table.setSortingEnabled(False)

        self._results_table.setItem(visual_row, 4, QTableWidgetItem(found_gps_text))
        self._results_table.setItem(visual_row, 5, QTableWidgetItem(method_label))
        self._results_table.setItem(visual_row, 6, QTableWidgetItem("已跟随"))

        # Color-code GPS(后) column
        same_brush = QBrush(QColor(220, 245, 220))
        follow_brush = QBrush(QColor(200, 230, 255))
        before_item = self._results_table.item(visual_row, 2)
        if before_item and before_item.text() not in ("无", "—") and before_item.text() == found_gps_text:
            self._results_table.item(visual_row, 4).setBackground(same_brush)
            before_item.setBackground(same_brush)
        else:
            self._results_table.item(visual_row, 4).setBackground(follow_brush)

        # Update detail dict
        detail["success"] = True
        detail["method"] = method_label
        if found_lat is not None and found_lon is not None:
            detail["latitude"] = found_lat
            detail["longitude"] = found_lon

        if sorting_was_enabled:
            self._results_table.setSortingEnabled(True)
        self._update_stats_card()

        # Advance selection
        next_row = visual_row + direction
        if 0 <= next_row < self._results_table.rowCount():
            self._results_table.selectRow(next_row)

    def _get_detail_row(self, visual_row: int) -> int:
        item = self._results_table.item(visual_row, 0)
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        return data if data is not None else visual_row

    def _open_log_viewer(self):
        from gps_photo_tracker.gui.log_viewer import LogViewerDialog
        from PySide6.QtCore import QSettings
        settings = QSettings()
        log_dir_str = settings.value("log_dir", "")
        if log_dir_str:
            log_dir = Path(log_dir_str)
        else:
            log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
        dialog = LogViewerDialog(log_dir, self)
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
        self._workers_spin.setValue(int(s.get("workers", 1)))
        self._keep_struct_cb.setChecked(bool(s.get("keep_structure", True)))

        mode_id = max(0, int(s.get("mode", 0)))
        for rb, mid in [(self._preview_rb, 0), (self._copy_rb, 1), (self._overwrite_rb, 2)]:
            if mid == mode_id:
                rb.setChecked(True)
                break

        geo = QSettings("GPSPhotoTracker", "GPSPhotoTracker").value("window_geometry")
        if geo:
            self.restoreGeometry(geo)

    def _open_gpx_browser(self):
        if self._cached_segments:
            dialog = GPXBrowserDialog(self._cached_segments, self)
            dialog.exec()
            self._excluded_filenames = dialog.get_excluded_filenames()

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        QSettings("GPSPhotoTracker", "GPSPhotoTracker").setValue("window_geometry", self.saveGeometry())
        event.accept()

    # ── Drag and drop ───────────────────────────────────────

    _TRACK_EXT = {".gpx", ".kml", ".tcx"}
    _IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            if any(u.isLocalFile() for u in event.mimeData().urls()):
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        event.ignore()

    def dropEvent(self, event):
        urls = [u for u in event.mimeData().urls() if u.isLocalFile()]
        if not urls:
            event.ignore()
            return
        gps_dir, photo_dir = self._classify_drop(urls)
        if gps_dir:
            self._gps_dir_edit.setCurrentText(str(gps_dir))
            self._add_path_history("gps_dir_history", str(gps_dir), self._gps_dir_edit)
            self._auto_scan_gpx(gps_dir)
        if photo_dir:
            self._photo_dir_edit.setCurrentText(str(photo_dir))
            self._add_path_history("photo_dir_history", str(photo_dir), self._photo_dir_edit)
            self._clear_results()
            self._auto_scan_photos(photo_dir)
        if not gps_dir and not photo_dir:
            QMessageBox.information(self, "拖放", "无法识别拖入的内容类型")
        event.accept()

    def _classify_drop(self, urls):
        """Classify dropped URLs into GPS dir and/or photo dir."""
        gps_dir = None
        photo_dir = None
        for url in urls:
            p = Path(url.toLocalFile())
            if p.is_file():
                ext = p.suffix.lower()
                if ext in self._TRACK_EXT and gps_dir is None:
                    gps_dir = p.parent
                elif ext in self._IMAGE_EXT and photo_dir is None:
                    photo_dir = p.parent
                continue
            if not p.is_dir():
                continue
            # Use iterdir (non-recursive) to avoid UI freeze on large directories
            children = list(p.iterdir())
            has_track = any(f.suffix.lower() in self._TRACK_EXT for f in children if f.is_file())
            has_image = any(f.suffix.lower() in self._IMAGE_EXT for f in children if f.is_file())
            if has_track and has_image:
                msg = QMessageBox(self)
                msg.setWindowTitle("识别目录")
                msg.setText(f"{p.name} 同时包含轨迹和照片文件。")
                gps_btn = msg.addButton("作为 GPS 目录", QMessageBox.ButtonRole.AcceptRole)
                photo_btn = msg.addButton("作为照片目录", QMessageBox.ButtonRole.RejectRole)
                msg.addButton("取消", QMessageBox.ButtonRole.DestructiveRole)
                msg.exec()
                if msg.clickedButton() == gps_btn:
                    gps_dir = p
                elif msg.clickedButton() == photo_btn:
                    photo_dir = p
            elif has_track:
                gps_dir = p
            elif has_image:
                photo_dir = p
        return gps_dir, photo_dir
