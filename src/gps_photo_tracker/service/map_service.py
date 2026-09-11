"""AMap static map service: URL building, view fitting, credential loading.

Zero new pip dependencies — uses urllib only. All URL/overlay formats were
validated against the live AMap API (2026-09-11); see
docs/superpowers/specs/2026-09-11-map-view-design.md.

Credentials (AMAP_KEY / AMAP_SECRET) are read from environment variables
first, then from a `.env` file. They are NEVER logged.
"""

import hashlib
import json
import math
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

STATIC_MAP_ENDPOINT = "https://restapi.amap.com/v3/staticmap"

ZOOM_MIN = 3
ZOOM_MAX = 17
DEFAULT_SIZE = (640, 360)  # must stay ≤ 1024*1024 (AMap limit)

# AMap limits: ≤4 path style groups, ≤10 marker style groups per request.
MAX_PATH_GROUPS = 4
MAX_PATH_POINTS = 128  # per segment, keeps the URL comfortably under limits
MAX_MARKERS = 96

_PATH_WEIGHT = "4"
_PATH_COLOR = "0x0000FF"
_PATH_ALPHA = "0.8"
_BULK_MARKER = ("small", "0x2A6FDB", "")   # photos: small blue dots
_SELECTED_MARKER = ("large", "0xFF0000", "S")  # selection: large red, label S

# urlencode(): keep AMap overlay punctuation literal (server accepts both raw
# and %-encoded, raw matches the official docs examples and the sig string).
_SAFE = "*,.:;|"


class MapFetchError(RuntimeError):
    """Raised when the static map request fails (network or AMap error)."""


# ── Credentials ────────────────────────────────────────────


