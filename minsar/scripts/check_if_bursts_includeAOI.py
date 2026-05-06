#!/usr/bin/env python3
"""Per acquisition date (YYYYMMDD in filename): test whether burst GeoTIFF footprints cover AOI.

Writes ``dates_not_including_AOI.txt`` in the common parent directory of the matched TIFFs:

    check_if_bursts_includeAOI.py -8.302:-8.235,123.491:123.543 'SLC/*.tif*'

One line per date that fails: ``YYYYMMDD``. No CLI flags except ``--help`` / ``-h``.
Uses a small fixed epsilon in WGS84 for footprint union vs AOI (covers)."""

from __future__ import annotations

import glob as glob_lib
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import DefaultDict, List, Optional, Sequence, Tuple

try:
    from shapely.geometry import Polygon
    from shapely.geometry.base import BaseGeometry
    from shapely.ops import unary_union
except ImportError:
    raise SystemExit('check_if_bursts_includeAOI.py requires shapely.') from None

try:
    from shapely.validation import make_valid as shapely_make_valid
except ImportError:

    def shapely_make_valid(g: BaseGeometry) -> BaseGeometry:
        return g.buffer(0) if hasattr(g, 'buffer') and not g.is_valid else g


# Small tolerance in degrees for geometric robustness (reprojection / rounding slivers).
# 5e-5 deg is ~5.5 m in latitude; enough to absorb numerical edges but not true AOI gaps.
_EPS_DEG = 5e-5

DATES_NOT_INCLUDING_AOI_LOG = 'dates_not_including_AOI.txt'

_BURST_ACQ_DATE_RE = re.compile(r'(\d{8})T\d{6}')


def _repair(geom: BaseGeometry) -> BaseGeometry:
    if geom.is_empty:
        return geom
    if geom.is_valid:
        return geom
    try:
        fixed = shapely_make_valid(geom)
        if fixed.is_empty and hasattr(geom, 'buffer'):
            return geom.buffer(0)
        return fixed if not fixed.is_empty else geom.buffer(0)
    except Exception:
        return geom.buffer(0) if hasattr(geom, 'buffer') else geom


def bbox_sn_we_to_polygon(bbox_sn_we: str) -> Polygon:
    s = bbox_sn_we.strip()
    if ',' not in s:
        raise ValueError('BBox must contain comma between lat bounds and lon bounds.')
    lat_side, lon_side = s.split(',', 1)
    if ':' not in lat_side or ':' not in lon_side:
        raise ValueError('Each side must be min:max, e.g. -8.3:-8.23,123.49:123.54')
    lat0, lat1 = map(float, lat_side.split(':', 1))
    lon0, lon1 = map(float, lon_side.split(':', 1))
    s_lat, n_lat = min(lat0, lat1), max(lat0, lat1)
    w_lon, e_lon = min(lon0, lon1), max(lon0, lon1)
    ring = [(w_lon, s_lat), (e_lon, s_lat), (e_lon, n_lat), (w_lon, n_lat), (w_lon, s_lat)]
    return _repair(Polygon(ring))


def _try_import_rasterio():
    try:
        import rasterio

        return rasterio
    except ImportError:
        return None


def _footprint_polygon_rasterio(path: Path) -> Polygon:
    import rasterio
    from rasterio.warp import transform_bounds

    with rasterio.open(path) as src:
        # Use dataset outer bounds (not pixel-center coordinates) to avoid
        # shrinking footprint by ~1 pixel in each direction.
        left, bottom, right, top = transform_bounds(src.crs, 'EPSG:4326', *src.bounds)
        ring = [(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)]
        return _repair(Polygon(ring))


def _footprint_polygon_gdal(path: Path) -> Polygon:
    from osgeo import gdal, osr

    gdal.UseExceptions()
    ds = gdal.Open(str(path), gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f'GDAL cannot open {path}')
    try:
        w, h = ds.RasterXSize, ds.RasterYSize
        gt = ds.GetGeoTransform()
        srs = ds.GetSpatialRef()
        proj = ds.GetProjectionRef()
        tgt = osr.SpatialReference()
        tgt.ImportFromEPSG(4326)
        # GDAL3+ may default EPSG:4326 to latitude/longitude axis order.
        # Force traditional GIS order (lon, lat) to match bbox and Shapely conventions.
        if hasattr(osr, 'OAMS_TRADITIONAL_GIS_ORDER'):
            try:
                if srs is not None:
                    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                tgt.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            except Exception:
                pass

        # Compute outer raster bounds in source CRS from geotransform and size.
        # Using (w,h) corners (not w-1,h-1) captures full pixel extent.
        src_corners = [(0.0, 0.0), (float(w), 0.0), (float(w), float(h)), (0.0, float(h))]
        xy_src = [
            (
                gt[0] + col * gt[1] + row * gt[2],
                gt[3] + col * gt[4] + row * gt[5],
            )
            for col, row in src_corners
        ]
        ct = osr.CoordinateTransformation(srs, tgt) if srs is not None else None
        if ct is None:
            ring = [(float(x), float(y)) for x, y in xy_src]
        else:
            ring = []
            for x, y in xy_src:
                lo, la, _ = ct.TransformPoint(float(x), float(y))
                ring.append((float(lo), float(la)))
        ring.append(ring[0])
        return _repair(Polygon(ring))
    finally:
        ds = None


