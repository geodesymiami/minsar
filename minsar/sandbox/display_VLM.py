#!/usr/bin/env python3
"""Plot airport VLM CSV points with MintPy view.py-compatible options."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from mintpy import view as mintpy_view
from mintpy.utils import arg_utils, plot as pp, readfile

EXAMPLE = """Examples:
  display_VLM.py MIA_VLM.csv --sub-lat 25.78 25.81 --sub-lon -80.31 -80.265 --ref-lalo 25.81018 -80.28961 --vlim -0.5 0.5 --style scatter --scatter-size 1 --add-basemap
  display_VLM.py MIA_VLM.csv --sub-lat 25.78 25.81 --sub-lon -80.31 -80.265 --ref-lalo 25.808 -80.28961 --vlim -0.5 0.5 --style scatter --scatter-size 10 --mask geo_polygon_mask.h5
  display_VLM.py MIA_VLM.csv --style scatter --no-display -o MIA_VLM.png
  display_VLM.py MIA_VLM.csv --notick --no-display -o MIA_VLM.png
  display_VLM.py MIA_VLM.csv --nowhitespace --no-display -o MIA_VLM.png
"""


def create_parser(subparsers=None):
    synopsis = "Plot VLM CSV samples in geo-coordinates (view.py-compatible options)."
    name = "display_VLM"
    parser = arg_utils.create_argument_parser(
        name,
        synopsis=synopsis,
        description=synopsis,
        epilog=EXAMPLE,
        subparsers=subparsers,
    )

    infile = parser.add_argument_group("Input File", "VLM CSV to display")
    infile.add_argument("file", type=str, help="VLM CSV (Longitude, Latitude, VLM in cm/yr)")
    infile.add_argument(
        "dset",
        type=str,
        nargs="*",
        default=[],
        help="ignored (view.py compatibility)",
    )

    parser.add_argument(
        "--noverbose",
        "--no-verbose",
        dest="print_msg",
        action="store_false",
        help="Disable verbose messages (default: print).",
    )

    parser = arg_utils.add_data_disp_argument(parser)
    parser = arg_utils.add_dem_argument(parser)
    parser = arg_utils.add_figure_argument(parser)
    parser = arg_utils.add_gnss_argument(parser)
    parser = arg_utils.add_mask_argument(parser)
    parser = arg_utils.add_map_argument(parser)
    from mintpy.utils.web_basemap import BASEMAP_CHOICES

    map_groups = [g for g in parser._action_groups if g.title == "Map"]
    if map_groups:
        mapg = map_groups[0]
        mapg.add_argument(
            "--add-basemap",
            dest="basemap",
            nargs="?",
            const="esri_satellite",
            default=None,
            choices=BASEMAP_CHOICES,
            metavar="PROVIDER",
            help="Opt-in web tile basemap. (choices: %(choices)s; default: esri_satellite).",
        )
        mapg.add_argument(
            "--basemap-alpha",
            dest="basemap_alpha",
            metavar="BASEMAP_ALPHA",
            type=float,
            default=1.0,
            help="Basemap opacity, between 0 and 1 (default: %(default)g).",
        )
    parser = arg_utils.add_memory_argument(parser)
    parser = arg_utils.add_point_argument(parser)
    parser = arg_utils.add_shape_argument(parser)
    parser = arg_utils.add_reference_argument(parser)
    parser = arg_utils.add_save_argument(parser)
    parser = arg_utils.add_subset_argument(parser)
    parser.add_argument(
        "--geo-grid",
        dest="geo_grid_file",
        default=None,
        metavar="FILE",
        help="Geocoded .h5 for view.py subset geo_box (figure size and map extent).",
    )
    parser.add_argument(
        "--no-display",
        dest="disp_fig",
        action="store_false",
        help="Save figure only; do not open an interactive window (same as --nodisplay).",
    )
    return parser


def cmd_line_parse(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    inps.argv = iargs or sys.argv[1:]

    if not os.path.isfile(inps.file):
        raise FileNotFoundError(f"input file {inps.file} NOT exist!")

    if not inps.save_fig and (inps.outfile or not inps.disp_fig):
        inps.save_fig = True

    if inps.lalo_step:
        inps.lalo_label = True

    # Same coupled options as mintpy/cli/view.py cmd_line_parse
    if not inps.disp_whitespace:
        inps.disp_axis = False
        inps.disp_title = False
        inps.disp_cbar = False

    if not inps.disp_axis:
        inps.disp_tick = False

    if inps.flip_lr or inps.flip_ud:
        inps.auto_flip = False

    if inps.basemap is not None:
        alpha = inps.basemap_alpha
        if alpha < 0 or alpha > 1:
            parser.error("--basemap-alpha must be between 0 and 1.")
    if inps.basemap == "mapbox":
        from mintpy.utils.web_basemap import mapbox_access_token, warn_mapbox_token_missing

        if not mapbox_access_token():
            warn_mapbox_token_missing(print_msg=True)

    if inps.zero_mask and not inps.mask_file:
        inps.mask_file = "no"

    if not inps.transparency:
        inps.transparency = 1.0

    if inps.style != "scatter":
        parser.error("display_VLM.py supports --style scatter only (CSV point data).")

    if inps.dset and inps.print_msg:
        print("WARNING: dataset name(s) ignored for VLM CSV input.")

    mask_file = getattr(inps, "mask_file", None)
    if mask_file not in (None, "no", "") and not os.path.isfile(mask_file):
        raise FileNotFoundError(f"input mask_file {mask_file} NOT exist!")

    for opt in ("dem_file", "disp_gnss", "pts_file"):
        val = getattr(inps, opt, None)
        if val not in (None, "no", False) and inps.print_msg:
            print(f"WARNING: {opt} is not used for VLM CSV display; ignored.")

    return inps


def vlm_disp_unit_from_headers(columns: list[str]) -> str | None:
    """Parse display unit from the VLM column header (e.g. 'VLM (in IGS14 cm/yr)')."""
    for col in columns:
        low = col.lower()
        if "vlm" not in low or "std" in low:
            continue
        m = re.search(r"\(([^)]+)\)", col)
        text = m.group(1) if m else col
        um = re.search(r"(cm|mm|m)\s*/\s*(yr|year)", text, flags=re.I)
        if um:
            u = um.group(1).lower()
            t = um.group(2).lower()
            return f"{u}/{'year' if t.startswith('year') else 'yr'}"
        um = re.search(r"(cm|mm|m)\s*/\s*(yr|year)", col, flags=re.I)
        if um:
            u = um.group(1).lower()
            t = um.group(2).lower()
            return f"{u}/{'year' if t.startswith('year') else 'yr'}"
    return None


def read_vlm_csv(csv_path: Path) -> tuple[pd.DataFrame, str | None]:
    df = pd.read_csv(csv_path)
    raw_columns = [c.strip() for c in df.columns]
    disp_unit = vlm_disp_unit_from_headers(raw_columns)
    df.columns = raw_columns
    rename = {}
    for col in df.columns:
        low = col.lower()
        if low == "longitude":
            rename[col] = "lon"
        elif low == "latitude":
            rename[col] = "lat"
        elif "vlm" in low and "std" not in low:
            rename[col] = "vlm"
        elif "std" in low:
            rename[col] = "vlm_std"
    df = df.rename(columns=rename)
    if "lon" not in df.columns or "lat" not in df.columns or "vlm" not in df.columns:
        raise ValueError(f"{csv_path}: expected Longitude, Latitude, and VLM columns (got {list(df.columns)})")
    df = df.dropna(subset=["lon", "lat", "vlm"])
    df = df[np.isfinite(df["lon"]) & np.isfinite(df["lat"]) & np.isfinite(df["vlm"])]
    return df, disp_unit


def subset_dataframe(df: pd.DataFrame, inps) -> pd.DataFrame:
    out = df
    if inps.subset_lat is not None:
        lat_min, lat_max = sorted(inps.subset_lat)
        out = out[(out["lat"] >= lat_min) & (out["lat"] <= lat_max)]
    if inps.subset_lon is not None:
        lon_min, lon_max = sorted(inps.subset_lon)
        out = out[(out["lon"] >= lon_min) & (out["lon"] <= lon_max)]
    return out


def geo_limits(inps, lon: np.ndarray, lat: np.ndarray) -> tuple[tuple[float, float], tuple[float, float]]:
    if inps.subset_lon is not None:
        xlim = tuple(sorted(inps.subset_lon))
    else:
        pad = max(0.0005, 0.02 * (float(lon.max()) - float(lon.min())))
        xlim = (float(lon.min()) - pad, float(lon.max()) + pad)
    if inps.subset_lat is not None:
        ylim = tuple(sorted(inps.subset_lat))
    else:
        pad = max(0.0005, 0.02 * (float(lat.max()) - float(lat.min())))
        ylim = (float(lat.min()) - pad, float(lat.max()) + pad)
    return xlim, ylim


def clean_plot_title(title: str) -> str:
    """Short title: RUN velocity.h5 (drop network_* dirs from path)."""
    p = Path(title)
    if p.suffix.lower() == ".csv":
        return p.name
    parts = p.resolve().parts
    run = next((x for x in parts if x.startswith("miaplpy_") or x.startswith("mintpy_")), None)
    if run:
        return f"{run} {p.name}"
    parent = p.parent.name
    if parent.startswith("network_"):
        parent = p.parent.parent.name
    return f"{parent} {p.name}" if parent else title


def geo_box_from_limits(xlim: tuple[float, float], ylim: tuple[float, float]) -> list[float]:
    """MintPy geo_box layout: [W, N, E, S] (same as view.py subset coverage)."""
    west, east = xlim
    south, north = ylim
    return [west, north, east, south]


def view_geo_box(inps, xlim: tuple[float, float], ylim: tuple[float, float]) -> list[float]:
    """Pixel-aligned [W, N, E, S] using the same subset logic as view.py."""
    from mintpy import subset
    from mintpy.utils import readfile, utils as ut

    for candidate in (getattr(inps, "geo_grid_file", None), getattr(inps, "mask_file", None)):
        if candidate in (None, "no", "") or not os.path.isfile(candidate):
            continue
        atr = readfile.read_attribute(candidate)
        if "Y_FIRST" not in atr:
            continue
        pix_box, _geo = subset.subset_input_dict2box(vars(inps), atr)
        coord = ut.coordinate(atr)
        pix_box = coord.check_box_within_data_coverage(pix_box)
        return list(coord.box_pixel2geo(pix_box))
    return geo_box_from_limits(xlim, ylim)


def _geocoded_grid_file(inps) -> str | None:
    for candidate in (getattr(inps, "geo_grid_file", None), getattr(inps, "mask_file", None)):
        if candidate in (None, "no", "") or not os.path.isfile(candidate):
            continue
        atr = readfile.read_attribute(candidate)
        if "Y_FIRST" in atr:
            return candidate
    return None


def _colormap_object(inps) -> None:
    cmap_name = inps.colormap if inps.colormap else "jet"
    if isinstance(cmap_name, str):
        inps.colormap = pp.ColormapExt(
            cmap_name,
            cmap_lut=inps.cmap_lut,
            vlist=inps.cmap_vlist,
        ).colormap


def geo_velocity_dlim_for_colorbar(inps, grid_file: str) -> tuple[float, float] | None:
    """Data min/max on the geo velocity grid (same as view.py for colorbar extend arrows)."""
    if not grid_file or not os.path.isfile(grid_file):
        return None
    pix_box = getattr(inps, "pix_box", None)
    if not pix_box:
        return None

    data = readfile.read(grid_file, datasetName="velocity", box=pix_box, print_msg=False)[0]
    atr = readfile.read_attribute(grid_file)

    msk, _ = pp.read_mask(
        grid_file,
        mask_file=inps.mask_file,
        datasetName="velocity",
        box=pix_box,
        vmin=inps.mask_vmin,
        vmax=inps.mask_vmax,
        print_msg=False,
    )
    if inps.zero_mask:
        data = np.ma.masked_where(data == 0.0, data)
    if msk is not None:
        data = np.ma.masked_where(msk == 0, data)

    if "REF_Y" in atr and "REF_X" in atr:
        ref_y, ref_x = int(atr["REF_Y"]), int(atr["REF_X"])
        ref_row = ref_y - pix_box[1]
        ref_col = ref_x - pix_box[0]
        if 0 <= ref_row < data.shape[0] and 0 <= ref_col < data.shape[1]:
            ref_val = data[ref_row, ref_col]
            if np.ma.is_masked(ref_val) or not np.isfinite(float(ref_val)):
                pass
            else:
                data = data - float(ref_val)

    data, _, _, _ = pp.scale_data4disp_unit_and_rewrap(
        data,
        metadata=atr,
        disp_unit=inps.disp_unit,
        wrap=inps.wrap,
        wrap_range=inps.wrap_range,
        print_msg=False,
    )
    return float(np.nanmin(data)), float(np.nanmax(data))


def sync_inps_with_view_geo(inps, dlim: tuple[float, float], vprint) -> list[float]:
    """MintPy view.py subset geo_box, figure size, colormap, and flip flags."""
    from mintpy import subset
    from mintpy.utils import utils as ut

    mintpy_view.vprint = vprint
    grid_file = _geocoded_grid_file(inps)
    if grid_file:
        atr = readfile.read_attribute(grid_file)
        inps.width = int(atr["WIDTH"])
        inps.length = int(atr["LENGTH"])
        inps.dsetNum = 1
        if not getattr(inps, "fig_coord", None):
            inps.fig_coord = "geo"
        coord = ut.coordinate(atr)
        inps.pix_box, _geo = subset.subset_input_dict2box(vars(inps), atr)
        inps.pix_box = coord.check_box_within_data_coverage(inps.pix_box)
        geo_box = list(coord.box_pixel2geo(inps.pix_box))
        inps.geo_box = geo_box
        vprint(f"subset coverage in lat/lon: {geo_box}")
        inps.colormap = pp.auto_colormap_name(
            atr,
            inps.colormap,
            datasetName="velocity",
            print_msg=inps.print_msg,
        )
        geo_unit, inps.wrap = pp.check_disp_unit_and_wrap(
            atr,
            disp_unit=inps.disp_unit,
            wrap=inps.wrap,
            wrap_range=inps.wrap_range,
            print_msg=inps.print_msg,
        )
        if not getattr(inps, "vlm_csv_disp_unit", None):
            inps.disp_unit = geo_unit
        if getattr(inps, "auto_flip", True):
            inps.flip_lr, inps.flip_ud = pp.auto_flip_direction(
                atr,
                print_msg=inps.print_msg,
            )
        if inps.font_size:
            inps.font_size = int(inps.font_size)
        elif not inps.font_size:
            inps.font_size = 16
        mintpy_view.update_figure_setting(inps)
    else:
        xlim = tuple(sorted(inps.subset_lon)) if inps.subset_lon else None
        ylim = tuple(sorted(inps.subset_lat)) if inps.subset_lat else None
        if xlim is None or ylim is None:
            raise RuntimeError(
                "VLM plot needs --geo-grid FILE (geocoded .h5) or --sub-lat/--sub-lon with a geocoded --mask "
                "so figure size matches view.py."
            )
        geo_box = geo_box_from_limits(xlim, ylim)
        if inps.font_size:
            inps.font_size = int(inps.font_size)
        elif not inps.font_size:
            inps.font_size = 16
        if not inps.fig_size:
            length = abs(geo_box[3] - geo_box[1])
            width = abs(geo_box[2] - geo_box[0])
            inps.fig_size = pp.auto_figure_size(
                ds_shape=(length, width),
                disp_cbar=inps.disp_cbar,
                print_msg=inps.print_msg,
            )
        if not inps.disp_unit and not getattr(inps, "vlm_csv_disp_unit", None):
            inps.disp_unit = "cm/year"
        elif getattr(inps, "vlm_csv_disp_unit", None):
            inps.disp_unit = inps.vlm_csv_disp_unit
        if not inps.colormap:
            inps.colormap = "jet"

    if grid_file:
        grid_dlim = geo_velocity_dlim_for_colorbar(inps, grid_file)
        if grid_dlim is not None:
            vprint(
                f"colorbar data range from {os.path.basename(grid_file)}: "
                f"[{grid_dlim[0]:.6g}, {grid_dlim[1]:.6g}] {inps.disp_unit}"
            )
            dlim = grid_dlim

    inps.dlim = [float(dlim[0]), float(dlim[1])]
    if not inps.vlim:
        inps.vlim = list(inps.dlim)
    inps.cbar_ext = None
    _colormap_object(inps)
    inps.extent = (geo_box[0], geo_box[2], geo_box[3], geo_box[1])
    return geo_box


def apply_geo_axis_ticks_before_cbar(ax, inps, geo_box: list[float], vprint) -> None:
    """view.py plot_slice geo branch: lalo-label or tick_params before colorbar."""
    if not inps.disp_axis:
        return
    if inps.lalo_label:
        from cartopy import crs as ccrs

        proj = getattr(inps, "map_proj_obj", None) or ccrs.PlateCarree()
        inps.map_proj_obj = proj
        pp.draw_lalo_label(
            ax=ax,
            geo_box=geo_box,
            lalo_step=inps.lalo_step,
            lalo_loc=inps.lalo_loc,
            lalo_max_num=inps.lalo_max_num,
            lalo_offset=inps.lalo_offset,
            font_size=inps.lalo_font_size if inps.lalo_font_size else inps.font_size,
            projection=proj,
            print_msg=inps.print_msg,
        )
    else:
        ax.tick_params(
            which="both",
            direction="in",
            labelsize=inps.font_size,
            left=True,
            right=True,
            top=True,
            bottom=True,
        )


def plot_reference_point(ax, inps) -> None:
    """Same marker as view.py: default black square (ks) at --ref-lalo."""
    if not (inps.disp_ref_pixel and inps.ref_lalo):
        return
    plot_kw = {}
    if getattr(inps, "map_proj_obj", None) is not None:
        plot_kw["transform"] = inps.map_proj_obj
    ax.plot(
        inps.ref_lalo[1],
        inps.ref_lalo[0],
        inps.ref_marker,
        ms=inps.ref_marker_size,
        **plot_kw,
    )


def read_vlm_mask(inps):
    """Read geocoded mask grid (MintPy view.py / plot.read_mask semantics)."""
    if inps.mask_file in (None, "no", ""):
        return None
    msk, _ = pp.read_mask(
        inps.mask_file,
        mask_file=inps.mask_file,
        vmin=inps.mask_vmin,
        vmax=inps.mask_vmax,
        print_msg=inps.print_msg,
    )
    return msk


def keep_points_by_mask(
    lon: np.ndarray,
    lat: np.ndarray,
    mask_file: str,
    msk: np.ndarray,
) -> np.ndarray:
    """True for CSV points that fall on mask pixels with value != 0 (after read_mask)."""
    from mintpy.objects.coord import coordinate
    from mintpy.utils import readfile

    atr = readfile.read_attribute(mask_file)
    coord = coordinate(atr)
    coord.open()
    if not coord.geocoded:
        raise ValueError(
            f"mask file {mask_file} is not geocoded; "
            "use a geo grid mask (e.g. geo_polygon_mask.h5 from polygon_2_mask.py)."
        )
    row, col = coord.lalo2yx(lat.tolist(), lon.tolist())
    row = np.asarray(row, dtype=int)
    col = np.asarray(col, dtype=int)
    length, width = msk.shape
    inside = (row >= 0) & (row < length) & (col >= 0) & (col < width)
    keep = np.zeros(lon.shape, dtype=bool)
    keep[inside] = msk[row[inside], col[inside]]
    return keep


def apply_vlm_mask(df: pd.DataFrame, inps, vprint) -> pd.DataFrame:
    msk = read_vlm_mask(inps)
    if msk is None:
        if inps.zero_mask:
            before = len(df)
            df = df[df["vlm"] != 0].copy()
            vprint(f"zero_mask: kept {len(df):,} / {before:,} points (vlm != 0)")
        return df

    before = len(df)
    lon = df["lon"].to_numpy()
    lat = df["lat"].to_numpy()
    keep = keep_points_by_mask(lon, lat, inps.mask_file, msk)
    if inps.zero_mask:
        keep &= df["vlm"].to_numpy() != 0
    df = df.loc[keep].copy()
    vprint(
        f"mask ({os.path.basename(inps.mask_file)}): "
        f"kept {len(df):,} / {before:,} VLM points"
    )
    if df.empty:
        raise RuntimeError("No VLM points left after masking.")
    return df


def reference_vlm_values(lon: np.ndarray, lat: np.ndarray, vlm: np.ndarray, ref_lalo) -> tuple[np.ndarray, float | None]:
    ref_lat, ref_lon = ref_lalo
    dist2 = (lat - ref_lat) ** 2 + (lon - ref_lon) ** 2
    idx = int(np.argmin(dist2))
    ref_val = float(vlm[idx])
    if not np.isfinite(ref_val):
        return vlm, None
    return vlm - ref_val, ref_val


def plot_vlm(inps) -> None:
    vprint = print if inps.print_msg else lambda *args, **kwargs: None
    csv_path = Path(inps.file).resolve()
    df, csv_unit = read_vlm_csv(csv_path)
    if csv_unit:
        inps.disp_unit = csv_unit
        inps.vlm_csv_disp_unit = csv_unit
        vprint(f"display unit from CSV: {inps.disp_unit}")
    df = subset_dataframe(df, inps)
    if df.empty:
        raise RuntimeError(f"No VLM points to display in {csv_path} (after subset).")
    df = apply_vlm_mask(df, inps, vprint)

    lon = df["lon"].to_numpy()
    lat = df["lat"].to_numpy()
    vlm = df["vlm"].to_numpy(dtype=np.float32)

    if inps.ref_lalo:
        vprint(f"input reference point in lat/lon: {inps.ref_lalo}")
        vlm, ref_val = reference_vlm_values(lon, lat, vlm, inps.ref_lalo)
        if ref_val is not None:
            vprint(
                f"referencing VLM to nearest CSV sample by subtracting "
                f"{ref_val:.6f} {inps.disp_unit or 'cm/year'}"
            )
        else:
            vprint("WARNING: reference point has no finite VLM nearby; skip re-referencing.")

    vlm_dlim = (float(np.nanmin(vlm)), float(np.nanmax(vlm)))
    geo_box = sync_inps_with_view_geo(inps, vlm_dlim, vprint)
    extent = inps.extent
    vprint(f"VLM scatter range: [{vlm_dlim[0]:.6g}, {vlm_dlim[1]:.6g}] {inps.disp_unit}")
    vprint(f"data    range: {inps.dlim} {inps.disp_unit}")
    vprint(f"display range: {inps.vlim} {inps.disp_unit}")
    vprint(f"display data in transparency: {inps.transparency}")

    use_cartopy = bool(inps.lalo_label or inps.coastline)
    if use_cartopy:
        from cartopy import crs as ccrs

        inps.map_proj_obj = ccrs.PlateCarree()
        fig = plt.figure(figsize=inps.fig_size)
        ax = fig.add_subplot(1, 1, 1, projection=inps.map_proj_obj)
    else:
        fig, ax = plt.subplots(figsize=inps.fig_size)
    if not inps.disp_whitespace:
        fig.subplots_adjust(left=0, right=1, bottom=0, top=1)

    if inps.basemap:
        from mintpy.utils.web_basemap import add_web_basemap

        add_web_basemap(
            ax,
            xlim=extent[0:2],
            ylim=extent[2:4],
            provider_key=inps.basemap,
            alpha=inps.basemap_alpha,
            print_msg=inps.print_msg,
        )

    if inps.coastline:
        vprint(f"draw coast line with resolution: {inps.coastline}")
        ax.coastlines(resolution=inps.coastline, linewidth=inps.coastline_linewidth)

    # Same scatter kwargs as view.py (do not zero linewidths; that shrinks markers).
    scatter_kw = dict(
        cmap=inps.colormap,
        vmin=inps.vlim[0],
        vmax=inps.vlim[1],
        alpha=inps.transparency,
        zorder=1,
    )
    if use_cartopy:
        scatter_kw["transform"] = inps.map_proj_obj

    vprint(f'plotting data as {inps.style} via matplotlib.pyplot.scatter (can take some time) ...')
    im = ax.scatter(lon, lat, c=vlm, marker="o", s=inps.scatter_marker_size, **scatter_kw)
    if use_cartopy:
        ax.set_extent([extent[0], extent[1], extent[2], extent[3]], crs=inps.map_proj_obj)
    else:
        ax.axis("equal")
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])

    if inps.shp_file:
        snwe = (geo_box[3], geo_box[1], geo_box[0], geo_box[2])
        pp.plot_shape(
            ax=ax,
            shp_files=inps.shp_file,
            SNWE=snwe,
            color=inps.shp_color,
            linewidth=inps.shp_linewidth,
            min_dist=inps.shp_min_dist,
            print_msg=inps.print_msg,
        )

    if inps.disp_scalebar:
        vprint(f"plot scale bar: {inps.scalebar}")
        pp.draw_scalebar(
            ax=ax,
            geo_box=geo_box,
            unit="degrees",
            loc=inps.scalebar,
            labelpad=inps.scalebar_pad,
            font_size=inps.font_size,
            linewidth=inps.scalebar_linewidth,
        )

    apply_geo_axis_ticks_before_cbar(ax, inps, geo_box, vprint)

    if inps.disp_ref_pixel and inps.ref_lalo:
        plot_reference_point(ax, inps)
        vprint("plot reference point")

    inps.fig_title = clean_plot_title(inps.fig_title if inps.fig_title else inps.file)
    mintpy_view.finalize_plot_axes(ax, im, inps)

    if inps.save_fig:
        if not inps.outfile:
            inps.outfile = [str(csv_path.with_suffix(inps.fig_ext))]
        for out_name in inps.outfile:
            out_path = os.path.abspath(out_name)
            vprint(f"save figure to {out_path} with dpi={inps.fig_dpi}")
            if not inps.disp_whitespace:
                fig.savefig(out_path, transparent=True, dpi=inps.fig_dpi, pad_inches=0.0)
            else:
                fig.savefig(out_path, bbox_inches="tight", transparent=True, dpi=inps.fig_dpi)

    if inps.disp_fig:
        plt.show()
    else:
        plt.close(fig)

    vprint(f"plotted {len(df):,} VLM points from {csv_path.name}")


def main(iargs=None) -> int:
    try:
        inps = cmd_line_parse(iargs)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    try:
        plot_vlm(inps)
    except (RuntimeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
