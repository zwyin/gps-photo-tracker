"""Detail dialog showing match result for a single photo."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


_REJECT_EXPLANATIONS = {
    "no_gps_coverage": "照片拍摄时间不在任何 GPX 轨迹的时间范围内",
    "time_diff": "照片与最近的 GPS 点时间差超出阈值",
    "gps_distance": "前后 GPS 点距离超出阈值，无法插值",
    "tail_isolated": "照片是首尾孤立照片（未启用匹配首尾）",
    "no_track_points": "对应的 GPX 轨迹段中没有有效的轨迹点",
}


class DetailDialog(QDialog):
    """Show detailed match info for one photo."""

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"照片匹配详情 - {data.get('filename', '')}")
        self.setMinimumSize(520, 500)
        self._build_ui(data)

    def _build_ui(self, data: dict):
        layout = QVBoxLayout(self)

        # Top row: thumbnail + photo info
        top_layout = QHBoxLayout()

        # Thumbnail
        self._thumb = QLabel()
        self._thumb.setFixedSize(300, 300)
        self._thumb.setAlignment(Qt.AlignCenter)
        self._thumb.setStyleSheet("border: 1px solid #ccc; background: #f5f5f5;")
        self._load_thumbnail(data.get("path", ""))
        top_layout.addWidget(self._thumb)

        # Photo info
        info_form = QFormLayout()
        info_form.addRow("文件名:", QLabel(data.get("filename", "")))
        info_form.addRow("路径:", QLabel(str(data.get("path", ""))))
        info_form.addRow("拍摄时间:", QLabel(data.get("capture_time", "—")))
        info_form.addRow("来源 GPX:", QLabel(data.get("source_gpx", "—")))
        top_layout.addLayout(info_form)
        layout.addLayout(top_layout)

        # GPS comparison
        gps_group = QGroupBox("GPS 匹配结果")
        gps_layout = QFormLayout(gps_group)

        has_gps_before = data.get("has_gps", False)
        gps_before_text = "无 GPS 信息"
        if has_gps_before:
            gps_before_text = data.get("gps_before", "有 GPS")
        gps_layout.addRow("匹配前:", QLabel(gps_before_text))

        success = data.get("success", False)
        if success:
            lat = data.get("latitude")
            lon = data.get("longitude")
            alt = data.get("altitude")
            if lat is not None and lon is not None:
                ns = "N" if lat >= 0 else "S"
                ew = "E" if lon >= 0 else "W"
                gps_after = f"{abs(lat):.4f}°{ns}, {abs(lon):.4f}°{ew}"
                gps_layout.addRow("匹配后:", QLabel(gps_after))
                if alt is not None:
                    gps_layout.addRow("海拔:", QLabel(f"{alt:.1f} m"))
            method = data.get("method", "")
            method_map = {"interpolated": "线性插值", "nearest": "就近匹配"}
            gps_layout.addRow("方式:", QLabel(method_map.get(method, "—")))
            time_diff = data.get("time_diff")
            if time_diff is not None:
                gps_layout.addRow("时间差:", QLabel(f"{time_diff:.1f} 秒"))
        else:
            reason = data.get("reject_reason", "")
            reason_map = {
                "no_gps_coverage": "无 GPS 覆盖",
                "time_diff": "时差过大",
                "gps_distance": "距离过大",
                "tail_isolated": "孤立照片",
                "no_track_points": "无轨迹点",
            }
            gps_layout.addRow("状态:", QLabel(f"匹配失败: {reason_map.get(reason, reason)}"))
            explanation = _REJECT_EXPLANATIONS.get(reason, "")
            if explanation:
                gps_layout.addRow("说明:", QLabel(explanation))

        layout.addWidget(gps_group)

        # Interpolation reference points
        if data.get("interpolation_prev"):
            interp_group = QGroupBox("插值参考点")
            interp_layout = QFormLayout(interp_group)

            prev = data["interpolation_prev"]
            prev_text = self._format_point(prev)
            interp_layout.addRow("前一点:", QLabel(prev_text))

            nxt = data.get("interpolation_next", {})
            nxt_text = self._format_point(nxt)
            interp_layout.addRow("后一点:", QLabel(nxt_text))

            dist = data.get("interpolation_distance")
            if dist is not None:
                interp_layout.addRow("前后距离:", QLabel(f"{dist:.1f} m"))

            ratio = data.get("interpolation_ratio")
            if ratio is not None:
                interp_layout.addRow("插值比例:", QLabel(f"{ratio:.1%}"))

            layout.addWidget(interp_group)

        # GPS overwrite comparison
        gps_old = data.get("gps_old")
        gps_new = data.get("gps_new")
        if gps_old and gps_new:
            overwrite_group = QGroupBox("GPS 覆盖对比")
            ow_layout = QFormLayout(overwrite_group)
            ow_layout.addRow("旧 GPS:", QLabel(gps_old))
            ow_layout.addRow("新 GPS:", QLabel(gps_new))
            layout.addWidget(overwrite_group)

        layout.addStretch()

        # Close button
        btn_layout = QHBoxLayout()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _load_thumbnail(self, path_str: str):
        if not path_str:
            self._thumb.setText("无缩略图")
            return
        path = Path(path_str)
        if not path.exists():
            self._thumb.setText("文件不存在")
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._thumb.setText("无法加载")
            return
        scaled = pixmap.scaled(300, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._thumb.setPixmap(scaled)

    @staticmethod
    def _format_point(pt: dict) -> str:
        lat = pt.get("lat", 0)
        lon = pt.get("lon", 0)
        alt = pt.get("alt")
        ns = "N" if lat >= 0 else "S"
        ew = "E" if lon >= 0 else "W"
        text = f"{abs(lat):.4f}°{ns}, {abs(lon):.4f}°{ew}"
        if alt is not None:
            text += f"  {alt:.0f}m"
        return text
