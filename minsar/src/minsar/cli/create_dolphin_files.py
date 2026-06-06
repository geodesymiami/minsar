#!/usr/bin/env python3

import argparse
import json
import os
import glob
import re
import h5py
import rasterio
import numpy as np
from datetime import date, datetime
from pathlib import Path

from matplotlib import pyplot as plt
from mintpy.utils import writefile, readfile
from minsar.src.minsar.helper_functions import (
    extract_identification_metadata,
    get_output_filename,
    utm_to_lonlat,
)

# Minimal attrs present in working insarmaps ingests (SARvey CSV + MintPy Galapagos).
# hdfeos5_2json_mbtiles.py copies these into metadata.pickle attribute_keys when present on .he5.
INSARMAPS_ESSENTIAL_ATTRS = (
    "WIDTH",
    "LENGTH",
    "mission",
    "relative_orbit",
    "beam_mode",
    "beam_swath",
    "processing_type",
    "processing_software",
    "post_processing_method",
    "first_date",
    "last_date",
    "history",
    "REF_LAT",
    "REF_LON",
    "look_direction",
    "atmos_correct_method",
    "first_frame",
    "last_frame",
    "data_footprint",
    "scene_footprint",
    "wavelength",
    "prf",
)

# Geo grid keys used by hdfeos5_2json_mbtiles (non-high-res); not in SARvey CSV ingest but required for .he5.
INSARMAPS_GEO_ATTRS = (
    "X_FIRST",
    "Y_FIRST",
    "X_STEP",
    "Y_STEP",
)

# Kept on .he5 for naming and MintPy/HDFEOS I/O; not all are ingested into insarmaps attribute_keys.
HDFEOS_STRUCTURAL_ATTRS = (
    "PROJECT_NAME",
    "REF_DATE",
    "START_DATE",
    "END_DATE",
    "ORBIT_DIRECTION",
    "PROCESSOR",
    "PLATFORM",
    "UNIT",
    "REF_X",
    "REF_Y",
    "X_UNIT",
    "Y_UNIT",
)


def _iso_date(ymd):
    """Convert YYYYMMDD to YYYY-MM-DD."""
    s = str(ymd).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10]


def _mission_name(metadata):
    platform = str(
        metadata.get("mission_id")
        or metadata.get("platform_id")
        or metadata.get("PLATFORM")
        or metadata.get("l1_slc_files")
        or ""
    ).upper()
    if "S1" in platform or "SEN" in platform:
        return "S1"
    return platform.split(",")[0].strip() or "S1"


def _beam_mode_swath(metadata):
    burst_id = str(metadata.get("burst_id", "")).lower()
    m = re.search(r"iw(\d+)", burst_id)
    if m:
        return "IW", int(m.group(1))
    product = str(metadata.get("product_type", metadata.get("l1_slc_files", ""))).upper()
    if "IW" in product:
        return "IW", int(metadata.get("beam_swath", 0) or 0)
    return str(metadata.get("beam_mode", "IW")), int(metadata.get("beam_swath", 0) or 0)


def _look_direction(metadata):
    look = str(metadata.get("look_direction", "Right")).strip().lower()
    if look.startswith("r"):
        return "R"
    if look.startswith("l"):
        return "L"
    return "R"


def _ref_lat_lon(latitude, longitude, ref_row, ref_col):
    lat_arr = np.asarray(latitude)
    lon_arr = np.asarray(longitude)
    if lat_arr.ndim == 2 and lon_arr.ndim == 2:
        return float(lat_arr[ref_row, ref_col]), float(lon_arr[ref_row, ref_col])
    if lat_arr.ndim == 1 and lon_arr.ndim == 1:
        return float(lat_arr[ref_row]), float(lon_arr[ref_col])
    return float(np.nanmean(lat_arr)), float(np.nanmean(lon_arr))