def footprint_polygon_geotiff(path: Path) -> Polygon:
    if _try_import_rasterio():
        try:
            return _footprint_polygon_rasterio(path)
        except Exception:
            pass
    fp = _footprint_polygon_gdal(path)
    # If bounds are clearly not lon/lat geographic, try companion XML footprint fallback.
    minx, miny, maxx, maxy = fp.bounds
    non_geo = (maxx > 360.0 or minx < -360.0 or maxy > 90.0 or miny < -90.0)
    if non_geo:
        xml_fp = _footprint_from_companion_xml(path)
        if xml_fp is not None:
            return xml_fp
    return fp


def _xml_candidates_for_tiff(path: Path) -> List[Path]:
    stem = path.name
    # Example burst tif: ..._56F3-BURST.tiff  -> token 56F3
    m = re.search(r'_([A-Za-z0-9]{4})-BURST\.tif{1,2}$', stem, re.IGNORECASE)
    cands: List[Path] = []
    if m:
        tok = m.group(1)
        cands.extend(sorted(path.parent.glob(f'*_{tok}_*.xml')))
    if not cands:
        cands.extend(sorted(path.parent.glob('*.xml')))
    return cands


def _polygon_from_gml_coordinates(text: str) -> Optional[Polygon]:
    # Expected order in Sentinel burst xml appears to be lat,lon pairs separated by spaces.
    pts: List[Tuple[float, float]] = []
    for pair in text.strip().split():
        if ',' not in pair:
            continue
        a, b = pair.split(',', 1)
        lat = float(a)
        lon = float(b)
        pts.append((lon, lat))
    if len(pts) < 3:
        return None
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return _repair(Polygon(pts))


def _polygon_from_latlon_grid(root: ET.Element) -> Optional[Polygon]:
    lats: List[float] = []
    lons: List[float] = []
    for el in root.iter():
        t = el.tag.lower()
        txt = (el.text or '').strip()
        if not txt:
            continue
        if t.endswith('latitude') or t == 'latitude':
            try:
                lats.append(float(txt))
            except Exception:
                pass
        elif t.endswith('longitude') or t == 'longitude':
            try:
                lons.append(float(txt))
            except Exception:
                pass
    if not lats or not lons:
        return None
    w, e = min(lons), max(lons)
    s, n = min(lats), max(lats)
    ring = [(w, s), (e, s), (e, n), (w, n), (w, s)]
    return _repair(Polygon(ring))


def _footprint_from_companion_xml(path: Path) -> Optional[Polygon]:
    for xml_path in _xml_candidates_for_tiff(path):
        try:
            root = ET.parse(xml_path).getroot()
            for el in root.iter():
                if el.tag.lower().endswith('coordinates'):
                    txt = (el.text or '').strip()
                    if txt:
                        poly = _polygon_from_gml_coordinates(txt)
                        if poly is not None and not poly.is_empty:
                            return poly
            poly2 = _polygon_from_latlon_grid(root)
            if poly2 is not None and not poly2.is_empty:
                return poly2
        except Exception:
            continue
    return None


def union_covers_aoi(
    footprints: Sequence[BaseGeometry],
    aoi: BaseGeometry,
) -> Tuple[bool, BaseGeometry]:
    if not footprints:
        return False, Polygon()
    merged = unary_union(list(footprints))
    buffered = merged.buffer(_EPS_DEG)
    aoi_eff = _repair(aoi)
    try:
        if buffered.covers(aoi_eff):
            return True, merged
    except Exception:
        pass
    try:
        return aoi_eff.difference(buffered).is_empty, merged
    except Exception:
        return False, merged


def uncovered_residual(aoi: BaseGeometry, merged: BaseGeometry) -> BaseGeometry:
    """Residual AOI not covered by merged footprints (with epsilon buffer)."""
    try:
        return _repair(aoi).difference(_repair(merged).buffer(_EPS_DEG))
    except Exception:
        try:
            return _repair(aoi).difference(_repair(merged))
        except Exception:
            return Polygon()


def expand_path_specs(paths: Sequence[str]) -> List[Path]:
    collected: List[Path] = []
    for spec in paths:
        expanded = sorted(glob_lib.glob(spec))
        if expanded:
            for m in expanded:
                pth = Path(m)
                if pth.is_file():
                    collected.append(pth.resolve())
        else:
            pth = Path(spec)
            if pth.is_file():
                collected.append(pth.resolve())

    return sorted({str(p): p for p in collected}.values(), key=str)


def filter_geotiff_paths(paths: Sequence[Path]) -> List[Path]:
    out = [p for p in paths if p.suffix.lower() in ('.tif', '.tiff')]
    return sorted(set(out), key=str)


