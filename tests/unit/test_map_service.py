"""Tests for service/map_service.py: AMap static map URL building & fetching.

URL/param formats below were validated against the live AMap API on 2026-09-11
(see docs/superpowers/specs/2026-09-11-map-view-design.md). No real key appears
in any assertion — literals use "test-key"/"test-secret" only.
"""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from gps_photo_tracker.service.map_service import (
    DEFAULT_SIZE,
    ZOOM_MAX,
    ZOOM_MIN,
    MapFetchError,
    MapService,
    build_markers_param,
    build_paths_param,
    build_static_map_url,
    fit_view,
    load_amap_credentials,
    sign_params,
)

BEIJING = (39.911954, 116.377817)
SHANGHAI = (31.1774276, 121.5272106)


# ── Credentials ────────────────────────────────────────────


class TestLoadAmapCredentials:

    def test_env_vars_win(self):
        key, secret = load_amap_credentials(
            env={"AMAP_KEY": "k1", "AMAP_SECRET": "s1"}, dotenv_path=Path("/nonexistent")
        )
        assert (key, secret) == ("k1", "s1")

    def test_dotenv_fallback(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# comment line\n"
            'AMAP_KEY="quoted-key"\n'
            "AMAP_SECRET='single-quoted'\n"
            "\n"
            "OTHER_VAR=x\n",
            encoding="utf-8",
        )
        key, secret = load_amap_credentials(env={}, dotenv_path=env_file)
        assert (key, secret) == ("quoted-key", "single-quoted")

    def test_env_overrides_dotenv_per_variable(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("AMAP_KEY=from-file\nAMAP_SECRET=file-secret\n", encoding="utf-8")
        key, secret = load_amap_credentials(
            env={"AMAP_KEY": "from-env"}, dotenv_path=env_file
        )
        assert (key, secret) == ("from-env", "file-secret")

    def test_missing_file_returns_none_none(self, tmp_path):
        assert load_amap_credentials(env={}, dotenv_path=tmp_path / ".env") == (None, None)

    def test_blank_values_treated_as_missing(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("AMAP_KEY=\nAMAP_SECRET=  \n", encoding="utf-8")
        assert load_amap_credentials(env={}, dotenv_path=env_file) == (None, None)

    def test_whitespace_and_inline_comment_tolerance(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("  AMAP_KEY =  spaced-key  \n", encoding="utf-8")
        key, secret = load_amap_credentials(env={}, dotenv_path=env_file)
        assert key == "spaced-key"
        assert secret is None


# ── View fitting ───────────────────────────────────────────


class TestFitView:

    def test_empty_returns_none(self):
        assert fit_view([], 640, 360) is None

    def test_single_point_max_zoom(self):
        center, zoom = fit_view([BEIJING], 640, 360)
        assert center == BEIJING
        assert zoom == ZOOM_MAX

    def test_center_is_bbox_midpoint(self):
        center, _ = fit_view([(30.0, 100.0), (40.0, 120.0)], 640, 360)
        assert center[0] == pytest.approx(35.0)
        assert center[1] == pytest.approx(110.0)

    def test_far_apart_points_low_zoom(self):
        _, zoom = fit_view([BEIJING, SHANGHAI], 640, 360)
        assert zoom <= 5, f"country-scale span should fit at low zoom, got {zoom}"

    def test_tight_cluster_high_zoom(self):
        # ~1 km cluster → street-level view.
        pts = [(31.1774, 121.5272), (31.1783, 121.5282)]
        _, zoom = fit_view(pts, 640, 360)
        assert zoom >= 14, f"~1 km cluster should get high zoom, got {zoom}"

    def test_zoom_clamped_to_bounds(self):
        # Half-globe span → still >= ZOOM_MIN.
        _, zoom = fit_view([(0.0, -80.0), (60.0, 140.0)], 640, 360)
        assert zoom == ZOOM_MIN

    def test_wider_viewport_never_lowers_zoom(self):
        pts = [BEIJING, SHANGHAI]
        _, small = fit_view(pts, 320, 180)
        _, wide = fit_view(pts, 1024, 1024)
        assert wide >= small

    def test_padding_argument_accepted(self):
        fit_view([BEIJING, SHANGHAI], 640, 360, padding=1.0)  # must not raise


# ── Paths / markers params ─────────────────────────────────


class TestBuildPathsParam:

    def test_none_for_no_segments(self):
        assert build_paths_param([]) is None
        assert build_paths_param([[]]) is None

    def test_single_segment_format(self):
        got = build_paths_param([[(39.90, 116.39), (39.91, 116.40)]])
        assert got == "4,0x0000FF,0.8,,:116.390000,39.900000;116.400000,39.910000"

    def test_two_segments_pipe_joined(self):
        seg1 = [(39.90, 116.39), (39.91, 116.40)]
        seg2 = [(39.92, 116.41), (39.93, 116.42)]
        got = build_paths_param([seg1, seg2])
        assert got == (
            "4,0x0000FF,0.8,,:116.390000,39.900000;116.400000,39.910000"
            "|4,0x0000FF,0.8,,:116.410000,39.920000;116.420000,39.930000"
        )

    def test_max_four_groups(self):
        segs = [[(float(i), 100.0 + i), (float(i) + 0.1, 100.1 + i)] for i in range(6)]
        got = build_paths_param(segs)
        assert got.count("|") == 3  # 4 groups = 3 separators

    def test_downsampling_keeps_first_last_and_cap(self):
        seg = [(10.0 + i * 0.001, 100.0) for i in range(1000)]
        got = build_paths_param([seg])
        points = got.split(",:")[1].split(";")
        assert len(points) == 128
        assert points[0] == "100.000000,10.000000"
        assert points[-1] == "100.000000,10.999000"


class TestBuildMarkersParam:

    def test_none_for_no_points(self):
        assert build_markers_param([]) is None

    def test_bulk_group_format(self):
        got = build_markers_param([(31.10, 121.50), (31.20, 121.60)])
        assert got == "small,0x2A6FDB,:121.500000,31.100000;121.600000,31.200000"

    def test_selected_appended_as_distinct_group(self):
        pts = [(31.10, 121.50), (31.15, 121.55)]
        got = build_markers_param(pts, selected=(31.20, 121.60))
        assert got == (
            "small,0x2A6FDB,:121.500000,31.100000;121.550000,31.150000"
            "|large,0xFF0000,S:121.600000,31.200000"
        )

    def test_marker_cap_even_sampling(self):
        pts = [(10.0 + i * 0.001, 100.0) for i in range(500)]
        got = build_markers_param(pts)
        points = got.split(",:")[1].split(";")
        assert len(points) == 96
        assert points[0].endswith("10.000000")
        assert points[-1].endswith("10.499000")


# ── Signature & URL ────────────────────────────────────────


class TestSignParams:

    def test_known_vector(self):
        # md5("key=test-key&zoom=11" + "test-secret") — precomputed literal.
        assert sign_params({"key": "test-key", "zoom": "11"}, "test-secret") == (
            "6092ef61ef5a79187a97e2d8ef53230b"
        )

    def test_sorted_regardless_of_input_order(self):
        assert sign_params({"zoom": "11", "key": "test-key"}, "test-secret") == (
            sign_params({"key": "test-key", "zoom": "11"}, "test-secret")
        )


class TestBuildStaticMapUrl:

    def test_minimal_url_exact(self):
        url = build_static_map_url(key="test-key", center=(39.9, 116.4), zoom=11)
        assert url == (
            "https://restapi.amap.com/v3/staticmap"
            "?key=test-key&location=116.400000,39.900000&scale=2&size=640*360&zoom=11"
        )

    def test_no_center_omits_location(self):
        url = build_static_map_url(key="test-key", zoom=11)
        assert "location=" not in url

    def test_full_url_with_overlays_and_signature(self):
        url = build_static_map_url(
            key="test-key",
            secret="test-secret",
            center=(39.9, 116.4),
            zoom=11,
            size=(320, 180),
            paths="4,0x0000FF,0.8,,:116.400000,39.900000",
            markers="mid,0xFF0000,A:116.410000,39.910000",
        )
        params = dict(p.split("=", 1) for p in url.split("?")[1].split("&"))
        assert params["paths"] == "4,0x0000FF,0.8,,:116.400000,39.900000"
        assert params["markers"] == "mid,0xFF0000,A:116.410000,39.910000"
        assert params["size"] == "320*180"
        assert params["scale"] == "2"
        assert params["zoom"] == "11"
        # sig over the signed portion, md5 literal style
        signed_qs = url.split("?")[1].rsplit("&sig=", 1)[0]
        assert params["sig"] == hashlib.md5((signed_qs + "test-secret").encode()).hexdigest()

    def test_no_secret_no_sig(self):
        url = build_static_map_url(key="test-key", zoom=11)
        assert "&sig=" not in url and "sig=" not in url


# ── Fetching ───────────────────────────────────────────────


class _FakeHeaders:
    def __init__(self, content_type: str):
        self._ct = content_type

    def get_content_type(self) -> str:
        return self._ct


class _FakeResponse:
    def __init__(self, body: bytes, content_type: str):
        self._body = body
        self.headers = _FakeHeaders(content_type)

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestFetchPng:

    def test_image_bytes_returned(self):
        png = b"\x89PNG\r\n\x1a\nfake-image-data"
        with patch(
            "gps_photo_tracker.service.map_service.urlopen",
            return_value=_FakeResponse(png, "image/png"),
        ):
            assert MapService().fetch_png("https://example.com/map") == png

    def test_amap_json_error_raises_with_infocode(self):
        err = json.dumps({"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"}).encode()
        with patch(
            "gps_photo_tracker.service.map_service.urlopen",
            return_value=_FakeResponse(err, "application/json"),
        ):
            with pytest.raises(MapFetchError) as e:
                MapService().fetch_png("https://example.com/map")
            assert "10001" in str(e.value)
            assert "INVALID_USER_KEY" in str(e.value)

    def test_http_error_wrapped(self):
        import urllib.error
        with patch(
            "gps_photo_tracker.service.map_service.urlopen",
            side_effect=urllib.error.HTTPError(
                "url", 503, "Service Unavailable", hdrs=None, fp=None
            ),
        ):
            with pytest.raises(MapFetchError):
                MapService().fetch_png("https://example.com/map")

    def test_network_error_wrapped(self):
        import urllib.error
        with patch(
            "gps_photo_tracker.service.map_service.urlopen",
            side_effect=urllib.error.URLError("no route to host"),
        ):
            with pytest.raises(MapFetchError):
                MapService().fetch_png("https://example.com/map")


# ── Constants sanity ───────────────────────────────────────


def test_constants():
    assert ZOOM_MIN == 3 and ZOOM_MAX == 17
    assert DEFAULT_SIZE == (640, 360)
