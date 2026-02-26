#!/usr/bin/env python3
############################################################
# Subset HDFEOS5 files (e.g. from save_hdfeos5.py)
# Uses geometry in the HDFEOS file; errors if geometry is missing.
# Supports --subset-lalo=lat_min:lat_max,lon_min:lon_max and standard MintPy subset options.
############################################################

import os
import re

import h5py
import numpy as np

from mintpy.utils import (
    attribute as attr,
    ptime,
    readfile,
    utils as ut,
    writefile,
)

# Import subset helpers from MintPy (same as tools/MintPy/src/mintpy/subset.py)
from mintpy.subset import (
    get_box_overlap_index,
    get_coverage_box,
    read_subset_template2box,
    subset_box2inps,
    subset_input_dict2box,
)


################################################################
# Geometry from HDFEOS
################################################################

def get_hdfeos_geometry_atr(fname):
    """Get attributes with geometry so lat/lon subset can be converted to pixel box.

    Uses root-level Y_FIRST/X_FIRST/Y_STEP/X_STEP if present; otherwise reads
    HDFEOS/GRIDS/timeseries/geometry/latitude and longitude and adds
    Y_FIRST/X_FIRST/Y_STEP/X_STEP from their extent (regular grid assumed).
    Raises if no geometry is found.
    """
    atr = readfile.read_attribute(fname)
    if atr.get('FILE_TYPE') != 'HDFEOS':
        raise ValueError(f'File is not HDFEOS: {fname}')

    # Geo coordinates in metadata (from save_hdfeos5 when stack was geocoded)
    if all(k in atr for k in ['Y_FIRST', 'X_FIRST', 'Y_STEP', 'X_STEP']):
        return atr

    # Try geometry group: latitude, longitude arrays
    with h5py.File(fname, 'r') as f:
        base = 'HDFEOS/GRIDS/timeseries/geometry'
        if base not in f:
            raise ValueError(
                'HDFEOS file has no usable geometry: missing Y_FIRST/X_FIRST/Y_STEP/X_STEP '
                'and missing HDFEOS/GRIDS/timeseries/geometry. '
                'Cannot subset by lat/lon.'
            )
        g = f[base]
        if 'latitude' not in g or 'longitude' not in g:
            raise ValueError(
                'HDFEOS file has no usable geometry: missing latitude/longitude in '
                'HDFEOS/GRIDS/timeseries/geometry. Cannot subset by lat/lon.'
            )
        lat = np.array(g['latitude'])
        lon = np.array(g['longitude'])
        if lat.ndim != 2 or lon.ndim != 2:
            raise ValueError(
                'HDFEOS geometry latitude/longitude must be 2D arrays.'
            )

    # Infer a regular grid from lat/lon extent (UL corner + step)
    # MintPy: Y_FIRST = lat of first row (north), Y_STEP negative (south); X_FIRST = lon of first col (west).
    length, width = lat.shape
    lat_min, lat_max = float(np.nanmin(lat)), float(np.nanmax(lat))
    lon_min, lon_max = float(np.nanmin(lon)), float(np.nanmax(lon))
    y_step = (lat_min - lat_max) / (length - 1) if length > 1 else 0.0  # negative
    x_step = (lon_max - lon_min) / (width - 1) if width > 1 else 0.0
    atr = dict(atr)
    atr['Y_FIRST'] = str(lat_max)   # north (first row)
    atr['X_FIRST'] = str(lon_min)   # west (first col)
    atr['Y_STEP'] = str(y_step)
    atr['X_STEP'] = str(x_step)
    atr['LENGTH'] = str(length)
    atr['WIDTH'] = str(width)
    return atr


def parse_subset_lalo(s):
    """Parse --subset-lalo=lat_min:lat_max,lon_min:lon_max into subset_lat, subset_lon.

    Returns (subset_lat, subset_lon) as ([lat_min, lat_max], [lon_min, lon_max]) or (None, None) if s is empty.
    """
    s = (s or '').strip()
    if not s:
        return None, None
    # Allow lat_min:lat_max,lon_min:lon_max
    m = re.match(r'([-\d.]+)\s*:\s*([-\d.]+)\s*,\s*([-\d.]+)\s*:\s*([-\d.]+)', s)
    if not m:
        raise ValueError(
            '--subset-lalo must be lat_min:lat_max,lon_min:lon_max '
            '(e.g. --subset-lalo=30.5:31.0,130.0:131.0)'
        )
    lat0, lat1, lon0, lon1 = [float(x) for x in m.groups()]
    subset_lat = [min(lat0, lat1), max(lat0, lat1)]
    subset_lon = [min(lon0, lon1), max(lon0, lon1)]
    return subset_lat, subset_lon


