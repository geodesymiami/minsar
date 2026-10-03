#!/usr/bin/env python3
"""Plot airport VLM CSV points with MintPy view.py-compatible options."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from mpl_toolkits.axes_grid1 import make_axes_locatable

from mintpy.utils import arg_utils, plot as pp

EXAMPLE = """Examples:
  display_VLM.py MIA_VLM.csv --sub-lat 25.78 25.81 --sub-lon -80.31 -80.265 --ref-lalo 25.81018 -80.28961 --vlim -0.5 0.5 --style scatter --scatter-size 1 --add-basemap
  display_VLM.py MIA_VLM.csv --sub-lat 25.78 25.81 --sub-lon -80.31 -80.265 --ref-lalo 25.808 -80.28961 --vlim -0.5 0.5 --style scatter --scatter-size 10 --mask geo_polygon_mask.h5
  display_VLM.py MIA_VLM.csv --style scatter --no-display -o MIA_VLM.png
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

    if not inps.disp_whitespace:
        inps.disp_axis = False
        inps.disp_title = False
        inps.disp_cbar = False

    if not inps.disp_axis:
        inps.disp_tick = False

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


def read_vlm_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]
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
    return df


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


# Same integer size view.py uses for title, ticks, and colorbar (MintPy --fontsize is int).
VLM_FONT_SIZE = 10

_TITLE_SUFFIXES = (
    "network_delaunay_4/geo_velocity.h5",
    "network_delaunay4/geo_velocity.h5",
)


def clean_plot_title(title: str) -> str:
    """Drop redundant network/geo_velocity tail from titles (airport comment plots)."""
    out = title
    for suffix in _TITLE_SUFFIXES:
        out = out.replace(suffix, "")
    return out.rstrip("/")


def geo_box_from_limits(xlim: tuple[float, float], ylim: tuple[float, float]) -> list[float]:
    """MintPy geo_box layout: [W, N, E, S] (same as view.py subset coverage)."""
    west, east = xlim
    south, north = ylim
    return [west, north, east, south]


def view_geo_box(inps, xlim: tuple[float, float], ylim: tuple[float, float]) -> list[float]:
    """Pixel-aligned [W, N, E, S] using the same subset logic as view.py.

    view.py converts --sub-lat/--sub-lon to a pixel box on the geocoded grid,
    then back to lat/lon. Figure size is auto_figure_size of that span.
    """
    mask_file = getattr(inps, "mask_file", None)
    if mask_file not in (None, "no", "") and os.path.isfile(mask_file):
        from mintpy import subset
        from mintpy.utils import readfile, utils as ut

        atr = readfile.read_attribute(mask_file)
        if "Y_FIRST" in atr and "X_FIRST" in atr:
            pix_box, _geo = subset.subset_input_dict2box(vars(inps), atr)
            coord = ut.coordinate(atr)
            pix_box = coord.check_box_within_data_coverage(pix_box)
            return list(coord.box_pixel2geo(pix_box))
    return geo_box_from_limits(xlim, ylim)


def apply_vlm_font_scale(inps) -> None:
    """Use the same font size as view.py for title, ticks, and colorbar."""
    if inps.font_size:
        inps.font_size = int(inps.font_size)
    else:
        inps.font_size = VLM_FONT_SIZE


def finalize_figure_view_style(ax, inps, im, vprint) -> None:
    """Match view.py plot_slice figure block (colorbar, title, axis, ticks)."""
    if inps.disp_cbar:
        divider = make_axes_locatable(ax)
        cax = divider.append_axes(inps.cbar_loc, inps.cbar_size, pad=inps.cbar_size, axes_class=plt.Axes)
        inps, _cbar = pp.plot_colorbar(inps, im, cax)

    if inps.disp_title:
        ax.set_title(inps.fig_title, fontsize=inps.font_size, color=inps.font_color)

    if inps.flip_lr:
        vprint("flip figure left and right")
        ax.invert_xaxis()
    if inps.flip_ud:
        vprint("flip figure up and down")
        ax.invert_yaxis()

    if not inps.disp_axis:
        ax.axis("off")
        vprint("turn off axis display")

    if inps.disp_tick:
        if inps.cbar_loc == "bottom":
            ax.tick_params(bottom=False, top=True, labelbottom=False, labeltop=True)
        ax.xaxis.set_visible(True)
        ax.yaxis.set_visible(True)
    else:
        ax.get_xaxis().set_ticks([])
        ax.get_yaxis().set_ticks([])

    if inps.ylabel_rot:
        tick_kwargs = dict(rotation=inps.ylabel_rot)
        if inps.ylabel_rot % 90 == 0:
            tick_kwargs["va"] = "center"
        plt.setp(ax.get_yticklabels(), **tick_kwargs)
        vprint(f"rotate Y-axis tick labels by {inps.ylabel_rot} deg")


