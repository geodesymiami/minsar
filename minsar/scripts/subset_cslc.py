#!/usr/bin/env python3
"""
ISCE SLC Geographic Subsetting Script
Converts lat/lon to pixel coordinates and subsets SLC files
"""

import os
import argparse
import subprocess
import numpy as np
from glob import glob
from osgeo import gdal
from pathlib import Path
from typing import Tuple, Dict


def create_parser():
    parser = argparse.ArgumentParser(
        description='Subset ISCE SLC files by geographic area',
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:
  # Show pixel bounds for a geographic area
  %(prog)s merged/SLC/*/*.vrt --lat-file merged/geom_reference/lat.hdr --lon-file merged/geom_reference/lon.hdr --bbox 18.97 19.07 -98.7 -98.57 --info-only

  # Subset using geographic coordinates (via .vrt geolocation)
  %(prog)s merged/SLC/*/*.vrt --lat-file merged/geom_reference/lat.hdr --lon-file merged/geom_reference/lon.hdr --bbox 18.97 19.07 -98.7 -98.57

  # Subset using pixel coordinates
  %(prog)s merged/SLC/*/*.vrt --pixels 100 200 150 250

  # Batch process all SLC directories
  %(prog)s merged/SLC/2014* --lat-file merged/geom_reference/lat.hdr --lon-file merged/geom_reference/lon.hdr --bbox 18.97 19.07 -98.7 -98.57 --output-suffix _subset
        """
    )

    parser.add_argument('slc_dirs', nargs='+', help='Path(s) to SLC directories (e.g., merged/SLC/*/*.vrt)')
    parser.add_argument('--lon-file', default='None', help='Path to longitude file (e.g., merged/geom_reference/lon.hdr)')
    parser.add_argument('--lat-file', default='None', help='Path to latitude file (e.g., merged/geom_reference/lat.hdr)')
    parser.add_argument('--bbox', type=float, nargs=4, metavar=('LAT1', 'LAT2', 'LON1', 'LON2'), help='Geographic bounding box: lat_min lat_max lon_min lon_max')
    parser.add_argument('--pixels', type=int, nargs=4, metavar=('ROW1', 'ROW2', 'COL1', 'COL2'), help='Pixel bounding box: row_start row_end col_start col_end')
    parser.add_argument('--output-suffix', type=str, default='_subset', help='Suffix for output files when processing multiple SLCs')
    parser.add_argument('--info-only', action='store_true', help='Only print metadata and pixel bounds, do not subset')

    inps = parser.parse_args()

    if inps.lon_file:
        inps.lon_file = str(Path(inps.lon_file).resolve())

    if inps.lat_file:
        inps.lat_file = str(Path(inps.lat_file).resolve())

    return inps