def lalo_box_to_pix_box_from_hdfeos_geometry(fname, lat_min, lat_max, lon_min, lon_max):
    """Convert lat/lon box to pixel box using HDFEOS geometry arrays (radar grid).

    For non-geocoded data, the grid is irregular; use actual lat/lon arrays instead
    of affine (Y_FIRST) to match geometryRadar subset with --lookup.
    Returns (x0, y0, x1, y1) or None on failure.
    """
    try:
        with h5py.File(fname, 'r') as f:
            base = 'HDFEOS/GRIDS/timeseries/geometry'
            if base not in f or 'latitude' not in f[base] or 'longitude' not in f[base]:
                return None
            lat = np.array(f[base]['latitude'])
            lon = np.array(f[base]['longitude'])
    except Exception:
        return None
    if lat.ndim != 2 or lon.ndim != 2:
        return None
    valid = np.isfinite(lat) & np.isfinite(lon)
    in_box = (
        (lat >= lat_min) & (lat <= lat_max) &
        (lon >= lon_min) & (lon <= lon_max) &
        valid
    )
    if not np.any(in_box):
        return None
    rows, cols = np.where(in_box)
    return (int(np.min(cols)), int(np.min(rows)), int(np.max(cols)) + 1, int(np.max(rows)) + 1)


def _update_subset_ref_and_corner_metadata(atr, geo_box):
    """Update REF_LAT/LON and LAT/LON_REF1-4 in atr for the subset.

    geo_box is (W, N, E, S) in degrees. REF_LAT/LON are set from REF_Y/X using
    Y_FIRST, X_FIRST, Y_STEP, X_STEP. Corner refs are the subset footprint.
    """
    atr = dict(atr)
    # Subset footprint corners (W, N, E, S) -> REF1=NW, REF2=NE, REF3=SW, REF4=SE
    west, north, east, south = geo_box[0], geo_box[1], geo_box[2], geo_box[3]
    atr['LAT_REF1'] = str(north)
    atr['LON_REF1'] = str(west)
    atr['LAT_REF2'] = str(north)
    atr['LON_REF2'] = str(east)
    atr['LAT_REF3'] = str(south)
    atr['LON_REF3'] = str(west)
    atr['LAT_REF4'] = str(south)
    atr['LON_REF4'] = str(east)

    # REF_LAT, REF_LON from REF_Y, REF_X and subset geo transform
    ref_y = atr.get('REF_Y')
    ref_x = atr.get('REF_X')
    if ref_y is not None and ref_x is not None:
        try:
            ry, rx = int(ref_y), int(ref_x)
        except (ValueError, TypeError):
            try:
                ry = int(ref_y.decode().strip()) if isinstance(ref_y, bytes) else int(ref_y)
                rx = int(ref_x.decode().strip()) if isinstance(ref_x, bytes) else int(ref_x)
            except (ValueError, TypeError, AttributeError):
                ry = rx = None
        if (ry is not None and rx is not None and
                'Y_FIRST' in atr and 'X_FIRST' in atr and 'Y_STEP' in atr and 'X_STEP' in atr):
            try:
                y0, x0 = float(atr['Y_FIRST']), float(atr['X_FIRST'])
                dy, dx = float(atr['Y_STEP']), float(atr['X_STEP'])
                ref_lat = y0 + ry * dy
                ref_lon = x0 + rx * dx
                atr['REF_LAT'] = str(ref_lat)
                atr['REF_LON'] = str(ref_lon)
            except (ValueError, TypeError):
                pass
    return atr


def _get_ref_latlon_from_geometry(fname, ref_y, ref_x, pix_box):
    """Read latitude and longitude at (ref_y, ref_x) in subset coords from HDFEOS geometry.

    pix_box is (x0, y0, x1, y1) in full-data pixel coords. Subset ref pixel maps to
    full-data row = pix_box[1] + ref_y, col = pix_box[0] + ref_x.
    Returns (ref_lat, ref_lon) or (None, None) on failure.
    """
    try:
        ry, rx = int(ref_y), int(ref_x)
    except (ValueError, TypeError):
        try:
            ry = int(ref_y.decode().strip()) if isinstance(ref_y, bytes) else int(ref_y)
            rx = int(ref_x.decode().strip()) if isinstance(ref_x, bytes) else int(ref_x)
        except (ValueError, TypeError, AttributeError):
            return None, None
    x0, y0 = pix_box[0], pix_box[1]
    row, col = y0 + ry, x0 + rx
    try:
        with h5py.File(fname, 'r') as f:
            base = 'HDFEOS/GRIDS/timeseries/geometry'
            if base not in f or 'latitude' not in f[base] or 'longitude' not in f[base]:
                return None, None
            lat = np.array(f[base]['latitude'][row, col])
            lon = np.array(f[base]['longitude'][row, col])
            return float(lat), float(lon)
    except Exception:
        return None, None


