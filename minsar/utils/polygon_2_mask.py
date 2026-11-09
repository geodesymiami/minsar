#!/usr/bin/env python3
"""Build a MintPy polygon mask on the grid of each reference file."""

from __future__ import annotations

import argparse
import csv
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

# VLM CSV has no pixel grid; this step (~11 m) covers the points for point lookup.
CSV_STEP_DEG = 0.0001

DESCRIPTION = """\
Create a MintPy mask HDF5 on the grid of each reference file.
Geocoded inputs (Y_FIRST) are sampled at pixel centers.
Radar inputs use per-pixel latitude/longitude.
One mask is written next to each reference file.
"""

EXAMPLE = """Examples:
polygon_2_mask.py Run*.kmz geo_velocity.h5
polygon_2_mask.py Run* ../ShirzaeiComment/MIA_VLM.csv miaplpy_201509_202609/network_delaunay_4/velocity.h5 miaplpy_201509_202101/network_delaunay_4/velocity.h5 ../MiamiMIADISPS1SenA48/geo_velocity.h5 mintpy_2015-2026/geo_velocity.h5
polygon_2_mask.py aoi.kmz geo_velocity.h5 --inverse
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EXAMPLE,
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        metavar="FILE",
        help="KMZ/KML polygons and reference files (.h5, .he5, or VLM .csv)",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="outfile",
        default=None,
        help="output path when there is a single reference file",
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


def expand_inputs(raw_paths: list[str]) -> tuple[list[Path], list[Path]]:
    """Split KMZ/KML polygons from reference grids. Globs are expanded."""
    kmz_paths: list[Path] = []
    ref_paths: list[Path] = []
    for raw in raw_paths:
        if any(ch in raw for ch in "*?[]"):
            matches = sorted(glob.glob(raw))
            if not matches:
                raise FileNotFoundError(f"no files match: {raw}")
            paths = [Path(p).resolve() for p in matches]
        else:
            path = Path(raw).expanduser().resolve()
            if not path.is_file():
                raise FileNotFoundError(f"file not found: {path}")
            paths = [path]
        for path in paths:
            suffix = path.suffix.lower()
            if suffix in {".kmz", ".kml"}:
                kmz_paths.append(path)
            elif suffix in {".h5", ".he5", ".csv"}:
                ref_paths.append(path)
            else:
                raise ValueError(f"expected .kmz, .kml, .h5, .he5, or .csv, got: {path}")
    return kmz_paths, ref_paths


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
    lat = np.asarray(readfile.read(str(geom_path), datasetName="latitude")[0], dtype=np.float64)
    lon = np.asarray(readfile.read(str(geom_path), datasetName="longitude")[0], dtype=np.float64)
    if lat.shape != shape or lon.shape != shape:
        raise ValueError(
            f"geometry grid {lat.shape} does not match reference grid {shape}: {geom_path}"
        )
    return lat, lon


def _is_geocoded(atr: dict) -> bool:
    return "Y_FIRST" in atr


def read_reference_grid(ref_path: Path) -> tuple[tuple[int, int], dict]:
    """Shape and original attributes. Radar HE5 metadata is not given a fake Y_FIRST."""
    ref_path = ref_path.expanduser().resolve()
    if not ref_path.is_file():
        raise FileNotFoundError(f"reference file not found: {ref_path}")

    if ref_path.suffix.lower() == ".he5":
        atr = dict(readfile.read_attribute(str(ref_path)))
        with h5py.File(ref_path) as handle:
            lat_name = "HDFEOS/GRIDS/timeseries/geometry/latitude"
            if lat_name not in handle:
                raise ValueError(f"HE5 has no latitude grid: {ref_path}")
            shape = tuple(int(n) for n in handle[lat_name].shape)
        return shape, atr

    if ref_path.suffix.lower() == ".csv":
        return _csv_grid(ref_path)

    atr = dict(readfile.read_attribute(str(ref_path)))
    if "LENGTH" not in atr or "WIDTH" not in atr:
        raise ValueError(f"reference file has no LENGTH/WIDTH: {ref_path}")
    shape = (int(atr["LENGTH"]), int(atr["WIDTH"]))
    return shape, atr


def _csv_lon_lat(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")
        fields = {name.strip().lower(): name for name in reader.fieldnames}
        if "longitude" not in fields or "latitude" not in fields:
            raise ValueError(f"CSV needs Longitude and Latitude columns: {path}")
        lon_key, lat_key = fields["longitude"], fields["latitude"]
        lon_vals: list[float] = []
        lat_vals: list[float] = []
        for row in reader:
            lon_vals.append(float(row[lon_key]))
            lat_vals.append(float(row[lat_key]))
    if not lon_vals:
        raise ValueError(f"CSV has no points: {path}")
    return np.asarray(lon_vals, dtype=np.float64), np.asarray(lat_vals, dtype=np.float64)


def _csv_grid(path: Path) -> tuple[tuple[int, int], dict]:
    """Regular lat/lon grid covering the CSV points. Y_FIRST is the north pixel corner."""
    lon, lat = _csv_lon_lat(path)
    step = CSV_STEP_DEG
    lat_s = float(np.min(lat)) - step
    lat_n = float(np.max(lat)) + step
    lon_w = float(np.min(lon)) - step
    lon_e = float(np.max(lon)) + step
    length = int(np.ceil((lat_n - lat_s) / step)) + 1
    width = int(np.ceil((lon_e - lon_w) / step)) + 1
    atr = {
        "LENGTH": str(length),
        "WIDTH": str(width),
        "Y_FIRST": str(lat_n + 0.5 * step),
        "X_FIRST": str(lon_w - 0.5 * step),
        "Y_STEP": str(-step),
        "X_STEP": str(step),
        "Y_UNIT": "degrees",
        "X_UNIT": "degrees",
    }
    return (length, width), atr


def _radar_geometry_latlon(ref_path: Path, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    candidates = [
        ref_path.parent / "geometryRadar.h5",
        ref_path.parent / "inputs" / "geometryRadar.h5",
    ]
    for candidate in candidates:
        if candidate.is_file():
            print(f"Grid:       radar lat/lon from {candidate.name}")
            return _lat_lon_from_geometry_h5(candidate, shape)
    raise ValueError(
        f"radar file {ref_path.name} needs geometryRadar.h5 in the same directory or inputs/"
    )


def lat_lon_grids(ref_path: Path, shape: tuple[int, int], atr: dict) -> tuple[np.ndarray, np.ndarray]:
    if _is_geocoded(atr):
        print("Grid:       geocoded lat/lon, pixel centers")
        return _regular_lat_lon_grid(shape, atr)

    if ref_path.suffix.lower() == ".he5":
        he5_ll = _he5_geometry_latlon(ref_path)
        if he5_ll is None or he5_ll[0].shape != shape:
            raise ValueError(f"HE5 latitude/longitude does not match the grid: {ref_path}")
        print("Grid:       radar lat/lon from HE5")
        return he5_ll

    return _radar_geometry_latlon(ref_path, shape)


def polygon_mask_on_grid(geom, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    inside = contains(geom, lon, lat)
    return inside.astype(np.float32)


def mask_metadata(reference_atr: dict) -> dict:
    meta = dict(reference_atr)
    meta["FILE_TYPE"] = "mask"
    return meta


def output_path(ref_path: Path, geocoded: bool, outfile: str | None) -> Path:
    if outfile:
        out = Path(outfile).expanduser()
        if not out.is_absolute():
            out = Path.cwd() / out
        return out
    name = "geo_polygon_2_mask.h5" if geocoded else "polygon_2_mask.h5"
    return ref_path.parent / name


def build_mask(
    geom,
    ref_path: Path,
    *,
    inverse: bool = False,
) -> tuple[np.ndarray, dict, bool]:
    shape, atr = read_reference_grid(ref_path)
    geocoded = _is_geocoded(atr)
    lat, lon = lat_lon_grids(ref_path, shape, atr)
    mask = polygon_mask_on_grid(geom, lat, lon)
    if inverse:
        mask = 1.0 - mask
    return mask, mask_metadata(atr), geocoded


def main(argv: list[str] | None = None) -> int:
    cmd_argv = sys.argv[1:] if argv is None else argv
    message_rsmas.log(os.getcwd(), os.path.basename(__file__) + " " + " ".join(cmd_argv))

    parser = create_parser()
    args = parser.parse_args(argv)

    try:
        kmz_paths, ref_paths = expand_inputs(args.inputs)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    if not kmz_paths:
        parser.error("need at least one KMZ/KML polygon file")
    if not ref_paths:
        parser.error("need at least one reference file (.h5, .he5, or .csv)")
    if args.outfile and len(ref_paths) != 1:
        parser.error("--output applies to a single reference file")

    geom = load_polygons(kmz_paths)
    for ref_path in ref_paths:
        print(f"reference:  {ref_path}")
        mask, meta, geocoded = build_mask(geom, ref_path, inverse=args.inverse)
        out_path = output_path(ref_path, geocoded, args.outfile)
        writefile.write(mask, out_file=str(out_path), metadata=meta)
        n_one = int(np.sum(mask))
        kind = "geocoded" if geocoded else "radar-coded"
        print(f"wrote {out_path}  {kind}  shape={mask.shape}  ones={n_one}  zeros={mask.size - n_one}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
