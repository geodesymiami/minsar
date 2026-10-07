#!/usr/bin/env python3
"""Build a MintPy geo mask (1 inside KMZ/KML polygons, 0 outside) on a geocoded grid."""

from __future__ import annotations

import argparse
import glob
import os
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import h5py
import numpy as np
from mintpy.utils import readfile, writefile
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.vectorized import contains

from minsar.objects import message_rsmas
from minsar.utils.subset_hdfeos5 import get_hdfeos_geometry_atr

DESCRIPTION = """\
Create a MintPy mask HDF5 on the grid of a geocoded reference file (.he5 or geo *.h5).
Pixels inside any polygon from the KMZ/KML inputs are 1; all others are 0.
A regular lat/lon grid is sampled at pixel centers. A projected HE5 uses its
per-pixel latitude/longitude. Default output geo_polygon_mask.h5 is written in CWD.
"""

EXAMPLE = """Examples:
polygon_2_mask.py Runway_*.kmz geo_velocity.h5
polygon_2_mask.py aoi.kmz geo_S1_*.he5
polygon_2_mask.py Runway_*.kmz --inverse geo_velocity.h5
polygon_2_mask.py aoi.kmz -o custom_mask.h5 geo_velocity.h5
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EXAMPLE,
    )
    parser.add_argument(
        "kmz",
        nargs="+",
        metavar="KMZ",
        help="One or more KMZ/KML polygon files (shell globs OK)",
    )
    parser.add_argument(
        "geocode_file",
        metavar="GEOCODE",
        help="Geocoded MintPy .h5 or HDF-EOS5 .he5 defining the output grid",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="outfile",
        default="geo_polygon_mask.h5",
        help="Output mask HDF5 in CWD unless path is given [default: geo_polygon_mask.h5]",
    )
    parser.add_argument(
        "--inverse",
        action="store_true",
        help="Swap mask values (0 inside polygons, 1 outside)",
    )
    return parser


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_coordinate_text(text: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for token in text.strip().split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        lon, lat = float(parts[0]), float(parts[1])
        points.append((lon, lat))
    return points


def _polygons_from_kml_root(root: ET.Element) -> list[Polygon]:
    polygons: list[Polygon] = []
    for element in root.iter():
        if _local_tag(element.tag) != "Polygon":
            continue
        rings: list[list[tuple[float, float]]] = []
        for sub in element.iter():
            if _local_tag(sub.tag) == "coordinates" and sub.text:
                ring = _parse_coordinate_text(sub.text)
                if len(ring) >= 3:
                    rings.append(ring)
        if not rings:
            continue
        holes = rings[1:] if len(rings) > 1 else None
        polygons.append(Polygon(rings[0], holes))
    return polygons


def _polygons_from_kml_path(path: Path) -> list[Polygon]:
    root = ET.parse(path).getroot()
    return _polygons_from_kml_root(root)


def _polygons_from_kmz_path(path: Path) -> list[Polygon]:
    with zipfile.ZipFile(path) as archive:
        kml_names = [name for name in archive.namelist() if name.lower().endswith(".kml")]
        if not kml_names:
            raise ValueError(f"no KML member in KMZ: {path}")
        root = ET.fromstring(archive.read(kml_names[0]))
    return _polygons_from_kml_root(root)


def load_polygons(kmz_paths: list[Path]) -> Polygon:
    all_polys: list[Polygon] = []
    for path in kmz_paths:
        suffix = path.suffix.lower()
        if suffix == ".kmz":
            all_polys.extend(_polygons_from_kmz_path(path))
        elif suffix == ".kml":
            all_polys.extend(_polygons_from_kml_path(path))
        else:
            raise ValueError(f"expected .kmz or .kml, got: {path}")
    if not all_polys:
        raise ValueError("no polygons found in KMZ/KML inputs")
    return unary_union(all_polys)


def expand_kmz_arguments(raw_paths: list[str]) -> list[Path]:
    expanded: list[Path] = []
    for raw in raw_paths:
        if any(ch in raw for ch in "*?[]"):
            matches = sorted(glob.glob(raw))
            if not matches:
                raise FileNotFoundError(f"no files match KMZ glob: {raw}")
            expanded.extend(Path(p).resolve() for p in matches)
        else:
            path = Path(raw).expanduser().resolve()
            if not path.is_file():
                raise FileNotFoundError(f"KMZ/KML not found: {path}")
            expanded.append(path)
    return expanded


def _regular_lat_lon_grid(shape: tuple[int, ...], atr: dict) -> tuple[np.ndarray, np.ndarray]:
    """Pixel-center lat/lon. MintPy Y_FIRST/X_FIRST are the upper-left corner."""
    length, width = shape
    y0 = float(atr["Y_FIRST"])
    x0 = float(atr["X_FIRST"])
    y_step = float(atr["Y_STEP"])
    x_step = float(atr["X_STEP"])
    rows = np.arange(length, dtype=np.float64) + 0.5
    cols = np.arange(width, dtype=np.float64) + 0.5
    lat = np.broadcast_to((y0 + rows * y_step)[:, None], (length, width)).copy()
    lon = np.broadcast_to(x0 + cols * x_step, (length, width)).copy()
    return lat, lon


def _axis_aligned_latlon(lat: np.ndarray, lon: np.ndarray, tol_deg: float = 1e-5) -> bool:
    """True when each row is one latitude and each column is one longitude."""
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    if lat.ndim != 2 or lon.ndim != 2 or lat.shape != lon.shape:
        return False
    if not (np.isfinite(lat).any() and np.isfinite(lon).any()):
        return False
    if lat.shape[1] > 1:
        row_span = np.nanmax(lat, axis=1) - np.nanmin(lat, axis=1)
        if float(np.nanmax(row_span)) > tol_deg:
            return False
    if lon.shape[0] > 1:
        col_span = np.nanmax(lon, axis=0) - np.nanmin(lon, axis=0)
        if float(np.nanmax(col_span)) > tol_deg:
            return False
    return True


def _he5_geometry_latlon(path: Path) -> tuple[np.ndarray, np.ndarray] | None:
    """2D latitude/longitude from an HDF-EOS5 file, or None."""
    if path.suffix.lower() != ".he5":
        return None
    base = "HDFEOS/GRIDS/timeseries/geometry"
    with h5py.File(path, "r") as f:
        lat_name = f"{base}/latitude"
        lon_name = f"{base}/longitude"
        if lat_name not in f or lon_name not in f:
            return None
        lat = np.asarray(f[lat_name][:], dtype=np.float64)
        lon = np.asarray(f[lon_name][:], dtype=np.float64)
    if lat.ndim != 2 or lon.ndim != 2 or lat.shape != lon.shape:
        return None
    return lat, lon


def _lat_lon_from_geometry_h5(geom_path: Path, shape: tuple[int, ...]) -> tuple[np.ndarray, np.ndarray]:
    geom_data, _ = readfile.read(str(geom_path))
    if not isinstance(geom_data, dict):
        raise ValueError(f"geometry file has no lat/lon datasets: {geom_path}")
    lat = np.asarray(geom_data["latitude"], dtype=np.float64)
    lon = np.asarray(geom_data["longitude"], dtype=np.float64)
    if lat.shape != shape or lon.shape != shape:
        raise ValueError(
            f"geometry grid {lat.shape} does not match reference grid {shape}: {geom_path}"
        )
    return lat, lon


def read_reference_grid(geocode_path: Path) -> tuple[tuple[int, int], dict]:
    geocode_path = geocode_path.expanduser().resolve()
    if not geocode_path.is_file():
        raise FileNotFoundError(f"geocode file not found: {geocode_path}")

    if geocode_path.suffix.lower() == ".he5":
        atr = get_hdfeos_geometry_atr(str(geocode_path))
        data, ds_atr = readfile.read(
            str(geocode_path),
            datasetName="HDFEOS/GRIDS/timeseries/quality/mask",
        )
        merged = dict(ds_atr)
        merged.update(atr)
        shape = (int(data.shape[0]), int(data.shape[1]))
        return shape, merged

    data, atr = readfile.read(str(geocode_path))
    if data.ndim != 2:
        raise ValueError(f"reference dataset must be 2-D, got shape {data.shape}: {geocode_path}")
    shape = (int(data.shape[0]), int(data.shape[1]))
    return shape, dict(atr)


def lat_lon_grids(geocode_path: Path, shape: tuple[int, int], atr: dict) -> tuple[np.ndarray, np.ndarray]:
    he5_ll = _he5_geometry_latlon(geocode_path)
    if he5_ll is not None and he5_ll[0].shape == shape and not _axis_aligned_latlon(*he5_ll):
        print("Grid:       per-pixel lat/lon (projected raster)")
        print(
            "Warning:    view.py places this mask with Y_FIRST, which is only exact "
            "near the northwest corner. Regenerate the HE5 on a regular lat/lon grid "
            "for the mask to sit on the basemap."
        )
        return he5_ll

    keys = ("Y_FIRST", "X_FIRST", "Y_STEP", "X_STEP")
    if all(k in atr for k in keys):
        print("Grid:       regular lat/lon, pixel centers")
        return _regular_lat_lon_grid(shape, atr)

    geom_candidates = [
        geocode_path.parent / "geo_geometryRadar.h5",
        geocode_path.parent / "inputs" / "geometryGeo.h5",
    ]
    for candidate in geom_candidates:
        if candidate.is_file():
            return _lat_lon_from_geometry_h5(candidate, shape)

    raise ValueError(
        "reference file has no Y_FIRST/X_FIRST/Y_STEP/X_STEP and no geo_geometryRadar.h5 nearby"
    )


def polygon_mask_on_grid(geom, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    inside = contains(geom, lon, lat)
    return inside.astype(np.float32)


def mask_metadata(reference_atr: dict) -> dict:
    meta = dict(reference_atr)
    meta["FILE_TYPE"] = "mask"
    return meta


def build_mask(
    kmz_paths: list[Path],
    geocode_path: Path,
    *,
    inverse: bool = False,
) -> tuple[np.ndarray, dict]:
    shape, atr = read_reference_grid(geocode_path)
    lat, lon = lat_lon_grids(geocode_path, shape, atr)
    geom = load_polygons(kmz_paths)
    mask = polygon_mask_on_grid(geom, lat, lon)
    if inverse:
        mask = 1.0 - mask
    return mask, mask_metadata(atr)


def main(argv: list[str] | None = None) -> int:
    cmd_argv = sys.argv[1:] if argv is None else argv
    message_rsmas.log(os.getcwd(), os.path.basename(__file__) + " " + " ".join(cmd_argv))

    parser = create_parser()
    args = parser.parse_args(argv)

    kmz_paths = expand_kmz_arguments(args.kmz)
    geocode_path = Path(args.geocode_file).expanduser().resolve()
    out_path = Path(args.outfile).expanduser()
    if not out_path.is_absolute():
        out_path = Path.cwd() / out_path

    mask, meta = build_mask(kmz_paths, geocode_path, inverse=args.inverse)
    writefile.write(mask, out_file=str(out_path), metadata=meta)

    n_one = int(np.sum(mask))
    print(f"wrote {out_path}  shape={mask.shape}  ones={n_one}  zeros={mask.size - n_one}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
