"""Map preview panel: AMap static map with track polyline + photo markers.

Pure preview (no pan/zoom interaction): the static map image is fetched via
QNetworkAccessManager whenever the data or the selected photo changes
(debounced). WGS-84 → GCJ-02 conversion happens on data entry, so everything
stored in this panel is GCJ-02 and ready for AMap rendering.

Degradation is always graceful: missing key / missing data / network failure
just show a hint message — map preview never blocks the tagging workflow.
"""

from PySide6.QtCore import QUrl, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gps_photo_tracker.core.geo import wgs84_to_gcj02
from gps_photo_tracker.service.map_service import (
    DEFAULT_SIZE,
    MapService,
    build_markers_param,
    build_paths_param,
    build_static_map_url,
    fit_view,
    load_amap_credentials,
)

_REFRESH_DEBOUNCE_MS = 300  # coalesce rapid selection changes
_CACHE_LIMIT = 16  # rendered maps kept in memory (URL → QPixmap)


class MapPanel(QWidget):
    """Static map preview: track polyline, photo dots, selected-photo marker."""

    def __init__(
        self,
        parent: QWidget | None = None,
        key: str | None = None,
        secret: str | None = None,
        service: MapService | None = None,
    ):
        super().__init__(parent)
        self._service = service or MapService()
        if key is None or secret is None:
            env_key, env_secret = load_amap_credentials()
            key = key if key is not None else env_key
            secret = secret if secret is not None else env_secret
        self._key = key
        self._secret = secret

        # GCJ-02 state (converted on entry)
        self._track_pts: list[list[tuple[float, float]]] = []
        self._photo_pts: list[tuple[float, float]] = []
        self._selected: tuple[float, float] | None = None

        self._cache: dict[str, QPixmap] = {}
        self._current: QPixmap | None = None
        self._active_url: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._image_label = QLabel("暂无轨迹")
        self._image_label.setMinimumSize(240, 140)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet("background: #e8e8e8; border: 1px solid #ccc;")
        layout.addWidget(self._image_label)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_REFRESH_DEBOUNCE_MS)
        self._debounce.timeout.connect(self.refresh)

        self._nam = QNetworkAccessManager(self)

    # ── Data entry (WGS-84 in → GCJ-02 stored) ─────────────

    def set_track(self, segments: list[dict]) -> None:
        """Store track polylines from worker scan segment dicts (`points` key)."""
        tracks: list[list[tuple[float, float]]] = []
        for seg in segments or []:
            raw = [
                (p["latitude"], p["longitude"])
                for p in (seg.get("points") or [])
                if p.get("latitude") is not None and p.get("longitude") is not None
            ]
            if len(raw) >= 2:
                tracks.append([wgs84_to_gcj02(lat, lon) for lat, lon in raw])
        self._track_pts = tracks
        self._schedule()

    def set_results(self, details: list[dict]) -> None:
        """Store photo positions from result-table row details."""
        pts: list[tuple[float, float]] = []
        for d in details or []:
            lat = d.get("latitude")
            lon = d.get("longitude")
            if lat is not None and lon is not None:
                pts.append(wgs84_to_gcj02(lat, lon))
        self._photo_pts = pts
        self._schedule()

    def set_selected(self, lat: float, lon: float) -> None:
        """Highlight the selected photo as a distinct marker."""
        self._selected = wgs84_to_gcj02(lat, lon)
        self._schedule()

    def clear_selected(self) -> None:
        self._selected = None
        self._schedule()

    # ── Refresh ────────────────────────────────────────────

    def _schedule(self) -> None:
        self._debounce.start()  # restart → rapid updates coalesce into one fetch

    def refresh(self) -> None:
        all_pts = [p for track in self._track_pts for p in track]
        all_pts += self._photo_pts
        if self._selected is not None:
            all_pts.append(self._selected)

        if not all_pts:
            self._show_message("暂无轨迹")
            return
        if not self._key:
            self._show_message("未配置 AMAP_KEY（环境变量或 .env）")
            return

        view = fit_view(all_pts, *DEFAULT_SIZE)
        assert view is not None  # all_pts non-empty
        center, zoom = view
        url = build_static_map_url(
            key=self._key,
            secret=self._secret,
            zoom=zoom,
            center=center,
            paths=build_paths_param(self._track_pts),
            markers=build_markers_param(self._photo_pts, self._selected),
        )
        self._active_url = url

        cached = self._cache.get(url)
        if cached is not None:
            self._display(cached)
            return

        self._show_message("地图加载中…")
        reply = self._nam.get(QNetworkRequest(QUrl(url)))
        reply.finished.connect(lambda r=reply: self._on_reply_finished(r))

    def _on_reply_finished(self, reply: QNetworkReply) -> None:
        url = reply.url().toString()
        error = reply.error()
        data = bytes(reply.readAll()) if error == QNetworkReply.NetworkError.NoError else b""
        reply.deleteLater()
        if error != QNetworkReply.NetworkError.NoError:
            self._show_message("地图加载失败（网络错误）")
            return
        self._handle_png(url, data)

    def _handle_png(self, url: str, data: bytes) -> None:
        """Turn fetched bytes into a pixmap (or an error hint)."""
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self._show_message("地图响应无效")
            return
        self._remember(url, pixmap)
        if url == self._active_url:  # stale replies only populate the cache
            self._display(pixmap)

    def _remember(self, url: str, pixmap: QPixmap) -> None:
        self._cache[url] = pixmap
        while len(self._cache) > _CACHE_LIMIT:
            self._cache.pop(next(iter(self._cache)))

    def _display(self, pixmap: QPixmap) -> None:
        self._current = pixmap
        self._rescale()

    def _show_message(self, message: str) -> None:
        self._current = None
        self._image_label.setPixmap(QPixmap())
        self._image_label.setText(message)

    # ── Resize ─────────────────────────────────────────────

    def _rescale(self) -> None:
        if self._current is None or self._current.isNull():
            return
        size = self._image_label.size()
        if size.width() <= 0:
            size = self._image_label.minimumSize()
        scaled = self._current.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setText("")
        self._image_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rescale()
