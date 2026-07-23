############################################################
# Program is part of MintPy                                #
# Copyright (c) 2013, Zhang Yunjun, Heresh Fattahi         #
# Author: Piyush Agram, Zhang Yunjun, Nov 2019             #
############################################################
# MinSAR: support timeseries or HDFEOS (.he5), geo or radar;
# always estimate velocity (MintPy polynomial=1); apply mask;
# default GeoPackage (.gpkg); --no-gpkg for shapefile.


import errno
import os

import h5py
import numpy as np
from osgeo import ogr
from scipy import linalg

from mintpy.objects import HDFEOS, timeseries
from mintpy.utils import ptime, readfile, time_func, utils as ut


#########################################################################################
def add_metadata(feature, location, attrs):
    '''
    Create one point in compatible shape format.
    '''

    point = ogr.Geometry(ogr.wkbPoint)
    point.AddPoint(location[0], location[1])  # Lon, Lat
    feature.SetGeometry(point)

    for k, v in attrs.items():
        feature.SetField(k, v)
    return


def get_ts_date_list(ts_file):
    """Return date list for a MintPy timeseries or HDFEOS file."""
    atr = readfile.read_attribute(ts_file)
    ftype = atr['FILE_TYPE']
    if ftype == 'HDFEOS':
        return HDFEOS(ts_file).get_date_list()
    if ftype == 'timeseries':
        return timeseries(ts_file).get_date_list()
    raise ValueError(f'Un-recognized time-series type: {ftype}')


def _geo_attrs_match(atr_a, atr_b):
    """True if length/width and (when present) geo transform attributes match."""
    keys = ('LENGTH', 'WIDTH')
    for key in keys:
        if str(atr_a.get(key)) != str(atr_b.get(key)):
            return False
    for key in ('Y_FIRST', 'X_FIRST', 'Y_STEP', 'X_STEP'):
        if key in atr_a and key in atr_b and str(atr_a.get(key)) != str(atr_b.get(key)):
            return False
    return True