def _find_valid_ref_in_subset(fname, pix_box4data, pix_box4subset, sub_length, sub_width):
    """Find a valid (mask != 0) pixel near center of the subset for use as REF_Y/X.

    Reads HDFEOS/GRIDS/timeseries/quality/mask in the subset region and returns
    (row, col) in subset coordinates (0..sub_length-1, 0..sub_width-1) closest to
    center, or (None, None) if no valid pixel.
    """
    try:
        with h5py.File(fname, 'r') as f:
            gpath = 'HDFEOS/GRIDS/timeseries/quality'
            if gpath not in f or 'mask' not in f[gpath]:
                return None, None
            mask = f[gpath]['mask'][
                pix_box4data[1]:pix_box4data[3],
                pix_box4data[0]:pix_box4data[2],
            ]
            mask = np.asarray(mask)
    except Exception:
        return None, None
    # Valid: mask is True / non-zero (handles bool and int/uint)
    valid = (mask != 0)
    if not np.any(valid):
        return None, None
    rows, cols = np.where(valid)
    # Map patch (overlap) coords to subset output coords
    sy0, sx0 = pix_box4subset[1], pix_box4subset[0]
    sub_rows = rows + sy0
    sub_cols = cols + sx0
    cy, cx = sub_length // 2, sub_width // 2
    dist = (sub_rows - cy) ** 2 + (sub_cols - cx) ** 2
    idx = np.argmin(dist)
    return int(sub_rows[idx]), int(sub_cols[idx])


