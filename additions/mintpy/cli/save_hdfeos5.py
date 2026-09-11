#!/usr/bin/env python3
############################################################
# Program is part of MintPy                                #
# Copyright (c) 2013, Zhang Yunjun, Heresh Fattahi         #
# Author: Antonio Valentino, Zhang Yunjun, Aug 2022        #
############################################################


import os
import sys

from mintpy.defaults.template import get_template_content
from mintpy.utils.arg_utils import create_argument_parser

################################################################
TEMPALTE = TEMPLATE = get_template_content('hdfeos5')

EXAMPLE = """example:
  save_hdfeos5.py geo/geo_timeseries_ERA5_ramp_demErr.h5
  save_hdfeos5.py geo/geo_timeseries_ERA5_ramp_demErr.h5 --dem-error geo/geo_demErr.h5
  save_hdfeos5.py timeseries_ERA5_ramp_demErr.h5 --tc temporalCoherence.h5 --asc avgSpatialCoh.h5 -m maskTempCoh.h5 -g inputs/geometryGeo.h5
  save_hdfeos5.py timeseries_ERA5_ramp_demErr.h5 --tc temporalCoherence.h5 --asc avgSpatialCoh.h5 -m maskTempCoh.h5 -g inputs/geometryRadar.h5
"""

NOTE = """
  https://earthdata.nasa.gov/esdis/eso/standards-and-references/hdf-eos5
  https://mintpy.readthedocs.io/en/latest/hdfeos5/
"""


def create_parser(subparsers=None):
    synopsis = 'Convert MintPy timeseries product into HDF-EOS5 format'
    epilog = TEMPALTE + '\n' + EXAMPLE
    name = __name__.split('.')[-1]
    parser = create_argument_parser(
        name, synopsis=synopsis, description=synopsis+NOTE, epilog=epilog, subparsers=subparsers)

    parser.add_argument('ts_file', default='timeseries.h5', help='Time-series file')
    parser.add_argument('-t', '--template', dest='template_file',
                        help='Template file for 1) arguments/options and 2) missing metadata')

    parser.add_argument('--tc','--temp-coh', dest='tcoh_file',
                        help='Coherence/correlation file, i.e. temporalCoherence.h5')
    parser.add_argument('--asc','--avg-spatial-coh', dest='scoh_file',
                        help='Average spatial coherence file, i.e. avgSpatialCoh.h5')
    parser.add_argument('-m', '--mask', dest='mask_file', help='Mask file')
    parser.add_argument('-g', '--geometry', dest='geom_file', help='geometry file')
    parser.add_argument('-de', '--dem-error', dest='dem_err_file', help='DEM error file')
    parser.add_argument('--suffix', dest='suffix', help='suffix to be appended to file name (e.g. PS).')

    parser.add_argument(
        '--update', action='store_true',
        help='Enable update mode: use XXXXXXXX in filename when last SAR date is recent (<31 days)'
    )
    parser.add_argument('--subset', action='store_true',
                        help='Enable subset mode, a.k.a. put suffix _N31700_N32100_E130500_E131100')
    return parser


def _ts_dir(ts_file):
    return os.path.dirname(os.path.abspath(ts_file)) or os.getcwd()


def _is_geo_ts(ts_file, meta):
    return os.path.basename(ts_file).startswith('geo_') or 'Y_FIRST' in meta.keys()


def _default_dem_err_file(ts_file, meta):
    ts_dir = _ts_dir(ts_file)
    if _is_geo_ts(ts_file, meta):
        return os.path.join(ts_dir, 'geo_demErr.h5')
    return os.path.join(ts_dir, 'demErr.h5')


def _radar_dem_err_file(ts_file):
    ts_dir = _ts_dir(ts_file)
    for path in (os.path.join(ts_dir, 'demErr.h5'), os.path.join(os.path.dirname(ts_dir), 'demErr.h5')):
        if os.path.isfile(path):
            return path
    return None


def _same_length_width(file_a, file_b):
    from mintpy.utils import readfile
    a = readfile.read_attribute(file_a)
    b = readfile.read_attribute(file_b)
    try:
        return int(float(a['LENGTH'])) == int(float(b['LENGTH'])) and int(float(a['WIDTH'])) == int(float(b['WIDTH']))
    except (KeyError, TypeError, ValueError):
        return False