def populate_insarmaps_metadata(metadata, date_list, latitude, longitude, ref_row, ref_col):
    """Set only insarmaps-essential UNAVCO attributes on metadata (see INSARMAPS_ESSENTIAL_ATTRS)."""
    beam_mode, beam_swath = _beam_mode_swath(metadata)
    rel_orbit = metadata.get("track_number", metadata.get("relative_orbit"))
    if rel_orbit is None:
        proj = str(metadata.get("PROJECT_NAME", os.path.basename(os.getcwd())))
        m = re.search(r"[Dd](\d+)", proj)
        if m:
            rel_orbit = int(m.group(1))
    if rel_orbit is not None:
        rel_orbit = int(rel_orbit)

    wavelength = metadata.get("wavelength")
    if wavelength is None and metadata.get("radar_center_frequency"):
        wavelength = 299792458.0 / float(metadata["radar_center_frequency"])

    prf = metadata.get("prf_raw_data", metadata.get("prf", metadata.get("PRF")))

    ref_lat, ref_lon = _ref_lat_lon(latitude, longitude, ref_row, ref_col)
    frame = metadata.get("burst_index", 0)
    try:
        frame = int(frame)
    except (TypeError, ValueError):
        frame = 0

    footprint = metadata.get("data_footprint") or metadata.get("scene_footprint") or ""

    insarmaps = {
        "mission": _mission_name(metadata),
        "beam_mode": beam_mode,
        "beam_swath": beam_swath,
        "relative_orbit": rel_orbit,
        "processing_type": "LOS_TIMESERIES",
        "first_date": _iso_date(date_list[0]),
        "last_date": _iso_date(date_list[-1]),
        "look_direction": _look_direction(metadata),
        "history": date.today().isoformat(),
        "atmos_correct_method": "None",
        "first_frame": frame,
        "last_frame": frame,
        "REF_LAT": ref_lat,
        "REF_LON": ref_lon,
        "data_footprint": footprint,
        "scene_footprint": footprint,
    }
    if wavelength is not None:
        insarmaps["wavelength"] = float(wavelength)
    if prf is not None:
        insarmaps["prf"] = float(prf)

    metadata.update(insarmaps)
    return metadata


def prune_metadata_for_hdfeos(metadata):
    """Keep only insarmaps-essential, geo-grid, and structural attrs before writing .he5."""
    keep = set(INSARMAPS_ESSENTIAL_ATTRS) | set(INSARMAPS_GEO_ATTRS) | set(HDFEOS_STRUCTURAL_ATTRS)
    return {k: metadata[k] for k in keep if k in metadata}


def _debug_log(location, message, data=None, hypothesis_id=""):
    """#region agent log"""
    payload = {
        "sessionId": "cd3173",
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": int(datetime.now().timestamp() * 1000),
        "runId": "chiles-patch",
        "hypothesisId": hypothesis_id,
    }
    try:
        with open("/home/exouser/code/minsar/.cursor/debug-cd3173.log", "a") as f:
            f.write(json.dumps(payload) + "\n")
    except OSError:
        pass
    """#endregion"""


def _normalize_attr_value(v):
    if isinstance(v, (bytes, bytearray)):
        return v.decode(errors="ignore")
    if isinstance(v, np.bytes_):
        return v.astype(str)
    if isinstance(v, np.generic):
        return v.item()
    return v


def _infer_project_name(he5_path, metadata):
    if metadata.get("PROJECT_NAME") and metadata["PROJECT_NAME"] not in ("timeseries", "dolphin", "mintpy"):
        return metadata["PROJECT_NAME"]
    resolved = Path(he5_path).resolve()
    for parent in (resolved.parent, resolved.parent.parent, resolved.parent.parent.parent):
        name = parent.name
        if name not in ("timeseries", "dolphin", "mintpy", "miaplpy", "JSON", "outputs", ""):
            return name
    return metadata.get("PROJECT_NAME", "unknown")


