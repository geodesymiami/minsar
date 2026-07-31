#!/usr/bin/env python3
"""Expand a geographic AOI to miaplpy.subset.lalo for ascending/descending tracks.

Uses platform heading (MintPy HEADING / S1 platformHeading): degrees clockwise from
North along the flight direction.

Default mode ``asymmetric_lat``: pad latitude on the along-track approach side using
heading skew over the AOI longitude width so Asc and Desc differ (lon unchanged).

Mode ``aabb``: geographic AABB of a radar-aligned (azimuth x range) rectangle that
covers the AOI. For a rectangular AOI this box is the same for Asc and Desc (heading
pair related by ~180 deg).
"""

from __future__ import annotations

import math
from typing import Sequence

# MintPy HEADING / S1 platformHeading defaults (~35 deg N mid-latitude Sentinel-1)
DEFAULT_ASC_HEADING_DEG = -13.0
DEFAULT_DESC_HEADING_DEG = -167.0

# WGS84 approx for local EN meters (sufficient for small AOIs)
_EARTH_RADIUS_M = 6371000.0

MODES = ("asymmetric_lat", "aabb")


def default_heading_deg(orbit: str) -> float:
    """Return default platform heading (deg) for 'asc' or 'desc'."""
    key = orbit.strip().lower()
    if key in ("asc", "ascending", "a"):
        return DEFAULT_ASC_HEADING_DEG
    if key in ("desc", "descending", "d"):
        return DEFAULT_DESC_HEADING_DEG
    raise ValueError(f"orbit must be asc or desc, got {orbit!r}")


def _normalize_orbit(orbit: str) -> str:
    key = orbit.strip().lower()
    if key in ("asc", "ascending", "a"):
        return "asc"
    if key in ("desc", "descending", "d"):
        return "desc"
    raise ValueError(f"orbit must be asc or desc, got {orbit!r}")


