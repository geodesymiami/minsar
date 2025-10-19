#!/usr/bin/env python3
import argparse
from pathlib import Path
import numpy as np
import rasterio
from rasterio.enums import Resampling
from pyproj import CRS, Transformer

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
        raise RuntimeError(f"Failed to calculate geoid height: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="Create zero-elevation DEM set to negative geoid height for ISCE processing."
    )
    parser.add_argument("dem_file", help="Input DEM file")
    parser.add_argument("--geoid-height", type=int, default=None,
                        help="Override geoid height (integer meters). If given, skip pyproj calculation.")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite input file instead of writing new file")

    args = parser.parse_args()
    input_path = Path(args.dem_file)

    if not input_path.exists():
        raise FileNotFoundError(f"Input DEM {input_path} not found")

    # Determine output path
    if args.overwrite:
        output_path = input_path
    else:
        if input_path.suffix:
            output_path = input_path.with_name(input_path.stem + "_zero" + input_path.suffix)
        else:
            output_path = Path(str(input_path) + "_zero.dem")

    print(f"Reading DEM: {input_path}")

    # Read DEM raster
    with rasterio.open(input_path) as src:
        profile = src.profile
        transform = src.transform

        # Compute DEM bounding upper-left coordinates
        ul_lon = transform.c
        ul_lat = transform.f
        print(f"Upper-left corner coordinates: lon={ul_lon}, lat={ul_lat}")

        # Determine geoid height
        if args.geoid_height is not None:
            geoid_value = int(args.geoid_height)
            print(f"Using provided geoid height: {geoid_value} m")
        else:
            print("Calculating geoid height via pyproj...")
            geoid_value = calculate_geoid_height(ul_lon, ul_lat)
            print(f"Calculated geoid height: {geoid_value} m")

        # Value to assign to all pixels (ocean should be -geoid_value)
        fill_value = -geoid_value
        print(f"Setting all DEM pixels to {fill_value} meters")

        # Fill array with this constant
        data = np.full((src.count, src.height, src.width), fill_value, dtype=src.dtypes[0])

        # Write output
        profile.update(dtype=src.dtypes[0], compress="lzw")
        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(data)

    print(f"✅ Zero-elevation DEM written to: {output_path}")

if __name__ == "__main__":
    main()