def load_amap_credentials(
    env: dict | None = None, dotenv_path: Path | str | None = None
) -> tuple[str | None, str | None]:
    """Load (AMAP_KEY, AMAP_SECRET): env vars win, `.env` fills the gaps.

    Missing file/vars are not an error — returns (None, None) so the GUI can
    show a configuration hint. Values are stripped; surrounding quotes removed.
    """
    env = os.environ if env is None else env
    key = (env.get("AMAP_KEY") or "").strip() or None
    secret = (env.get("AMAP_SECRET") or "").strip() or None

    path = Path(".env") if dotenv_path is None else Path(dotenv_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return key, secret

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'").strip()
        if name.strip() == "AMAP_KEY" and key is None:
            key = value or None
        elif name.strip() == "AMAP_SECRET" and secret is None:
            secret = value or None
    return key, secret


# ── View fitting (pure math) ───────────────────────────────


def _merc_y(lat: float) -> float:
    """Web-Mercator y (radians-space), clamped to the usable lat range."""
    lat = max(-85.05112878, min(85.05112878, lat))
    s = math.sin(math.radians(lat))
    return math.log((1 + s) / (1 - s))


def fit_view(
    points: list[tuple[float, float]],
    width: int,
    height: int,
    padding: float = 1.25,
) -> tuple[tuple[float, float], int] | None:
    """Compute (center, zoom) so all (lat, lon) points fit the viewport.

    padding > 1 keeps a margin around the bbox. Empty input → None (caller
    shows a placeholder instead).
    """
    if not points:
        return None
    lat_min = min(p[0] for p in points)
    lat_max = max(p[0] for p in points)
    lon_min = min(p[1] for p in points)
    lon_max = max(p[1] for p in points)
    center = ((lat_min + lat_max) / 2.0, (lon_min + lon_max) / 2.0)

    span_x = (lon_max - lon_min) / 360.0
    span_y = (_merc_y(lat_max) - _merc_y(lat_min)) / (2.0 * math.pi)

    max_world_px = math.inf
    if span_x > 0:
        max_world_px = min(max_world_px, width / (padding * span_x))
    if span_y > 0:
        max_world_px = min(max_world_px, height / (padding * span_y))

    if math.isinf(max_world_px):  # single point / zero span
        return center, ZOOM_MAX
    zoom = math.floor(math.log2(max_world_px / 256.0))
    return center, max(ZOOM_MIN, min(ZOOM_MAX, zoom))


# ── Overlay params (pure string building) ──────────────────


def _fmt(lat: float, lon: float) -> str:
    return f"{lon:.6f},{lat:.6f}"  # AMap order: lon,lat


def _downsample(points: list[tuple[float, float]], cap: int) -> list[tuple[float, float]]:
    """Even sampling that always keeps the first and last point."""
    if len(points) <= cap:
        return list(points)
    last = len(points) - 1
    idx = sorted({round(i * last / (cap - 1)) for i in range(cap)})
    return [points[i] for i in idx]


def build_paths_param(segments: list[list[tuple[float, float]]]) -> str | None:
    """Build the `paths=` value: one polyline per GPS segment.

    Points are GCJ-02 (convert before calling). Segments beyond AMap's 4-group
    limit are dropped (documented in the spec); per-segment points are
    downsampled to MAX_PATH_POINTS keeping endpoints.
    """
    groups = []
    for seg in segments[:MAX_PATH_GROUPS]:
        pts = _downsample(list(seg), MAX_PATH_POINTS)
        if len(pts) < 2:
            continue
        coords = ";".join(_fmt(lat, lon) for lat, lon in pts)
        groups.append(f"{_PATH_WEIGHT},{_PATH_COLOR},{_PATH_ALPHA},,:{coords}")
    return "|".join(groups) if groups else None


def build_markers_param(
    points: list[tuple[float, float]],
    selected: tuple[float, float] | None = None,
) -> str | None:
    """Build the `markers=` value: bulk photo dots + distinct selected marker.

    Points are GCJ-02. Bulk markers are capped at MAX_MARKERS via even
    sampling; the selected photo renders as a separate large red marker.
    """
    groups = []
    if points:
        pts = _downsample(list(points), MAX_MARKERS)
        size, color, label = _BULK_MARKER
        coords = ";".join(_fmt(lat, lon) for lat, lon in pts)
        groups.append(f"{size},{color},{label}:{coords}")
    if selected is not None:
        size, color, label = _SELECTED_MARKER
        groups.append(f"{size},{color},{label}:{_fmt(*selected)}")
    return "|".join(groups) if groups else None


# ── URL building & fetching ────────────────────────────────


def sign_params(params: dict[str, str], secret: str) -> str:
    """AMap digital signature: md5(urlencode(sorted params) + secret)."""
    qs = urlencode(sorted(params.items()), safe=_SAFE)
    return hashlib.md5((qs + secret).encode()).hexdigest()


def build_static_map_url(
    *,
    key: str,
    zoom: int,
    center: tuple[float, float] | None = None,
    size: tuple[int, int] = DEFAULT_SIZE,
    paths: str | None = None,
    markers: str | None = None,
    scale: int = 2,
    secret: str | None = None,
) -> str:
    """Assemble the static map URL. center is (lat, lon); location is lon,lat.

    When `secret` is given, `sig` is appended (required for keys with digital
    signature enabled — this project's key is, per live validation).
    """
    params: dict[str, str] = {
        "key": str(key),
        "zoom": str(zoom),
        "scale": str(scale),
        "size": f"{size[0]}*{size[1]}",
    }
    if center is not None:
        lat, lon = center
        params["location"] = f"{lon:.6f},{lat:.6f}"
    if paths:
        params["paths"] = paths
    if markers:
        params["markers"] = markers
    qs = urlencode(sorted(params.items()), safe=_SAFE)
    if secret:
        qs += "&sig=" + sign_params(params, secret)
    return f"{STATIC_MAP_ENDPOINT}?{qs}"


class MapService:
    """Thin fetch facade; URL building stays in module functions for testability."""

    def fetch_png(self, url: str, timeout: float = 10.0) -> bytes:
        """Fetch a static map PNG.

        Raises MapFetchError on network failure or when AMap answers with a
        JSON error document (status=0) instead of an image.
        """
        from urllib.error import HTTPError, URLError

        try:
            with urlopen(url, timeout=timeout) as resp:
                body = resp.read()
                content_type = resp.headers.get_content_type()
        except HTTPError as e:
            raise MapFetchError(f"HTTP {e.code}: {e.reason}") from e
        except URLError as e:
            raise MapFetchError(f"network error: {e.reason}") from e

        if content_type == "application/json":
            try:
                info = json.loads(body)
            except ValueError:
                info = {}
            raise MapFetchError(
                f"AMap error infocode={info.get('infocode')} info={info.get('info')}"
            )
        return body


__all__ = [
    "DEFAULT_SIZE",
    "MapFetchError",
    "MapService",
    "ZOOM_MAX",
    "ZOOM_MIN",
    "build_markers_param",
    "build_paths_param",
    "build_static_map_url",
    "fit_view",
    "load_amap_credentials",
    "sign_params",
]
