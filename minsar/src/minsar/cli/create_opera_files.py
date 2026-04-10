#!/usr/bin/env python3


import os
import glob
import tqdm
import netCDF4
import argparse
import datetime
import subprocess
import numpy as np
from datetime import date
from shapely import wkt as _wkt
from mintpy.objects import HDFEOS
from minsar.src.minsar.cli import asf_search_args as asf
from minsar.src.minsar.helper_functions import parse_polygon, convert_to_coord, extract_identification_metadata, normalize_meta_value


def create_parser():
    parser = argparse.ArgumentParser(
        description="Create OPERA timeseries file."
    )

    parser.add_argument('--dir', help='Output directory for downloads')
    parser.add_argument('--dem-file', default=None, help='DEM file to download (optional)')

    inps = parser.parse_args()

    if inps.dem_file and not os.path.abspath(inps.dem_file):
        inps.dem_file = os.path.join(os.getcwd(), inps.dem_file)

    return inps


def temporal_inversion(aggregated_time_1, aggregated_time_2, aggregated_displacement):
    # ============================================
    # Build cumulative displacement time series
    # from pairwise (t1 -> t2) aggregated data
    # ============================================
    # --------------------------------------------------
    # INPUT (assumed structure)
    # --------------------------------------------------
    # aggregated_time_1: list of start dates (len = n_obs)
    # aggregated_time_2: list of end dates   (len = n_obs)
    # aggregated_displacement: list of 2D arrays (ny, nx)
    # Each entry i represents:
    #   D_i = displacement from t1_i to t2_i
    # --------------------------------------------------

    # --------------------------------------------------
    # 1. Build global time axis
    # --------------------------------------------------
    # Collect all unique times and sort them
    times = np.unique(np.array(aggregated_time_1 + aggregated_time_2))
    times = np.sort(times)
    nt = len(times)

    # Map each time to an index
    time_to_idx = {t: i for i, t in enumerate(times)}

    # --------------------------------------------------
    # 2. Build design matrix A
    # --------------------------------------------------
    # A encodes: X(t2) - X(t1) = D
    # We add +1 row for reference constraint: X(t0) = 0
    n_obs = len(aggregated_time_1)
    A = np.zeros((n_obs + 1, nt))

    for i in range(n_obs):
        i1 = time_to_idx[aggregated_time_1[i]]
        i2 = time_to_idx[aggregated_time_2[i]]

        A[i, i2] = 1     # +X(t2)
        A[i, i1] = -1    # -X(t1)

    # Reference constraint (fix solution uniqueness)
    # Set displacement at earliest time to 0
    A[-1, 0] = 1

    # --------------------------------------------------
    # 3. Prepare output array
    # --------------------------------------------------
    # Assume all displacement arrays share same shape
    ny, nx = aggregated_displacement[0].shape

    # Output: cumulative displacement time series
    # shape = (nt, ny, nx)
    X = np.zeros((nt, ny, nx))

    # --------------------------------------------------
    # 4. Solve per pixel (least squares)
    # --------------------------------------------------
    for y in tqdm.tqdm(range(ny), desc="Inverting pixels", unit="row"):
        for xpix in range(nx):

            # Build observation vector b for this pixel
            # b = [D_1, D_2, ..., D_n, 0]
            b = np.zeros(n_obs + 1)

            for i in range(n_obs):
                b[i] = aggregated_displacement[i][y, xpix]

            # reference constraint
            b[-1] = 0.0

            # ------------------------------------------
            # Handle missing data (NaNs)
            # ------------------------------------------
            valid = ~np.isnan(b[:-1])  # ignore reference row

            # If no valid observations → skip
            if np.sum(valid) == 0:
                X[:, y, xpix] = np.nan
                continue

            # Select valid rows
            A_valid = A[:-1][valid]
            b_valid = b[:-1][valid]

            # Add back reference constraint
            A_valid = np.vstack([A_valid, A[-1]])
            b_valid = np.concatenate([b_valid, [0.0]])

            # ------------------------------------------
            # Solve least squares: A x = b
            # ------------------------------------------
            sol, *_ = np.linalg.lstsq(A_valid, b_valid, rcond=None)

            # Store result
            X[:, y, xpix] = sol

    # --------------------------------------------------
    # 5. Output
    # --------------------------------------------------
    # times → time axis
    # X     → cumulative displacement (time, y, x)

    print("Done.")
    print("Time steps:", nt)
    print("Output shape:", X.shape)

    return times, X


