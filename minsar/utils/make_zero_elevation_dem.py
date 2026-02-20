#!/usr/bin/env python3
"""
Create zero-elevation DEM set to negative geoid height for ISCE processing.

Accepts either a .dem file path or a directory containing a .dem file.
With --swap-in-place, backs up originals to .orig, writes zero-elevation data
to the main .dem (from .dem.orig), then runs fixImageXml.py so .dem.xml is
correct for ISCE.

Examples (Miami):
  make_zero_elevation_dem.py DEM/elevation_N25_N27_W082_W078.dem
  make_zero_elevation_dem.py DEM/
  make_zero_elevation_dem.py DEM/ --swap-in-place
  make_zero_elevation_dem.py DEM/ --swap-in-place --dry-run
  make_zero_elevation_dem.py DEM/ --swap-in-place --geoid-height -28
"""
import argparse
import shutil
import subprocess
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS, Transformer

# Original-side suffixes to back up when --swap-in-place
ORIGINAL_SUFFIXES = [".dem", ".dem.aux.xml", ".dem.vrt", ".dem.xml", ".hdr"]


def calculate_geoid_height(lon, lat):
    """
    Calculate geoid height using EGM96 via pyproj.
    Returns rounded integer.
    """
    try:
        crs_ellipsoid = CRS.from_string("EPSG:4979")  # WGS84 ellipsoidal
        crs_geoid = CRS.from_string("EPSG:4326+5773")  # WGS84 + EGM96 geoid
        transformer = Transformer.from_crs(crs_ellipsoid, crs_geoid, always_xy=True)
        _, _, geoid_height = transformer.transform(lon, lat, 0)
        return int(round(geoid_height))
    except Exception as e:
        raise RuntimeError(f"Failed to calculate geoid height: {e}") from e


def resolve_dem_path(dem_path: Path) -> Path:
    """
    Resolve dem_path to the canonical .dem file.
    Accepts a file path or directory; rejects *_zero.dem as primary.
    """
    dem_path = dem_path.resolve()
    if not dem_path.exists():
        raise FileNotFoundError(f"Path {dem_path} not found")

    if dem_path.is_file():
        if dem_path.suffix != ".dem" and not dem_path.name.endswith(".dem"):
            raise ValueError(f"File {dem_path} does not end in .dem")
        if dem_path.stem.endswith("_zero"):
            raise ValueError(
                "Cannot use *_zero.dem as primary input. Give the main .dem file or directory."
            )
        return dem_path

    if dem_path.is_dir():
        candidates = sorted(p for p in dem_path.glob("*.dem") if "_zero" not in p.stem)
        if not candidates:
            raise FileNotFoundError(
                f"No primary .dem file found in {dem_path} (excluding *_zero.dem)"
            )
        return candidates[0]

    raise ValueError(f"Path {dem_path} is neither a file nor a directory")


def get_auxiliary_files(dem_path: Path) -> list:
    """Return existing paths for base + each of ORIGINAL_SUFFIXES."""
    base = dem_path.parent / dem_path.stem
    result = []
    for suffix in ORIGINAL_SUFFIXES:
        p = Path(str(base) + suffix)
        if p.exists():
            result.append(p)
    return result


def backup_path_for(base: Path, orig: Path) -> Path:
    """
    Backup path so the file keeps a format-recognized extension (e.g. .dem).
    base.dem -> base_orig.dem so rasterio can open the backup; base.dem.aux.xml -> base_orig.dem.aux.xml.
    """
    suffix = orig.name[len(base.name) :]  # e.g. ".dem", ".dem.aux.xml"
    return base.parent / (base.name + "_orig" + suffix)


def do_swap_in_place(dem_path: Path, dry_run: bool) -> None:
    """
    Backup original DEM and auxiliary files to _orig names (e.g. base.dem -> base_orig.dem)
    so the backup raster keeps a .dem extension and can be opened by rasterio.
    """
    base = dem_path.parent / dem_path.stem
    for p in get_auxiliary_files(dem_path):
        dest = backup_path_for(base, p)
        if dry_run:
            print(f"Would rename: {p} -> {dest}")
        else:
            p.rename(dest)


def ensure_dem_xml_for_fix(dem_path: Path) -> None:
    """
    If .dem.xml is missing but *_orig.dem.xml exists, copy it so fixImageXml.py
    has an XML to update (fixImageXml updates existing XML; it may not create one).
    """
    main_xml = dem_path.parent / f"{dem_path.stem}.dem.xml"
    orig_xml = dem_path.parent / f"{dem_path.stem}_orig.dem.xml"
    if not main_xml.exists() and orig_xml.exists():
        shutil.copy2(orig_xml, main_xml)