def _az_rg_unit_vectors(heading_deg: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return (û_az, û_rg) in (east, north) for platform heading (deg, CW from North).

    Right-looking SAR: range is 90 deg clockwise from flight direction.
    """
    alpha = math.radians(heading_deg)
    u_az = (math.sin(alpha), math.cos(alpha))
    u_rg = (math.cos(alpha), -math.sin(alpha))
    return u_az, u_rg


def _latlon_to_en(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Local east/north meters from (lat0, lon0)."""
    lat_r = math.radians(lat0)
    dlat = math.radians(lat - lat0)
    dlon = math.radians(lon - lon0)
    east = _EARTH_RADIUS_M * dlon * math.cos(lat_r)
    north = _EARTH_RADIUS_M * dlat
    return east, north


def _en_to_latlon(east: float, north: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Inverse of _latlon_to_en."""
    lat_r = math.radians(lat0)
    lat = lat0 + math.degrees(north / _EARTH_RADIUS_M)
    lon = lon0 + math.degrees(east / (_EARTH_RADIUS_M * math.cos(lat_r)))
    return lat, lon


def _aoi_corners(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> list[tuple[float, float]]:
    return [
        (min_lat, min_lon),
        (min_lat, max_lon),
        (max_lat, min_lon),
        (max_lat, max_lon),
    ]


def heading_skew_delta_lat(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    heading_deg: float,
) -> float:
    """Latitude pad (deg) from E-W AOI width and |tan(heading)| track skew."""
    mid_lat = 0.5 * (min_lat + max_lat)
    dlon = max_lon - min_lon
    return abs(dlon * math.cos(math.radians(mid_lat)) * math.tan(math.radians(heading_deg)))


def expand_bounds_asymmetric_lat(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    heading_deg: float,
    orbit: str,
) -> tuple[float, float, float, float]:
    """Pad south (Asc) or north (Desc) by heading skew; lon unchanged."""
    if max_lat < min_lat or max_lon < min_lon:
        raise ValueError("AOI bounds must satisfy min <= max for lat and lon")
    orbit_key = _normalize_orbit(orbit)
    delta = heading_skew_delta_lat(min_lat, max_lat, min_lon, max_lon, heading_deg)
    if orbit_key == "asc":
        # Ascending: flight ~north — pad southern edge for along-track skew
        return min_lat - delta, max_lat, min_lon, max_lon
    # Descending: flight ~south — pad northern edge
    return min_lat, max_lat + delta, min_lon, max_lon


def expand_bounds_for_heading(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    heading_deg: float,
) -> tuple[float, float, float, float]:
    """Expand geographic bounds to the AABB of a covering radar-aligned rectangle.

    Note: for a rectangular AOI, Asc/Desc headings that differ by ~180 deg yield the
    same geographic AABB (parallelogram rotated about center).
    """
    if max_lat < min_lat or max_lon < min_lon:
        raise ValueError("AOI bounds must satisfy min <= max for lat and lon")

    lat0 = 0.5 * (min_lat + max_lat)
    lon0 = 0.5 * (min_lon + max_lon)
    u_az, u_rg = _az_rg_unit_vectors(heading_deg)

    az_vals: list[float] = []
    rg_vals: list[float] = []
    for lat, lon in _aoi_corners(min_lat, max_lat, min_lon, max_lon):
        east, north = _latlon_to_en(lat, lon, lat0, lon0)
        az_vals.append(east * u_az[0] + north * u_az[1])
        rg_vals.append(east * u_rg[0] + north * u_rg[1])

    az_min, az_max = min(az_vals), max(az_vals)
    rg_min, rg_max = min(rg_vals), max(rg_vals)

    radar_corners_en = [
        (az_min * u_az[0] + rg_min * u_rg[0], az_min * u_az[1] + rg_min * u_rg[1]),
        (az_min * u_az[0] + rg_max * u_rg[0], az_min * u_az[1] + rg_max * u_rg[1]),
        (az_max * u_az[0] + rg_min * u_rg[0], az_max * u_az[1] + rg_min * u_rg[1]),
        (az_max * u_az[0] + rg_max * u_rg[0], az_max * u_az[1] + rg_max * u_rg[1]),
    ]

    lats: list[float] = []
    lons: list[float] = []
    for east, north in radar_corners_en:
        lat, lon = _en_to_latlon(east, north, lat0, lon0)
        lats.append(lat)
        lons.append(lon)

    return min(lats), max(lats), min(lons), max(lons)


def expand_bounds(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    heading_deg: float,
    orbit: str,
    *,
    mode: str = "asymmetric_lat",
) -> tuple[float, float, float, float]:
    """Expand AOI bounds for one orbit using ``mode``."""
    if mode == "asymmetric_lat":
        return expand_bounds_asymmetric_lat(
            min_lat, max_lat, min_lon, max_lon, heading_deg, orbit
        )
    if mode == "aabb":
        return expand_bounds_for_heading(min_lat, max_lat, min_lon, max_lon, heading_deg)
    raise ValueError(f"mode must be one of {MODES}, got {mode!r}")


def format_subset_lalo(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    *,
    decimals: int = 3,
) -> str:
    """Format S:N,W:E string."""
    fmt = f"{{:.{decimals}f}}"
    return (
        f"{fmt.format(min_lat)}:{fmt.format(max_lat)},"
        f"{fmt.format(min_lon)}:{fmt.format(max_lon)}"
    )


def miaplpy_subset_lalo_line(
    subset_str: str,
    *,
    orbit_label: str,
    heading_deg: float,
) -> str:
    """One template-style assignment line with Asc/Desc comment."""
    return (
        f"miaplpy.subset.lalo                  = {subset_str}"
        f"    # {orbit_label}  heading={heading_deg:.3f}"
    )


def expand_aoi_to_subset_lines(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    *,
    orbits: Sequence[str] = ("asc", "desc"),
    asc_heading: float = DEFAULT_ASC_HEADING_DEG,
    desc_heading: float = DEFAULT_DESC_HEADING_DEG,
    decimals: int = 3,
    mode: str = "asymmetric_lat",
) -> list[str]:
    """Return miaplpy.subset.lalo lines for the requested orbits."""
    heading_by_orbit = {
        "asc": asc_heading,
        "descending": desc_heading,
        "desc": desc_heading,
        "ascending": asc_heading,
        "a": asc_heading,
        "d": desc_heading,
    }
    label_by_orbit = {
        "asc": "Asc",
        "ascending": "Asc",
        "a": "Asc",
        "desc": "Desc",
        "descending": "Desc",
        "d": "Desc",
    }
    lines: list[str] = []
    seen: set[str] = set()
    for orbit in orbits:
        key = orbit.strip().lower()
        if key not in heading_by_orbit:
            raise ValueError(f"unknown orbit {orbit!r}; use asc or desc")
        label = label_by_orbit[key]
        if label in seen:
            continue
        seen.add(label)
        heading = heading_by_orbit[key]
        exp = expand_bounds(
            min_lat, max_lat, min_lon, max_lon, heading, key, mode=mode
        )
        subset = format_subset_lalo(*exp, decimals=decimals)
        lines.append(
            miaplpy_subset_lalo_line(subset, orbit_label=label, heading_deg=heading)
        )
    return lines


def bounds_contain(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
    *,
    atol: float = 1e-9,
) -> bool:
    """True if outer AABB contains inner AABB (with tolerance)."""
    o_s, o_n, o_w, o_e = outer
    i_s, i_n, i_w, i_e = inner
    return (
        o_s <= i_s + atol
        and o_n >= i_n - atol
        and o_w <= i_w + atol
        and o_e >= i_e - atol
    )


def expand_for_orbits(
    bounds: tuple[float, float, float, float],
    *,
    asc_heading: float = DEFAULT_ASC_HEADING_DEG,
    desc_heading: float = DEFAULT_DESC_HEADING_DEG,
    mode: str = "asymmetric_lat",
) -> dict[str, tuple[float, float, float, float]]:
    """Expand bounds for asc and desc; return dict with keys 'asc' and 'desc'."""
    s, n, w, e = bounds
    return {
        "asc": expand_bounds(s, n, w, e, asc_heading, "asc", mode=mode),
        "desc": expand_bounds(s, n, w, e, desc_heading, "desc", mode=mode),
    }


__all__ = [
    "DEFAULT_ASC_HEADING_DEG",
    "DEFAULT_DESC_HEADING_DEG",
    "MODES",
    "bounds_contain",
    "default_heading_deg",
    "expand_aoi_to_subset_lines",
    "expand_bounds",
    "expand_bounds_asymmetric_lat",
    "expand_bounds_for_heading",
    "expand_for_orbits",
    "format_subset_lalo",
    "heading_skew_delta_lat",
    "miaplpy_subset_lalo_line",
]
