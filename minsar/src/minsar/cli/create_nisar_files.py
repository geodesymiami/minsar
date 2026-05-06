#!/usr/bin/env python3

import os
import tqdm
import argparse
import datetime
import subprocess
import numpy as np
from datetime import date
from shapely import wkt as _wkt
import mintpy.prep_nisar as nisar

from minsar.src.minsar.cli import asf_search_args as asf
from minsar.src.minsar.helper_functions import parse_polygon

try:
    from pyproj import CRS, Transformer
    import xarray as xr
except ImportError:
    pass  # Will error if processing section is used without these


def create_parser():
    parser = argparse.ArgumentParser(
        description="Wrapper to call asf_search_args.py for NISAR GUNW downloads and postprocess."
    )
    parser.add_argument('--flightDirection', default=['DESCENDING', 'ASCENDING'], help='ASCENDING or DESCENDING')
    parser.add_argument('--intersectsWith', help='WKT POLYGON string')
    parser.add_argument('--processingLevel', dest='processing_level', choices=['GUNW', 'RSLC'], default='GUNW', help='Product type to download')
    parser.add_argument('--start', default='20251029', help='Start date (YYYYMMDD or YYYY-MM-DD)')
    parser.add_argument('--end', default=date.today().isoformat(), help='End date (YYYYMMDD or YYYY-MM-DD)')
    parser.add_argument('--dir', help='Output directory for downloads')
    parser.add_argument('--download', action='store_true', help='Download the data (default if specified)')
    parser.add_argument('--process', action='store_true', help='Process/crop files after download')
    parser.add_argument('--dem-file', default=None, help='DEM file to use for processing')
    parser.add_argument('--mask-file', default=None, help='Mask file to use for processing')

    parser.add_argument('extra', nargs=argparse.REMAINDER, help='Other options for asf_search_args.py')

    inps = parser.parse_args()

    if inps.intersectsWith:
        min_lon, max_lon, min_lat, max_lat = parse_polygon(inps.intersectsWith)
        inps.subset_lat = (min_lat, max_lat)
        inps.subset_lon = (min_lon, max_lon)

    if not inps.dem_file:
        inps.dem_file = os.path.join(inps.dir, "dem.tif")
    else:
        inps.dem_file = os.path.join(os.getcwd(), inps.dem_file) if not os.path.isabs(inps.dem_file) else inps.dem_file

    return inps