def patch_hdfeos_insarmaps_attrs(he5_path, project_name=None):
    """Backfill insarmaps-essential metadata on an existing Dolphin .he5 file."""
    he5_path = str(Path(he5_path).resolve())
    with h5py.File(he5_path, "r") as f:
        metadata = {_k: _normalize_attr_value(_v) for _k, _v in f.attrs.items()}
        lats = f["HDFEOS/GRIDS/timeseries/geometry/latitude"][:]
        lons = f["HDFEOS/GRIDS/timeseries/geometry/longitude"][:]
        raw_dates = f["HDFEOS/GRIDS/timeseries/observation/date"][:]
    date_list = [_normalize_attr_value(d) for d in raw_dates]
    ref_row, ref_col = int(metadata["REF_Y"]), int(metadata["REF_X"])
    metadata["PROJECT_NAME"] = project_name or _infer_project_name(he5_path, metadata)
    before_keys = {k for k in INSARMAPS_ESSENTIAL_ATTRS if k in metadata}
    populate_insarmaps_metadata(metadata, date_list, lats, lons, ref_row, ref_col)
    patched = prune_metadata_for_hdfeos(metadata)
    patched["FILE_TYPE"] = "HDFEOS"
    patched["FILE_PATH"] = he5_path
    after_keys = {k for k in INSARMAPS_ESSENTIAL_ATTRS if k in patched}
    _debug_log(
        "create_dolphin_files.py:patch_hdfeos_insarmaps_attrs",
        "patching he5 metadata",
        {
            "he5_path": he5_path,
            "project_name": patched.get("PROJECT_NAME"),
            "essential_before": sorted(before_keys),
            "essential_after": sorted(after_keys),
            "added": sorted(after_keys - before_keys),
        },
        hypothesis_id="H1-H3",
    )
    with h5py.File(he5_path, "r+") as f:
        for k, v in patched.items():
            if isinstance(v, (float, int, np.floating, np.integer)):
                f.attrs[k] = v
            else:
                f.attrs[k] = str(v)
    print(f"Patched insarmaps metadata on: {he5_path}")
    print(f"  PROJECT_NAME: {patched.get('PROJECT_NAME')}")
    print(f"  Added attrs: {', '.join(sorted(after_keys - before_keys)) or '(none)'}")
    return he5_path


SCRATCHDIR = Path(os.getenv("SCRATCHDIR")) if os.getenv("SCRATCHDIR") else None

