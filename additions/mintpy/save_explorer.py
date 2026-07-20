############################################################
# Program is part of MintPy                                #
# Copyright (c) 2013, Zhang Yunjun, Heresh Fattahi         #
# Author: Mahmud Haghighi, Mar 2025                        #
############################################################
# MinSAR: support geocoded HDFEOS (.he5): dates, quality/mask,
# geo/geo_velocity.h5 discovery, else MintPy poly-1 velocity.


import os

import numpy as np
from scipy import linalg

from mintpy.objects import HDFEOS, timeseries
from mintpy.save_gmt import write_grd_file
from mintpy.utils import ptime, readfile, time_func


####################################################################################
def convert2mm(data, atr):
    """Convert displacement (velocity) data to mm or mm/year."""
    if atr['UNIT'] in ['m', 'm/year']:
        return data * 1000
    elif atr['UNIT'] in ['cm', 'cm/year']:
        return data * 10
    elif atr['UNIT'] in ['mm', 'mm/year']:
        return data
    else:
        raise ValueError(f"ERROR: unit {atr['UNIT']} is not supported!")


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
    """True if length/width and geo transform attributes match."""
    keys = ('LENGTH', 'WIDTH', 'Y_FIRST', 'X_FIRST', 'Y_STEP', 'X_STEP')
    for key in keys:
        if str(atr_a.get(key)) != str(atr_b.get(key)):
            return False
    return True


def resolve_mask(ts_file, msk_file=None, atr=None):
    """Resolve mask array: -m file, matching geo mask, or HDFEOS quality/mask."""
    atr = atr or readfile.read_attribute(ts_file)
    ts_dir = os.path.dirname(os.path.abspath(ts_file))
    prefix = 'geo_' if os.path.basename(ts_file).startswith('geo_') else ''

    if msk_file:
        path = os.path.abspath(msk_file)
        if not os.path.isfile(path):
            raise FileNotFoundError(f'mask file not found: {path}')
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
            print(f'WARNING: could not read mask from HDFEOS ({exc})')

    return None, None