def acquisition_date_yyyymmdd_from_burst_filename(name: str) -> Optional[str]:
    m = _BURST_ACQ_DATE_RE.search(name)
    return m.group(1) if m else None


def _common_parent_dir(paths: Sequence[Path]) -> Path:
    if not paths:
        return Path.cwd()
    parents = [p.parent.resolve() for p in paths]
    try:
        return Path(os.path.commonpath([str(p) for p in parents]))
    except ValueError:
        return parents[0]


USAGE = '''Usage:
  check_if_bursts_includeAOI.py LAT_S:LAT_N,LON_W:LON_E GLOB_OR_FILE [GLOB_OR_FILE ...]

Example:
  check_if_bursts_includeAOI.py -8.302:-8.235,123.491:123.543 'SLC/*.tif*'

Writes dates_not_including_AOI.txt in the directory holding the TIFFs (one YYYYMMDD per line
for acquisitions whose footprint union does not fully cover the bbox AOI).'''


def _looks_like_negative_number(tok: str) -> bool:
    """True if token resembles a bbox lat/lon numeric token (starts with -.digit or -.)."""
    if not tok.startswith('-') or tok == '-':
        return False
    rest = tok[1:]
    if not rest:
        return False
    return rest[0].isdigit() or rest[0] == '.'


def _looks_like_bad_cli_flag(tok: str) -> bool:
    if not tok.startswith('-'):
        return False
    if _looks_like_negative_number(tok):
        return False
    if tok.startswith('--'):
        return True
    # short flag -x (reject); allow lone negative-number-looking handled above
    return len(tok) >= 2 and tok[1].isalpha()


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print(USAGE)
        return 2

    if argv[0] in ('-h', '--help'):
        print(USAGE)
        return 0

    for tok in argv:
        if _looks_like_bad_cli_flag(tok):
            print(f'ERROR: no options accepted (got {tok!r}).\n', file=sys.stderr)
            print(USAGE, file=sys.stderr)
            return 2

    if len(argv) < 2:
        print('ERROR: need LAT_S:LAT_N,LON_W:LON_E and at least one .tif/.tiff glob or path.', file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2

    bbox_token, *path_tokens = argv
    try:
        aoi = bbox_sn_we_to_polygon(bbox_token)
    except Exception as exc:
        print(f'ERROR: bbox parse failed ({bbox_token!r}): {exc}', file=sys.stderr)
        return 2

    raw_paths = expand_path_specs(path_tokens)
    tifs = filter_geotiff_paths(raw_paths)
    if not tifs:
        print(
            f'ERROR: no .tif/.tiff matched {path_tokens!r} '
            f'({len(raw_paths)} non-tiff paths ignored).',
            file=sys.stderr,
        )
        return 2

    by_date: DefaultDict[str, List[Path]] = defaultdict(list)
    undated: List[Path] = []
    for pth in tifs:
        dk = acquisition_date_yyyymmdd_from_burst_filename(pth.name)
        if dk is None:
            undated.append(pth)
            continue
        by_date[dk].append(pth)

    if undated:
        print(
            f'WARN: {len(undated)} GeoTIFF(s) have no YYYYMMDDT###### in filename; skipping: '
            f'{", ".join(p.name for p in undated[:8])}',
            file=sys.stderr,
        )

    bad_dates: List[str] = []
    for ymd in sorted(by_date.keys()):
        chunk = sorted(by_date[ymd])
        footprints: List[BaseGeometry] = []
        for pth in chunk:
            try:
                fp = footprint_polygon_geotiff(pth)
                footprints.append(fp)
            except Exception:
                continue
        if not footprints:
            bad_dates.append(ymd)
            print(
                f'WARN {ymd}: no readable GeoTIFF footprints from {len(chunk)} file(s); marking as not covered.',
                file=sys.stderr,
            )
            continue
        ok, merged = union_covers_aoi(footprints, aoi)
        if not ok:
            bad_dates.append(ymd)
            residual = uncovered_residual(aoi, merged)
            try:
                r_area = residual.area if hasattr(residual, 'area') else None
            except Exception:
                r_area = None
            r_bounds = None
            try:
                if not residual.is_empty:
                    r_bounds = residual.bounds
            except Exception:
                r_bounds = None
            print(
                f'WARN {ymd}: AOI not fully covered. '
                f'merged_bounds={getattr(merged, "bounds", None)} '
                f'uncovered_area_deg2={r_area} '
                f'uncovered_bounds={r_bounds} '
                f'n_tifs={len(chunk)}',
                file=sys.stderr,
            )

    out_dir = _common_parent_dir(tifs)
    log_path = out_dir / DATES_NOT_INCLUDING_AOI_LOG

    payload = ''.join(d + '\n' for d in sorted(bad_dates))
    log_path.write_text(payload, encoding='utf-8')

    if bad_dates:
        print(
            f'Wrote {log_path}: {len(bad_dates)} acquisition date(s) do not fully cover AOI.',
            file=sys.stderr,
        )
    else:
        print(f'Wrote {log_path}: (empty) all grouped dates cover bbox AOI.', file=sys.stderr)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