def resolve_mask(ts_file, msk_file=None, atr=None):
    """Resolve mask array: -m file, matching sibling mask, or HDFEOS quality/mask."""
    atr = atr or readfile.read_attribute(ts_file)
    ts_dir = os.path.dirname(os.path.abspath(ts_file))
    prefix = 'geo_' if os.path.basename(ts_file).startswith('geo_') else ''

    if msk_file:
        path = os.path.abspath(msk_file)
        if not os.path.isfile(path):
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path)
        msk_atr = readfile.read_attribute(path)
        if not _geo_attrs_match(atr, msk_atr):
            raise ValueError(
                f'mask {path} grid does not match time series '
                f'({atr.get("LENGTH")}x{atr.get("WIDTH")} vs '
                f'{msk_atr.get("LENGTH")}x{msk_atr.get("WIDTH")})'
            )
        print(f'read mask data from file: {path}')
        return readfile.read(path)[0], path

    candidates = [
        os.path.join(ts_dir, 'geo', 'geo_maskTempCoh.h5'),
        os.path.join(ts_dir, 'geo_maskTempCoh.h5'),
        os.path.join(ts_dir, f'{prefix}maskTempCoh.h5'),
        os.path.join(ts_dir, 'maskTempCoh.h5'),
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        msk_atr = readfile.read_attribute(path)
        if not _geo_attrs_match(atr, msk_atr):
            print(
                f'WARNING: skip mask {path} (grid does not match time series '
                f'{atr.get("LENGTH")}x{atr.get("WIDTH")} vs '
                f'{msk_atr.get("LENGTH")}x{msk_atr.get("WIDTH")})'
            )
            continue
        print(f'read mask data from file: {path}')
        return readfile.read(path)[0], os.path.abspath(path)

    if atr.get('FILE_TYPE') == 'HDFEOS':
        try:
            print(f'read mask data from HDFEOS quality/mask: {ts_file}')
            return readfile.read(ts_file, datasetName='mask')[0], ts_file
        except Exception as exc:
            raise FileNotFoundError(
                f'could not read mask from HDFEOS {ts_file}: {exc}'
            ) from exc

    raise FileNotFoundError(
        errno.ENOENT, os.strerror(errno.ENOENT),
        os.path.join(ts_dir, f'{prefix}maskTempCoh.h5'),
    )


def estimate_velocity_mintpy_default(ts_file, atr=None):
    """Estimate linear LOS velocity with MintPy default time function (polynomial=1).

    Same estimator as timeseries2velocity.py default (time_func / lstsq).
    """
    atr = atr or readfile.read_attribute(ts_file)
    print(f'estimating velocity from {ts_file} via MintPy default (polynomial=1)')
    print(f'equivalent command: timeseries2velocity.py {ts_file}')

    date_list = get_ts_date_list(ts_file)
    num_date = len(date_list)
    length, width = int(atr['LENGTH']), int(atr['WIDTH'])
    seconds = atr.get('CENTER_LINE_UTC', 0)

    if atr['FILE_TYPE'] == 'HDFEOS':
        ts_data = HDFEOS(ts_file).read(datasetName='displacement', print_msg=True)
    else:
        ts_data = readfile.read(ts_file, datasetName=date_list, print_msg=True)[0]

    if ts_data.ndim != 3:
        raise ValueError(f'Expected 3D displacement, got shape {ts_data.shape}')

    unit = atr.get('UNIT', 'm')
    if unit == 'mm':
        ts_data = ts_data * (1.0 / 1000.0)
    elif unit == 'cm':
        ts_data = ts_data * 0.01

    ts_flat = ts_data.reshape(num_date, -1)
    del ts_data

    ts_stack = np.nanmean(ts_flat, axis=0)
    pix_mask = np.multiply(~np.isnan(ts_stack), ts_stack != 0.0)
    del ts_stack

    vel = np.full(length * width, np.nan, dtype=np.float32)
    num_pixel2inv = int(np.sum(pix_mask))
    print(f'number of pixels to invert: {num_pixel2inv} out of {length * width} '
          f'({100.0 * num_pixel2inv / (length * width):.1f}%)')

    if num_pixel2inv > 0:
        model = {'polynomial': 1}
        G = time_func.get_design_matrix4time_func(
            date_list, model=model, seconds=seconds
        )
        m = linalg.lstsq(G, ts_flat[:, pix_mask], cond=None)[0]
        vel[pix_mask] = m[1].astype(np.float32)

    return vel.reshape(length, width)


def gather_files(ts_file, geom_file=None, msk_file=None):
    '''
    Gather mintpy / HDFEOS inputs. Velocity is always estimated (not from velocity.h5).
    '''
    print('gather auxliary data files')
    atr = readfile.read_attribute(ts_file)
    ftype = atr['FILE_TYPE']
    ts_dir = os.path.dirname(os.path.abspath(ts_file))
    prefix = 'geo_' if os.path.basename(ts_file).startswith('geo_') else ''

    if ftype == 'HDFEOS':
        coh_file = ts_file
        geom_path = geom_file if geom_file else ts_file
        if geom_file and not os.path.isfile(geom_file):
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), geom_file)
    else:
        coh_file = os.path.join(ts_dir, f'{prefix}temporalCoherence.h5')
        if not geom_file:
            raise ValueError('-g/--geom is required for classic timeseries input')
        geom_path = geom_file
        for fname in (coh_file, geom_path):
            if not os.path.isfile(fname):
                raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), fname)

    # resolve mask now so gather summary shows the real source
    _, msk_src = resolve_mask(ts_file, msk_file=msk_file, atr=atr)

    fDict = {
        'TimeSeries': ts_file,
        'Velocity': None,  # estimated in write_shape_file
        'Coherence': coh_file,
        'Mask': msk_src,
        'Geometry': geom_path,
    }

    for key, value in fDict.items():
        if key == 'Velocity':
            print(f'{key:<10}: estimated (MintPy polynomial=1)')
        else:
            print(f'{key:<10}: {value}')
    return fDict


def read_bounding_box(pix_box, geo_box, geom_file, atr=None):
    atr_box = readfile.read_attribute(geom_file) if geom_file else atr
    if atr_box is None:
        raise ValueError('geometry file or time-series attributes required for bounding box')
    coord = ut.coordinate(atr_box, lookup_file=geom_file)

    if pix_box is None and geo_box is None:
        length, width = int(atr_box['LENGTH']), int(atr_box['WIDTH'])
        return (0, 0, width, length)

    if geo_box is not None:
        S, N, W, E = geo_box
        pix_box = coord.bbox_geo2radar((W, N, E, S))
        print(f'input bounding box in (S, N, W, E): {geo_box}')

    if pix_box is not None:
        pix_box = coord.check_box_within_data_coverage(pix_box)
        print(f'bounding box in (x0, y0, x1, y1): {pix_box}')

    return pix_box


def _is_hdfeos_file(fname):
    return readfile.read_attribute(fname).get('FILE_TYPE') == 'HDFEOS'


def _h5_path(is_hdfeos, classic_name, hdfeos_group):
    if is_hdfeos:
        return f'HDFEOS/GRIDS/timeseries/{hdfeos_group}/{classic_name}'
    return classic_name


