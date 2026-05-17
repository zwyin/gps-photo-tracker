"""Configuration panel widgets for GPS Photo Tracker."""

from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
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
    spin.setToolTip("照片前后无轨迹点的时间窗口。超过此值的孤立照片将被跳过。\n增大此值可匹配更多边缘照片，但可能降低准确度。")
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
    spin2.setToolTip("照片前后均有轨迹点时的最大匹配时间差。\n照片拍摄时间与此窗口内的轨迹点进行匹配。")
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
    spin3.setToolTip("用于插值计算时，前后轨迹点的最大时间跨度。\n在此窗口内的前后轨迹点会通过插值计算照片位置。")
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
    spin4.setToolTip("匹配时允许的最大 GPS 距离偏差。\n轨迹点到照片推测位置的距离超过此值将被拒绝。")
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
    spin5.setToolTip("照片时间与 GPS 时间的校正值。\n正数表示照片时间比 GPS 时间快（如相机时钟偏快）。\n负数表示照片时间比 GPS 时间慢。")
    row5.addWidget(spin5)
    layout.addLayout(row5)
    widgets["offset_spin"] = spin5

    # Checkboxes
    match_isolated_cb = QCheckBox("匹配孤立照片（头部/尾部/中间）")
    match_isolated_cb.setChecked(True)
    match_isolated_cb.setToolTip("允许匹配轨迹开头/结尾/中间的孤立照片。\n开启后，这些照片会使用最近的轨迹点。")
    layout.addWidget(match_isolated_cb)
    widgets["match_isolated_cb"] = match_isolated_cb

    overwrite_gps_cb = QCheckBox("覆盖已有 GPS")
    overwrite_gps_cb.setChecked(False)
    overwrite_gps_cb.setToolTip("覆盖照片中已有的 GPS 数据。\n关闭时，已有 GPS 信息的照片将被跳过。")
    layout.addWidget(overwrite_gps_cb)
    widgets["overwrite_gps_cb"] = overwrite_gps_cb

    keep_struct_cb = QCheckBox("保持目录结构")
    keep_struct_cb.setChecked(True)
    keep_struct_cb.setToolTip("拷贝模式时保持源目录结构到输出目录。\n关闭后所有照片将拷贝到输出目录的根层级。")
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


def build_step_group() -> tuple[QGroupBox, QPushButton, QPushButton, QPushButton, QPushButton]:
    """Build step-based workflow buttons. Returns (group, step1_btn, step2_btn, step3_copy_btn, step3_overwrite_btn)."""
    group = QGroupBox("工作流")
    layout = QHBoxLayout(group)

    step1_btn = QPushButton("① 预览匹配")
    step1_btn.setToolTip("扫描 GPS 轨迹和照片，进行自动匹配预览")

    step2_btn = QPushButton("② 审核")
    step2_btn.setEnabled(False)
    step2_btn.setToolTip("对匹配失败的照片进行人工审核修正")

    step3_copy_btn = QPushButton("③ 拷贝")
    step3_copy_btn.setEnabled(False)
    step3_copy_btn.setToolTip("将匹配结果拷贝到输出目录（保留原文件）")

    step3_overwrite_btn = QPushButton("③ 覆盖")
    step3_overwrite_btn.setEnabled(False)
    step3_overwrite_btn.setToolTip("将匹配结果写入原照片文件")

    layout.addWidget(step1_btn)
    layout.addWidget(step2_btn)
    layout.addWidget(step3_copy_btn)
    layout.addWidget(step3_overwrite_btn)

    return group, step1_btn, step2_btn, step3_copy_btn, step3_overwrite_btn