class SLCGeoSubsetter:
    """Handle geographic subsetting of ISCE SLC files"""

    def __init__(self, slc: str, lat_file = None, lon_file = None):
        self.slc = slc
        self.slc_dir = str(Path(slc).parent)

        if lat_file and lon_file:
            self.lat = self._fetch_coords(lat_file)
            self.lon = self._fetch_coords(lon_file)

    def _fetch_coords(self,file):
        return gdal.Open(file).ReadAsArray()

    def lat_lon_to_pixels(self, lat: float, lon: float) -> Tuple[int, int]:
        """
        Convert geographic coordinates to pixel indices

        Args:
            lat: latitude
            lon: longitude

        Returns:
            (row, col) pixel indices in radar coordinates
        """
        first_lat = float(self.rsc.get('FIRST_LAT'))
        first_lon = float(self.rsc.get('FIRST_LON'))
        delta_lat = float(self.rsc.get('DELTA_LAT'))
        delta_lon = float(self.rsc.get('DELTA_LON'))

        # Pixel indices
        col = int((lon - first_lon) / delta_lon)
        row = int((lat - first_lat) / delta_lat)

        return row, col

    def bbox_to_pixels(self, lat1: float, lat2: float, lon1: float, lon2: float) -> Dict:
        """
        Convert bounding box (lat/lon) to pixel coordinates

        Args:
            lat1, lat2: latitude bounds (min, max)
            lon1, lon2: longitude bounds (min, max)

        Returns:
            Dictionary with pixel bounds: {row_start, row_end, col_start, col_end}
        """
        mask = ((self.lat >= lat1) & (self.lat <= lat2) & (self.lon >= lon1) & (self.lon <= lon2))

        rows, cols = np.where(mask)

        if rows.size == 0:
            raise ValueError("No pixels found inside bbox")

        row_start = rows.min()
        row_end = rows.max()
        col_start = cols.min()
        col_end = cols.max()

        return row_start, row_end, col_start, col_end

    def subset_with_gdal(self, output_file: str):
        """
        Subset SLC using gdal_translate

        Args:
            output_file: output .vrt filename
            use_pixels: if True, treat inputs as pixel indices (not lat/lon)
        """
        # Geographic subsetting (GDAL handles conversion via .vrt geolocation)
        cmd = [
            'gdal_translate',
            '-srcwin', str(self.bounds[2]), str(self.bounds[0]), str(self.bounds[3] - self.bounds[2]), str(self.bounds[1] - self.bounds[0]), 
            str(self.slc), output_file
        ]

        print(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
        new_gt = (
            self.gt[0] + self.bounds[2] * self.gt[1],
            self.gt[1],
            self.gt[2],
            self.gt[3] + self.bounds[0] * self.gt[5],
            self.gt[4],
            self.gt[5],
        )

        # Apply CRS + transform
        ds = gdal.Open(output_file, gdal.GA_Update)
        ds.SetGeoTransform(new_gt)
        ds.SetProjection(self.proj)
        ds = None

    def print_pixel_bounds(self, lat1: float, lat2: float, lon1: float, lon2: float):
        """Print pixel bounds for a geographic area"""
        self.bounds = self.bbox_to_pixels(lat1, lat2, lon1, lon2) #row_start, row_end, col_start, col_end
        print(f"\n=== Pixel bounds for bbox ({lat1}:{lat2}, {lon1}:{lon2}) ===")
        print(f"Row range: {self.bounds[0]} - {self.bounds[1]}")
        print(f"Col range: {self.bounds[2]} - {self.bounds[3]}")

    def subset(self):
        slc_path = Path(self.slc)
        sub_path = slc_path.parent / "subset"
        os.makedirs(sub_path, exist_ok=True)
        output = sub_path / slc_path.name

        print(f"\nSubsetting to: {output}")
        self.subset_with_gdal(str(output))


def main():
    os.chdir('/scratch/09580/gdisilvestro/ChilesSenD142')
    inps = create_parser()

    # Expand glob patterns if needed
    slc_files = []
    for pattern in inps.slc_dirs:
        raw = sorted({(Path(m)) for m in glob(pattern)})
        slc_files.extend(str(Path(r).resolve()) for r in raw)

    if not slc_files:
        print("No SLC files found")
        return

    for slc in sorted(slc_files):
        print(f"\n{'='*60}")
        print(f"Processing: {slc}")
        print(f"{'='*60}")

        try:
            subsetter = SLCGeoSubsetter(slc, inps.lat_file, inps.lon_file)

            if inps.bbox:
                lon1, lat1, lon2, lat2 = inps.bbox
                subsetter.print_pixel_bounds(lat1, lat2, lon1, lon2)

                if not inps.info_only:
                    subsetter.subset()

            elif inps.pixels:
                row1, row2, col1, col2 = inps.pixels
                print(f"\n=== Pixel bounds: rows {row1}-{row2}, cols {col1}-{col2} ===")

                if not inps.info_only:
                    subsetter.subset()

        except Exception as e:
            print(f"ERROR processing {slc}: {e}")
            continue


if __name__ == '__main__':
    main()