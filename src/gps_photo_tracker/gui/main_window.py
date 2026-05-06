"""Main window for GPS Photo Tracker."""

from pathlib import Path

from PySide6.QtCore import Qt, QSettings
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

from gps_photo_tracker.core.models import MatcherConfig, ProcessMode, ProcessOptions
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

        self._worker: Worker | None = None
        self._result_details: list[dict] = []
        self._cached_segments = []
        self._cached_photos = []
        self._excluded_filenames: set[str] = set()

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
        self._gps_dir_edit.lineEdit().setPlaceholderText("GPS 轨迹目录...")
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
            "padding: 4px; background: #e8e8e8; border-radius: 3px; cursor: pointer;"
        )
        self._gpx_browser_label.mousePressEvent = lambda e: self._open_gpx_browser()
        browser_row.addWidget(self._gpx_browser_label)

        self._photo_browser_label = QLabel("照片: —")
        self._photo_browser_label.setStyleSheet(
            "padding: 4px; background: #e8e8e8; border-radius: 3px; cursor: pointer;"
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
        result_widget, self._stats_label, self._result_filter, self._results_table = build_result_panel()
        self._result_filter.currentIndexChanged.connect(self._apply_result_filter)
        self._results_table.doubleClicked.connect(self._on_table_double_click)
        self._results_table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        layout = result_widget.layout()

        # Photo preview (from photo_preview module)
        self._photo_preview = PhotoPreview()
        layout.addWidget(self._photo_preview)

        return result_widget

    # ── Actions ─────────────────────────────────────────────

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
            self._auto_scan_photos(Path(path))

    def _browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self._output_dir_edit.setCurrentText(path)
            self._add_path_history("output_dir_history", path, self._output_dir_edit)

    def _auto_scan_gpx(self, gps_dir: Path):
        from gps_photo_tracker.core.file_provider import FileProvider
        from gps_photo_tracker.core.track_parser import TrackParser
        provider = FileProvider()
        parser = TrackParser()
        track_files = provider.list_tracks(gps_dir)
        total_points = 0
        for f in track_files:
            try:
                segs = parser.parse_file(f)
                total_points += sum(len(s.points) for s in segs)
            except Exception:
                pass
        self._gpx_browser_label.setText(f"GPS: {len(track_files)}文件 {total_points}点")

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
                pass
        self._photo_browser_label.setText(f"照片: {len(photo_paths)}张 {has_gps}有GPS")

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
        mode_id = self._mode_group.checkedId()
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

        self._worker = Worker(
            gps_dir=Path(gps_dir),
            photo_dir=Path(photo_dir),
            config=config,
            options=options,
            log_dir=log_dir,
            excluded_filenames=self._excluded_filenames,
        )
        self._worker.progress_signal.connect(self._on_progress)
        self._worker.photo_signal.connect(self._on_photo_processed)
        self._worker.done_signal.connect(self._on_done)
        self._worker.scan_done_signal.connect(self._on_scan_done)
        self._worker.photos_scanned_signal.connect(self._on_photos_scanned)
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
        row = self._results_table.rowCount()
        self._results_table.insertRow(row)

        filename = result_dict.get("filename", "")
        self._results_table.setItem(row, 0, QTableWidgetItem(filename))

        has_existing = result_dict.get("has_gps", False)
        self._results_table.setItem(row, 1, QTableWidgetItem("有" if has_existing else "无"))

        lat = result_dict.get("latitude")
        lon = result_dict.get("longitude")
        if lat is not None and lon is not None:
            gps_text = f"{lat:.4f}, {lon:.4f}"
        else:
            gps_text = "—"
        self._results_table.setItem(row, 2, QTableWidgetItem(gps_text))

        method = result_dict.get("method", "")
        method_text = {"interpolated": "插值", "nearest": "就近"}.get(method, "")
        self._results_table.setItem(row, 3, QTableWidgetItem(method_text))

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
        self._apply_result_filter()
        self._update_stats_card()

    def _update_stats_card(self):
        total = len(self._result_details)
        matched = sum(1 for d in self._result_details if d.get("success"))
        failed = sum(1 for d in self._result_details if not d.get("success"))
        skipped = sum(1 for d in self._result_details
                      if d.get("has_gps") and d.get("success"))
        overwritten = sum(1 for d in self._result_details if d.get("overwritten"))
        rate = matched / total if total > 0 else 0
        self._stats_label.setText(
            f"总数: {total} | 成功: {matched} | 跳过: {skipped} | 失败: {failed} | 覆盖: {overwritten} | 成功率: {rate:.1%}"
        )

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

        QMessageBox.information(
            self, "处理完成",
            f"处理完成！\n\n总数: {total}\n成功: {matched}\n失败: {failed}\n跳过: {skipped}\n成功率: {rate:.1%}"
        )

    def _apply_result_filter(self):
        filter_idx = self._result_filter.currentIndex()
        for row in range(self._results_table.rowCount()):
            if row >= len(self._result_details):
                self._results_table.setRowHidden(row, False)
                continue
            detail = self._result_details[row]
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

    def _open_photo_browser(self):
        if self._cached_photos:
            dialog = PhotoBrowserDialog(self._cached_photos, self)
            dialog.exec()

    def _on_table_double_click(self, index):
        row = index.row()
        if 0 <= row < len(self._result_details):
            dialog = DetailDialog(self._result_details[row], self)
            dialog.exec()

    def _on_selection_changed(self):
        rows = self._results_table.selectionModel().selectedRows()
        if not rows:
            self._photo_preview.clear()
            return
        row = rows[0].row()
        if 0 <= row < len(self._result_details):
            detail = self._result_details[row]
            photo_path = detail.get("path", "")
            lat = detail.get("latitude")
            lon = detail.get("longitude")
            method = detail.get("method", "")
            method_text = {"interpolated": "插值", "nearest": "就近"}.get(method, "—")
            gps_str = f"{lat:.4f}, {lon:.4f}" if lat is not None and lon is not None else "—"
            info = f"文件: {detail.get('filename', '—')}\nGPS: {gps_str}\n方式: {method_text}"
            self._photo_preview.show_photo(photo_path, info)

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

        mode_id = int(s.get("mode", 0))
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
