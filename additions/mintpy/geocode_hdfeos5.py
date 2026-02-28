#!/usr/bin/env python3
############################################################
# MinSAR addition: Geocode S1*.he5 (HDFEOS5) files
# Full in-place (B2): read HDFEOS5 → geocode → write HDFEOS5
# No extract step, no temp directory (minimal temp for lookup only)
############################################################


import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

import h5py
import numpy as np

from mintpy.objects.resample import resample
from mintpy.utils import attribute as attr, readfile

# Constants matching save_hdfeos5
BOOL_ZERO = np.bool_(0)
FLOAT_ZERO = np.float32(0.0)
COMPRESSION = 'lzf'


def parse_args(iargs=None):
    """Parse arguments for geocoding .he5 files."""
    parser = argparse.ArgumentParser(
        description='Geocode radar-coordinate HDFEOS5 (.he5) file to geographic coordinates.',
        epilog='Full in-place (B2): read HDFEOS5 directly, geocode block-by-block, write HDFEOS5 directly.',
    )
    parser.add_argument('file', nargs='+', help='.he5 file(s) to geocode')
    parser.add_argument('-l', '--lookup', dest='lookupFile',
                        help='Lookup table (e.g. inputs/geometryRadar.h5). '
                             'Default: extract geometry only from .he5.')
    parser.add_argument('-t', '--template', dest='templateFile',
                        help='Template file with geocoding options')
    parser.add_argument('-o', '--output', dest='outfile', help='Output .he5 file')
    parser.add_argument('--outdir', '--output-dir', dest='out_dir',
                        help='Output directory (default: same as input)')
    parser.add_argument('--ram', '--memory', dest='maxMemory', type=float, default=4.0,
                        help='Max memory in GB (default: 4.0)')
    parser.add_argument('-b', '--bbox', dest='SNWE', type=float, nargs=4,
                        metavar=('S', 'N', 'W', 'E'),
                        help='Bounding box for output grid')
    parser.add_argument('--lalo', '--lalo-step', dest='laloStep', type=float, nargs=2,
                        metavar=('LAT_STEP', 'LON_STEP'),
                        help='Output pixel size in degrees')
    return parser.parse_args(args=iargs or sys.argv[1:])