def get_utm_crs_from_bbox(lon, lat):
    zone = int((lon + 180) // 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return CRS.from_epsg(epsg)


def utm_to_latlon(x, y, utm_crs):
    wgs84 = CRS.from_epsg(4326)
    transformer = Transformer.from_crs(utm_crs, wgs84, always_xy=True)
    lon, lat = transformer.transform(x, y)
    return lon, lat

def _normalize_meta_value(value):
    def _collapse_singleton(v):
        while isinstance(v, (list, tuple)) and len(v) == 1 and not isinstance(v[0], (float, int, str)):
            v = v[0]
        return v
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return _normalize_meta_value(value.item())
        norm_list = [_normalize_meta_value(item) for item in value.tolist()]
        return _collapse_singleton(norm_list)
    if isinstance(value, (list, tuple)):
        if len(value) == 1 and isinstance(value[0], (float, int, str)):
            return value[0]
        norm_list = [_normalize_meta_value(item) for item in value]
        return _collapse_singleton(norm_list)
    return value


def extract_identification_metadata(nc):
    identification_group = nc.groups.get("identification") if hasattr(nc, "groups") else None
    if identification_group is None:
        return argparse.Namespace(attrs={}, variables={})
    identification_variables = {}
    for var_name, var_obj in identification_group.variables.items():
        var_value = _normalize_meta_value(var_obj[...])
        identification_variables[var_name] = var_value
    return argparse.Namespace(**identification_variables)


def get_output_filename(metadata,):
    def mget(key, default=None):
        if isinstance(metadata, dict):
            return metadata.get(key, default)
        if hasattr(metadata, "attrs") and key in metadata.attrs:
            return metadata.attrs.get(key, default)
        if hasattr(metadata, "variables") and key in metadata.variables:
            return metadata.variables.get(key, default)
        if hasattr(metadata, key):
            return getattr(metadata, key)
        return default
    def parse_ymd(value):
        if not value:
            return "00000000"
        s = str(value).strip()
        for fmt in (
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
        ):
            try:
                return datetime.datetime.strptime(s, fmt).strftime("%Y%m%d")
            except ValueError:
                pass
        return s[:10].replace("-", "")
    direction = metadata.orbit_pass_direction if hasattr(metadata, "orbit_pass_direction") else None
    if direction is not None:
        direction = str(direction).strip().upper()
    sat_raw = mget("source_data_satellite_names", mget("mission", "NISAR"))
    sat_str = str(sat_raw).upper().replace(" ", "") if sat_raw is not None else ""
    if "NISAR" in sat_str:
        sat = "NISAR"
    else:
        sat = str(sat_raw).split(",")[0].strip() if sat_raw else "NISAR"
    relorb = f"{int(mget('relative_orbit', mget('track_number', 0))):03d}"
    relorb2 = f"{int(mget('relative_orbit_second', mget('frame_id', 0))):05d}"
    method_str = str(mget("post_processing_method", "gunw")).lower()
    date1 = parse_ymd(
        mget("first_date", mget("reference_datetime", mget("reference_zero_doppler_start_time")))
    )
    date2 = parse_ymd(
        mget("last_date", mget("secondary_datetime", mget("secondary_zero_doppler_start_time")))
    )
    update_flag = str(mget("cfg.mintpy.save.hdfEos5.update", "")).lower() == "yes"
    if update_flag:
        date2 = "XXXXXXXX"
    direction_val = direction or mget("orbit_pass_direction", None)
    if direction_val:
        direction_upper = str(direction_val).strip().upper()
        if "ASC" in direction_upper:
            direction_val = "asc"
        elif "DES" in direction_upper:
            direction_val = "desc"
        else:
            direction_val = str(direction_val).strip().lower()
    if direction_val:
        out_name = f"{sat}_{direction_val}_{relorb}_{relorb2}_{method_str}_{date1}_{date2}.h5"
    else:
        out_name = f"{sat}_{relorb}_{relorb2}_{method_str}_{date1}_{date2}.h5"
    fbase, fext = os.path.splitext(out_name)
    polygon_str = mget("data_footprint", mget("bounding_polygon", None))
    if polygon_str:
        try:
            sub = polygon_corners_string(polygon_str)
            out_name = f"{fbase}_{sub}{fext}"
        except Exception:
            pass
    return out_name


def merge_metadata(metadata: list[argparse.Namespace]) -> argparse.Namespace:
    def _as_set(val):
        if isinstance(val, str) and ',' in val:
            return set(s.strip() for s in val.split(','))
        return val
    dicts = [vars(m) for m in metadata]
    shared_keys = set(dicts[0]).intersection(*dicts[1:])
    shared = {}
    for k in shared_keys:
        v0 = dicts[0][k]
        if all(_as_set(d[k]) == _as_set(v0) for d in dicts[1:]):
            shared[k] = v0
    return argparse.Namespace(**shared)


def polygon_corners_string(polygon_str: str) -> str:
    def fmt_lat(lat: float) -> str:
        val = int(round(abs(lat) * 100))
        return f"{'N' if lat >= 0 else 'S'}{val:04d}"
    def fmt_lon(lon: float) -> str:
        val = int(round(abs(lon) * 100))
        return f"{'E' if lon >= 0 else 'W'}{val:05d}"
    poly = _wkt.loads(polygon_str)
    coords = list(poly.exterior.coords)[:-1]
    corners = [(lat, lon) for lon, lat in coords]
    parts = [f"{fmt_lat(lat)}{fmt_lon(lon)}" for (lat, lon) in corners]
    corners_str = "_".join(parts)
    return  corners_str


def main():
    inps = create_parser()

    files = []
    # Download section
    if inps.download:
        asf_inps = [
            '--intersectsWith', inps.intersectsWith,
            '--start', inps.start,
            '--end', inps.end,
            '--processingLevel', inps.processing_level,
            '--platform', 'NISAR',
            '--dir', inps.dir,
            '--flightDirection', inps.flightDirection,
        ]
        if inps.download:
            asf_inps.append('--download')
        if inps.extra:
            asf_inps.extend(inps.extra)
        results = asf.main(asf_inps)
        centroid = []
        for r in results:
            files.append(os.path.join(inps.dir, r.properties['fileName']))
            centroid.append((r.centroid().x, r.centroid().y))

    if not os.path.exists(inps.dem_file):
        region = parse_polygon(inps.intersectsWith)
        subprocess.run([
            "sardem",
            "--bbox", str(region[0]), str(region[2]), str(region[1]), str(region[3]),
            "--data-source", "NISAR",
            "--output", inps.dem_file,
        ])

    # Processing section
    if inps.process:
        inps.input_glob = inps.dir + "/*.h5"
        inps.out_dir = inps.dir
        inps.update_mode = False

        nisar.load_nisar(inps)

        pass

if __name__ == '__main__':
    main()