def create_hdfeos_output(ts_data: np.ndarray, mask: np.ndarray, latitude: np.ndarray, longitude: np.ndarray,
                         date_list: np.ndarray, output_path: str, temporal_coherence: np.ndarray = None, height: np.ndarray = None, azimuth: np.ndarray = None,
                         incidence: np.ndarray = None, slant_range: np.ndarray = None, bperp: np.ndarray = None, metadata: dict = {}):
    """Create and write an HDFEOS output file with proper structure.

    Args:
        ts_data: Timeseries data array (n_time, length, width)
        date_list: List of dates
        mask: Mask array (length, width)
        bperp: Perpendicular baseline array
        latitude: Latitude array (length,)
        longitude: Longitude array (width,)
        metadata: Metadata dictionary
        output_path: Output file path (should end with .he5)
        length: Number of rows
        width: Number of columns
    """
    # Ensure output path has .he5 extension
    if not output_path.endswith('.he5'):
        output_path = output_path.replace('.h5', '.he5')

    if metadata:
        length, width = int(metadata['LENGTH']), int(metadata['WIDTH'])
    else:
        length, width = ts_data.shape[1], ts_data.shape[2]

    if latitude.ndim == 1:
        lat_grid = np.tile(latitude[:, np.newaxis], (1, width))
    else:
        lat_grid = latitude
    if longitude.ndim == 1:
        lon_grid = np.tile(longitude, (length, 1))
    else:
        lon_grid = longitude

    if bperp is None:
        bperp = np.zeros(len(date_list))

    # Structure data dictionary with HDFEOS paths
    hdfeos_dict = {
        # Geometry datasets (using NaN placeholders where None is requested)
        'HDFEOS/GRIDS/timeseries/geometry/latitude': lat_grid.astype('float32'),
        'HDFEOS/GRIDS/timeseries/geometry/longitude': lon_grid.astype('float32'),
        'HDFEOS/GRIDS/timeseries/geometry/shadowMask': np.zeros((length, width), dtype='uint8'),
        'HDFEOS/GRIDS/timeseries/geometry/height': np.full((length, width), np.nan, dtype='float32') if height is None else height.astype('float32'),
        'HDFEOS/GRIDS/timeseries/geometry/azimuthAngle': np.full((length, width), np.nan, dtype='float32') if azimuth is None else azimuth.astype('float32'),
        'HDFEOS/GRIDS/timeseries/geometry/incidenceAngle': np.full((length, width), np.nan, dtype='float32') if incidence is None else incidence.astype('float32'),
        'HDFEOS/GRIDS/timeseries/geometry/slantRangeDistance': np.full((length, width), np.nan, dtype='float32') if slant_range is None else slant_range.astype('float32'),
        # Observation datasets
        'HDFEOS/GRIDS/timeseries/observation/bperp': bperp.astype('float32'),
        'HDFEOS/GRIDS/timeseries/observation/date': date_list.astype('S8'),
        'HDFEOS/GRIDS/timeseries/observation/displacement': ts_data.astype('float32'),
        # Quality datasets (using NaN placeholders where None is requested)
        'HDFEOS/GRIDS/timeseries/quality/avgSpatialCoherence': np.full((length, width), np.nan, dtype='float32'),
        'HDFEOS/GRIDS/timeseries/quality/mask': mask.astype('bool'),
        'HDFEOS/GRIDS/timeseries/quality/temporalCoherence': np.full((length, width), np.nan, dtype='float32') if temporal_coherence is None else temporal_coherence.astype('float32'),
        # ---- aliases (short names for easier reading) ----
        # 'latitude': lat_grid.astype('float32'),
        # 'longitude': lon_grid.astype('float32'),
        # 'bperp': bperp.astype('float32'),
        # 'date': date_list.astype('S8'),
        # 'mask': mask.astype('bool'),
    }


    # Update metadata for HDFEOS format
    if 'vert' in output_path:
        metadata['displacementType'] = 'VERTICAL'
    elif 'hor' in output_path:
        metadata['displacementType'] = 'HORIZONTAL'
    metadata['FILE_TYPE'] = 'HDFEOS'
    metadata['FILE_PATH'] = output_path
    metadata['WIDTH'] = str(width)
    metadata['LENGTH'] = str(length)
    metadata['PROCESSOR'] = 'mintpy' if 'dolphin' not in output_path else 'dolphin'
    if not metadata.get('PROJECT_NAME'):
        parent = os.path.dirname(output_path)
        if os.path.basename(parent) in ('timeseries', 'mintpy', 'miaplpy', 'dolphin'):
            metadata['PROJECT_NAME'] = os.path.basename(os.path.dirname(parent))
        else:
            metadata['PROJECT_NAME'] = os.path.basename(parent)
    metadata['REF_DATE'] = str(date_list[0])

    if hasattr(metadata, 'OG_FILE_PATH'):
        metadata['OG_FILE_PATH'] = output_path

    # Write using writefile.write
    writefile.write(hdfeos_dict, out_file=output_path, metadata=metadata)
    print(f'\n HDFEOS file created: {output_path}')


def define_path():
    path = Path.cwd()
    if not 'timeseries' in str(path):
        if (path / 'timeseries').exists():
            timeseries_path = path / 'timeseries'
        elif (path / 'dolphin' / 'timeseries').exists():
            timeseries_path = path / 'dolphin' / 'timeseries'
        else:
            raise FileNotFoundError(f"No .tif files or timeseries directory found in {path}.")
    else:
        raise FileNotFoundError(f"No .tif files found in {path}.")

    if False:
        timeseries_path = SCRATCHDIR / "opera_download/Popcatepetl/timeseries" if SCRATCHDIR else Path.getcwd() / "opera_download/Popcatepetl/timeseries"

    return timeseries_path


