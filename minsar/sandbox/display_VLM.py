#!/usr/bin/env python3
"""Plot airport VLM CSV points with MintPy view.py-compatible options."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from mintpy.utils import arg_utils, plot as pp

EXAMPLE = """Examples:
  display_VLM.py MIA_VLM.csv --sub-lat 25.78 25.81 --sub-lon -80.31 -80.265 --ref-lalo 25.81018 -80.28961 --vlim -0.5 0.5 --style scatter --scatter-size 1 --add-basemap
  display_VLM.py MIA_VLM.csv --style scatter --save --nodisplay
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

    if inps.style != "scatter":
        parser.error("display_VLM.py supports --style scatter only (CSV point data).")

    if inps.dset and inps.print_msg:
        print("WARNING: dataset name(s) ignored for VLM CSV input.")

    for opt in ("dem_file", "mask_file", "disp_gnss", "pts_file"):
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


def plot_reference_point(ax, inps) -> None:
    """Same marker as view.py: default black square (ks) at --ref-lalo."""
    if not (inps.disp_ref_pixel and inps.ref_lalo):
        return
    ax.plot(
        inps.ref_lalo[1],
        inps.ref_lalo[0],
        inps.ref_marker,
        ms=inps.ref_marker_size,
        zorder=10,
        clip_on=False,
    )


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

    fig_w, fig_h = inps.fig_size if inps.fig_size else (10.0, 5.3)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    xlim, ylim = geo_limits(inps, lon, lat)
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)

    if inps.basemap:
        from mintpy.utils.web_basemap import add_web_basemap

        add_web_basemap(
            ax,
            xlim=xlim,
            ylim=ylim,
            provider_key=inps.basemap,
            alpha=inps.basemap_alpha,
            print_msg=inps.print_msg,
        )

    cmap = inps.colormap if inps.colormap else "jet"
    kwargs = {"cmap": cmap, "linewidths": 0, "zorder": 3}
    if inps.vlim:
        kwargs["vmin"] = inps.vlim[0]
        kwargs["vmax"] = inps.vlim[1]
        vprint(f"display range: [{inps.vlim[0]}, {inps.vlim[1]}] cm/year")

    vprint(f'plotting data as {inps.style} via matplotlib.pyplot.scatter (can take some time) ...')
    im = ax.scatter(lon, lat, c=vlm, marker="o", s=inps.scatter_marker_size, **kwargs)
    ax.axis("equal")

    if inps.disp_cbar:
        label = inps.cbar_label if inps.cbar_label else "VLM (cm/yr)"
        plt.colorbar(im, ax=ax, label=label)

    if inps.disp_title:
        title = inps.fig_title if inps.fig_title else csv_path.stem
        ax.set_title(title)

    if inps.disp_axis:
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")

    if inps.shp_file:
        snwe = (ylim[0], ylim[1], xlim[0], xlim[1])
        pp.plot_shape(
            ax=ax,
            shp_files=inps.shp_file,
            SNWE=snwe,
            color=inps.shp_color,
            linewidth=inps.shp_linewidth,
            min_dist=inps.shp_min_dist,
            print_msg=inps.print_msg,
        )

    if inps.disp_ref_pixel and inps.ref_lalo:
        plot_reference_point(ax, inps)
        vprint("plot reference point")

    if inps.save_fig:
        if not inps.outfile:
            inps.outfile = [str(csv_path.with_suffix(inps.fig_ext))]
        for out_name in inps.outfile:
            out_path = os.path.abspath(out_name)
            vprint(f"save figure to {out_path} with dpi={inps.fig_dpi}")
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
