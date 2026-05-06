"""Result table panel with stats card, filter, and results display."""

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)


def build_result_panel() -> tuple[QWidget, QLabel, QComboBox, QTableWidget]:
    """Build right-side result panel.

    Returns (widget, stats_label, result_filter, results_table).
    """
    widget = QWidget()
    layout = QVBoxLayout(widget)

    # Stats card
    stats_label = QLabel("匹配结果将在此显示")
    stats_label.setStyleSheet("padding: 8px; background: #f0f0f0; border-radius: 4px;")
    layout.addWidget(stats_label)

    # Result filter
    filter_row = QHBoxLayout()
    filter_row.addWidget(QLabel("筛选:"))
    result_filter = QComboBox()
    result_filter.addItems(["全部", "成功", "失败", "跳过"])
    filter_row.addWidget(result_filter)
    filter_row.addStretch()
    layout.addLayout(filter_row)

    # Results table
    results_table = QTableWidget(0, 5)
    results_table.setHorizontalHeaderLabels(["文件名", "GPS(前)", "GPS(后)", "方式", "状态"])
    results_table.horizontalHeader().setStretchLastSection(True)
    results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    results_table.setSortingEnabled(True)
    layout.addWidget(results_table, stretch=1)

    return widget, stats_label, result_filter, results_table
