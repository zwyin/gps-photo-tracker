"""Detail dialog showing match result for a single photo."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class DetailDialog(QDialog):
    """Show detailed match info for one photo."""

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"照片匹配详情 - {data.get('filename', '')}")
        self.setMinimumSize(420, 380)
        self._build_ui(data)

    def _build_ui(self, data: dict):
        layout = QVBoxLayout(self)

        # Photo info
        info_group = QGroupBox("照片信息")
        info_layout = QFormLayout(info_group)
        info_layout.addRow("文件名:", QLabel(data.get("filename", "")))
        info_layout.addRow("路径:", QLabel(str(data.get("path", ""))))
        layout.addWidget(info_group)

        # Match result
        result_group = QGroupBox("匹配结果")
        result_layout = QFormLayout(result_group)

        success = data.get("success", False)
        result_layout.addRow("状态:", QLabel("成功" if success else "失败"))

        method = data.get("method", "")
        method_map = {"interpolated": "线性插值", "nearest": "就近匹配"}
        result_layout.addRow("方式:", QLabel(method_map.get(method, "—")))

        lat = data.get("latitude")
        lon = data.get("longitude")
        alt = data.get("altitude")
        if lat is not None and lon is not None:
            result_layout.addRow("GPS:", QLabel(f"{lat:.6f}, {lon:.6f}"))
        else:
            result_layout.addRow("GPS:", QLabel("未匹配"))
        if alt is not None:
            result_layout.addRow("海拔:", QLabel(f"{alt:.1f} m"))

        reason = data.get("reject_reason", "")
        if reason:
            reason_map = {
                "no_gps_coverage": "无GPS覆盖", "time_diff": "时差过大",
                "gps_distance": "距离过大", "tail_isolated": "孤立照片",
                "no_track_points": "无轨迹点",
            }
            result_layout.addRow("拒绝原因:", QLabel(reason_map.get(reason, reason)))

        time_diff = data.get("time_diff")
        if time_diff is not None:
            result_layout.addRow("时间差:", QLabel(f"{time_diff:.1f} 秒"))

        layout.addWidget(result_group)

        # Interpolation details
        if data.get("interpolation_prev"):
            interp_group = QGroupBox("插值参考点")
            interp_layout = QFormLayout(interp_group)

            prev = data["interpolation_prev"]
            interp_layout.addRow("前一点:",
                QLabel(f"{prev.get('lat', 0):.6f}, {prev.get('lon', 0):.6f}  {prev.get('alt', '')}m"))

            nxt = data.get("interpolation_next", {})
            interp_layout.addRow("后一点:",
                QLabel(f"{nxt.get('lat', 0):.6f}, {nxt.get('lon', 0):.6f}  {nxt.get('alt', '')}m"))

            dist = data.get("interpolation_distance")
            if dist is not None:
                interp_layout.addRow("前后距离:", QLabel(f"{dist:.1f} m"))

            ratio = data.get("interpolation_ratio")
            if ratio is not None:
                interp_layout.addRow("插值比例:", QLabel(f"{ratio:.1%}"))

            layout.addWidget(interp_group)

        layout.addStretch()

        # Close button
        btn_layout = QHBoxLayout()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
