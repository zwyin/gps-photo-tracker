"""Settings dialog with parameter persistence via QSettings."""

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QRadioButton,
    QButtonGroup,
)

SETTINGS_KEYS = {
    "isolated_window": 300,
    "middle_time_window": 3600,
    "context_window": 300,
    "max_gps_distance": 200,
    "match_tail": True,
    "time_offset": 0,
    "overwrite_gps": False,
    "keep_structure": True,
    "timezone_offset": 8,
    "mode": 0,  # 0=preview, 1=copy, 2=overwrite
    "log_dir": "",
    "log_retention_days": 30,
    "workers": 1,
    "resume": False,
    "generate_report": False,
}


def load_settings() -> dict:
    s = QSettings("GPSPhotoTracker", "GPSPhotoTracker")
    result = {}
    for k, default in SETTINGS_KEYS.items():
        if isinstance(default, bool):
            result[k] = s.value(k, default, type=bool)
        elif isinstance(default, int):
            result[k] = s.value(k, default, type=int)
        else:
            result[k] = s.value(k, default)
    return result


def save_settings(values: dict) -> None:
    s = QSettings("GPSPhotoTracker", "GPSPhotoTracker")
    for k, v in values.items():
        s.setValue(k, v)


def format_timestamp(ts: float) -> str:
    """Format a UTC timestamp using the configured timezone offset."""
    from datetime import datetime, timezone, timedelta
    s = QSettings("GPSPhotoTracker", "GPSPhotoTracker")
    offset = int(s.value("timezone_offset", 8))
    tz = timezone(timedelta(hours=offset))
    try:
        dt = datetime.fromtimestamp(ts, tz=tz)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError):
        return "—"


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(520)
        self._settings = load_settings()
        self._build_ui()

    def _build_ui(self):
        outer_layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        # Profile management
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("配置预设:"))
        self._profile_cb = QComboBox()
        self._profile_cb.addItem("— 选择预设 —")
        self._profile_cb.addItems(self._list_profiles())
        profile_row.addWidget(self._profile_cb, stretch=1)
        load_btn = QPushButton("加载")
        load_btn.clicked.connect(self._load_profile)
        profile_row.addWidget(load_btn)
        save_as_btn = QPushButton("另存为")
        save_as_btn.clicked.connect(self._save_as_profile)
        profile_row.addWidget(save_as_btn)
        delete_btn = QPushButton("删除")
        delete_btn.clicked.connect(self._delete_profile)
        profile_row.addWidget(delete_btn)
        layout.addLayout(profile_row)

        # Match params
        match_group = QGroupBox("匹配参数")
        match_layout = QFormLayout(match_group)

        self._isolated = self._spin("孤立窗口:", 60, 3600, "isolated_window", " 秒")
        match_layout.addRow(self._isolated[0], self._isolated[1])

        self._middle = self._spin("中间窗口:", 600, 7200, "middle_time_window", " 秒")
        match_layout.addRow(self._middle[0], self._middle[1])

        self._context = self._spin("上下文窗口:", 60, 1800, "context_window", " 秒")
        match_layout.addRow(self._context[0], self._context[1])

        self._distance = self._spin("距离阈值:", 50, 1000, "max_gps_distance", " 米")
        match_layout.addRow(self._distance[0], self._distance[1])

        self._offset = self._spin("时间偏移:", -3600, 3600, "time_offset", " 秒")
        match_layout.addRow(self._offset[0], self._offset[1])

        self._match_tail = QCheckBox("匹配首尾孤立照片")
        self._match_tail.setChecked(self._settings.get("match_tail", True))
        match_layout.addRow(self._match_tail)

        layout.addWidget(match_group)

        # Process options
        proc_group = QGroupBox("处理选项")
        proc_layout = QFormLayout(proc_group)

        self._overwrite = QCheckBox("覆盖已有 GPS")
        self._overwrite.setChecked(self._settings.get("overwrite_gps", False))
        proc_layout.addRow(self._overwrite)

        self._keep_structure = QCheckBox("保持目录结构")
        self._keep_structure.setChecked(self._settings.get("keep_structure", True))
        proc_layout.addRow(self._keep_structure)

        self._resume = QCheckBox("断点续传（拷贝模式）")
        self._resume.setChecked(self._settings.get("resume", False))
        proc_layout.addRow(self._resume)

        self._generate_report = QCheckBox("生成 HTML 报告")
        self._generate_report.setChecked(self._settings.get("generate_report", False))
        proc_layout.addRow(self._generate_report)

        # Workers (experimental)
        workers_row = QHBoxLayout()
        workers_row.addWidget(QLabel("并发线程:"))
        self._workers_spin = QSpinBox()
        self._workers_spin.setRange(1, 8)
        self._workers_spin.setValue(int(self._settings.get("workers", 1)))
        self._workers_spin.setSuffix(" (实验性)")
        workers_row.addWidget(self._workers_spin)
        workers_row.addStretch()
        proc_layout.addRow(workers_row)

        # Default processing mode radio buttons
        self._mode_group = QButtonGroup(self)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("默认处理模式:"))
        self._mode_preview_rb = QRadioButton("预览")
        self._mode_copy_rb = QRadioButton("拷贝")
        self._mode_overwrite_rb = QRadioButton("覆盖")
        self._mode_group.addButton(self._mode_preview_rb, 0)
        self._mode_group.addButton(self._mode_copy_rb, 1)
        self._mode_group.addButton(self._mode_overwrite_rb, 2)
        mode_id = int(self._settings.get("mode", 0))
        [self._mode_preview_rb, self._mode_copy_rb, self._mode_overwrite_rb][mode_id].setChecked(True)
        mode_row.addWidget(self._mode_preview_rb)
        mode_row.addWidget(self._mode_copy_rb)
        mode_row.addWidget(self._mode_overwrite_rb)
        mode_row.addStretch()
        proc_layout.addRow(mode_row)

        layout.addWidget(proc_group)

        # Display settings
        display_group = QGroupBox("显示")
        display_layout = QFormLayout(display_group)
        self._tz_spin = QSpinBox()
        self._tz_spin.setRange(-12, 14)
        self._tz_spin.setValue(int(self._settings.get("timezone_offset", 8)))
        self._tz_spin.setPrefix("UTC")
        self._tz_spin.setSuffix(" (东八区=8)")
        self._tz_spin.setMinimumWidth(150)
        display_layout.addRow("时区偏移:", self._tz_spin)
        layout.addWidget(display_group)

        # Log settings
        log_group = QGroupBox("日志")
        log_layout = QFormLayout(log_group)

        log_dir_row = QHBoxLayout()
        self._log_dir_edit = QLineEdit()
        self._log_dir_edit.setText(str(self._settings.get("log_dir", "")))
        self._log_dir_edit.setPlaceholderText("默认: 应用目录/logs")
        log_dir_btn = QPushButton("浏览")
        log_dir_btn.clicked.connect(self._browse_log_dir)
        log_dir_row.addWidget(self._log_dir_edit)
        log_dir_row.addWidget(log_dir_btn)
        log_layout.addRow("日志目录:", log_dir_row)

        self._retention_spin = QSpinBox()
        self._retention_spin.setRange(1, 365)
        self._retention_spin.setValue(int(self._settings.get("log_retention_days", 30)))
        self._retention_spin.setSuffix(" 天")
        log_layout.addRow("保留天数:", self._retention_spin)

        layout.addWidget(log_group)

        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

        # Buttons (outside scroll area so always visible)
        btn_layout = QHBoxLayout()
        reset_btn = QPushButton("恢复默认值")
        reset_btn.clicked.connect(self._reset_defaults)
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        btn_layout.addStretch()
        btn_layout.addWidget(reset_btn)
        btn_layout.addWidget(save_btn)
        outer_layout.addLayout(btn_layout)

    def _spin(self, label, min_val, max_val, key, suffix):
        lbl = QLabel(label)
        spin = QSpinBox()
        spin.setRange(min_val, max_val)
        spin.setValue(int(self._settings.get(key, SETTINGS_KEYS[key])))
        spin.setSuffix(suffix)
        spin.setMinimumWidth(100)
        return lbl, spin

    def _reset_defaults(self):
        self._apply_values(SETTINGS_KEYS)

    def _browse_log_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择日志目录")
        if path:
            self._log_dir_edit.setText(path)

    def _save(self):
        values = self._collect_form_values()
        save_settings(values)
        self.accept()

    # ── Profile management ──────────────────────────────────

    @staticmethod
    def _list_profiles() -> list[str]:
        s = QSettings("GPSPhotoTracker", "GPSPhotoTracker")
        return s.value("profile_list", [], type=list)

    @staticmethod
    def _set_profile_list(names: list[str]):
        s = QSettings("GPSPhotoTracker", "GPSPhotoTracker")
        s.setValue("profile_list", names)

    def _collect_form_values(self) -> dict:
        return {
            "isolated_window": self._isolated[1].value(),
            "middle_time_window": self._middle[1].value(),
            "context_window": self._context[1].value(),
            "max_gps_distance": self._distance[1].value(),
            "time_offset": self._offset[1].value(),
            "match_tail": self._match_tail.isChecked(),
            "overwrite_gps": self._overwrite.isChecked(),
            "keep_structure": self._keep_structure.isChecked(),
            "resume": self._resume.isChecked(),
            "generate_report": self._generate_report.isChecked(),
            "workers": self._workers_spin.value(),
            "mode": self._mode_group.checkedId(),
            "log_dir": self._log_dir_edit.text(),
            "log_retention_days": self._retention_spin.value(),
            "timezone_offset": self._tz_spin.value(),
        }

    def _apply_values(self, values: dict):
        if "isolated_window" in values:
            self._isolated[1].setValue(int(values["isolated_window"]))
        if "middle_time_window" in values:
            self._middle[1].setValue(int(values["middle_time_window"]))
        if "context_window" in values:
            self._context[1].setValue(int(values["context_window"]))
        if "max_gps_distance" in values:
            self._distance[1].setValue(int(values["max_gps_distance"]))
        if "time_offset" in values:
            self._offset[1].setValue(int(values["time_offset"]))
        if "match_tail" in values:
            self._match_tail.setChecked(bool(values["match_tail"]))
        if "overwrite_gps" in values:
            self._overwrite.setChecked(bool(values["overwrite_gps"]))
        if "keep_structure" in values:
            self._keep_structure.setChecked(bool(values["keep_structure"]))
        if "resume" in values:
            self._resume.setChecked(bool(values["resume"]))
        if "generate_report" in values:
            self._generate_report.setChecked(bool(values["generate_report"]))
        if "workers" in values:
            self._workers_spin.setValue(int(values["workers"]))
        if "mode" in values:
            mode_id = int(values["mode"])
            if 0 <= mode_id <= 2:
                [self._mode_preview_rb, self._mode_copy_rb, self._mode_overwrite_rb][mode_id].setChecked(True)
        if "log_dir" in values:
            self._log_dir_edit.setText(str(values["log_dir"]))
        if "log_retention_days" in values:
            self._retention_spin.setValue(int(values["log_retention_days"]))
        if "timezone_offset" in values:
            self._tz_spin.setValue(int(values["timezone_offset"]))

    def _load_profile(self):
        idx = self._profile_cb.currentIndex()
        if idx <= 0:
            return
        name = self._profile_cb.currentText()
        s = QSettings("GPSPhotoTracker", "GPSPhotoTracker")
        values = s.value(f"profile/{name}", {})
        if values:
            self._apply_values(values)

    def _save_as_profile(self):
        name, ok = QInputDialog.getText(self, "保存配置预设", "预设名称:")
        if not ok or not name.strip():
            return
        name = name.strip()
        s = QSettings("GPSPhotoTracker", "GPSPhotoTracker")
        values = self._collect_form_values()
        s.setValue(f"profile/{name}", values)
        profiles = self._list_profiles()
        if name not in profiles:
            profiles.append(name)
            self._set_profile_list(profiles)
            self._profile_cb.addItem(name)
        self._profile_cb.setCurrentText(name)

    def _delete_profile(self):
        idx = self._profile_cb.currentIndex()
        if idx <= 0:
            return
        name = self._profile_cb.currentText()
        reply = QMessageBox.question(
            self, "删除预设", f"确定删除预设「{name}」？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        s = QSettings("GPSPhotoTracker", "GPSPhotoTracker")
        s.remove(f"profile/{name}")
        profiles = self._list_profiles()
        if name in profiles:
            profiles.remove(name)
            self._set_profile_list(profiles)
        self._profile_cb.removeItem(idx)
        self._profile_cb.setCurrentIndex(0)