def find_geometry_file(path=None):
    """Find geometry file in current or nearby directories.

    Searches for geometryRadar.h5 or geo_geometryRadar.h5 in:
    - path
    - path/inputs
    - path/..
    - path/../inputs
    """
    if path is None:
        path = Path.cwd()

    search_dirs = [
        path,
        path / 'inputs',
        path.parent,
        path.parent / 'inputs',
    ]

    filenames = ['geometryRadar.h5', 'geo_geometryRadar.h5']

    for search_dir in search_dirs:
        for fname in filenames:
            candidate = search_dir / fname
            if candidate.exists():
                return candidate

    searched = '\n  '.join(str(d / f) for d in search_dirs for f in filenames)
    raise FileNotFoundError(f"No geometry file found. Searched:\n  {searched}")

def find_geometry_path(path=None):
    if not path:
        path = Path.cwd()

    if glob.glob(str(path / 'geometry')):
        return glob.glob(str(path / 'geometry'))[0]
    elif glob.glob(str(path.parent / 'geometry')):
        return glob.glob(str(path.parent / 'geometry'))[0]
    elif glob.glob(str(path.parent.parent / 'geometry')):
        return glob.glob(str(path.parent.parent / 'geometry'))[0]
    else:
        raise FileNotFoundError("No geometry file found in current or parent directories.")

def find_dem_path(path=None):
    if not path:
        path = Path.cwd()

    ext = ['*.dem', '*.tif']
    for e in ext:
        files = glob.glob(str(path.parent / 'DEM' / e))
        if files:
            return files[0]
    for e in ext:
        files = glob.glob(str(path.parent / e))
        if files:
            return (files[0])
    for e in ext:
        files = glob.glob(str(path.parent.parent / e))
        if files:
            return (files[0])


def collect_data(timeseries_path):
    deformation_data = []
    temp_coh = None
    for f in os.listdir(str(timeseries_path)):
        path = timeseries_path / f

        if f == "temporal_coherence_average.tif" or "temporal_coherence_average" in f:
            with rasterio.open(path) as src:
                temp_coh = src.read(1)
            continue

        if path.suffix.lower() not in {".tif", ".tiff"}:
            continue

        stem = path.stem
        if not re.fullmatch(r"\d{8}_\d{8}", stem):
            continue

        reference, secondary = stem.split("_", 1)
        with rasterio.open(path) as src:
            data = src.read(1)
            shape = data.shape
            crs = src.crs
            bbox = src.bounds
            transform = src.transform
            deformation_data.append({"reference": reference, "secondary": secondary, "data": data})

    if temp_coh is None and (timeseries_path.parent / 'interferograms').exists():
        temp_coh_path = glob.glob(str(timeseries_path.parent / 'interferograms' / '*temporal*coherence*average*'))
        if temp_coh_path:
            try:
                with rasterio.open(temp_coh_path[0]) as src:
                    temp_coh = src.read(1)
            except:
                raise FileNotFoundError("No temporal coherence file found in interferograms directory.")


    metadata=dict(crs=crs.to_string(),transform=transform, bbox=bbox, LENGTH=shape[0], WIDTH=shape[1])

    deformation_data.append({'reference': reference, 'secondary': reference, 'data': np.zeros(shape)})
    deformation_data = sorted(deformation_data, key=lambda x: x['secondary'])

    return deformation_data, temp_coh, metadata


def collect_geometry_data(geometry_file):
    latitude, metadata = readfile.read(geometry_file, datasetName='latitude')
    longitude, _ = readfile.read(geometry_file, datasetName='longitude')
    height, _ = readfile.read(geometry_file, datasetName='height')
    try:
        az, _ = readfile.read(geometry_file, datasetName='azimuthAngle')
    except:
        az = None
    try:
        incidence, _ = readfile.read(geometry_file, datasetName='incidenceAngle')
    except:
        incidence = None

    return latitude, longitude, height, az, incidence, metadata


