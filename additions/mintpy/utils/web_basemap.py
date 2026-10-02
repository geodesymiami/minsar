"""Web map tile basemaps for MintPy view.py (MinSAR overlay)."""

from __future__ import annotations

import math
import os
import urllib.request
from io import BytesIO
from pathlib import Path

import numpy as np

try:
    from PIL import Image, ImageOps
except Exception:
    Image = None

BASEMAP_PROVIDERS = {
    "osm": {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "grayscale": False,
        "cache_suffix": "osm",
    },
    "osm_gray": {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "grayscale": True,
        "cache_suffix": "osm_gray",
    },
    "cartodb_light": {
        "url": "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
        "grayscale": False,
        "cache_suffix": "cartodb_light",
    },
    "cartodb_dark": {
        "url": "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "grayscale": False,
        "cache_suffix": "cartodb_dark",
    },
    "esri_gray": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        "grayscale": False,
        "cache_suffix": "esri_gray",
    },
    "esri_satellite": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "grayscale": False,
        "cache_suffix": "esri_satellite",
    },
    "mapbox": {
        # access_token appended at runtime from MAPBOX_ACCESS_TOKEN
        "url_template": (
            "https://api.mapbox.com/styles/v1/mapbox/satellite-v9/tiles/256/{z}/{x}/{y}"
            "?access_token={access_token}"
        ),
        "grayscale": False,
        "cache_suffix": "mapbox",
        "needs_mapbox_token": True,
    },
}

BASEMAP_CHOICES = tuple(sorted(BASEMAP_PROVIDERS.keys()))

MAPBOX_TOKEN_ENV = "MAPBOX_ACCESS_TOKEN"

_PIL_WARNED = False
_MAPBOX_TOKEN_WARNED = False


def mapbox_access_token() -> str | None:
    """Return Mapbox token from MAPBOX_ACCESS_TOKEN, or None if unset/empty."""
    token = os.environ.get(MAPBOX_TOKEN_ENV, "").strip()
    return token or None


def warn_mapbox_token_missing(*, print_msg: bool = True) -> None:
    global _MAPBOX_TOKEN_WARNED
    if print_msg and not _MAPBOX_TOKEN_WARNED:
        print(
            f"WARNING: --add-basemap mapbox requires {MAPBOX_TOKEN_ENV} to be set; "
            "basemap skipped."
        )
        _MAPBOX_TOKEN_WARNED = True


def default_tile_cache_root() -> Path:
    """Tile cache under MINTPY_HOME or ~/.mintpy/tile_cache."""
    scratch = os.environ.get("SCRATCHDIR")
    if scratch:
        return Path(scratch).expanduser() / ".mintpy_tile_cache"
    mintpy_home = os.environ.get("MINTPY_HOME", "~/.mintpy")
    return Path(mintpy_home).expanduser() / "tile_cache"


def lonlat_to_tile(lon, lat, zoom):
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile


def tile_edges(x, y, z):
    n = 2.0 ** z
    lon_w = x / n * 360.0 - 180.0
    lon_e = (x + 1) / n * 360.0 - 180.0
    lat_n = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_s = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon_w, lon_e, lat_s, lat_n


def zoom_for_extent(w, e, s, n, max_zoom=19, min_zoom=1, target_tiles=12):
    """Pick a web-map zoom so the AOI spans roughly target_tiles across the wider axis."""
    lon_span = abs(float(e) - float(w))
    lat_span = abs(float(n) - float(s))
    span = max(lon_span, lat_span, 1e-9)
    for z in range(max_zoom, min_zoom - 1, -1):
        x0, y0 = lonlat_to_tile(w, n, z)
        x1, y1 = lonlat_to_tile(e, s, z)
        nx = abs(x1 - x0) + 1
        ny = abs(y1 - y0) + 1
        if max(nx, ny) <= target_tiles:
            return z
    return min_zoom


def fetch_tile(x, y, z, cache_dir, provider_url, grayscale=False):
    if Image is None:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    tile_path = cache_dir / f"z{z}_x{x}_y{y}.png"
    if tile_path.exists():
        img = Image.open(tile_path).convert("RGB")
        if grayscale:
            img = ImageOps.grayscale(img).convert("RGB")
        return img

    url = provider_url.format(z=z, x=x, y=y)
    req = urllib.request.Request(url, headers={"User-Agent": "mintpy-view-basemap/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            data = response.read()
        img = Image.open(BytesIO(data)).convert("RGB")
        img.save(tile_path)
        if grayscale:
            img = ImageOps.grayscale(img).convert("RGB")
        return img
    except Exception as exc:
        print(f"[WARNING] could not fetch tile {z}/{x}/{y}: {exc}")
        return None


def _geoaxes_imshow_kwargs(ax):
    """Return imshow kwargs for cartopy GeoAxes, or empty dict for plain Axes."""
    try:
        from cartopy.mpl.geoaxes import GeoAxes
    except ImportError:
        return {}
    if isinstance(ax, GeoAxes):
        from cartopy import crs as ccrs
        return {"transform": ccrs.PlateCarree()}
    return {}


def add_web_basemap(
    ax,
    xlim,
    ylim,
    provider_key="esri_satellite",
    zoom=None,
    alpha=1.0,
    cache_root=None,
    print_msg=True,
):
    """Draw slippy-map tiles under existing plot content. xlim=(W,E), ylim=(S,N) in degrees."""
    global _PIL_WARNED
    if Image is None:
        if print_msg and not _PIL_WARNED:
            print("WARNING: Pillow (PIL) not available; --add-basemap skipped.")
            _PIL_WARNED = True
        return False
    if provider_key not in BASEMAP_PROVIDERS:
        raise ValueError(f"Unknown basemap provider: {provider_key}")

    provider = BASEMAP_PROVIDERS[provider_key]
    if provider.get("needs_mapbox_token"):
        token = mapbox_access_token()
        if not token:
            warn_mapbox_token_missing(print_msg=print_msg)
            return False
        provider_url = provider["url_template"].format(access_token=token)
    else:
        provider_url = provider["url"]
    grayscale = provider.get("grayscale", False)
    if cache_root is None:
        cache_root = default_tile_cache_root()
    cache_dir = Path(cache_root) / provider.get("cache_suffix", provider_key)

    w, e = xlim
    s, n = ylim
    if not all(np.isfinite([w, e, s, n])):
        return False

    if zoom is None:
        zoom = zoom_for_extent(w, e, s, n)

    x0, y0 = lonlat_to_tile(w, n, zoom)
    x1, y1 = lonlat_to_tile(e, s, zoom)
    xmin, xmax = sorted([x0, x1])
    ymin, ymax = sorted([y0, y1])

    imshow_extra = _geoaxes_imshow_kwargs(ax)
    ok = False
    for xt in range(xmin, xmax + 1):
        for yt in range(ymin, ymax + 1):
            img = fetch_tile(xt, yt, zoom, cache_dir, provider_url, grayscale=grayscale)
            if img is None:
                continue
            lon_w, lon_e, lat_s, lat_n = tile_edges(xt, yt, zoom)
            ax.imshow(
                img,
                extent=[lon_w, lon_e, lat_s, lat_n],
                origin="upper",
                alpha=alpha,
                zorder=0,
                **imshow_extra,
            )
            ok = True

    ax.set_xlim(w, e)
    ax.set_ylim(s, n)
    if print_msg and ok:
        print(f"web basemap: {provider_key} (zoom={zoom}, alpha={alpha})")
    return ok