def get_output_filename(metadata,):
    """Build output filename from OPERA identification metadata."""
    def mget(key, default=None):
        # supports dict metadata and argparse.Namespace(attrs=..., variables=...)
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
        # fallback for strings like "2017-01-07T04:30:28.815125Z"
        return s[:10].replace("-", "")

    direction = metadata.orbit_pass_direction if hasattr(metadata, "orbit_pass_direction") else None
    if direction is not None:
        direction = str(direction).strip().upper()

    sat_raw = mget("source_data_satellite_names", mget("mission", "OPERA"))
    sat_str = str(sat_raw).upper().replace(" ", "") if sat_raw is not None else ""

    if "S1A" in sat_str or "S1B" in sat_str:
        sat = "S1"
    else:
        sat = str(sat_raw).split(",")[0].strip() if sat_raw else "OPERA"

    relorb = f"{int(mget('relative_orbit', mget('track_number', 0))):03d}"
    relorb2 = f"{int(mget('relative_orbit_second', mget('frame_id', 0))):05d}"

    method_str = str(mget("post_processing_method", "opera")).lower()

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
        out_name = f"{sat}_{direction_val}_{relorb}_{relorb2}_{method_str}_{date1}_{date2}.he5"
    else:
        out_name = f"{sat}_{relorb}_{relorb2}_{method_str}_{date1}_{date2}.he5"

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
    """
    Return corners from the polygon as S0081W09112_S0081W09130_S0100W09130_S0100W09112
    """

    def fmt_lat(lat: float) -> str:
        val = int(round(abs(lat) * 100))              # keep 2 decimals
        return f"{'N' if lat >= 0 else 'S'}{val:04d}" # 2 deg digits + 2 decimals

    def fmt_lon(lon: float) -> str:
        val = int(round(abs(lon) * 100))
        return f"{'E' if lon >= 0 else 'W'}{val:05d}" # 3 deg digits + 2 decimals

    poly = _wkt.loads(polygon_str)

    # polygon vertices in counter-clockwise order starting SW, drop duplicate last point
    coords = list(poly.exterior.coords)[:-1]
    corners = [(lat, lon) for lon, lat in coords]
    parts = [f"{fmt_lat(lat)}{fmt_lon(lon)}" for (lat, lon) in corners]

    corners_str = "_".join(parts)

    return  corners_str


