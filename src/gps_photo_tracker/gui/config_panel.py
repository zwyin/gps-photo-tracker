"""Configuration panel widgets for GPS Photo Tracker."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QButtonGroup,
    QSpinBox,
    QVBoxLayout,
    QPushButton,
)


def build_params_group() -> tuple[QGroupBox, dict]:
    """Build parameter configuration panel. Returns (group, widget_dict)."""
    group = QGroupBox("参数配置")
    layout = QVBoxLayout(group)
    widgets = {}

    # Isolated window (spec BF-01: 60-3600)
    row1 = QHBoxLayout()
    row1.addWidget(QLabel("孤立窗口:"))
    spin = QSpinBox()
    spin.setRange(60, 3600)
    spin.setValue(300)
    spin.setSuffix(" 秒")
    row1.addWidget(spin)
    layout.addLayout(row1)
    widgets["isolated_spin"] = spin

    # Middle time window (spec BF-01: 600-7200)
    row2 = QHBoxLayout()
    row2.addWidget(QLabel("中间窗口:"))
    spin2 = QSpinBox()
    spin2.setRange(600, 7200)
    spin2.setValue(3600)
    spin2.setSuffix(" 秒")
    row2.addWidget(spin2)
    layout.addLayout(row2)
    widgets["middle_spin"] = spin2

    # Context window (spec BF-01: 60-1800)
    row3 = QHBoxLayout()
    row3.addWidget(QLabel("上下文窗口:"))
    spin3 = QSpinBox()
    spin3.setRange(60, 1800)
    spin3.setValue(300)
    spin3.setSuffix(" 秒")
    row3.addWidget(spin3)
    layout.addLayout(row3)
    widgets["context_spin"] = spin3

    # Max distance (spec BF-01: 50-1000)
    row4 = QHBoxLayout()
    row4.addWidget(QLabel("距离阈值:"))
    spin4 = QSpinBox()
    spin4.setRange(50, 1000)
    spin4.setValue(200)
    spin4.setSuffix(" 米")
    row4.addWidget(spin4)
    layout.addLayout(row4)
    widgets["distance_spin"] = spin4

    # Time offset
    row5 = QHBoxLayout()
    row5.addWidget(QLabel("时间偏移:"))
    spin5 = QSpinBox()
    spin5.setRange(-3600, 3600)
    spin5.setValue(0)
    spin5.setSuffix(" 秒")
    row5.addWidget(spin5)
    layout.addLayout(row5)
    widgets["offset_spin"] = spin5

    # Checkboxes
    match_tail_cb = QCheckBox("匹配首尾孤立照片")
    match_tail_cb.setChecked(True)
    layout.addWidget(match_tail_cb)
    widgets["match_tail_cb"] = match_tail_cb

    overwrite_gps_cb = QCheckBox("覆盖已有 GPS")
    overwrite_gps_cb.setChecked(False)
    layout.addWidget(overwrite_gps_cb)
    widgets["overwrite_gps_cb"] = overwrite_gps_cb

    keep_struct_cb = QCheckBox("保持目录结构")
    keep_struct_cb.setChecked(True)
    layout.addWidget(keep_struct_cb)
    widgets["keep_struct_cb"] = keep_struct_cb

    # Auto-tune button
    auto_tune_btn = QPushButton("智能推荐参数")
    auto_tune_btn.setToolTip("根据扫描到的轨迹和照片数据自动推荐匹配参数")
    layout.addWidget(auto_tune_btn)
    widgets["auto_tune_btn"] = auto_tune_btn

    # Workers spinbox
    row_workers = QHBoxLayout()
    row_workers.addWidget(QLabel("并发线程:"))
    workers_spin = QSpinBox()
    workers_spin.setRange(1, 8)
    workers_spin.setValue(1)
    workers_spin.setToolTip("实验性功能。多线程可加速大批量写入，但可能影响稳定性。")
    row_workers.addWidget(workers_spin)
    layout.addLayout(row_workers)
    widgets["workers_spin"] = workers_spin

    return group, widgets


def build_mode_group() -> tuple[QGroupBox, QButtonGroup, dict]:
    """Build process mode selection panel. Returns (group, button_group, radio_dict)."""
    group = QGroupBox("处理模式")
    layout = QHBoxLayout(group)

    btn_group = QButtonGroup(group)
    radios = {}

    rb_preview = QRadioButton("预览")
    rb_preview.setChecked(True)
    btn_group.addButton(rb_preview, 0)
    layout.addWidget(rb_preview)
    radios["preview_rb"] = rb_preview

    rb_copy = QRadioButton("拷贝")
    btn_group.addButton(rb_copy, 1)
    layout.addWidget(rb_copy)
    radios["copy_rb"] = rb_copy

    rb_overwrite = QRadioButton("覆盖")
    btn_group.addButton(rb_overwrite, 2)
    layout.addWidget(rb_overwrite)
    radios["overwrite_rb"] = rb_overwrite

    return group, btn_group, radios