def run_cmd(cmd, check=True):
    """Run a command; raise on failure if check=True."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {result.returncode}: {' '.join(cmd)}")
    return result.returncode


def _ensure_lookup(he5_file, lookup_pre, he5_dir):
    """Return path to geometryRadar.h5: use -l if given, else extract geometry only."""
    if lookup_pre and os.path.isfile(lookup_pre):
        return os.path.abspath(lookup_pre)
    # Extract geometry only (no --all). extract_hdfeos5 writes to dir of input;
    # symlink he5 into temp dir so extract writes there.
    with tempfile.TemporaryDirectory(prefix='.geocode_he5_lut_', dir=he5_dir) as tmpdir:
        he5_basename = os.path.basename(he5_file)
        he5_in_tmp = os.path.join(tmpdir, he5_basename)
        os.symlink(os.path.abspath(he5_file), he5_in_tmp)
        run_cmd(['extract_hdfeos5.py', he5_in_tmp])
        lut = os.path.join(tmpdir, 'geometryRadar.h5')
        if not os.path.isfile(lut):
            lut = os.path.join(tmpdir, 'inputs', 'geometryRadar.h5')
        if not os.path.isfile(lut):
            raise FileNotFoundError(
                "Lookup not found. Provide -l /path/to/geometryRadar.h5 or ensure extract_hdfeos5 produces geometryRadar.h5."
            )
        out_lut = os.path.join(he5_dir, '.geocode_he5_lut_geometryRadar.h5')
        shutil.copy(lut, out_lut)
    return out_lut


def _read_he5_dates(he5_path):
    """Read date list from HDFEOS observation."""
    with h5py.File(he5_path, 'r') as f:
        dates = f['HDFEOS/GRIDS/timeseries/observation/date'][()]
    return [d.decode() if isinstance(d, bytes) else str(d) for d in dates]


def _read_he5_bperp(he5_path):
    """Read bperp from HDFEOS observation."""
    with h5py.File(he5_path, 'r') as f:
        return f['HDFEOS/GRIDS/timeseries/observation/bperp'][()]


def _prep_metadata_b2(he5_path, res_obj, geometry_radar_path, template_path=None):
    """Prepare metadata for output HDFEOS5 (B2 path, no geo_ts file)."""
    atr = readfile.read_attribute(he5_path)
    if 'Y_FIRST' not in atr:
        atr = readfile.read_attribute(
            he5_path, datasetName='HDFEOS/GRIDS/timeseries/observation/displacement'
        )
    atr = attr.update_attribute4radar2geo(atr, res_obj=res_obj)
    date_list = _read_he5_dates(he5_path)

    try:
        from mintpy.save_hdfeos5 import metadata_mintpy2unavco
    except ImportError:
        from save_hdfeos5 import metadata_mintpy2unavco
    try:
        unavco = metadata_mintpy2unavco(atr, date_list, geometry_radar_path)
    except (KeyError, ValueError, TypeError) as e:
        print(f"Warning: metadata_mintpy2unavco failed ({e}), using minimal metadata", file=sys.stderr)
        unavco = {
            'first_date': f'{date_list[0][:4]}-{date_list[0][4:6]}-{date_list[0][6:8]}',
            'last_date': f'{date_list[-1][:4]}-{date_list[-1][4:6]}-{date_list[-1][6:8]}',
        }
    meta = {**atr, **unavco, 'FILE_TYPE': 'HDFEOS'}

    if template_path and os.path.isfile(template_path):
        template = readfile.read_template(template_path)
        meta['cfg.template_file'] = os.path.abspath(template_path)
        for k, v in template.items():
            if not k.startswith(('mintpy', 'isce', '_')) and 'auto' not in str(v).lower():
                meta[f'cfg.{k}'] = v
    return meta


def _create_hdf5_dataset(group, dsName, data, compression=COMPRESSION):
    """Create HDF5 dataset in group (2D or 1D)."""
    if data.ndim == 1:
        return group.create_dataset(dsName, data=data, compression=compression)
    return group.create_dataset(
        dsName, data=data, chunks=True, compression=compression
    )


def main(iargs=None):
    inps = parse_args(iargs)
    he5_files = [f for f in inps.file if f.endswith('.he5') and os.path.isfile(f)]
    if not he5_files:
        raise SystemExit("Error: No .he5 input files found.")

    he5_file = os.path.abspath(he5_files[0])
    he5_dir = os.path.dirname(he5_file)
    lookup_pre = os.path.abspath(inps.lookupFile) if inps.lookupFile else None
    template_abs = os.path.abspath(inps.templateFile) if inps.templateFile else None

    # Check: input already geocoded? (same as geocode_orig)
    atr = readfile.read_attribute(he5_file)
    if 'Y_FIRST' in atr.keys():
        print('input file is already geocoded')
        print('to resample geocoded files into radar coordinates, use --geo2radar option')
        print('exit without doing anything.')
        sys.exit(0)

    # 1. Ensure lookup (geometryRadar.h5)
    lut_path = _ensure_lookup(he5_file, lookup_pre, he5_dir)
    start_time = time.time()
    try:
        # 2. Init resample (use geometryRadar as both lut and src for dimensions)
        kwargs = dict(
            interp_method='nearest',
            fill_value=np.nan,
            nprocs=1,
            max_memory=inps.maxMemory,
            software='pyresample',
            print_msg=True,
        )
        res_obj = resample(
            lut_file=lut_path,
            src_file=lut_path,
            SNWE=inps.SNWE,
            lalo_step=inps.laloStep,
            **kwargs,
        )
        res_obj.open()
        res_obj.prepare()

        # number of processor (same as geocode_orig)
        print(f'number of processor to be used: {res_obj.nprocs}')

        # 4. Output path (same as geocode_orig: prepend geo_ to basename)
        out_dir = inps.out_dir or he5_dir
        os.makedirs(out_dir, exist_ok=True)
        if inps.outfile:
            out_path = os.path.join(out_dir, inps.outfile)
        else:
            fbase, fext = os.path.splitext(os.path.basename(he5_file))
            out_name = f'geo_{fbase}{fext}'
            out_path = os.path.join(out_dir, out_name)

        # resampling file (same as geocode.py)
        print('-' * 50)
        print(f'resampling file: {os.path.basename(he5_file)}')
        # 3. Prepare metadata (update REF_LAT/LON/Y/X comes from update_attribute4radar2geo)
        meta = _prep_metadata_b2(he5_file, res_obj, lut_path, template_abs)
        print('-' * 50)
        print(f'grab dataset structure from ref_file: {os.path.basename(he5_file)}')
        print(f'create HDF5 file: {os.path.basename(out_path)} with w mode')

        # 5. Read dates and bperp from input
        date_list = _read_he5_dates(he5_file)
        bperp = _read_he5_bperp(he5_file)
        num_date = len(date_list)

        geo_len, geo_wid = res_obj.length, res_obj.width

        def _geocode_2d(radar_data, ds_name, infile_basename, outfile_basename):
            """Geocode 2D array block-by-block, with output matching geocode.py."""
            out = np.zeros((geo_len, geo_wid), dtype=radar_data.dtype)
            max_digit = max(len(ds_name), 12)
            for i in range(res_obj.num_box):
                src_box = res_obj.src_box_list[i]
                dest_box = res_obj.dest_box_list[i]
                print('-' * 50 + f'{i+1}/{res_obj.num_box}')
                print('reading {d:<{w}} in block {b} from {f} ...'.format(
                    d=ds_name, w=max_digit, b=src_box, f=infile_basename))
                block = radar_data[src_box[1]:src_box[3], src_box[0]:src_box[2]]
                geo_block = res_obj.run_resample(block, box_ind=i, print_msg=True)
                if geo_block.ndim == 2:
                    blk = [dest_box[1], dest_box[3], dest_box[0], dest_box[2]]
                else:
                    blk = [0, geo_block.shape[0], dest_box[1], dest_box[3], dest_box[0], dest_box[2]]
                print(f'write data in block {blk} to file: {outfile_basename}')
                out[dest_box[1]:dest_box[3], dest_box[0]:dest_box[2]] = geo_block
            return out

        he5_basename = os.path.basename(he5_file)
        out_basename = os.path.basename(out_path)
        with h5py.File(out_path, 'w') as outf:
            # --- Observation ---
            g_obs = outf.create_group('HDFEOS/GRIDS/timeseries/observation')
            print('create dataset  : bperp      of float32                   in size of ({},)               with compression = None'.format(num_date))
            g_obs.create_dataset('bperp', data=bperp.astype(np.float32))
            print('create dataset  : date       of |S8                       in size of ({},)               with compression = None'.format(num_date))
            g_obs.create_dataset('date', data=np.array(date_list, dtype='S8'))
            print('create dataset  : displacement of float32                   in size of ({}, {}, {})    with compression = None'.format(num_date, geo_len, geo_wid))
            ds_disp = g_obs.create_dataset(
                'displacement',
                shape=(num_date, geo_len, geo_wid),
                dtype=np.float32,
                chunks=True,
                compression=COMPRESSION,
            )
            ds_disp.attrs['Title'] = 'displacement'
            ds_disp.attrs['MissingValue'] = FLOAT_ZERO
            ds_disp.attrs['_FillValue'] = FLOAT_ZERO
            ds_disp.attrs['Units'] = 'meters'

            print('close  HDF5 file: {}'.format(out_basename))

            # Block-by-block like geocode.py (read full 3D block, resample, write)
            ds_name = 'displacement'
            max_digit = len(ds_name)
            with h5py.File(he5_file, 'r') as inf:
                dset_in = inf['HDFEOS/GRIDS/timeseries/observation/displacement']
                for bi in range(res_obj.num_box):
                    src_box = res_obj.src_box_list[bi]
                    dest_box = res_obj.dest_box_list[bi]
                    print('-' * 50 + f'{bi+1}/{res_obj.num_box}')
                    print('reading {d:<{w}} in block {b} from {f} ...'.format(
                        d=ds_name, w=max_digit, b=src_box, f=he5_basename))
                    block = dset_in[:, src_box[1]:src_box[3], src_box[0]:src_box[2]]
                    geo_block = res_obj.run_resample(block, box_ind=bi, print_msg=True)
                    blk = [0, geo_block.shape[0], dest_box[1], dest_box[3], dest_box[0], dest_box[2]]
                    print(f'write data in block {blk} to file: {out_basename}')
                    ds_disp[:, dest_box[1]:dest_box[3], dest_box[0]:dest_box[2]] = geo_block

            # --- Quality ---
            g_qual = outf.create_group('HDFEOS/GRIDS/timeseries/quality')
            for ds_name, path in [
                ('temporalCoherence', 'HDFEOS/GRIDS/timeseries/quality/temporalCoherence'),
                ('avgSpatialCoherence', 'HDFEOS/GRIDS/timeseries/quality/avgSpatialCoherence'),
                ('mask', 'HDFEOS/GRIDS/timeseries/quality/mask'),
            ]:
                try:
                    data, _ = readfile.read(he5_file, datasetName=path)
                    geo_data = _geocode_2d(data, ds_name, he5_basename, out_basename)
                    ds = _create_hdf5_dataset(g_qual, ds_name, geo_data)
                    ds.attrs['Title'] = ds_name
                    ds.attrs['MissingValue'] = FLOAT_ZERO if 'Coherence' in ds_name else BOOL_ZERO
                    ds.attrs['_FillValue'] = FLOAT_ZERO if 'Coherence' in ds_name else BOOL_ZERO
                    ds.attrs['Units'] = '1'
                except Exception as e:
                    print(f"Warning: skipping {ds_name}: {e}", file=sys.stderr)

            # --- Geometry ---
            g_geom = outf.create_group('HDFEOS/GRIDS/timeseries/geometry')
            geom_path = 'HDFEOS/GRIDS/timeseries/geometry'
            geom_slices = [
                'height', 'incidenceAngle', 'latitude', 'longitude',
                'slantRangeDistance', 'azimuthAngle', 'rangeCoord', 'azimuthCoord',
                'shadowMask', 'waterMask',
            ]
            for ds_name in geom_slices:
                try:
                    data, _ = readfile.read(he5_file, datasetName=f'{geom_path}/{ds_name}')
                    geo_data = _geocode_2d(data, ds_name, he5_basename, out_basename)
                    ds = _create_hdf5_dataset(g_geom, ds_name, geo_data)
                    ds.attrs['Title'] = ds_name
                    if ds_name in ['height', 'slantRangeDistance', 'bperp']:
                        ds.attrs['MissingValue'] = FLOAT_ZERO
                        ds.attrs['_FillValue'] = FLOAT_ZERO
                        ds.attrs['Units'] = 'meters'
                    elif ds_name in ['incidenceAngle', 'azimuthAngle', 'latitude', 'longitude']:
                        ds.attrs['MissingValue'] = FLOAT_ZERO
                        ds.attrs['_FillValue'] = FLOAT_ZERO
                        ds.attrs['Units'] = 'degrees'
                    elif ds_name in ['rangeCoord', 'azimuthCoord']:
                        ds.attrs['MissingValue'] = FLOAT_ZERO
                        ds.attrs['_FillValue'] = FLOAT_ZERO
                        ds.attrs['Units'] = '1'
                    else:
                        ds.attrs['MissingValue'] = BOOL_ZERO
                        ds.attrs['_FillValue'] = BOOL_ZERO
                        ds.attrs['Units'] = '1'
                except Exception:
                    pass  # optional geometry datasets

            # Root metadata
            print('write metadata to root level')
            for k, v in meta.items():
                try:
                    outf.attrs[k] = v
                except (TypeError, ValueError):
                    pass

        m, s = divmod(time.time() - start_time, 60)
        print(f'time used: {m:02.0f} mins {s:02.1f} secs.\n')
        print(f"Wrote geocoded .he5: {out_path}")
    finally:
        # Clean up temp lookup if we created it
        tmp_lut = os.path.join(he5_dir, '.geocode_he5_lut_geometryRadar.h5')
        if os.path.isfile(tmp_lut) and tmp_lut == lut_path:
            try:
                os.remove(tmp_lut)
            except OSError:
                pass
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]) or 0)