def find_geo_velocity_file(ts_file, atr=None):
    """Return path to matching geo_velocity.h5 beside the product, or None."""
    atr = atr or readfile.read_attribute(ts_file)
    ts_dir = os.path.dirname(os.path.abspath(ts_file))
    candidates = [
        os.path.join(ts_dir, 'geo', 'geo_velocity.h5'),
        os.path.join(ts_dir, 'geo_velocity.h5'),
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        vel_atr = readfile.read_attribute(path)
        if _geo_attrs_match(atr, vel_atr):
            return os.path.abspath(path)
        print(
            f'WARNING: skip {path} (grid does not match time series '
            f'{atr.get("LENGTH")}x{atr.get("WIDTH")} vs '
            f'{vel_atr.get("LENGTH")}x{vel_atr.get("WIDTH")})'
        )
    return None


def estimate_velocity_mintpy_default(ts_file, atr=None):
    """Estimate linear LOS velocity with MintPy default time function (polynomial=1).

    Same estimator as timeseries2velocity.py default (time_func.estimate_time_func).
    """
    atr = atr or readfile.read_attribute(ts_file)
    print(f'estimating velocity from {os.path.basename(ts_file)} '
          f'via MintPy time_func (polynomial=1) ...')

    date_list = get_ts_date_list(ts_file)
    num_date = len(date_list)
    length, width = int(atr['LENGTH']), int(atr['WIDTH'])
    seconds = atr.get('CENTER_LINE_UTC', 0)

    # read full displacement cube (HDFEOS or timeseries)
    if atr['FILE_TYPE'] == 'HDFEOS':
        ts_data = HDFEOS(ts_file).read(datasetName='displacement', print_msg=True)
    else:
        ts_data = readfile.read(ts_file, datasetName=date_list, print_msg=True)[0]

    if ts_data.ndim != 3:
        raise ValueError(f'Expected 3D displacement, got shape {ts_data.shape}')

    # unit → meters (MintPy timeseries2velocity does the same)
    unit = atr.get('UNIT', 'm')
    if unit == 'mm':
        ts_data = ts_data * (1.0 / 1000.0)
    elif unit == 'cm':
        ts_data = ts_data * 0.01

    ts_flat = ts_data.reshape(num_date, -1)
    del ts_data

    # skip pixels with zero/nan in all acquisitions (same as timeseries2velocity)
    ts_stack = np.nanmean(ts_flat, axis=0)
    mask = np.multiply(~np.isnan(ts_stack), ts_stack != 0.0)
    del ts_stack

    vel = np.full(length * width, np.nan, dtype=np.float32)
    num_pixel2inv = int(np.sum(mask))
    print(f'number of pixels to invert: {num_pixel2inv} out of {length * width} '
          f'({100.0 * num_pixel2inv / (length * width):.1f}%)')

    if num_pixel2inv > 0:
        model = {'polynomial': 1}
        # Same design matrix / lstsq as time_func.estimate_time_func (MintPy default).
        # Call lstsq directly so exact fits (e.g. 2 dates → empty residual vector)
        # do not raise ValueError like estimate_time_func.
        G = time_func.get_design_matrix4time_func(
            date_list, model=model, seconds=seconds
        )
        m = linalg.lstsq(G, ts_flat[:, mask], cond=None)[0]
        # poly-1: m[0]=offset, m[1]=velocity (m/year)
        vel[mask] = m[1].astype(np.float32)

    vel = vel.reshape(length, width)
    atr_vel = dict(atr)
    atr_vel['FILE_TYPE'] = 'velocity'
    atr_vel['UNIT'] = 'm/year'
    atr_vel['START_DATE'] = date_list[0]
    atr_vel['END_DATE'] = date_list[-1]
    atr_vel['DATE12'] = f'{date_list[0]}_{date_list[-1]}'
    atr_vel['mintpy.timeFunc.polynomial'] = '1'
    return vel, atr_vel


def resolve_velocity(ts_file, vel_file=None, atr=None):
    """Resolve velocity data and metadata for GRD export.

    Returns (data, atr, source_label) or (None, None, None).
    Priority: explicit -v → geo/geo_velocity.h5 → estimate (HDFEOS) → sibling velocity.h5.
    """
    atr = atr or readfile.read_attribute(ts_file)
    ts_dir = os.path.dirname(os.path.abspath(ts_file))
    prefix = 'geo_' if os.path.basename(ts_file).startswith('geo_') else ''

    # 1) explicit -v
    if vel_file:
        path = os.path.abspath(vel_file)
        if not os.path.isfile(path):
            raise FileNotFoundError(f'velocity file not found: {path}')
        data, atr_v = readfile.read(path)
        return data, atr_v, path

    # 2) MintPy geocoded velocity beside product
    geo_vel = find_geo_velocity_file(ts_file, atr=atr)
    if geo_vel:
        print(f'using geocoded MintPy velocity: {geo_vel}')
        data, atr_v = readfile.read(geo_vel)
        return data, atr_v, geo_vel

    # 3) estimate from geocoded HDFEOS (or timeseries) with MintPy default
    if atr.get('FILE_TYPE') in ['HDFEOS', 'timeseries']:
        # Prefer estimate for HDFEOS; for plain timeseries keep old sibling velocity.h5 first
        if atr.get('FILE_TYPE') == 'HDFEOS':
            data, atr_v = estimate_velocity_mintpy_default(ts_file, atr=atr)
            return data, atr_v, 'estimated (MintPy polynomial=1)'

    # 4) classic sibling velocity.h5 (timeseries workflow)
    sibling = os.path.join(ts_dir, f'{prefix}velocity.h5')
    if os.path.isfile(sibling):
        print(f'using velocity file: {sibling}')
        data, atr_v = readfile.read(sibling)
        return data, atr_v, os.path.abspath(sibling)

    if atr.get('FILE_TYPE') == 'timeseries':
        data, atr_v = estimate_velocity_mintpy_default(ts_file, atr=atr)
        return data, atr_v, 'estimated (MintPy polynomial=1)'

    return None, None, None


def save_explorer(inps):

    # create output directory
    inps.outdir = os.path.abspath(inps.outdir)
    print(f'output directory: {inps.outdir}')
    if not os.path.isdir(inps.outdir):
        print('output directory does not exist, creating directory: '+inps.outdir)
        os.makedirs(inps.outdir)

    inps.ts_file = os.path.abspath(inps.ts_file)
    atr = readfile.read_attribute(inps.ts_file)

    mask, msk_src = resolve_mask(inps.ts_file, msk_file=getattr(inps, 'msk_file', None), atr=atr)
    vel_data, atr_vel, vel_src = resolve_velocity(
        inps.ts_file, vel_file=getattr(inps, 'vel_file', None), atr=atr
    )

    print(f'time series file: {inps.ts_file}')
    print(f'velocity    src : {vel_src}')
    print(f'mask        src : {msk_src}')

    # export velocity
    if vel_data is not None:
        data = convert2mm(vel_data, atr_vel)
        if mask is not None:
            data = np.array(data, dtype=np.float32, copy=True)
            data[~np.array(mask, dtype=bool)] = np.nan

        if isinstance(vel_src, str) and os.path.isfile(vel_src):
            out_base = os.path.splitext(os.path.basename(vel_src))[0]
        else:
            out_base = 'velocity'
        out_file = os.path.join(inps.outdir, f'{out_base}_mm.grd')
        write_grd_file(data, atr_vel, out_file, print_msg=True)

    # export time series to a list of grd files
    print('writing time series to a list of timeseries-{YYYYMMDD}_mm.grd files ...')
    date_list = get_ts_date_list(inps.ts_file)
    num_date = len(date_list)
    prog_bar = ptime.progressBar(maxValue=num_date)
    for i, date_str in enumerate(date_list):
        prog_bar.update(i+1, suffix=f'{i+1}/{num_date} {date_str}')

        data, atr_ts = readfile.read(inps.ts_file, datasetName=date_str)
        data = convert2mm(data, atr_ts)
        if mask is not None:
            data = np.array(data, dtype=np.float32, copy=True)
            data[np.array(mask) == 0] = np.nan

        out_file = os.path.join(inps.outdir, f'timeseries-{date_str}_mm.grd')
        write_grd_file(data, atr_ts, out_file, print_msg=False)
    prog_bar.close()

    print('Done.')
    return
