"""Tests for gui/map_panel.py (logic only — no live rendering/network)."""

import io
from unittest.mock import patch

import pytest

from PySide6.QtWidgets import QApplication, QTableWidgetItem

from gps_photo_tracker.core.geo import wgs84_to_gcj02
from gps_photo_tracker.gui.map_panel import MapPanel
from gps_photo_tracker.gui.main_window import MainWindow
from gps_photo_tracker.service.map_service import (
    build_markers_param,
    build_paths_param,
    build_static_map_url,
    fit_view,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _png_bytes() -> bytes:
    """Minimal real PNG via Pillow (test-only dependency)."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(30, 144, 255)).save(buf, "PNG")
    return buf.getvalue()


def _seg(points, filename="t.gpx"):
    return {
        "filename": filename,
        "points": [{"latitude": lat, "longitude": lon} for lat, lon in points],
    }


# eviltransform reference: WGS (31.1774276, 121.5272106) → GCJ (31.17530398…, 121.53154186…)
WGS_PTS = [(31.1774276, 121.5272106), (31.1774276 + 0.001, 121.5272106 + 0.001)]


class TestMapPanelData:

    def test_initial_placeholder(self, qapp):
        panel = MapPanel(key="k", secret="s")
        assert "暂无轨迹" in panel._image_label.text()

    def test_set_track_converts_wgs_to_gcj(self, qapp):
        panel = MapPanel(key="k", secret="s")
        panel._debounce.stop()  # inspect without firing refresh
        panel.set_track([_seg(WGS_PTS)])
        assert len(panel._track_pts) == 1
        lat0, lon0 = panel._track_pts[0][0]
        assert lat0 == pytest.approx(31.17530398, abs=1e-6)
        assert lon0 == pytest.approx(121.53154186, abs=1e-6)

    def test_set_track_skips_too_short_segments(self, qapp):
        panel = MapPanel(key="k", secret="s")
        panel.set_track([_seg([(31.0, 121.0)])])  # single point
        assert panel._track_pts == []

    def test_set_track_empty_clears(self, qapp):
        panel = MapPanel(key="k", secret="s")
        panel.set_track([_seg(WGS_PTS)])
        panel.set_track([])
        assert panel._track_pts == []

    def test_set_results_filters_missing_gps(self, qapp):
        panel = MapPanel(key="k", secret="s")
        panel.set_results([
            {"latitude": 31.1774276, "longitude": 121.5272106},
            {"latitude": None, "longitude": None},
            {"latitude": 31.2, "longitude": 121.6},
        ])
        assert len(panel._photo_pts) == 2

    def test_set_selected_and_clear(self, qapp):
        panel = MapPanel(key="k", secret="s")
        panel.set_selected(31.1774276, 121.5272106)
        assert panel._selected is not None
        assert panel._selected[0] == pytest.approx(31.17530398, abs=1e-6)
        panel.clear_selected()
        assert panel._selected is None

    def test_debounce_coalesces_rapid_updates(self, qapp, monkeypatch):
        panel = MapPanel(key="k", secret="s")
        calls = []
        monkeypatch.setattr(panel, "refresh", lambda: calls.append(1))
        panel.set_track([_seg(WGS_PTS)])
        panel.set_selected(31.1774276, 121.5272106)
        assert panel._debounce.isActive()
        assert calls == []  # not refreshed yet — waiting for debounce


class TestMapPanelRefresh:

    def _panel(self, qapp):
        panel = MapPanel(key="test-key", secret="test-secret")
        return panel

    def test_refresh_without_data_shows_placeholder(self, qapp):
        panel = self._panel(qapp)
        panel.refresh()
        assert "暂无轨迹" in panel._image_label.text()

    def test_refresh_without_key_shows_hint(self, qapp):
        with patch(
            "gps_photo_tracker.gui.map_panel.load_amap_credentials",
            return_value=(None, None),
        ):
            panel = MapPanel()
        panel.set_track([_seg(WGS_PTS)])
        panel._debounce.stop()
        panel.refresh()
        assert "AMAP_KEY" in panel._image_label.text()

    def test_refresh_uses_cache_no_network(self, qapp):
        from PySide6.QtGui import QPixmap

        panel = self._panel(qapp)
        panel.set_track([_seg(WGS_PTS)])
        panel._debounce.stop()
        # Rebuild the exact URL the panel will build, seed the cache.
        all_pts = [p for t in panel._track_pts for p in t]
        center, zoom = fit_view(all_pts, 640, 360)
        url = build_static_map_url(
            key="test-key", secret="test-secret", zoom=zoom, center=center,
            paths=build_paths_param(panel._track_pts),
            markers=build_markers_param(panel._photo_pts, panel._selected),
        )
        panel._cache[url] = QPixmap(8, 8)
        panel.refresh()
        assert not panel._image_label.pixmap().isNull()

    def test_handle_png_valid_displays_and_caches(self, qapp):
        panel = self._panel(qapp)
        panel._active_url = "https://example.com/map"
        panel._handle_png("https://example.com/map", _png_bytes())
        assert not panel._image_label.pixmap().isNull()
        assert "https://example.com/map" in panel._cache

    def test_handle_png_invalid_shows_error(self, qapp):
        panel = self._panel(qapp)
        panel._handle_png("https://example.com/map", b"not-an-image")
        assert "失败" in panel._image_label.text() or "无效" in panel._image_label.text()

    def test_handle_png_stale_url_not_displayed(self, qapp):
        panel = self._panel(qapp)
        panel._active_url = "https://example.com/current"
        panel._handle_png("https://example.com/stale", _png_bytes())
        # Cached but not displayed (stale reply lost the race).
        assert "https://example.com/stale" in panel._cache
        assert panel._image_label.pixmap().isNull()

    def test_cache_eviction_fifo(self, qapp):
        panel = self._panel(qapp)
        from PySide6.QtGui import QPixmap

        for i in range(20):
            panel._remember(f"url-{i}", QPixmap(4, 4))
        assert len(panel._cache) <= 16


class TestMainWindowIntegration:

    @pytest.fixture
    def main_window(self, qapp):
        window = MainWindow()
        yield window
        window.close()

    def test_map_panel_exists_in_right_panel(self, main_window):
        assert isinstance(main_window._map_panel, MapPanel)
        assert not main_window._map_panel.isHidden()  # visible by default

    def test_map_toggle_action(self, main_window):
        action = main_window._toggle_map_action
        assert action is not None and action.isCheckable() and action.isChecked()
        # Handler semantics (menu action is wired to the same method).
        main_window._toggle_map_panel(False)
        assert main_window._map_panel.isHidden()
        main_window._toggle_map_panel(True)
        assert not main_window._map_panel.isHidden()

    def test_on_scan_done_feeds_track(self, main_window):
        main_window._on_scan_done([
            {**_seg(WGS_PTS), "start": 0.0, "end": 1.0, "point_count": 2},
        ])
        assert len(main_window._map_panel._track_pts) == 1
        lat0, _ = main_window._map_panel._track_pts[0][0]
        assert lat0 == pytest.approx(31.17530398, abs=1e-6)

    def test_on_done_feeds_results(self, main_window, monkeypatch):
        # Neutralize the delayed "处理完成" modal (same pattern as test_gui.py).
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.information", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            "PySide6.QtCore.QTimer.singleShot", lambda ms, cb: cb()
        )
        main_window._result_details = [
            {"latitude": 31.1774276, "longitude": 121.5272106, "filename": "a.jpg"},
        ]
        main_window._on_done({"total": 1, "matched": 1, "failed": 0,
                              "skipped": 0, "overwritten": 0, "success_rate": 1.0})
        assert len(main_window._map_panel._photo_pts) == 1

    def test_selection_sets_selected_marker(self, main_window):
        main_window._result_details = [{
            "filename": "a.jpg", "path": "/tmp/a.jpg",
            "latitude": 31.1774276, "longitude": 121.5272106, "method": "interpolated",
        }]
        main_window._results_table.insertRow(0)
        main_window._results_table.setItem(0, 0, QTableWidgetItem("a.jpg"))
        main_window._results_table.selectRow(0)
        assert main_window._map_panel._selected is not None

    def test_selection_without_gps_clears(self, main_window):
        main_window._map_panel.set_selected(31.1774276, 121.5272106)
        main_window._result_details = [{
            "filename": "b.jpg", "path": "/tmp/b.jpg",
            "latitude": None, "longitude": None, "method": "",
        }]
        main_window._results_table.insertRow(0)
        main_window._results_table.setItem(0, 0, QTableWidgetItem("b.jpg"))
        main_window._results_table.selectRow(0)
        assert main_window._map_panel._selected is None