def normalize(v):
    if isinstance(v, (bytes, bytearray)):
        return v.decode(errors="ignore")
    if isinstance(v, np.bytes_):
        return v.astype(str)
    if isinstance(v, np.generic):
        return v.item()
    return v


def get_coords_from_metadata(metadata):
    lon, lat = utm_to_lonlat((metadata['bbox'].left, metadata['bbox'].right), (metadata['bbox'].bottom, metadata['bbox'].top), metadata['crs'])

    longitude_1d = np.linspace(min(lon), max(lon), metadata['WIDTH'])
    latitude_1d = np.linspace(min(lat), max(lat), metadata['LENGTH'])
    longitude, latitude = np.meshgrid(longitude_1d, latitude_1d)
    return longitude, latitude, lon, lat

def plot_to_test(deformation_data, temp_coh):
    datelist = [d['secondary'] for d in deformation_data]
    deformation = np.array([d['data'] for d in deformation_data])

    shape = deformation[0].shape
    MASK = temp_coh < 0.8



    t = np.arange(deformation.shape[0], dtype=float)
    A = np.vstack([t, np.ones_like(t)]).T  # y = m*t + b
    Y = deformation.reshape(deformation.shape[0], -1)
    LINREG = np.full(Y.shape[1], np.nan, dtype=float)
    valid = np.isfinite(Y).all(axis=0)
    coef = np.linalg.lstsq(A, Y[:, valid], rcond=None)[0]
    LINREG[valid] = coef[0]   # slope only
    LINREG = LINREG.reshape(shape)

    x, y = shape[1]//2, shape[0]//2
    x, y = 382, 67
    TS = deformation[:, y, x]

    fig, axes = plt.subplots(1, 2, figsize=(20, 8))
    axes[0].imshow(np.where(MASK, np.nan, LINREG), cmap='rainbow')
    axes[0].scatter(x, y, color='black', marker='x')
    axes[1].scatter(range(len(TS)), TS, marker='o', alpha=0.7, color='#a85e8e')