def main():
    inps = create_parser()

    # DEM section
    if inps.dem_file and not os.path.exists(inps.dem_file):
        region = parse_polygon(inps.intersectsWith)
        subprocess.run([
            "sardem",
            "--bbox", str(region[0]), str(region[2]), str(region[1]), str(region[3]),
            "--output", inps.dem_file,
        ])

    # Processing section
    files = glob.glob(os.path.join(inps.dir, "*.nc"))
    centroid = [((parse_polygon(inps.intersectsWith)[0] + parse_polygon(inps.intersectsWith)[1]) / 2,(parse_polygon(inps.intersectsWith)[2] + parse_polygon(inps.intersectsWith)[3]) / 2)] * len(files)

    ref_x, ref_y, ref_temporal_coh = None, None, None

    # Initialize dictionary to store by secondary date
    pair_dict = {}

    for f, c in tqdm.tqdm(zip(files, centroid), desc="Processing files", unit=" file", total=len(files)):
        nc = netCDF4.Dataset(f, 'r')
        x = np.asarray(nc.variables["x"][:], dtype=float)
        y = np.asarray(nc.variables["y"][:], dtype=float)
        temporal_coh = np.asarray(nc.variables["temporal_coherence"][:], dtype=np.float32)
        mask = nc.variables['recommended_mask'][:]

        # Set reference shapes on first valid file
        if ref_x is None:
            ref_x, ref_y, ref_temporal_coh = x.shape, y.shape, temporal_coh.shape

        # Check shapes
        if x.shape != ref_x or y.shape != ref_y or temporal_coh.shape != ref_temporal_coh:
            print(f"Skipping {f}: shape mismatch.")
            nc.close()
            try:
                os.remove(f)
                print(f"Removed {f} due to shape mismatch.")
            except Exception as e:
                print(f"Could not remove {f}: {e}")
            continue

        displacement = nc.variables["displacement"][:]
        displacement_data = displacement.filled(np.nan) if hasattr(displacement, "filled") else np.asarray(displacement)
        ref_time = nc.variables["reference_time"][:]
        sec_time = nc.variables["time"]
        ref_date = netCDF4.num2date(ref_time[:], units=sec_time.units, calendar=getattr(sec_time, "calendar", "standard"), only_use_cftime_datetimes=False)[0].date()
        sec_date = netCDF4.num2date(sec_time[:], units=sec_time.units, calendar=getattr(sec_time, "calendar", "standard"), only_use_cftime_datetimes=False)[0].date()
        meta = extract_identification_metadata(nc)
        pair_dict[sec_date] = {
            'ref_date': ref_date,
            'displacement': displacement_data,
            'mask': mask,
            'temporal_coherence': temporal_coh,
            'meta': meta
        }
        nc.close()

    # Sort by secondary date
    pair_dict = {k: pair_dict[k] for k in sorted(pair_dict)}
    date_list = [d.strftime("%Y%m%d") for d in pair_dict]

    if not np.all(ref_time == ref_time[0]):
        time, X = temporal_inversion([pair_dict[d]['ref_date'] for d in pair_dict.keys()],  list(pair_dict.keys()), [pair_dict[d]['displacement'] for d in pair_dict.keys()])
    else:
        time = list(pair_dict.keys())
        X = np.stack([pair_dict[d]['displacement'] for d in pair_dict], axis=0)

    meta = merge_metadata([pair_dict[d]['meta'] for d in pair_dict.keys()])

    if not hasattr(meta, 'reference_datetime'):
        setattr(meta, 'reference_datetime', pair_dict[datetime.datetime.strptime(date_list[0], '%Y%m%d').date()]['ref_date'].strftime("%Y-%m-%d"))
    if not hasattr(meta, 'last_date'):
        setattr(meta, 'last_date', date_list[-1])
    if hasattr(meta, 'source_data_file_list'):
        delattr(meta, 'source_data_file_list')
    if not hasattr(meta, 'PROJECT_NAME'):
        setattr(meta, 'PROJECT_NAME', 'OPERA')

    longitude, latitude = convert_to_coord(x, y, c)

    out_file = get_output_filename(meta)

    # Format date_list as YYYYMMDD strings for MintPy compatibility
    date_list = [d.strftime("%Y%m%d") if hasattr(d, 'strftime') else str(d).replace('-', '') for d in time]
    mask_2d = np.multiply.reduce([pair_dict[d]['mask'] for d in pair_dict.keys()])
    temporal_2d = next(iter(pair_dict.values()))['temporal_coherence']

    with netCDF4.Dataset(os.path.join(inps.dir, out_file), "w", format="NETCDF4") as f:
        f.createDimension("time", len(date_list))
        f.createDimension("y", X.shape[1])
        f.createDimension("x", X.shape[2])

        hdfeos_group = f.createGroup("HDFEOS")
        grids_group = hdfeos_group.createGroup("GRIDS")
        ts_group = grids_group.createGroup("timeseries")
        obs_group = ts_group.createGroup("observation")
        qual_group = ts_group.createGroup("quality")
        geom_group = ts_group.createGroup("geometry")

        disp_var = obs_group.createVariable("displacement", "f4", ("time", "y", "x"), zlib=True, complevel=4)
        disp_var[:] = X.astype(np.float32)

        date_var = obs_group.createVariable("date", str, ("time",))
        date_var[:] = np.asarray(date_list, dtype=object)

        # Also write a top-level dataset 'date_list' for compatibility
        date_list_var = f.createVariable("date_list", str, ("time",))
        date_list_var[:] = np.asarray(date_list, dtype=object)

        bperp_var = obs_group.createVariable("bperp", "f4", ("time",))
        bperp_var[:] = np.zeros((len(date_list),), dtype=np.float32)

        tcoh_var = qual_group.createVariable("temporalCoherence", "f4", ("y", "x"), zlib=True, complevel=4)
        tcoh_var[:] = temporal_2d.astype(np.float32)

        mask_var = qual_group.createVariable("mask", "i1", ("y", "x"), zlib=True, complevel=4)
        mask_var[:] = mask_2d.astype(np.int8)


        # Write latitude and longitude grids instead of x and y
        lat_var = geom_group.createVariable("latitude", "f4", ("y", "x"))
        lat_var[:, :] = latitude.astype(np.float32)

        lon_var = geom_group.createVariable("longitude", "f4", ("y", "x"))
        lon_var[:, :] = longitude.astype(np.float32)

        f.FILE_TYPE = "HDFEOS"
        f.LENGTH = str(X.shape[1])
        f.WIDTH = str(X.shape[2])

        # Add meta attributes if available
        if meta is not None:
            meta_attrs = vars(meta)
            for key, value in meta_attrs.items():
                if value is None:
                    continue
                norm_val = normalize_meta_value(value)
                setattr(f, key, str(norm_val) if isinstance(norm_val, (list, tuple, dict, np.ndarray)) else norm_val)

if __name__ == '__main__':
    main()