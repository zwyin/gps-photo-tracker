"""Progress panel with 4-phase progress bars."""

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)


def build_progress_group() -> tuple[QGroupBox, list[QProgressBar], QLabel, QLabel]:
    """Build progress panel with 4 phase bars.

    Returns (group, phase_bars, progress_label, elapsed_label).
    """
    group = QGroupBox("进度")
    layout = QVBoxLayout(group)

    phase_labels = ["扫描GPS", "扫描照片", "匹配", "写入"]
    phase_bars: list[QProgressBar] = []
    for label_text in phase_labels:
        row = QHBoxLayout()
        lbl = QLabel(f"{label_text}:")
        lbl.setFixedWidth(60)
        bar = QProgressBar()
        bar.setValue(0)
        bar.setMaximum(100)
        bar.setFixedHeight(16)
        bar.setTextVisible(False)
        row.addWidget(lbl)
        row.addWidget(bar)
        layout.addLayout(row)
        phase_bars.append(bar)

    progress_label = QLabel("就绪")
    layout.addWidget(progress_label)

    elapsed_label = QLabel("")
    layout.addWidget(elapsed_label)

    return group, phase_bars, progress_label, elapsed_label
