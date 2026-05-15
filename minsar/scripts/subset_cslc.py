#!/usr/bin/env python3
"""
ISCE SLC Geographic Subsetting Script
Converts lat/lon to pixel coordinates and subsets SLC files
"""

import os
import re
import shutil
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
  %(prog)s merged/SLC/*/*.vrt --lat-file merged/geom_reference/lat.rdr --lon-file merged/geom_reference/lon.rdr --bbox -98.7 18.97 -98.57 19.07 --info-only

  # Subset using geographic coordinates (via .vrt geolocation)
  %(prog)s merged/SLC/*/*.vrt --lat-file merged/geom_reference/lat.rdr --lon-file merged/geom_reference/lon.rdr --bbox -98.7 18.97 -98.57 19.07

  # Subset using pixel coordinates
  %(prog)s merged/SLC/*/*.vrt --pixels 100 200 150 250

  # Batch process all SLC directories
  %(prog)s merged/SLC/2014* --lat-file merged/geom_reference/lat.hdr --lon-file merged/geom_reference/lon.hdr --bbox -98.7 18.97 -98.57 19.07 --output-suffix _subset
        """
    )

    parser.add_argument('slc_dirs', nargs='+', help='Path(s) to SLC directories (e.g., merged/SLC/*/*.vrt)')
    parser.add_argument('--lon-file', default='None', help='Path to longitude file (e.g., merged/geom_reference/lon.hdr)')
    parser.add_argument('--lat-file', default='None', help='Path to latitude file (e.g., merged/geom_reference/lat.hdr)')
    parser.add_argument('--bbox', type=float, nargs=4, metavar=('LON1', 'LAT1', 'LON2', 'LAT2'), help='Geographic bounding box: lat_min lat_max lon_min lon_max')
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

        ds = gdal.Open(self.slc)
        self.gt = ds.GetGeoTransform()
        self.proj = ds.GetProjection()
        ds = None

        path = Path(os.path.join(os.getcwd(), 'merged', 'geom_reference'))
        if not lat_file:
            if path.exists():
                lat_file = path / 'lat.rdr'
        if not lon_file:
            if path.exists():
                lon_file = path / 'lon.rdr'

        self.lat = self._fetch_coords(lat_file)
        self.lon = self._fetch_coords(lon_file)

    def _open_gdal_dataset(self, file_path: str):
        candidates = []
        path = Path(file_path)

        if file_path:
            candidates.append(path)

        # Common sidecar formats for ISCE geometry files.
        if path.suffix != ".vrt":
            candidates.append(Path(str(path) + ".vrt"))
            candidates.append(path.with_suffix(".vrt"))

        if path.suffix != ".xml":
            candidates.append(Path(str(path) + ".xml"))
            candidates.append(path.with_suffix(".xml"))

        if path.suffix != ".hdr":
            candidates.append(Path(str(path) + ".hdr"))
            candidates.append(path.with_suffix(".hdr"))

        for candidate in candidates:
            if not candidate.exists():
                continue
            ds = gdal.Open(str(candidate))
            if ds is not None:
                return ds

        raise FileNotFoundError(
            f"Unable to open dataset. Checked: {', '.join(str(c) for c in candidates if c.exists())}"
        )

    def _fetch_coords(self, file_path: str):
        ds = self._open_gdal_dataset(file_path)
        band = ds.GetRasterBand(1)
        if band is None:
            raise ValueError(f"No raster band found in {file_path}")
        return band.ReadAsArray()

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


def subset_aux(bounds: Tuple[int, int, int, int], src_file: str):
    if not src_file:
        return

    src_path = Path(src_file)
    full_path = src_path.with_name("fullsize_" + src_path.name)
    tmp_out = src_path.with_name(src_path.stem + "_subset_tmp" + src_path.suffix)

    full_vrt = full_path.with_suffix(full_path.suffix + ".vrt")
    src_for_gdal = full_vrt if full_vrt.exists() else src_path

    if not full_path.exists():
        shutil.copy2(src_path, full_path)
        for suf in [".vrt", ".xml", ".hdr", ".rsc", ".aux.xml"]:
            sidecar = src_path.with_suffix(src_path.suffix + suf)
            if sidecar.exists():
                shutil.copy2(sidecar, full_path.with_suffix(full_path.suffix + suf))

    cmd = [
        "gdal_translate",
        "-of", "ENVI",
        "-srcwin",
        str(bounds[2]), str(bounds[0]),
        str(bounds[3] - bounds[2]), str(bounds[1] - bounds[0]),
        str(src_for_gdal),
        str(tmp_out),
    ]
    subprocess.run(cmd, check=True)

    shutil.move(str(tmp_out), str(src_path))

    # 4) Move ENVI header
    tmp_hdr = tmp_out.with_suffix(".hdr")
    if tmp_hdr.exists():
        final_hdr = src_path.with_suffix(".hdr")
        shutil.move(str(tmp_hdr), str(final_hdr))

    # 5) Delete ALL stale metadata that may have fullsize dimensions
    for suf in [".vrt", ".xml", ".rsc", ".aux.xml"]:
        stale = src_path.with_suffix(src_path.suffix + suf)
        if stale.exists():
            stale.unlink()

def subset_geom_files(bounds: Tuple[int, int, int, int], geom_dir: Path, geom_files: list[str]):
    for name in geom_files:
        src_path = geom_dir / name
        if not src_path.exists():
            continue
        subset_aux(bounds, str(src_path))


def main():
    # os.chdir('/scratch/09580/gdisilvestro/Falk/ChilesSenD142')
    inps = create_parser()

    # Expand glob patterns if needed
    slc_files = []
    for pattern in inps.slc_dirs:
        raw = sorted({(Path(m)) for m in glob(pattern)})
        slc_files.extend(str(Path(r).resolve()) for r in raw)

    if not slc_files:
        print("No SLC files found")
        return

    bounds = None

    for slc in sorted(slc_files):
        print(f"\n{'='*60}")
        print(f"Processing: {slc}")
        print(f"{'='*60}")

        try:
            subsetter = SLCGeoSubsetter(slc, inps.lat_file, inps.lon_file)

            if inps.bbox:
                lon1, lat1, lon2, lat2 = inps.bbox
                subsetter.print_pixel_bounds(lat1, lat2, lon1, lon2)
                bounds = subsetter.bounds

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

    if bounds and not inps.info_only:
        geom_files = [
            'lat.rdr',
            'lon.rdr',
            'hgt.rdr',
            'los.rdr',
            'shadowMask.rdr',
            'waterMask.rdr',
            'incLocal.rdr',
        ]

        geom_dir = None
        if inps.lat_file:
            geom_dir = Path(inps.lat_file).parent
        elif inps.lon_file:
            geom_dir = Path(inps.lon_file).parent
        else:
            geom_dir = Path(os.getcwd()) / 'merged' / 'geom_reference'

        # Backup geometry files before subsetting
        backup = geom_dir.parent / (geom_dir.name + "_backup")
        if not backup.exists():
            print(f"\nBacking up geometry files from {geom_dir} to {backup}")
            shutil.copytree(geom_dir, backup)

        subset_geom_files(bounds, geom_dir, geom_files)


if __name__ == '__main__':
    main()