def subset_file_hdfeos(fname, subset_dict_input, out_file=None):
    """Subset an HDFEOS5 file using geometry in the file.

    Uses geometry from the file (Y_FIRST/X_FIRST or geometry/latitude, longitude).
    Fails if geometry is missing. Copies coordinate type (RADAR/GEO) from the original file.
    """
    atr_orig = readfile.read_attribute(fname)
    original_has_geo = 'Y_FIRST' in atr_orig

    atr = get_hdfeos_geometry_atr(fname)
    width = int(atr['WIDTH'])
    length = int(atr['LENGTH'])
    print(f"subset HDFEOS file: {fname} ...")

    subset_dict = subset_dict_input.copy()
    outfill = 'fill_value' in subset_dict and subset_dict.get('fill_value') is not None
    if not outfill:
        subset_dict['fill_value'] = np.nan

    # For radar (not geocoded): convert lat/lon to pixel box using HDFEOS geometry arrays
    # so result matches geometryRadar subset with --lookup (affine Y_FIRST is wrong for radar grid)
    if (not original_has_geo and subset_dict.get('subset_lat') and subset_dict.get('subset_lon')):
        lat0, lat1 = sorted(subset_dict['subset_lat'])
        lon0, lon1 = sorted(subset_dict['subset_lon'])
        pix_box_geo = lalo_box_to_pix_box_from_hdfeos_geometry(fname, lat0, lat1, lon0, lon1)
        if pix_box_geo is not None:
            subset_dict['subset_x'] = [pix_box_geo[0], pix_box_geo[2]]
            subset_dict['subset_y'] = [pix_box_geo[1], pix_box_geo[3]]
            subset_dict['subset_lat'] = None
            subset_dict['subset_lon'] = None
            print('convert bounding box in lat/lon to y/x (from HDFEOS geometry)')
            print(f'input bounding box in lat/lon: ({lon0}, {lat1}, {lon1}, {lat0})')
            print(f'box to read for datasets in y/x: {pix_box_geo}')

    pix_box, geo_box = subset_input_dict2box(subset_dict, atr)
    coord = ut.coordinate(atr)
    if not outfill:
        pix_box = coord.check_box_within_data_coverage(pix_box)
        subset_dict['fill_value'] = np.nan
    geo_box = coord.box_pixel2geo(pix_box)
    data_box = (0, 0, width, length)
    print(f'data   range in (x0,y0,x1,y1): {data_box}')
    print(f'subset range in (x0,y0,x1,y1): {pix_box}')
    print(f'data   range in (W, N, E, S): {coord.box_pixel2geo(data_box)}')
    print(f'subset range in (W, N, E, S): {geo_box}')

    if pix_box == data_box:
        print('Subset range == data coverage, no need to subset. Skip.')
        return fname

    pix_box4data, pix_box4subset = get_box_overlap_index(data_box, pix_box)

    # Output file name
    if not out_file:
        if os.getcwd() == os.path.dirname(os.path.abspath(fname)):
            out_file = 'sub_' + os.path.basename(fname)
        else:
            out_file = os.path.basename(fname)
    print('writing >>> ' + out_file)

    atr = attr.update_attribute4subset(atr, pix_box)
    sub_length = int(atr['LENGTH'])
    sub_width = int(atr['WIDTH'])

    # Update all size-related attributes (update_attribute4subset only does LENGTH, WIDTH)
    atr['FILE_LENGTH'] = str(sub_length)
    atr['length'] = str(sub_length)
    atr['width'] = str(sub_width)

    # If reference point (REF_Y, REF_X) falls outside the subset, set a new one near
    # center that is valid (mask != 0) so viewers (e.g. tsview.py) do not crash.
    ref_y = atr.get('REF_Y')
    ref_x = atr.get('REF_X')
    need_new_ref = False
    if ref_y is not None and ref_x is not None:
        try:
            ry, rx = int(ref_y), int(ref_x)
            if not (0 <= ry < sub_length and 0 <= rx < sub_width):
                need_new_ref = True
        except (ValueError, TypeError):
            need_new_ref = True

    if need_new_ref:
        # Use valid pixel closest to subset center as new reference (mask != 0)
        new_ry, new_rx = _find_valid_ref_in_subset(
            fname,
            pix_box4data,
            pix_box4subset,
            sub_length,
            sub_width,
        )
        if new_ry is not None and new_rx is not None:
            atr['REF_Y'] = str(new_ry)
            atr['REF_X'] = str(new_rx)
            # Set REF_LAT/REF_LON for the new ref from geometry (never keep old full-scene values)
            for k in ['REF_LAT', 'REF_LON']:
                if k in atr:
                    del atr[k]
            ref_lat, ref_lon = _get_ref_latlon_from_geometry(fname, new_ry, new_rx, pix_box)
            if ref_lat is not None and ref_lon is not None:
                atr['REF_LAT'] = str(ref_lat)
                atr['REF_LON'] = str(ref_lon)
            print(f'reference point outside subset; set to valid pixel near center: ({new_ry}, {new_rx})')
        else:
            if ref_y is not None and ref_x is not None:
                for k in ['REF_Y', 'REF_X', 'REF_LAT', 'REF_LON']:
                    if k in atr:
                        del atr[k]
            print('reference point outside subset; no valid mask pixel found, removed from metadata')

    # Update all REF and corner metadata for the subset (viewers use REF_LAT/LON and LAT/LON_REF1-4)
    atr = _update_subset_ref_and_corner_metadata(atr, geo_box)
    if 'REF_LAT' in atr and 'REF_LON' in atr:
        print('update REF_LAT/REF_LON')

    # If REF_LAT/REF_LON still missing (e.g. formula skipped due to type/bytes), set from geometry
    if ('REF_Y' in atr and 'REF_X' in atr and
            ('REF_LAT' not in atr or 'REF_LON' not in atr)):
        ref_lat, ref_lon = _get_ref_latlon_from_geometry(
            fname, atr['REF_Y'], atr['REF_X'], pix_box
        )
        if ref_lat is not None and ref_lon is not None:
            atr['REF_LAT'] = str(ref_lat)
            atr['REF_LON'] = str(ref_lon)
            print('update REF_LAT/REF_LON (from geometry)')

    # Do not write Y_FIRST/X_FIRST/Y_STEP/X_STEP when original is not geocoded (radar).
    if not original_has_geo:
        for key in ['Y_FIRST', 'X_FIRST', 'Y_STEP', 'X_STEP']:
            if key in atr:
                del atr[key]

    with h5py.File(fname, 'r') as fi, h5py.File(out_file, 'w') as fo:
        # Copy root attributes (updated)
        for key, value in atr.items():
            try:
                fo.attrs[key] = value if not isinstance(value, str) else str(value)
            except TypeError:
                fo.attrs[key] = str(value)

        base = 'HDFEOS/GRIDS/timeseries'
        for group_name in ['observation', 'quality', 'geometry']:
            gpath = f'{base}/{group_name}'
            if gpath not in fi:
                continue
            gi = fi[gpath]
            fo.create_group(gpath)
            go = fo[gpath]

            for dname in gi.keys():
                ds = gi[dname]
                if not isinstance(ds, h5py.Dataset):
                    continue
                shape = ds.shape
                ndim = ds.ndim

                if ndim == 1:
                    go.create_dataset(dname, data=ds[:], compression='lzf')
                    continue

                if ndim == 2:
                    data = ds[
                        pix_box4data[1]:pix_box4data[3],
                        pix_box4data[0]:pix_box4data[2],
                    ]
                    out = np.ones((sub_length, sub_width), dtype=ds.dtype) * np.nan
                    out[
                        pix_box4subset[1]:pix_box4subset[3],
                        pix_box4subset[0]:pix_box4subset[2],
                    ] = data
                    go.create_dataset(dname, data=out, compression='lzf')
                    for k, v in ds.attrs.items():
                        go[dname].attrs[k] = v
                    continue

                if ndim == 3:
                    nslice = shape[0]
                    out = np.ones(
                        (nslice, sub_length, sub_width),
                        dtype=ds.dtype,
                    ) * np.nan
                    for i in range(nslice):
                        data = ds[
                            i,
                            pix_box4data[1]:pix_box4data[3],
                            pix_box4data[0]:pix_box4data[2],
                        ]
                        out[
                            i,
                            pix_box4subset[1]:pix_box4subset[3],
                            pix_box4subset[0]:pix_box4subset[2],
                        ] = data
                    go.create_dataset(dname, data=out, compression='lzf')
                    for k, v in ds.attrs.items():
                        go[dname].attrs[k] = v
                    continue

    print(f'finished writing to {out_file}')
    return out_file