def main():
    # TODO for debug ########################################################################################################
    #os.chdir('/scratch/09580/gdisilvestro/qChilesSenD142') #REMOVE!!!
    #########################################################################################################################

    CSLC = glob.glob(str(Path.cwd() / 'OPERA*.h5')) if glob.glob(str(Path.cwd() / 'OPERA*.h5')) else glob.glob(str(Path.cwd() / 'CSLC' / 'OPERA*.h5'))

    timeseries_path = define_path()

    deformation_data, temp_coh, metadata1 = collect_data(timeseries_path)
    ny, nx = deformation_data[0]["data"].shape
    if CSLC:
        with h5py.File(CSLC[0], "r") as hf:
            metadata2 = dict(extract_identification_metadata(hf))
            if "identification" in hf:
                def id_visit(name, obj):
                    if isinstance(obj, h5py.Dataset) and obj.shape == ():
                        metadata2[name.split("/")[-1]] = normalize(obj[()])
                hf["identification"].visititems(id_visit)
            grp = hf['/metadata']
            def visit(name, obj):
                if isinstance(obj, h5py.Dataset) and obj.shape == ():
                    key = name.split("/")[-1]   # keep only child name
                    metadata2[key] = normalize(obj[()])
            grp.visititems(visit)

            longitude, latitude, lon_bounds, lat_bounds = get_coords_from_metadata(metadata1)

        dem = find_dem_path(timeseries_path)
        with rasterio.open(dem) as src:
            window = rasterio.windows.from_bounds(min(lon_bounds), min(lat_bounds), max(lon_bounds), max(lat_bounds), transform=src.transform)
            height = src.read(1, window=window)
            az = None
            incidence = None

    elif (Path.cwd() / 'gslcs').exists():
        geometry_folder = find_geometry_path(timeseries_path)
        longitude, latitude, lon_bounds, lat_bounds = get_coords_from_metadata(metadata1)
        for file in ['height.tif', 'local_incidence_angle.tif', 'los_east.tif', 'los_north.tif']:
            with rasterio.open(Path(geometry_folder) / file) as src:
                variable = file.split('.')[0]
                if variable == 'height':
                    height = src.read(1)
                elif variable == 'local_incidence_angle':
                    incidence = src.read(1)
                elif variable == 'los_east':
                    los_east = src.read(1)
                elif variable == 'los_north':
                    los_north = src.read(1)
        az = np.rad2deg(np.arctan2(los_east, los_north))

        t = metadata1['transform']
        lon0, lat0 = utm_to_lonlat(t.c, t.f, metadata1["crs"])
        lon_x, _ = utm_to_lonlat(t.c + t.a,t.f,metadata1["crs"])
        _, lat_y = utm_to_lonlat(t.c,t.f + t.e,metadata1["crs"])
        x_step = lon_x - lon0
        y_step = lat_y - lat0

        metadata2 = {
        "X_FIRST": str(lon0),
        "Y_FIRST": str(lat0),
        "X_STEP": str(x_step),
        "Y_STEP": str(y_step),
        "EPSG": 4326,
        "DATA_TYPE": src.dtypes[0],
        }

        burst_dir = Path("gslcs/t*")
        static_file = glob.glob(str(burst_dir / "**" / "static_layers_*.h5"), recursive=True)

        if static_file:
            def clean(v):
                if isinstance(v, bytes):
                    return v.decode("utf-8")
                return v
            with h5py.File(static_file[0], "r") as hf:
                def visitor(name, obj):
                    if isinstance(obj, h5py.Dataset) and obj.shape == ():
                        try:
                            key = name.split("/")[-1]   # <-- ROOT ONLY NAME
                            metadata2[key] = clean(obj[()])
                        except Exception:
                            pass
                hf.visititems(visitor)


    else: #latitude and longitude merda
        geometry_file = find_geometry_file(timeseries_path)
        latitude, longitude, height, az, incidence, metadata2 = collect_geometry_data(geometry_file)
        if metadata1.get('bbox', None):
            longitude, latitude, lon_bounds, lat_bounds = get_coords_from_metadata(metadata1)
        elif metadata1.get('bounding_polygon', None):
            latitude = np.linspace(metadata1['bounding_polygon'][0][1], metadata1['bounding_polygon'][0][3], metadata1['LENGTH'])
            longitude = np.linspace(metadata1['bounding_polygon'][0][0], metadata1['bounding_polygon'][0][2], metadata1['WIDTH'])

    metadata = {**metadata2, **metadata1}

    stack = np.stack([d['data'] for d in deformation_data])
    date_list = np.array([d['secondary'] for d in deformation_data])
    lon_min, lon_max = min(lon_bounds), max(lon_bounds)
    lat_min, lat_max = min(lat_bounds), max(lat_bounds)
    wkt = (
        f"POLYGON(("
        f"{lon_min} {lat_min},"
        f"{lon_min} {lat_max},"
        f"{lon_max} {lat_max},"
        f"{lon_max} {lat_min},"
        f"{lon_min} {lat_min}"
        f"))"
    )

    # Set Center incident angle
    if incidence is not None and not hasattr(metadata, 'CENTER_INCIDENCE_ANGLE'):
        center_incidence = incidence[metadata['LENGTH'] // 2, metadata['WIDTH'] // 2]
        metadata['CENTER_INCIDENCE_ANGLE'] = str(center_incidence)

    # Set Heading
    if az is not None and not hasattr(metadata, 'HEADING'):
        metadata['HEADING'] = str(np.nanmean(az) + 90)

    # Set reference point
    if 'REF_X' not in metadata or 'REF_Y' not in metadata:
        r, c = np.where(temp_coh == np.nanmax(temp_coh))
    variance = []
    for r, c in zip(r, c):
        points = [d['data'][r, c] for d in deformation_data]
        variance.append((np.abs(np.nanmean(points - np.nanmedian(points))), int(r), int(c)))
    reference = min(variance, key=lambda x: x[0])
    metadata['REF_X'] = str(reference[2])
    metadata['REF_Y'] = str(reference[1])
    #####################

    metadata['processing_software'] = 'isce'
    metadata['post_processing_method'] = 'dolphin'
    metadata['PROCESSOR'] = 'DOLPHIN'
    metadata['PLATFORM'] = 'S1' if 'S1' in metadata.get('l1_slc_files', metadata.get('platform_id', '')) else ''
    metadata['X_FIRST'] = lon_min #metadata['transform'][2]
    metadata['Y_FIRST'] = lat_max #metadata['transform'][5]
    metadata['X_STEP'] = (lon_max - lon_min) / (nx - 1) #metadata['transform'][0]
    metadata['Y_STEP'] = (lat_min - lat_max) / (ny - 1) #metadata['transform'][4]
    metadata['X_UNIT'] = 'degrees'
    metadata['Y_UNIT'] = 'degrees'
    metadata['REF_DATE'] = str(date_list[0])
    metadata['ORBIT_DIRECTION'] = metadata.get('orbit_pass_direction', metadata.get('orbit_direction', None)).upper()
    metadata['PROJECT_NAME'] = os.path.basename(os.getcwd())
    metadata['START_DATE'] = str(date_list[0])
    metadata['END_DATE'] = str(date_list[-1])
    metadata['UNIT'] = 'm'

    # Add the date list
    metadata['reference_datetime'] = deformation_data[0]['reference']
    metadata['secondary_datetime'] = deformation_data[-1]['secondary']
    metadata['data_footprint'] = metadata['scene_footprint'] = wkt
    ref_row, ref_col = int(metadata['REF_Y']), int(metadata['REF_X'])
    populate_insarmaps_metadata(metadata, date_list, latitude, longitude, ref_row, ref_col)
    metadata = prune_metadata_for_hdfeos(metadata)
    output_path = str(timeseries_path / get_output_filename(metadata))

    create_hdfeos_output(ts_data=stack, mask=temp_coh > 0.65, temporal_coherence=temp_coh, date_list=date_list, output_path=output_path, metadata=metadata,
                         latitude=latitude, longitude=longitude, height=height, azimuth=az, incidence=incidence)

    he5_name = os.path.basename(output_path)
    mbtiles_name = he5_name.replace('.he5', '.mbtiles')
    print(f'\nIngest with:\n  ingest_insarmaps.bash "{output_path}"')
    print(f'  (not the older S1_desc_000_* file if one exists in {timeseries_path})')


    if False:
        mask = temp_coh < 0.6
        stack = np.stack([d['data'] for d in deformation_data])
        date_list = np.array([d['secondary'] for d in deformation_data])

        create_hdfeos_output(stack, mask, np.zeros((metadata['LENGTH'], metadata['WIDTH'])), latitude, longitude, date_list, output_path, metadata)
        pass
        # tsobj = timeseries(os.path.join(os.path.dirname(timeseries_path), 'timeseries.h5'))
        # tsobj.write2hdf5(data=deformation, dates=datelist, metadata=metadata)


    if False:
        plot_to_test(deformation_data, temp_coh)


def parse_args():
    parser = argparse.ArgumentParser(description="Create or patch Dolphin HDFEOS5 files for insarmaps.")
    parser.add_argument("--patch-he5", metavar="FILE.he5", help="Backfill insarmaps metadata on an existing .he5 file")
    parser.add_argument("--project-name", help="PROJECT_NAME for --patch-he5 (default: infer from path)")
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    if args.patch_he5:
        patch_hdfeos_insarmaps_attrs(args.patch_he5, project_name=args.project_name)
    else:
        main()