def run_fix_image_xml(dem_path: Path, dry_run: bool) -> None:
    """
    Run ISCE fixImageXml.py -f -i <dem_path> so .dem.xml matches the raster.
    """
    if dry_run:
        print(f"Would run: fixImageXml.py -f -i {dem_path}")
        return
    ensure_dem_xml_for_fix(dem_path)
    try:
        subprocess.run(
            ["fixImageXml.py", "-f", "-i", str(dem_path)],
            check=True,
            capture_output=True,
        )
    except FileNotFoundError:
        print(
            f"fixImageXml.py not found (ISCE may not be on PATH). "
            f"Run manually: fixImageXml.py -f -i {dem_path}"
        )
        raise
    except subprocess.CalledProcessError as e:
        print(f"fixImageXml.py failed: {e.stderr.decode() if e.stderr else e}")
        raise


def create_zero_raster(
    src_path: Path,
    dst_path: Path,
    geoid_height_override: int | None = None,
) -> None:
    """
    Read DEM from src_path, fill with -geoid_value, write to dst_path (and .hdr).
    """
    with rasterio.open(src_path) as src:
        profile = src.profile
        transform = src.transform
        ul_lon = transform.c
        ul_lat = transform.f
        print(f"Upper-left corner coordinates: lon={ul_lon}, lat={ul_lat}")

        if geoid_height_override is not None:
            geoid_value = geoid_height_override
            print(f"Using provided geoid height: {geoid_value} m")
        else:
            print("Calculating geoid height via pyproj...")
            geoid_value = calculate_geoid_height(ul_lon, ul_lat)
            print(f"Calculated geoid height: {geoid_value} m")

        fill_value = -geoid_value
        print(f"Setting all DEM pixels to {fill_value} meters")

        data = np.full(
            (src.count, src.height, src.width), fill_value, dtype=src.dtypes[0]
        )
        profile.update(dtype=src.dtypes[0], compress="lzw")
        with rasterio.open(dst_path, "w", **profile) as dst:
            dst.write(data)


def main():
    parser = argparse.ArgumentParser(
        description="Create zero-elevation DEM set to negative geoid height for ISCE processing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  make_zero_elevation_dem.py DEM/elevation_N25_N27_W082_W078.dem
  make_zero_elevation_dem.py DEM/
  make_zero_elevation_dem.py DEM/ --swap-in-place
  make_zero_elevation_dem.py DEM/ --swap-in-place --dry-run
  make_zero_elevation_dem.py DEM/ --swap-in-place --geoid-height -28
""",
    )
    parser.add_argument(
        "dem_path",
        help="Input DEM file or directory containing a .dem file (e.g. DEM/ or DEM/elevation_N25_N27_W082_W078.dem)",
    )
    parser.add_argument(
        "--geoid-height",
        type=int,
        default=None,
        help="Override geoid height (integer meters). If given, skip pyproj calculation.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite input file instead of writing new file (ignored with --swap-in-place)",
    )
    parser.add_argument(
        "--swap-in-place",
        action="store_true",
        help="Backup originals to .orig, write zero-elevation to main .dem, run fixImageXml.py for ISCE",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print intended operations without modifying files",
    )

    args = parser.parse_args()
    dem_path_arg = Path(args.dem_path)

    input_dem = resolve_dem_path(dem_path_arg)
    base = input_dem.parent / input_dem.stem
    main_dem = base.with_suffix(".dem")
    dem_orig = base.parent / (base.name + "_orig.dem")

    if args.swap_in_place:
        args.overwrite = False  # Ignore --overwrite

    if args.dry_run and args.swap_in_place:
        print(f"Would find DEM: {input_dem}")
        do_swap_in_place(input_dem, dry_run=True)
        print(f"Would read {dem_orig} and write zero to {main_dem} (and .hdr)")
        run_fix_image_xml(main_dem, dry_run=True)
        return

    if args.dry_run and not args.swap_in_place:
        output_path = input_dem.with_name(input_dem.stem + "_zero.dem")
        print(f"Would find DEM: {input_dem}")
        print(f"Would create: {output_path} (and .hdr)")
        return

    if args.swap_in_place:
        # Backup first if .dem.orig does not exist (first run)
        if not dem_orig.exists():
            do_swap_in_place(input_dem, dry_run=False)
        # Create zero from .dem.orig -> .dem (re-run uses same .dem.orig)
        print(f"Reading DEM: {dem_orig}")
        create_zero_raster(
            dem_orig,
            main_dem,
            geoid_height_override=args.geoid_height,
        )
        print(f"Zero-elevation DEM written to: {main_dem}")
        run_fix_image_xml(main_dem, dry_run=False)
        print("Swap complete. Zero-elevation DEM is now primary.")
        return

    # Non–swap-in-place: create *_zero.dem (and .hdr)
    output_path = input_dem.with_name(input_dem.stem + "_zero.dem")
    if args.overwrite:
        output_path = input_dem
    print(f"Reading DEM: {input_dem}")
    create_zero_raster(
        input_dem,
        output_path,
        geoid_height_override=args.geoid_height,
    )
    print(f"Zero-elevation DEM written to: {output_path}")


if __name__ == "__main__":
    main()
