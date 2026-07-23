#!/usr/bin/env python3
############################################################
# Program is part of MintPy                                #
# Copyright (c) 2013, Zhang Yunjun, Heresh Fattahi         #
# Author: Antonio Valentino, Piyush Agram, Aug 2022        #
############################################################
# MinSAR: accept timeseries or HDFEOS (.he5); geo or radar;
# -g optional for HDFEOS; optional -m mask override;
# default GeoPackage (.gpkg); --no-gpkg for shapefile.


import os
import sys

from mintpy.utils import readfile
from mintpy.utils.arg_utils import create_argument_parser

#########################################################################################
EXAMPLE = """example:
  save_qgis.py timeseries_ERA5_ramp_demErr.h5 -g inputs/geometrygeo.h5
  save_qgis.py timeseries_ERA5_ramp_demErr.h5 -g inputs/geometryRadar.h5
  save_qgis.py timeseries_ERA5_ramp_demErr.h5 -g inputs/geometryRadar.h5 -b 200 150 400 350
  save_qgis.py geo/geo_timeseries_ERA5_ramp_demErr.h5 -g geo/geo_geometryRadar.h5
  save_qgis.py S1_desc_109_miaplpy_20141013_XXXXXXXX_N3651E02528_N3651E02553_N3630E02553_N3630E02528.he5
  save_qgis.py S1_....he5 -g inputs/geometryRadar.h5 -m maskTempCoh.h5
  save_qgis.py S1_....he5 --no-gpkg
  save_qgis.py S1_....he5 -o out/points.gpkg
"""


def create_parser(subparsers=None):
    synopsis = 'Convert to QGIS compatible ps time-series'
    epilog = EXAMPLE
    name = __name__.split('.')[-1]
    parser = create_argument_parser(
        name, synopsis=synopsis, description=synopsis, epilog=epilog, subparsers=subparsers)

    parser.add_argument('ts_file', type=str, help='time-series HDF5 / HDFEOS (.he5) file')
    parser.add_argument('-g', '--geom', dest='geom_file', type=str, default=None,
                        help='geometry HDF5 file (required for classic timeseries; optional for HDFEOS).')
    parser.add_argument('-m', '--mask', dest='msk_file', type=str, default=None,
                        help='mask file (optional; else sibling maskTempCoh / HDFEOS quality/mask).')
    parser.add_argument('-o', '--output', '--outshp', dest='out_file', type=str, default=None,
                        help='Output path (.gpkg default; .shp with --no-gpkg).')
    parser.add_argument('--no-gpkg', dest='no_gpkg', action='store_true',
                        help='Write ESRI shapefile (.shp) instead of GeoPackage (.gpkg).')

    # bounding box
    parser.add_argument('-b', '--bbox', dest='pix_bbox', type=int, nargs=4, default=None,
                        metavar=('Y0', 'Y1', 'X0', 'X1'), help='bounding box : minLine maxLine minPixel maxPixel')
    parser.add_argument('-B', '--geo-bbox', dest='geo_bbox', type=float, nargs=4, default=None,
                        metavar=('S', 'N', 'W', 'E'), help='bounding box in lat lon: South North West East')

    # other options
    parser.add_argument('--zf', '--zero-first', dest='zero_first', action='store_true',
                        help='Set displacement at the first acquisition to zero.')

    return parser


def cmd_line_parse(iargs=None):
    '''Command line parser.'''
    parser = create_parser()
    inps = parser.parse_args(args=iargs)

    atr = readfile.read_attribute(inps.ts_file)
    ftype = atr['FILE_TYPE']
    if ftype not in ['timeseries', 'HDFEOS']:
        raise Exception(f'Input file ({ftype}) is NOT time series or HDFEOS!')

    if ftype == 'timeseries' and not inps.geom_file:
        raise Exception('-g/--geom is required for classic timeseries HDF5 input.')

    # output path / format: default .gpkg; --no-gpkg → .shp; -o extension wins when .gpkg/.shp
    if inps.out_file:
        ext = os.path.splitext(inps.out_file)[1].lower()
        if ext == '.shp':
            inps.no_gpkg = True
        elif ext == '.gpkg':
            inps.no_gpkg = False
        elif ext == '':
            inps.out_file = inps.out_file + ('.shp' if inps.no_gpkg else '.gpkg')
    else:
        fbase = os.path.splitext(inps.ts_file)[0]
        inps.out_file = fbase + ('.shp' if inps.no_gpkg else '.gpkg')

    # backward-compatible alias used by save_qgis()
    inps.shp_file = inps.out_file

    return inps


#########################################################################################
def main(iargs=None):
    # parse
    inps = cmd_line_parse(iargs)

    # import
    from mintpy.save_qgis import save_qgis

    # run
    save_qgis(inps)


#########################################################################################
if __name__ == '__main__':
    main(sys.argv[1:])
