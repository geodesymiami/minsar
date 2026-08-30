"""Dolphin GeoTIFF discovery for summary PNG plotting (no MintPy dependency)."""

from __future__ import annotations

import glob
import re
from pathlib import Path

import numpy as np
import rasterio

TC_VMIN = 0.6


def resolve_run_paths(input_path: Path) -> tuple[Path, Path, Path]:
    """Return (dataset_dir, dolphin_dir, timeseries_dir)."""
    path = input_path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input path does not exist: {path}")
    if path.is_file():
        path = path.parent
    if path.name == "timeseries":
        ts_dir = path
        dolphin_dir = path.parent if path.parent.name == "dolphin" else path.parent
        dataset_dir = dolphin_dir.parent if dolphin_dir.name == "dolphin" else dolphin_dir
        return dataset_dir, dolphin_dir, ts_dir
    if (path / "timeseries").is_dir() and path.name == "dolphin":
        return path.parent, path, path / "timeseries"
    if (path / "dolphin" / "timeseries").is_dir():
        return path, path / "dolphin", path / "dolphin" / "timeseries"
    if (path / "timeseries").is_dir():
        return path, path, path / "timeseries"
    raise FileNotFoundError(
        f"No timeseries/ directory in {path} (pass the dolphin dir, e.g. plot_dolphin_summary_pngs.py --dir dolphin)"
    )


def find_geometry_path(path: Path | None = None) -> Path:
    """Return a geometry directory next to path or a parent."""
    path = path or Path.cwd()
    for candidate in (path / "geometry", path.parent / "geometry", path.parent.parent / "geometry"):
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"No geometry directory found near {path}")


def read_geotiff(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        return src.read(1)


def _timeseries_tifs(ts_dir: Path) -> tuple[list[Path], list[Path]]:
    pair_files = sorted(
        p for p in ts_dir.iterdir()
        if p.suffix.lower() in {".tif", ".tiff"} and re.fullmatch(r"\d{8}_\d{8}", p.stem)
    )
    date_files = sorted(
        p for p in ts_dir.iterdir()
        if p.suffix.lower() in {".tif", ".tiff"} and re.fullmatch(r"\d{8}", p.stem)
    )
    return pair_files, date_files


def _glob_existing(pattern: Path) -> list[Path]:
    return [Path(path) for path in sorted(glob.glob(str(pattern)))]


def _geometry_dir(dataset_dir: Path, dolphin_dir: Path, ts_dir: Path) -> Path | None:
    for candidate in (
        dolphin_dir / "geometry",
        ts_dir / "geometry",
        dataset_dir / "geometry",
    ):
        if candidate.is_dir():
            return candidate
    try:
        return find_geometry_path(ts_dir)
    except FileNotFoundError:
        return None


def resolve_plot_files(dolphin_dir: Path) -> dict:
    """Locate Dolphin rasters for summary PNGs. Omits missing layers (no raise)."""
    dataset_dir, dolphin_dir, ts_dir = resolve_run_paths(dolphin_dir)
    files: dict = {
        "dataset_dir": dataset_dir,
        "dolphin_dir": dolphin_dir,
        "ts_dir": ts_dir,
    }

    pair_files, date_files = _timeseries_tifs(ts_dir)
    if pair_files:
        files["timeseries_pairs"] = pair_files
    if date_files:
        files["timeseries_dates"] = date_files

    velocity = ts_dir / "velocity.tif"
    if velocity.is_file():
        files["velocity"] = velocity

    temp_files: list[Path] = []
    for candidate in (
        ts_dir / "temporal_coherence_average.tif",
        ts_dir / "temporal_coherence.tif",
    ):
        if candidate.is_file():
            temp_files = [candidate]
            break
    if not temp_files:
        ifg_dir = dolphin_dir / "interferograms"
        temp_files = _glob_existing(ifg_dir / "*temporal*coherence*average*")
        if not temp_files:
            temp_files = _glob_existing(ifg_dir / "temporal_coherence_*.tif")
    if temp_files:
        files["temporal_coherence"] = temp_files[-1]

    conn_path = ts_dir / "conncomp_intersection.tif"
    if conn_path.is_file():
        files["conncomp"] = conn_path

    geom_dir = _geometry_dir(dataset_dir, dolphin_dir, ts_dir)
    if geom_dir is not None:
        files["geometry_dir"] = geom_dir
        height = geom_dir / "height.tif"
        if height.is_file():
            files["height"] = height

    ifg_dir = dolphin_dir / "interferograms"
    avg_paths = _glob_existing(ifg_dir / "*.int.cor.tif")
    if avg_paths:
        files["avg_spatial_paths"] = avg_paths

    int_paths = sorted(
        p for p in ifg_dir.glob("*.int.tif") if p.is_file() and ".cor." not in p.name
    )
    if int_paths:
        files["interferograms"] = int_paths

    return files
