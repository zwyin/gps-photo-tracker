"""Result table panel with stats card, filter, and results display."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)


def build_result_panel() -> tuple[QWidget, QLabel, QLabel, QComboBox, QTableWidget, QPushButton, QPushButton]:
    """Build right-side result panel.

    Returns (widget, pre_stats_label, stats_label, result_filter, results_table, review_btn, export_btn).
    """
    widget = QWidget()
    layout = QVBoxLayout(widget)

    # Pre-processing stats
    pre_stats_label = QLabel("")
    pre_stats_label.setStyleSheet("padding: 6px 8px; background: #f5f5f5; border-radius: 4px; font-size: 12px; color: #444;")
    layout.addWidget(pre_stats_label)

    # Stats card
    stats_label = QLabel("匹配结果将在此显示")
    stats_label.setStyleSheet("padding: 6px 8px; background: #f0f0f0; border-radius: 4px; font-size: 12px; color: #333;")
    layout.addWidget(stats_label)

    # Result filter
    filter_row = QHBoxLayout()
    filter_row.addWidget(QLabel("筛选:"))
    result_filter = QComboBox()
    result_filter.addItems(["全部", "成功", "失败", "跳过", "已保护"])
    filter_row.addWidget(result_filter)
    filter_row.addStretch()

    shortcut_hint = QLabel("←→ 跟随GPS | . 保护/取消 | Esc 撤销 | ↑↓ 导航")
    shortcut_hint.setStyleSheet("color: #888; font-size: 11px;")
    filter_row.addWidget(shortcut_hint)

    review_btn = QPushButton("审核")
    review_btn.setFixedWidth(60)
    review_btn.setEnabled(False)
    filter_row.addWidget(review_btn)

    export_btn = QPushButton("导出")
    export_btn.setFixedWidth(60)
    export_btn.setEnabled(False)
    filter_row.addWidget(export_btn)
    layout.addLayout(filter_row)

    # Results table
    results_table = QTableWidget(0, 9)
    results_table.setHorizontalHeaderLabels(["文件名", "日期时间", "GPS(前)", "计算GPS", "GPS(后)", "来源", "状态", "写入状态", "备注"])
    header = results_table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
    results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    results_table.setSortingEnabled(True)
    results_table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
    layout.addWidget(results_table, stretch=1)

    return widget, pre_stats_label, stats_label, result_filter, results_table, review_btn, export_btn