def resolve_lat_lon(atr, geom_file, box):
    """Pixel lat/lon for geocoded metadata or radar geometry / HDFEOS."""
    if 'Y_FIRST' in atr:
        return ut.get_lat_lon(atr, box=box)

    if geom_file is None:
        raise ValueError(
            'Radar-coded input needs latitude/longitude: pass -g geometry file '
            'or use an HDFEOS file that contains geometry/latitude and longitude.'
        )

    if _is_hdfeos_file(geom_file):
        try:
            lats = readfile.read(geom_file, datasetName='latitude', box=box, print_msg=False)[0]
            lons = readfile.read(geom_file, datasetName='longitude', box=box, print_msg=False)[0]
            return lats, lons
        except Exception as exc:
            raise ValueError(
                f'Could not read latitude/longitude from HDFEOS {geom_file}: {exc}. '
                'Pass -g with a geometry file that contains latitude/longitude.'
            ) from exc

    return ut.get_lat_lon(atr, geom_file=geom_file, box=box)


def _ogr_driver_for_outfile(out_file):
    """Return (driver_name, human_label) for .gpkg or shapefile."""
    ext = os.path.splitext(out_file)[1].lower()
    if ext == '.gpkg':
        return 'GPKG', 'GeoPackage'
    return 'ESRI Shapefile', 'shape file'


