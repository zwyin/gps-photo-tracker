"""Photo browser dialog — view scanned photos with filter/sort/search."""

from gps_photo_tracker.gui.settings_dialog import format_timestamp

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QPixmapCache
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class PhotoBrowserDialog(QDialog):
    """Browse all scanned photos with filtering and thumbnail preview."""

    def __init__(self, photos: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("照片列表")
        self.setMinimumSize(700, 500)
        self._photos = photos
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Toolbar: filter + search
        toolbar = QHBoxLayout()

        self._filter_cb = QComboBox()
        self._filter_cb.addItems(["全部", "有GPS", "无GPS"])
        self._filter_cb.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(QLabel("筛选:"))
        toolbar.addWidget(self._filter_cb)

        self._sort_cb = QComboBox()
        self._sort_cb.addItems(["文件名", "拍摄时间", "GPS状态"])
        self._sort_cb.currentIndexChanged.connect(self._apply_sort)
        toolbar.addWidget(QLabel("排序:"))
        toolbar.addWidget(self._sort_cb)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索文件名...")
        self._search_edit.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self._search_edit)

        layout.addLayout(toolbar)

        # Table
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["文件名", "拍摄时间", "GPS状态", "GPS坐标"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.selectionModel().selectionChanged.connect(self._on_selection)
        layout.addWidget(self._table, stretch=1)

        # Thumbnail + info
        thumb_row = QHBoxLayout()
        self._thumb_label = QLabel()
        self._thumb_label.setFixedSize(150, 150)
        self._thumb_label.setStyleSheet("background: #e8e8e8; border: 1px solid #ccc;")
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_row.addWidget(self._thumb_label)
        self._info_label = QLabel("选中照片查看详情")
        self._info_label.setWordWrap(True)
        thumb_row.addWidget(self._info_label, stretch=1)
        layout.addLayout(thumb_row)

        # Summary
        total = len(self._photos)
        with_gps = sum(1 for p in self._photos if p.get("has_gps"))
        self._summary = QLabel(f"共 {total} 张照片, {with_gps} 张有GPS, {total - with_gps} 张无GPS")
        self._summary.setStyleSheet("padding: 6px; background: #f0f0f0; border-radius: 4px;")
        layout.addWidget(self._summary)

        # Close
        btn_row = QHBoxLayout()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        # Initial populate
        self._filtered: list[dict] = list(self._photos)
        self._pending_thumb_path: str = ""
        # QPixmapCache size limit is set once at app startup (run_app); this
        # dialog must not override it (process-global singleton — v0.22.0 M2).
        self._populate_table()

    def _populate_table(self):
        self._table.setRowCount(len(self._filtered))
        for i, p in enumerate(self._filtered):
            self._table.setItem(i, 0, QTableWidgetItem(p.get("filename", "")))
            self._table.setItem(i, 1, QTableWidgetItem(self._fmt_time(p.get("timestamp", 0))))
            has_gps = p.get("has_gps", False)
            self._table.setItem(i, 2, QTableWidgetItem("有" if has_gps else "无"))
            lat = p.get("latitude")
            lon = p.get("longitude")
            coord = f"{lat:.4f}, {lon:.4f}" if lat is not None and lon is not None else "—"
            self._table.setItem(i, 3, QTableWidgetItem(coord))

    def _apply_filter(self):
        text = self._search_edit.text().lower()
        filter_idx = self._filter_cb.currentIndex()
        filtered = []
        for p in self._photos:
            # Text search
            if text and text not in p.get("filename", "").lower():
                continue
            # GPS filter
            if filter_idx == 1 and not p.get("has_gps"):
                continue
            if filter_idx == 2 and p.get("has_gps"):
                continue
            filtered.append(p)
        self._filtered = filtered
        self._apply_sort_to_filtered()

    def _apply_sort(self):
        self._apply_sort_to_filtered()

    def _apply_sort_to_filtered(self):
        sort_idx = self._sort_cb.currentIndex()
        if sort_idx == 0:
            self._filtered.sort(key=lambda p: p.get("filename", ""))
        elif sort_idx == 1:
            self._filtered.sort(key=lambda p: p.get("timestamp", 0))
        else:
            self._filtered.sort(key=lambda p: (0 if p.get("has_gps") else 1, p.get("filename", "")))
        self._populate_table()

    def _on_selection(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            self._thumb_label.clear()
            self._info_label.setText("选中照片查看详情")
            return
        row = rows[0].row()
        if 0 <= row < len(self._filtered):
            p = self._filtered[row]
            photo_path = p.get("path", "")

            # Update info immediately
            lat = p.get("latitude")
            lon = p.get("longitude")
            alt = p.get("altitude")
            coord = f"{lat:.4f}, {lon:.4f}" if lat is not None and lon is not None else "—"
            alt_str = f"{alt:.1f}m" if alt is not None else "—"
            info = (
                f"文件: {p.get('filename', '—')}\n"
                f"路径: {photo_path}\n"
                f"拍摄: {self._fmt_time(p.get('timestamp', 0))}\n"
                f"GPS: {coord}  海拔: {alt_str}"
            )
            self._info_label.setText(info)

            # Async thumbnail with QPixmapCache
            if photo_path:
                cache_key = f"thumb:{photo_path}"
                cached = QPixmapCache.find(cache_key)
                if cached:
                    self._thumb_label.setPixmap(cached)
                else:
                    self._thumb_label.setText("加载中...")
                    self._pending_thumb_path = photo_path
                    QTimer.singleShot(10, self._load_thumbnail)

    def _load_thumbnail(self):
        path = self._pending_thumb_path
        if not path:
            return
        cache_key = f"thumb:{path}"
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            from pathlib import Path
            from gps_photo_tracker.core.orientation import OrientationReader
            orientation = OrientationReader.get_orientation(Path(path))
            if orientation and orientation != 1:
                pixmap = OrientationReader.apply_orientation(pixmap, orientation)
            scaled = pixmap.scaled(
                150, 150,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            QPixmapCache.insert(cache_key, scaled)
            # Only apply if still viewing the same photo
            if path == self._pending_thumb_path:
                self._thumb_label.setPixmap(scaled)
        else:
            self._thumb_label.clear()

    @staticmethod
    def _fmt_time(ts: float) -> str:
        if not ts:
            return "—"
        return format_timestamp(ts)
