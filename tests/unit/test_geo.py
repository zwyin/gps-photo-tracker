"""Tests for WGS-84 ↔ GCJ-02 coordinate conversion (core/geo.py).

Reference vectors come from googollee/eviltransform's official cross-language
test suite (go/transform_test.go) — an independent implementation, so these
assertions are NOT circular.
"""

import math

import pytest

from gps_photo_tracker.core.geo import (
    haversine_m,
    out_of_china,
    wgs84_to_gcj02,
)

# eviltransform official test set: (wgs_lat, wgs_lng, gcj_lat, gcj_lng)
_EVILTRANSFORM_VECTORS = [
    (31.1774276, 121.5272106, 31.17530398364597, 121.531541859215),  # Shanghai
    (22.543847, 113.912316, 22.540796131694766, 113.9171764808363),  # Shenzhen
    (39.911954, 116.377817, 39.91334545536069, 116.38404722455657),  # Beijing
]


class TestWgs84ToGcj02:

    @pytest.mark.parametrize("wgs_lat,wgs_lng,gcj_lat,gcj_lng", _EVILTRANSFORM_VECTORS)
    def test_reference_vectors(self, wgs_lat, wgs_lng, gcj_lat, gcj_lng):
        got_lat, got_lng = wgs84_to_gcj02(wgs_lat, wgs_lng)
        assert got_lat == pytest.approx(gcj_lat, abs=1e-6)
        assert got_lng == pytest.approx(gcj_lng, abs=1e-6)

    @pytest.mark.parametrize("wgs_lat,wgs_lng,gcj_lat,gcj_lng", _EVILTRANSFORM_VECTORS)
    def test_offset_magnitude_300_to_700m(self, wgs_lat, wgs_lng, gcj_lat, gcj_lng):
        """GCJ-02 shift at these cities is the well-known ~300–700 m.

        Measured with this implementation: Shanghai 475.5 m, Shenzhen 604.2 m,
        Beijing 554.1 m (fixed in docs/superpowers/specs/2026-09-11-map-view-design.md).
        """
        d = haversine_m(wgs_lat, wgs_lng, gcj_lat, gcj_lng)
        assert 300 <= d <= 700, f"offset {d:.1f} m outside expected band"

    def test_outside_china_is_identity(self):
        # New York, London, Sydney, Tokyo — outside the GCJ-02 coverage box.
        for lat, lng in [(40.7128, -74.0060), (51.5074, -0.1278),
                         (-33.8688, 151.2093), (35.6762, 139.6503)]:
            assert wgs84_to_gcj02(lat, lng) == (lat, lng)

    def test_offset_is_small_degree_delta(self):
        lat, lng = wgs84_to_gcj02(39.911954, 116.377817)
        assert abs(lat - 39.911954) < 0.01
        assert abs(lng - 116.377817) < 0.01

    def test_continuous_nearby_inputs(self):
        a = wgs84_to_gcj02(31.1774, 121.5272)
        b = wgs84_to_gcj02(31.1774 + 1e-6, 121.5272 + 1e-6)
        assert abs(a[0] - b[0]) < 1e-4
        assert abs(a[1] - b[1]) < 1e-4


class TestOutOfChina:

    @pytest.mark.parametrize("lat,lng", [
        (39.9042, 116.4074),   # Beijing
        (31.2304, 121.4737),   # Shanghai
        (43.8256, 87.6168),    # Urumqi (west edge, inside)
        (18.2528, 109.5119),   # Sanya (south, inside)
    ])
    def test_inside_china(self, lat, lng):
        assert out_of_china(lat, lng) is False

    @pytest.mark.parametrize("lat,lng", [
        (40.7128, -74.0060),   # New York
        (51.5074, -0.1278),    # London
        (35.6762, 139.6503),   # Tokyo (lng 139.65 > 137.8347)
        (55.9, 116.4),         # North of lat bound
        (0.5, 116.4),          # South of lat bound
    ])
    def test_outside_china(self, lat, lng):
        assert out_of_china(lat, lng) is True

    def test_boundary_box(self):
        # Exactly on the documented bounds → inside (not offset-applied edge).
        assert out_of_china(0.8293, 72.004) is False
        assert out_of_china(55.8271, 137.8347) is False


class TestHaversine:

    def test_eviltransform_reference_distance(self):
        # eviltransform test: Shanghai↔Beijing ≈ 1,078,164 m (±1 m).
        d = haversine_m(31.17530398364597, 121.531541859215,
                        39.91334545536069, 116.38404722455657)
        assert abs(d - 1078164) < 1.0

    def test_zero_distance(self):
        assert haversine_m(31.2, 121.5, 31.2, 121.5) == 0.0

    def test_one_degree_longitude_equator(self):
        # 1° lon at equator ≈ 111,195 m (R=6378137: 2πR/360 = 111,319.49).
        d = haversine_m(0.0, 0.0, 0.0, 1.0)
        assert d == pytest.approx(111319.49, rel=1e-3)

    def test_antipodal_does_not_crash(self):
        d = haversine_m(0.0, 0.0, 0.0, 180.0)
        assert d == pytest.approx(math.pi * 6378137, rel=1e-3)
