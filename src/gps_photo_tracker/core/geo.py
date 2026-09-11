"""Geodesy helpers: WGS-84 → GCJ-02 conversion and distance.

GPS tracks and photo EXIF carry WGS-84 coordinates; AMap tiles/labels use the
GCJ-02 datum. Rendering unconverted coordinates shifts everything ~300–600 m
to the northwest, so conversion is mandatory before calling AMap.

Algorithm matches the community-standard implementation (googollee/eviltransform,
MIT licensed) — verified against its published cross-language test vectors.
Outside mainland China's bounding box the offset is not applied (GCJ-02 does
not exist there; AMap itself renders WGS-84 unshifted abroad).

References:
- https://github.com/googollee/eviltransform (algorithm + test vectors)
- AMap static map guide: https://lbs.amap.com/api/webservice/guide/api/staticmaps
"""

import math

_EARTH_R = 6378137.0  # WGS-84 semi-major axis (m)
_EE = 0.00669342162296594323  # eccentricity squared


def out_of_china(lat: float, lng: float) -> bool:
    """True when (lat, lng) is outside the GCJ-02 coverage bounding box."""
    if lng < 72.004 or lng > 137.8347:
        return True
    if lat < 0.8293 or lat > 55.8271:
        return True
    return False


def _transform(x: float, y: float) -> tuple[float, float]:
    """Base offset polynomial (degrees) for delta computation."""
    xy = x * y
    abs_x = math.sqrt(abs(x))
    x_pi = x * math.pi
    y_pi = y * math.pi
    d = 20.0 * math.sin(6.0 * x_pi) + 20.0 * math.sin(2.0 * x_pi)

    d_lat = d + 20.0 * math.sin(y_pi) + 40.0 * math.sin(y_pi / 3.0)
    d_lng = d + 20.0 * math.sin(x_pi) + 40.0 * math.sin(x_pi / 3.0)

    d_lat += 160.0 * math.sin(y_pi / 12.0) + 320.0 * math.sin(y_pi / 30.0)
    d_lng += 150.0 * math.sin(x_pi / 12.0) + 300.0 * math.sin(x_pi / 30.0)

    d_lat *= 2.0 / 3.0
    d_lng *= 2.0 / 3.0

    d_lat += -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * xy + 0.2 * abs_x
    d_lng += 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * xy + 0.1 * abs_x
    return d_lat, d_lng


def _delta(lat: float, lng: float) -> tuple[float, float]:
    """GCJ-02 offset (degrees) at a WGS-84 position, with ellipsoid correction."""
    d_lat, d_lng = _transform(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = 1 - _EE * math.sin(rad_lat) ** 2
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((_EARTH_R * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    d_lng = (d_lng * 180.0) / (_EARTH_R / sqrt_magic * math.cos(rad_lat) * math.pi)
    return d_lat, d_lng


def wgs84_to_gcj02(lat: float, lng: float) -> tuple[float, float]:
    """Convert WGS-84 to GCJ-02. Outside China the input is returned unchanged."""
    if out_of_china(lat, lng):
        return lat, lng
    d_lat, d_lng = _delta(lat, lng)
    return lat + d_lat, lng + d_lng


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters (sphere, R = 6,378,137 m).

    Sufficient for the ~100 m … ~1,000 km checks here; not geodesic-grade.
    """
    pi180 = math.pi / 180.0
    arc_lat1 = lat1 * pi180
    arc_lat2 = lat2 * pi180
    x = math.cos(arc_lat1) * math.cos(arc_lat2) * math.cos((lon1 - lon2) * pi180)
    y = math.sin(arc_lat1) * math.sin(arc_lat2)
    s = x + y
    s = max(-1.0, min(1.0, s))
    return math.acos(s) * _EARTH_R