################################################################
# CLI: add --subset-lalo and dispatch HDFEOS vs standard subset
################################################################

def read_aux_subset2inps_hdfeos(inps):
    """Fill subset_y/x/lat/lon from ref/template/--subset-lalo/--lookup, like read_aux_subset2inps."""
    subset_lalo = getattr(inps, 'subset_lalo', None)
    if subset_lalo:
        inps.subset_lat, inps.subset_lon = parse_subset_lalo(subset_lalo)
        inps.subset_x = None
        inps.subset_y = None

    if all(
        not i
        for i in [
            getattr(inps, 'subset_x', None),
            getattr(inps, 'subset_y', None),
            getattr(inps, 'subset_lat', None),
            getattr(inps, 'subset_lon', None),
        ]
    ):
        if inps.reference:
            ref_atr = readfile.read_attribute(inps.reference)
            pix_box, geo_box = get_coverage_box(ref_atr)
            print('using subset info from ' + inps.reference)
        elif inps.template_file:
            pix_box, geo_box = read_subset_template2box(inps.template_file)
            print('using subset info from ' + inps.template_file)
        else:
            raise Exception('No subset inputs found. Use --subset-lalo=lat_min:lat_max,lon_min:lon_max or -l/-L or -x/-y or -r or -t.')
        inps = subset_box2inps(inps, pix_box, geo_box)
        return inps

    # HDFEOS/radar with lat/lon: use lookup if provided to match geometryRadar subset exactly
    lookup_file = getattr(inps, 'lookup_file', None)
    if lookup_file:
        lookup_file = ut.get_lookup_file(lookup_file)
    if (lookup_file and inps.file
            and getattr(inps, 'subset_lat', None) and getattr(inps, 'subset_lon', None)
            and not getattr(inps, 'subset_x', None) and not getattr(inps, 'subset_y', None)):
        atr = readfile.read_attribute(inps.file[0])
        if atr.get('FILE_TYPE') == 'HDFEOS' and 'Y_FIRST' not in atr:
            if not os.path.isfile(lookup_file):
                raise FileNotFoundError(f'lookup file {lookup_file} NOT found!')
            geo_box = (inps.subset_lon[0], inps.subset_lat[1],
                       inps.subset_lon[1], inps.subset_lat[0])
            coord = ut.coordinate(atr, lookup_file=lookup_file)
            pix_box = coord.bbox_geo2radar(geo_box, buf=0)
            pix_box = coord.check_box_within_data_coverage(pix_box)
            print('convert bounding box in lat/lon to y/x')
            print(f'input bounding box in lat/lon: {geo_box}')
            print(f'box to read for datasets in y/x: {pix_box}')
            inps.subset_x = [pix_box[0], pix_box[2]]
            inps.subset_y = [pix_box[1], pix_box[3]]
            inps.subset_lat = None
            inps.subset_lon = None
    return inps