def prepare_view_style(inps, geo_box: list[float]) -> None:
    """Align figure size with view.py update_figure_setting (geo spans + colorbar)."""
    # geo_box is [W, N, E, S], same indices as view.py
    lat_span = abs(geo_box[1] - geo_box[3])
    lon_span = abs(geo_box[2] - geo_box[0])
    apply_vlm_font_scale(inps)
    if not inps.fig_size:
        inps.fig_size = pp.auto_figure_size(
            ds_shape=(lat_span, lon_span),
            disp_cbar=inps.disp_cbar,
            print_msg=inps.print_msg,
        )
    if not inps.disp_unit:
        inps.disp_unit = "cm/year"
    if inps.vlim:
        inps.dlim = [inps.vlim[0], inps.vlim[1]]
    cmap_name = inps.colormap if inps.colormap else "jet"
    inps.colormap = pp.ColormapExt(
        cmap_name,
        cmap_lut=inps.cmap_lut,
        vlist=inps.cmap_vlist,
    ).colormap


def plot_reference_point(ax, inps) -> None:
    """Same marker as view.py: default black square (ks) at --ref-lalo."""
    if not (inps.disp_ref_pixel and inps.ref_lalo):
        return
    ax.plot(
        inps.ref_lalo[1],
        inps.ref_lalo[0],
        inps.ref_marker,
        ms=inps.ref_marker_size,
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
    df = read_vlm_csv(csv_path)
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
            vprint(f"referencing VLM to nearest CSV sample by subtracting {ref_val:.6f} cm/yr")
        else:
            vprint("WARNING: reference point has no finite VLM nearby; skip re-referencing.")

    xlim, ylim = geo_limits(inps, lon, lat)
    geo_box = view_geo_box(inps, xlim, ylim)
    extent = (geo_box[0], geo_box[2], geo_box[3], geo_box[1])  # W, E, S, N
    if not inps.vlim:
        inps.vlim = [float(np.nanmin(vlm)), float(np.nanmax(vlm))]
    prepare_view_style(inps, geo_box)
    vprint(f"subset coverage in lat/lon: {geo_box}")

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

    # Same scatter kwargs as view.py (do not zero linewidths; that shrinks markers).
    kwargs = {
        "cmap": inps.colormap,
        "vmin": inps.vlim[0],
        "vmax": inps.vlim[1],
        "alpha": inps.transparency,
        "zorder": 1,
    }
    vprint(f"display range: [{inps.vlim[0]}, {inps.vlim[1]}] {inps.disp_unit}")

    vprint(f'plotting data as {inps.style} via matplotlib.pyplot.scatter (can take some time) ...')
    im = ax.scatter(lon, lat, c=vlm, marker="o", s=inps.scatter_marker_size, **kwargs)
    # Same window as view.py imshow: pixel-aligned extent, equal aspect inside the axes.
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal", adjustable="box")

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

    if inps.disp_tick:
        ax.tick_params(
            which="both",
            direction="in",
            labelsize=inps.font_size,
            left=True,
            right=True,
            top=True,
            bottom=True,
        )
        if inps.cbar_loc == "bottom":
            ax.tick_params(bottom=False, top=True, labelbottom=False, labeltop=True)
    else:
        ax.get_xaxis().set_ticks([])
        ax.get_yaxis().set_ticks([])

    if inps.disp_ref_pixel and inps.ref_lalo:
        plot_reference_point(ax, inps)
        vprint("plot reference point")

    inps.fig_title = clean_plot_title(inps.fig_title if inps.fig_title else inps.file)
    finalize_figure_view_style(ax, inps, im, vprint)

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