def write_vector_file(fDict, out_file, box=None, zero_first=False, atr=None):
    '''Write time-series data to a GeoPackage (.gpkg) or ESRI shapefile.

    Parameters: fDict      - dict, with value for path of data files
                out_file   - str, output filename (.gpkg or .shp)
                box        - tuple of 4 int, in (x0, y0, x1, y1)
                zero_first - bool, set displacement at 1st acquisition to zero
                atr        - dict, time-series attributes (optional)
    Returns:    out_file   - str, output filename
    '''

    driver_name, label = _ogr_driver_for_outfile(out_file)
    driver = ogr.GetDriverByName(driver_name)
    if driver is None:
        raise RuntimeError(f'OGR driver not available: {driver_name}')

    print(f'output {label}: {out_file}')

    ##Check if output already exists
    if os.path.exists(out_file):
        print(f'output {label}: {out_file} exists, will be overwritten ....')
        driver.DeleteDataSource(out_file)

    ##Start creating dataset and layer definition
    ds = driver.CreateDataSource(out_file)
    if ds is None:
        raise RuntimeError(f'failed to create output: {out_file}')
    srs = ogr.osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    layer = ds.CreateLayer('mintpy', srs, geom_type=ogr.wkbPoint)

    #Add code for each point
    fd = ogr.FieldDefn('CODE', ogr.OFTString)
    fd.SetWidth(8)
    layer.CreateField(fd)

    #Add DEM height for each point - this could be before / after DEM error correction
    fd = ogr.FieldDefn('HEIGHT', ogr.OFTReal)
    fd.SetWidth(7)
    fd.SetPrecision(2)
    layer.CreateField(fd)

    #Supposed to represent DEM error estimation uncertainty
    fd = ogr.FieldDefn('H_STDEV', ogr.OFTReal)
    fd.SetWidth(5)
    fd.SetPrecision(2)
    layer.CreateField(fd)

    #Estimated LOS velocity
    fd = ogr.FieldDefn('VEL', ogr.OFTReal)
    fd.SetWidth(8)
    fd.SetPrecision(2)
    layer.CreateField(fd)

    #Estimated uncertainty in velocity
    fd = ogr.FieldDefn('V_STDEV', ogr.OFTReal)
    fd.SetWidth(6)
    fd.SetPrecision(2)
    layer.CreateField(fd)

    #Temporal coherence
    fd = ogr.FieldDefn('COHERENCE', ogr.OFTReal)
    fd.SetWidth(5)
    fd.SetPrecision(3)
    layer.CreateField(fd)

    #Effective area - SqueeSAR DS / PS
    layer.CreateField(ogr.FieldDefn('EFF_AREA', ogr.OFTInteger))

    ##Time to load the dates from time-series and create one attribute for each date
    date_list = get_ts_date_list(fDict['TimeSeries'])
    for date in date_list:
        fd = ogr.FieldDefn(f'D{date}', ogr.OFTReal)
        fd.SetWidth(8)
        fd.SetPrecision(2)
        layer.CreateField(fd)
    layerDefn = layer.GetLayerDefn()

    atr = atr or readfile.read_attribute(fDict['TimeSeries'])
    if box is None:
        box = (0, 0, int(atr['WIDTH']), int(atr['LENGTH']))

    # mask (already resolved path in gather_files; re-read with box)
    mask = readfile.read(fDict['Mask'], datasetName='mask' if _is_hdfeos_file(fDict['Mask']) else None,
                         box=box, print_msg=False)[0]
    # classic maskTempCoh often has dataset "mask" too; if None datasetName, readfile picks first
    if mask.dtype == np.bool_ or mask.dtype == bool:
        mask = mask.astype(np.uint8)
    nValid = int(np.sum(mask != 0))
    print('number of points with time-series:', nValid)
    if zero_first:
        print('set displacement at the first acquisition to zero.')

    # velocity (always estimated)
    vel2d = estimate_velocity_mintpy_default(fDict['TimeSeries'], atr=atr)
    vel2d = vel2d[box[1]:box[3], box[0]:box[2]]

    lats, lons = resolve_lat_lon(atr, fDict['Geometry'], box=box)

    ts_is_hdfeos = _is_hdfeos_file(fDict['TimeSeries'])
    coh_is_hdfeos = _is_hdfeos_file(fDict['Coherence'])
    geom_is_hdfeos = _is_hdfeos_file(fDict['Geometry'])

    ts_path = ('HDFEOS/GRIDS/timeseries/observation/displacement' if ts_is_hdfeos
               else 'timeseries')
    coh_path = _h5_path(coh_is_hdfeos, 'temporalCoherence', 'quality')
    hgt_path = _h5_path(geom_is_hdfeos, 'height', 'geometry')

    ### Use context managers to skip close statements
    with (
        h5py.File(fDict["TimeSeries"], "r") as tsid,
        h5py.File(fDict["Coherence"], "r") as cohid,
        h5py.File(fDict["Geometry"], "r") as geomid,
    ):
        length = box[3] - box[1]
        width = box[2] - box[0]

        # Start counter
        counter = 1
        prog_bar = ptime.progressBar(maxValue=max(nValid, 1))

        # For each line
        for i in range(length):
            line = i + box[1]

            # read data for the line
            ts = tsid[ts_path][:, line, box[0]:box[2]].astype(np.float64)
            if zero_first:
                ts -= np.tile(ts[0, :], (ts.shape[0], 1))

            coh = cohid[coh_path][line, box[0]:box[2]].astype(np.float64)
            hgt = geomid[hgt_path][line, box[0]:box[2]].astype(np.float64)
            vel = vel2d[i, :].astype(np.float64)
            lat = lats[i, :].astype(np.float64)
            lon = lons[i, :].astype(np.float64)

            for j in range(width):
                if mask[i, j] == 0:
                    continue

                # Create metadata dict
                rdict = {
                    "CODE": hex(counter)[2:].zfill(8),
                    "HEIGHT": hgt[j],
                    "H_STDEV": 0.0,
                    "VEL": float(vel[j] * 1000) if np.isfinite(vel[j]) else 0.0,
                    "V_STDEV": 0.0,
                    "COHERENCE": coh[j],
                    "EFF_AREA": 1,
                }

                for ind, date in enumerate(date_list):
                    rdict[f"D{date}"] = ts[ind, j] * 1000

                # Create feature with definition
                feature = ogr.Feature(layerDefn)
                add_metadata(feature, [lon[j], lat[j]], rdict)
                layer.CreateFeature(feature)
                feature = None

                # update counter / progress bar
                counter += 1
                prog_bar.update(counter, every=100, suffix=f"line {counter}/{nValid}")
        prog_bar.close()

    # flush / close datasource (important for GPKG)
    ds = None
    print(f'finished writing to file: {out_file}')
    return out_file


def write_shape_file(fDict, shp_file, box=None, zero_first=False, atr=None):
    """Backward-compatible alias for write_vector_file (shapefile or gpkg by extension)."""
    return write_vector_file(fDict, shp_file, box=box, zero_first=zero_first, atr=atr)


#########################################################################################
def save_qgis(inps):

    atr = readfile.read_attribute(inps.ts_file)
    geom_for_box = inps.geom_file or inps.ts_file

    # Read bounding box
    box = read_bounding_box(
        pix_box=inps.pix_bbox,
        geo_box=inps.geo_bbox,
        geom_file=geom_for_box,
        atr=atr,
    )

    # Gather data files (mask resolved here)
    fDict = gather_files(
        inps.ts_file,
        geom_file=getattr(inps, 'geom_file', None),
        msk_file=getattr(inps, 'msk_file', None),
    )

    out_file = getattr(inps, 'out_file', None) or inps.shp_file
    write_vector_file(fDict, out_file, box=box, zero_first=inps.zero_first, atr=atr)

    return
