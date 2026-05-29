#!/usr/bin/env python3

import os
import glob
import re
import h5py
import rasterio
import numpy as np
from pathlib import Path

from matplotlib import pyplot as plt
from mintpy.utils import writefile, readfile
from minsar.src.minsar.helper_functions import get_output_filename, utm_to_lonlat

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
    metadata['PROJECT_NAME'] = os.path.basename(os.path.dirname(output_path))
    metadata['REF_DATE'] = str(date_list[0])
    metadata['first_frame'] = ' '

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

    if not temp_coh and (timeseries_path.parent / 'interferograms').exists():
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
    os.chdir('/scratch/09580/gdisilvestro/qChilesSenA120') #REMOVE!!!
    #########################################################################################################################

    CSLC = glob.glob(str(Path.cwd() / 'OPERA*.h5')) if glob.glob(str(Path.cwd() / 'OPERA*.h5')) else glob.glob(str(Path.cwd() / 'CSLC' / 'OPERA*.h5'))

    timeseries_path = define_path()

    deformation_data, temp_coh, metadata1 = collect_data(timeseries_path)
    ny, nx = deformation_data[0]["data"].shape
    if CSLC:
        with h5py.File(CSLC[0], "r") as hf:
            metadata2 = {}
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
        lon_x, lat_x = utm_to_lonlat(t.c + t.a,t.f,metadata1["crs"])
        lon_y, lat_y = utm_to_lonlat(t.c,t.f + t.e,metadata1["crs"])
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
    metadata['ORBITAL_DIRECTION'] = metadata.get('orbit_pass_direction', metadata.get('orbit_direction', None)).upper()
    metadata['PROJECT_NAME'] = os.path.basename(os.getcwd())
    metadata['START_DATE'] = str(date_list[0])
    metadata['END_DATE'] = str(date_list[-1])
    metadata['UNIT'] = 'm'

    # Add the date list
    metadata['reference_datetime'] = deformation_data[0]['reference']
    metadata['secondary_datetime'] = deformation_data[-1]['secondary']
    metadata['data_footprint'] = metadata['scene_footprint'] = metadata['bounding_polygon'] = wkt
    output_path = str(timeseries_path / get_output_filename(metadata))

    create_hdfeos_output(ts_data=stack, mask=temp_coh > 0.65, temporal_coherence=temp_coh, date_list=date_list, output_path=output_path, metadata=metadata,
                         latitude=latitude, longitude=longitude, height=height, azimuth=az, incidence=incidence)


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


if __name__ == '__main__':
    main()