def subset_file_or_hdfeos(fname, subset_dict_input, out_file=None):
    """Subset file: use HDFEOS path if FILE_TYPE is HDFEOS, else MintPy subset_file."""
    atr = readfile.read_attribute(fname)
    if atr.get('FILE_TYPE') == 'HDFEOS':
        return subset_file_hdfeos(fname, subset_dict_input, out_file=out_file)
    from mintpy.subset import subset_file
    return subset_file(fname, subset_dict_input, out_file=out_file)


def create_parser(subparsers=None):
    """CLI parser with MintPy subset options plus --subset-lalo."""
    from mintpy.utils.arg_utils import create_argument_parser
    synopsis = 'Subset file(s), including HDFEOS5 (e.g. from save_hdfeos5). Uses geometry in file; errors if missing.'
    epilog = """
Examples:
  subset.py S1_desc_120_142_mintpy_20141025_XXXXXXXX.he5 --subset-lalo=30.5:31.0,130.0:131.0
  subset.py file.he5 -l 30.5 31.0 -L 130.0 131.0
  subset.py file.he5 -y 0 500 -x 0 400
  subset.py file.he5 -r reference.h5
  subset.py file.he5 -t template.txt
  subset.py file.he5 geometryRadar.h5 --lookup geometryRadar.h5 -l 36.60 36.61 -L 24.90 24.92
"""
    name = __name__.split('.')[-1] if '__name__' in dir() else 'subset'
    parser = create_argument_parser(
        name, synopsis=synopsis, description=synopsis, epilog=epilog, subparsers=subparsers
    )
    parser.add_argument('file', nargs='+', help='File(s) to subset')
    parser.add_argument(
        '--subset-lalo',
        dest='subset_lalo',
        type=str,
        default=None,
        help='Subset in lat/lon: lat_min:lat_max,lon_min:lon_max (e.g. 30.5:31.0,130.0:131.0)',
    )
    parser.add_argument('-x', '--sub-x', '--subset-x', dest='subset_x', type=int, nargs=2, help='subset range in x')
    parser.add_argument('-y', '--sub-y', '--subset-y', dest='subset_y', type=int, nargs=2, help='subset range in y')
    parser.add_argument('-l', '--lat', '--sub-lat', '--subset-lat', dest='subset_lat', type=float, nargs=2, help='subset range in latitude')
    parser.add_argument('-L', '--lon', '--sub-lon', '--subset-lon', dest='subset_lon', type=float, nargs=2, help='subset range in longitude')
    parser.add_argument('-t', '--template', dest='template_file', help='template file with subset setting')
    parser.add_argument('-r', '--reference', help='reference file, subset to same coverage')
    parser.add_argument('--outfill', dest='fill_value', type=float, help='fill value for area outside data coverage')
    parser.add_argument('-o', '--output', dest='outfile', help='output file name')
    parser.add_argument(
        '--lookup',
        dest='lookup_file',
        help='lookup file (e.g. geometryRadar.h5) to convert lat/lon to pixel for radar-coded files',
    )
    return parser


def main(iargs=None):
    import sys
    parser = create_parser()
    inps = parser.parse_args(args=iargs)

    from mintpy.utils import utils1 as ut
    flist = ut.get_file_list(inps.file)
    if not flist:
        raise FileNotFoundError(f'No file found: {inps.file}')
    inps.file = flist
    if len(inps.file) > 1 and inps.outfile:
        inps.outfile = None
        print('WARNING: --output disabled for multiple input files.')

    inps = read_aux_subset2inps_hdfeos(inps)

    subset_dict = {
        'subset_x': inps.subset_x,
        'subset_y': inps.subset_y,
        'subset_lat': inps.subset_lat,
        'subset_lon': inps.subset_lon,
        'fill_value': getattr(inps, 'fill_value', None),
    }
    for fname in inps.file:
        print('-' * 30)
        subset_file_or_hdfeos(fname, subset_dict, out_file=inps.outfile)


if __name__ == '__main__':
    import sys
    main(sys.argv[1:])