def _geocode_dem_err(radar_file, out_dir, template_file):
    """Geocode radar demErr.h5 into out_dir/geo_demErr.h5. Returns output path or None."""
    work_dir = os.path.dirname(os.path.abspath(radar_file)) or os.getcwd()
    os.makedirs(out_dir, exist_ok=True)
    iargs = [os.path.abspath(radar_file), '--outdir', os.path.abspath(out_dir), '--update']
    tmpl = template_file
    if not tmpl:
        cand = os.path.join(work_dir, 'smallbaselineApp.cfg')
        if os.path.isfile(cand):
            tmpl = cand
    if tmpl:
        iargs += ['-t', os.path.abspath(tmpl)]
    print('geocode.py', ' '.join(iargs))
    cwd = os.getcwd()
    try:
        os.chdir(work_dir)
        from mintpy.cli.geocode import main as geocode_main
        try:
            geocode_main(iargs)
        except SystemExit as exc:
            if exc.code not in (0, None):
                print(f'WARNING: geocode.py exited with {exc.code}; skip demError')
                return None
    except Exception as exc:
        print(f'WARNING: failed to geocode {radar_file}: {exc}; skip demError')
        return None
    finally:
        os.chdir(cwd)
    out_file = os.path.join(os.path.abspath(out_dir), 'geo_demErr.h5')
    return out_file if os.path.isfile(out_file) else None


def cmd_line_parse(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(args=iargs)

    from mintpy.utils import readfile

    meta = readfile.read_attribute(inps.ts_file)

    ts_dir = _ts_dir(inps.ts_file)
    if os.path.basename(inps.ts_file).startswith('geo_'):
        tcoh_file = os.path.join(ts_dir, 'geo_temporalCoherence.h5')
        scoh_file = os.path.join(ts_dir, 'geo_avgSpatialCoh.h5')
        mask_file = os.path.join(ts_dir, 'geo_maskTempCoh.h5')
        geom_file = os.path.join(ts_dir, 'geo_geometryRadar.h5')
    else:
        tcoh_file = os.path.join(ts_dir, 'temporalCoherence.h5')
        scoh_file = os.path.join(ts_dir, 'avgSpatialCoh.h5')
        mask_file = os.path.join(ts_dir, 'maskTempCoh.h5')
        geom_file = os.path.join(ts_dir, 'inputs/geometry')
        geom_file += 'Geo.h5' if 'Y_FIRST' in meta.keys() else 'Radar.h5'

    inps.tcoh_file = inps.tcoh_file if inps.tcoh_file else tcoh_file
    inps.scoh_file = inps.scoh_file if inps.scoh_file else scoh_file
    inps.mask_file = inps.mask_file if inps.mask_file else mask_file
    inps.geom_file = inps.geom_file if inps.geom_file else geom_file

    for fname in [inps.ts_file, inps.tcoh_file, inps.scoh_file, inps.mask_file, inps.geom_file]:
        if not os.path.isfile(fname):
            raise FileNotFoundError(fname)

    dem_err_user = inps.dem_err_file
    if dem_err_user:
        if not os.path.isfile(dem_err_user):
            raise FileNotFoundError(dem_err_user)
        dem_meta = readfile.read_attribute(dem_err_user)
        if _is_geo_ts(inps.ts_file, meta) and 'Y_FIRST' not in dem_meta.keys():
            geo_dem = _geocode_dem_err(dem_err_user, ts_dir, inps.template_file)
            inps.dem_err_file = geo_dem
            if not geo_dem:
                print(f'WARNING: failed to geocode {dem_err_user}; skip demError')
    else:
        inps.dem_err_file = _default_dem_err_file(inps.ts_file, meta)
        if not os.path.isfile(inps.dem_err_file) and _is_geo_ts(inps.ts_file, meta):
            radar = _radar_dem_err_file(inps.ts_file)
            if radar:
                geo_dem = _geocode_dem_err(radar, ts_dir, inps.template_file)
                inps.dem_err_file = geo_dem
        if inps.dem_err_file and not os.path.isfile(inps.dem_err_file):
            print(f'WARNING: DEM error file not found ({inps.dem_err_file}), skip demError')
            inps.dem_err_file = None

    if inps.dem_err_file and not _same_length_width(inps.dem_err_file, inps.ts_file):
        print(f'WARNING: demError grid {inps.dem_err_file} does not match {inps.ts_file}; skip demError')
        inps.dem_err_file = None

    return inps


################################################################
def main(iargs=None):
    # parse
    inps = cmd_line_parse(iargs)

    # Hack to make sure save_hdfeos5.py one dir down is imported
    #cli_dir = os.path.dirname(os.path.abspath(__file__))
    #root_dir = os.path.dirname(cli_dir)  # one level up: additions/mintpy/
    #if root_dir not in sys.path:
        #sys.path.insert(0, root_dir)
    #from save_hdfeos5 import save_hdfeos5

    # import
    from mintpy.save_hdfeos5 import save_hdfeos5

    # run
    save_hdfeos5(inps)


################################################################
if __name__ == '__main__':
    main(sys.argv[1:])
