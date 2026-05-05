"""Settings dialog with parameter persistence via QSettings."""

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
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
    "mode": 0,  # 0=preview, 1=copy, 2=overwrite
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


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(400)
        self._settings = load_settings()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Match params
        match_group = QGroupBox("匹配参数")
        match_layout = QFormLayout(match_group)

        self._isolated = self._spin("孤立窗口:", 30, 7200, "isolated_window", " 秒")
        match_layout.addRow(self._isolated[0], self._isolated[1])

        self._middle = self._spin("中间窗口:", 60, 14400, "middle_time_window", " 秒")
        match_layout.addRow(self._middle[0], self._middle[1])

        self._context = self._spin("上下文窗口:", 30, 3600, "context_window", " 秒")
        match_layout.addRow(self._context[0], self._context[1])

        self._distance = self._spin("距离阈值:", 50, 5000, "max_gps_distance", " 米")
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

        # Buttons
        btn_layout = QHBoxLayout()
        reset_btn = QPushButton("恢复默认值")
        reset_btn.clicked.connect(self._reset_defaults)
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        btn_layout.addStretch()
        btn_layout.addWidget(reset_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def _spin(self, label, min_val, max_val, key, suffix):
        lbl = QLabel(label)
        spin = QSpinBox()
        spin.setRange(min_val, max_val)
        spin.setValue(int(self._settings.get(key, SETTINGS_KEYS[key])))
        spin.setSuffix(suffix)
        return lbl, spin

    def _reset_defaults(self):
        for key, default in SETTINGS_KEYS.items():
            self._settings[key] = default
        self._isolated[1].setValue(SETTINGS_KEYS["isolated_window"])
        self._middle[1].setValue(SETTINGS_KEYS["middle_time_window"])
        self._context[1].setValue(SETTINGS_KEYS["context_window"])
        self._distance[1].setValue(SETTINGS_KEYS["max_gps_distance"])
        self._offset[1].setValue(SETTINGS_KEYS["time_offset"])
        self._match_tail.setChecked(SETTINGS_KEYS["match_tail"])
        self._overwrite.setChecked(SETTINGS_KEYS["overwrite_gps"])
        self._keep_structure.setChecked(SETTINGS_KEYS["keep_structure"])
        self._mode_preview_rb.setChecked(True)

    def _save(self):
        values = {
            "isolated_window": self._isolated[1].value(),
            "middle_time_window": self._middle[1].value(),
            "context_window": self._context[1].value(),
            "max_gps_distance": self._distance[1].value(),
            "time_offset": self._offset[1].value(),
            "match_tail": self._match_tail.isChecked(),
            "overwrite_gps": self._overwrite.isChecked(),
            "keep_structure": self._keep_structure.isChecked(),
            "mode": self._mode_group.checkedId(),
        }
        save_settings(values)
        self.accept()
