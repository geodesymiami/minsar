#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import re
import urllib.request
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import cm
from matplotlib.colors import LinearSegmentedColormap

try:
    from PIL import Image, ImageOps
except Exception:
    Image = None


BASEMAP_PROVIDERS = {
    "osm": {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "grayscale": False,
        "cache_suffix": "osm",
    },
    "osm_gray": {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "grayscale": True,
        "cache_suffix": "osm_gray",
    },
    "cartodb_light": {
        "url": "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
        "grayscale": False,
        "cache_suffix": "cartodb_light",
    },
    "cartodb_dark": {
        "url": "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "grayscale": False,
        "cache_suffix": "cartodb_dark",
    },
    "esri_gray": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        "grayscale": False,
        "cache_suffix": "esri_gray",
    },
    "esri_satellite": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "grayscale": False,
        "cache_suffix": "esri_satellite",
    },
}


def parse_vlim(text):
    if text is None or str(text).strip() == "":
        return None
    a, b = [float(v) for v in str(text).split(",")]
    return (a, b)


def get_date_columns(df):
    cols = []
    for c in df.columns:
        s = str(c)
        if re.fullmatch(r"D\d{8}", s) or re.fullmatch(r"\d{8}", s):
            cols.append(c)
    return sorted(cols, key=lambda c: str(c).replace("D", ""))


def robust_total_displacement_from_series(values, n_edge=3):
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        return np.nan
    n = min(n_edge, arr.size // 2)
    n = max(n, 1)
    return float(np.nanmean(arr[-n:]) - np.nanmean(arr[:n]))


def robust_total_displacement_matrix(ts_2d, n_edge=3):
    out = np.full(ts_2d.shape[0], np.nan, dtype=float)
    for i in range(ts_2d.shape[0]):
        out[i] = robust_total_displacement_from_series(ts_2d[i, :], n_edge=n_edge)
    return out


def normalize_point_id(v):
    if pd.isna(v):
        return ""
    try:
        f = float(v)
        if f.is_integer():
            return str(int(f))
    except Exception:
        pass
    return str(v).strip()


def find_one(result_dir, suffix):
    files = sorted(result_dir.glob(f"*{suffix}"))
    if not files:
        raise FileNotFoundError(f"Missing *{suffix} in {result_dir}")
    return files[0]


def read_manifest(path):
    df = pd.read_csv(path)
    required = {"building_id", "label", "result_dir"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Manifest missing columns: {sorted(missing)}")
    if "order" not in df.columns:
        df["order"] = np.arange(len(df)) + 1
    return df.sort_values("order").reset_index(drop=True)


def robust_vlim(values, percentile=98.0, min_abs=1.0, symmetric=True, negative_only=False):
    vals = np.asarray(values, dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return (-1.0, 1.0)

    if negative_only:
        lo = float(np.nanpercentile(vals, 100.0 - percentile))
        lo = min(lo, -min_abs)
        return (lo, 0.0)

    if symmetric:
        m = float(np.nanpercentile(np.abs(vals), percentile))
        if not np.isfinite(m) or m <= 0:
            m = min_abs
        m = max(m, min_abs)
        return (-m, m)

    lo, hi = np.nanpercentile(vals, [100.0 - percentile, percentile])
    if hi - lo < min_abs:
        mid = 0.5 * (hi + lo)
        lo, hi = mid - min_abs / 2, mid + min_abs / 2
    return (float(lo), float(hi))


def lonlat_aspect(ax, df):
    lat0 = float(np.nanmean(df["Y"]))
    if np.isfinite(lat0):
        ax.set_aspect(1.0 / np.cos(np.deg2rad(lat0)), adjustable="box")


def lonlat_to_tile(lon, lat, zoom):
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile


def tile_edges(x, y, z):
    n = 2.0 ** z
    lon_w = x / n * 360.0 - 180.0
    lon_e = (x + 1) / n * 360.0 - 180.0
    lat_n = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_s = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon_w, lon_e, lat_s, lat_n


def fetch_tile(x, y, z, cache_dir, provider_url, grayscale=False):
    if Image is None:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    tile_path = cache_dir / f"z{z}_x{x}_y{y}.png"
    if tile_path.exists():
        img = Image.open(tile_path).convert("RGB")
        if grayscale:
            img = ImageOps.grayscale(img).convert("RGB")
        return img

    url = provider_url.format(z=z, x=x, y=y)
    req = urllib.request.Request(url, headers={"User-Agent": "building-component-maps/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            data = response.read()
        img = Image.open(BytesIO(data)).convert("RGB")
        img.save(tile_path)
        if grayscale:
            img = ImageOps.grayscale(img).convert("RGB")
        return img
    except Exception as exc:
        print(f"[WARNING] could not fetch tile {z}/{x}/{y}: {exc}")
        return None


def add_web_basemap(ax, xlim, ylim, provider_key="osm_gray", zoom=19, alpha=0.38, cache_root=Path(".tile_cache")):
    if Image is None:
        return False
    if provider_key not in BASEMAP_PROVIDERS:
        raise ValueError(f"Unknown basemap provider: {provider_key}")

    provider = BASEMAP_PROVIDERS[provider_key]
    provider_url = provider["url"]
    grayscale = provider.get("grayscale", False)
    cache_dir = cache_root / provider.get("cache_suffix", provider_key)

    w, e = xlim
    s, n = ylim
    if not all(np.isfinite([w, e, s, n])):
        return False

    x0, y0 = lonlat_to_tile(w, n, zoom)
    x1, y1 = lonlat_to_tile(e, s, zoom)
    xmin, xmax = sorted([x0, x1])
    ymin, ymax = sorted([y0, y1])

    ok = False
    for xt in range(xmin, xmax + 1):
        for yt in range(ymin, ymax + 1):
            img = fetch_tile(xt, yt, zoom, cache_dir, provider_url, grayscale=grayscale)
            if img is None:
                continue
            lon_w, lon_e, lat_s, lat_n = tile_edges(xt, yt, zoom)
            ax.imshow(img, extent=[lon_w, lon_e, lat_s, lat_n], origin="upper", alpha=alpha, zorder=0)
            ok = True

    ax.set_xlim(w, e)
    ax.set_ylim(s, n)
    return ok


def bluegreen_cmap():
    colors = [
        "#1e1ea8",  # deep blue
        "#2647ff",  # blue
        "#4d86ff",  # light blue
        "#67c8ff",  # cyan-blue
        "#73e4d6",  # aqua-green
        "#8ae08a",  # light green
    ]
    return LinearSegmentedColormap.from_list("bluegreen", colors, N=256)


def bluegreen_vivid_cmap():
    """Darker/more saturated blue-to-green map for points over satellite imagery."""
    colors = [
        "#06147a",  # dark navy
        "#0033ff",  # saturated blue
        "#0088ff",  # vivid blue-cyan
        "#00d4ff",  # cyan
        "#00d88a",  # green-cyan
        "#26d926",  # vivid green
    ]
    return LinearSegmentedColormap.from_list("bluegreen_vivid", colors, N=256)


def bluegreen_orange_cmap():
    """Blue -> cyan -> green -> yellow/orange for signed component maps."""
    colors = [
        "#06147a",  # dark navy
        "#0033ff",  # saturated blue
        "#0099ff",  # blue-cyan
        "#00d4ff",  # cyan
        "#00d88a",  # green-cyan
        "#7ee000",  # green-yellow
        "#ffd000",  # yellow/orange
    ]
    return LinearSegmentedColormap.from_list("bluegreen_orange", colors, N=256)


def resolve_cmap(name):
    low = name.lower()
    if low in {"bluegreen", "blue-green", "blue_to_green"}:
        return bluegreen_cmap()
    if low in {"bluegreen_vivid", "bluegreen-vivid", "blue_to_green_vivid"}:
        return bluegreen_vivid_cmap()
    if low in {"bluegreen_orange", "bluegreen-orange", "blue_to_green_orange"}:
        return bluegreen_orange_cmap()
    return cm.get_cmap(name)


def read_building(row, base_dir):
    result_dir = Path(row["result_dir"])
    if not result_dir.is_absolute():
        result_dir = base_dir / result_dir
    result_dir = result_dir.resolve()

    selected_path = find_one(result_dir, "_selected_points.csv")
    selected = pd.read_csv(selected_path)

    return {
        "building_id": row["building_id"],
        "label": row["label"],
        "order": row.get("order", 0),
        "result_dir": result_dir,
        "selected_path": selected_path,
        "selected": selected,
    }


def match_original_to_selected(original_all, selected):
    if "point_id" in original_all.columns and "point_id" in selected.columns:
        orig = original_all.copy()
        sel = selected.copy()
        orig["_pid_norm"] = orig["point_id"].map(normalize_point_id)
        sel["_pid_norm"] = sel["point_id"].map(normalize_point_id)
        wanted = sel["_pid_norm"].tolist()

        orig = orig.drop_duplicates("_pid_norm").set_index("_pid_norm")
        matched = [pid for pid in wanted if pid in orig.index]
        out = orig.loc[matched].copy().reset_index(drop=False)

        order = pd.DataFrame({"_pid_norm": wanted, "_order": np.arange(len(wanted))})
        out = out.merge(order, on="_pid_norm", how="left").sort_values("_order")
        return out.reset_index(drop=True)

    orig = original_all.copy()
    sel = selected.copy()
    orig["_xy_key"] = orig["X"].round(7).astype(str) + "_" + orig["Y"].round(7).astype(str)
    sel["_xy_key"] = sel["X"].round(7).astype(str) + "_" + sel["Y"].round(7).astype(str)
    orig = orig.drop_duplicates("_xy_key").set_index("_xy_key")
    keys = sel["_xy_key"].tolist()
    matched = [k for k in keys if k in orig.index]
    out = orig.loc[matched].copy().reset_index(drop=False)
    order = pd.DataFrame({"_xy_key": keys, "_order": np.arange(len(keys))})
    out = out.merge(order, on="_xy_key", how="left").sort_values("_order")
    return out.reset_index(drop=True)


def prepare_components_for_building(b, original_all, args):
    df = b["selected"].copy()

    orig_sel = match_original_to_selected(original_all, df)
    date_cols_orig = get_date_columns(orig_sel)
    if date_cols_orig:
        orig_total = robust_total_displacement_matrix(orig_sel[date_cols_orig].to_numpy(dtype=float), n_edge=args.n_edge)
        if "point_id" in orig_sel.columns and "point_id" in df.columns:
            map_orig = pd.DataFrame({
                "_pid_norm": orig_sel["point_id"].map(normalize_point_id),
                "original_total_displacement": orig_total,
            })
            df["_pid_norm"] = df["point_id"].map(normalize_point_id)
            df = df.merge(map_orig, on="_pid_norm", how="left").drop(columns=["_pid_norm"], errors="ignore")
        else:
            df["original_total_displacement"] = np.nan
            n = min(len(df), len(orig_total))
            df.loc[df.index[:n], "original_total_displacement"] = orig_total[:n]
    else:
        df["original_total_displacement"] = np.nan

    if "thermal_total_displacement" not in df.columns:
        date_cols = get_date_columns(df)
        if not date_cols:
            raise ValueError(f"{b['label']}: missing thermal_total_displacement and no date columns found.")
        df["thermal_total_displacement"] = robust_total_displacement_matrix(df[date_cols].to_numpy(dtype=float), n_edge=args.n_edge)

    if "uniform_component_displacement" not in df.columns:
        raise ValueError(f"{b['label']}: missing uniform_component_displacement.")

    if "shrinkage_component_displacement" in df.columns:
        df["height_dependent_component_displacement"] = df["shrinkage_component_displacement"]
    else:
        raise ValueError(f"{b['label']}: missing shrinkage_component_displacement.")

    df["differential_settlement_displacement"] = (
        df["thermal_total_displacement"]
        - df["uniform_component_displacement"]
        - df["height_dependent_component_displacement"]
    )

    if args.display_mode == "settlement":
        df["original_total_displacement_plot"] = np.minimum(df["original_total_displacement"], 0.0)
        df["thermal_total_displacement_plot"] = np.minimum(df["thermal_total_displacement"], 0.0)
    else:
        df["original_total_displacement_plot"] = df["original_total_displacement"]
        df["thermal_total_displacement_plot"] = df["thermal_total_displacement"]

    return df


def compute_common_map_extent(buildings, pad_fraction=0.25):
    """
    Compute one common lon/lat span for all building panels.
    This keeps all maps at the same geographic scale.
    """
    xspans = []
    yspans = []

    for b in buildings:
        df = b["plot_df"]
        good = np.isfinite(df["X"]) & np.isfinite(df["Y"])
        dfg = df.loc[good]
        if len(dfg) == 0:
            continue

        dx = float(dfg["X"].max() - dfg["X"].min())
        dy = float(dfg["Y"].max() - dfg["Y"].min())

        if np.isfinite(dx) and dx > 0:
            xspans.append(dx)
        if np.isfinite(dy) and dy > 0:
            yspans.append(dy)

    if not xspans or not yspans:
        return None

    # Use largest building extent, then add padding.
    common_xspan = max(xspans) * (1.0 + 2.0 * pad_fraction)
    common_yspan = max(yspans) * (1.0 + 2.0 * pad_fraction)

    return common_xspan, common_yspan


def add_map_panel(ax, df, value_col, cmap, vlim, add_basemap, basemap_provider, basemap_alpha, cache_dir, title="", s=13, point_alpha=1.0, point_edgecolor="none", point_linewidth=0.0, point_marker="o", common_extent=None):
    ax.set_facecolor("0.82")

    vals = pd.to_numeric(df[value_col], errors="coerce")
    good = np.isfinite(vals) & np.isfinite(df["X"]) & np.isfinite(df["Y"])
    dfg = df.loc[good].copy()
    vals = vals.loc[good]

    if len(dfg) == 0:
        ax.set_axis_off()
        ax.text(0.5, 0.5, "no data", transform=ax.transAxes, ha="center", va="center")
        return None

    if common_extent is None:
        pad_x = max((dfg["X"].max() - dfg["X"].min()) * 0.10, 0.00003)
        pad_y = max((dfg["Y"].max() - dfg["Y"].min()) * 0.10, 0.00003)
        xlim = (float(dfg["X"].min() - pad_x), float(dfg["X"].max() + pad_x))
        ylim = (float(dfg["Y"].min() - pad_y), float(dfg["Y"].max() + pad_y))
    else:
        common_xspan, common_yspan = common_extent

        cx = 0.5 * float(dfg["X"].min() + dfg["X"].max())
        cy = 0.5 * float(dfg["Y"].min() + dfg["Y"].max())

        xlim = (cx - 0.5 * common_xspan, cx + 0.5 * common_xspan)
        ylim = (cy - 0.5 * common_yspan, cy + 0.5 * common_yspan)

    if add_basemap:
        add_web_basemap(ax, xlim, ylim, provider_key=basemap_provider, alpha=basemap_alpha, cache_root=cache_dir)

    edge = point_edgecolor
    if isinstance(edge, str) and edge.lower() in {"none", "no", "off"}:
        edge = "none"

    sc = ax.scatter(
        dfg["X"], dfg["Y"],
        c=vals,
        s=s,
        cmap=cmap,
        vmin=vlim[0] if vlim else None,
        vmax=vlim[1] if vlim else None,
        marker=point_marker,
        edgecolors=edge,
        linewidths=point_linewidth,
        alpha=point_alpha,
        zorder=3,
    )

    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    lonlat_aspect(ax, dfg)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(True, alpha=0.18, linewidth=0.5)
    if title:
        ax.set_title(title, fontsize=20, fontweight="bold", pad=10)
    return sc


def compute_two_group_vlims(buildings, columns, args):
    """
    Fixed shared color scales for the 2-colorbar layout.

    Left colorbar (columns 1-2):
      - After thermal correction Total
      - Uniform settlement
      Range: about -100 to +30 mm

    Right colorbar (columns 3-4):
      - Height-dependent component
      - Differential settlement
      Range: about -30 to +30 mm
    """
    settlement_family = {
        "original_total_displacement_plot",
        "thermal_total_displacement_plot",
        "uniform_component_displacement",
    }
    residual_family = {
        "height_dependent_component_displacement",
        "differential_settlement_displacement",
    }

    settlement_vlim = (-100.0, 30.0)
    residual_vlim = (-30.0, 30.0)

    vlims = {}
    for _title, plot_col in columns:
        if plot_col in settlement_family:
            vlims[plot_col] = settlement_vlim
        elif plot_col in residual_family:
            vlims[plot_col] = residual_vlim
    return vlims


def make_component_maps(buildings, out_prefix, args):
    columns = [
        ("After thermal correction\nTotal", "thermal_total_displacement_plot"),
        ("Uniform settlement", "uniform_component_displacement"),
        ("Height-dependent\ncomponent", "height_dependent_component_displacement"),
        ("Differential\nsettlement", "differential_settlement_displacement"),
    ]

    vlim_overrides = {
        "thermal_total_displacement_plot": args.after_vlim,
        "uniform_component_displacement": args.uniform_vlim,
        "height_dependent_component_displacement": args.height_vlim,
        "differential_settlement_displacement": args.differential_vlim,
    }

    cmap = resolve_cmap(args.map_cmap)

    if args.colorbar_mode == "two" and not any(v is not None for v in vlim_overrides.values()):
        vlims = compute_two_group_vlims(buildings, columns, args)
    else:
        vlims = {}
        for _, plot_col in columns:
            if vlim_overrides[plot_col] is not None:
                vlims[plot_col] = vlim_overrides[plot_col]
                continue

            vals = []
            for b in buildings:
                df = b["plot_df"]
                if plot_col in df.columns:
                    vals.append(pd.to_numeric(df[plot_col], errors="coerce").to_numpy(dtype=float))
            vals = np.concatenate(vals) if vals else np.array([])

            if args.display_mode == "settlement" and plot_col in {"original_total_displacement_plot", "thermal_total_displacement_plot"}:
                vlims[plot_col] = robust_vlim(vals, percentile=args.map_percentile, min_abs=5.0, symmetric=False, negative_only=True)
            elif plot_col == "uniform_component_displacement":
                vlims[plot_col] = robust_vlim(vals, percentile=args.map_percentile, min_abs=5.0, symmetric=False, negative_only=True)
            else:
                vlims[plot_col] = robust_vlim(vals, percentile=args.map_percentile, min_abs=5.0, symmetric=True, negative_only=False)

    nrows = len(buildings)
    ncols = len(columns)

    fig_w = max(25.0, 5.2 * ncols)
    fig_h = max(4.0 * nrows + 2.8, 16.0)
    fig, axes = plt.subplots(nrows, ncols, figsize=(fig_w, fig_h), squeeze=False)
    fig.suptitle(args.title, fontsize=34, fontweight="bold", y=0.985)

    cache_dir = out_prefix.parent / "_tile_cache"
    first_scatter_by_col = {}
    
    common_extent = compute_common_map_extent(buildings, pad_fraction=0.25)

    for i, b in enumerate(buildings):
        df = b["plot_df"]

        for j, (title, plot_col) in enumerate(columns):
            ax = axes[i, j]
            sc = add_map_panel(
                ax,
                df,
                plot_col,
                cmap=cmap,
                vlim=vlims[plot_col],
                add_basemap=args.add_basemap,
                basemap_provider=args.basemap_provider,
                basemap_alpha=args.basemap_alpha,
                cache_dir=cache_dir,
                title=title if i == 0 else "",
                s=args.point_size,
                point_alpha=args.point_alpha,
                point_edgecolor=args.point_edgecolor,
                point_linewidth=args.point_linewidth,
                point_marker=args.point_marker,
                common_extent=common_extent,
            )

            vals = pd.to_numeric(df[plot_col], errors="coerce").to_numpy(dtype=float)
            vals = vals[np.isfinite(vals)]
            if vals.size:
                max_abs_mm = float(np.nanpercentile(np.abs(vals), args.map_percentile))
                ax.text(
                    0.97, 0.93,
                    f"max: {max_abs_mm / 10.0:.1f} cm",
                    transform=ax.transAxes,
                    ha="right",
                    va="top",
                    fontsize=18,
                    fontweight="bold",
                    bbox=dict(facecolor="white", alpha=0.70, edgecolor="none", pad=0.25),
                )

            if sc is not None and j not in first_scatter_by_col:
                first_scatter_by_col[j] = sc

        pos = axes[i, 0].get_position()
        y_mid = 0.5 * (pos.y0 + pos.y1)
        fig.text(
            0.145,
            y_mid,
            str(b["label"]),
            rotation=0,
            va="center",
            ha="right",
            fontsize=18,
            fontweight="bold",
        )

    fig.subplots_adjust(left=0.18, right=0.985, top=0.90, bottom=0.13, wspace=0.08, hspace=0.08)

    if args.colorbar_mode == "two":
        # first group: columns 0-1, second group: columns 2-3
        group_specs = [
            (0, 1, "Displacement [mm]"),
            (2, 3, "Displacement [mm]"),
        ]
        mappables = [first_scatter_by_col.get(0), first_scatter_by_col.get(2)]
        for (j0, j1, label), mappable in zip(group_specs, mappables):
            if mappable is None:
                continue
            pos0 = axes[-1, j0].get_position()
            pos1 = axes[-1, j1].get_position()
            x0 = pos0.x0 + 0.05 * pos0.width
            x1 = pos1.x1 - 0.05 * pos1.width
            cax = fig.add_axes([x0, 0.075, x1 - x0, 0.022])
            cb = fig.colorbar(mappable, cax=cax, orientation="horizontal")
            cb.ax.tick_params(labelsize=24, length=4, pad=3)
            cb.set_label(label, fontsize=22, fontweight="bold")
    else:
        for j, (_title, plot_col) in enumerate(columns):
            if j not in first_scatter_by_col:
                continue
            pos = axes[-1, j].get_position()
            cax = fig.add_axes([pos.x0 + 0.04 * pos.width, 0.075, pos.width * 0.92, 0.028])
            cb = fig.colorbar(first_scatter_by_col[j], cax=cax, orientation="horizontal")
            cb.ax.tick_params(labelsize=24, length=4, pad=3)
            cb.set_label("Displacement [mm]", fontsize=22, fontweight="bold")

    #note = (
    #    "Model columns: After thermal correction = Uniform + Height-dependent component + Differential settlement for each pixel. "
    #    "Panel labels show maximum magnitude in each displayed panel; maxima do not need to add."
    #)
    #fig.text(0.52, 0.035, note, ha="center", fontsize=13)

    out_png = out_prefix.with_name(out_prefix.name + "_component_maps.png")
    fig.savefig(out_png, dpi=args.dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] wrote component maps: {out_png}")
    return out_png


def write_component_table(buildings, out_prefix, args):
    rows = []
    for b in buildings:
        df = b["plot_df"]
        row = {"building_id": b["building_id"], "label": b["label"], "n_points": len(df)}

        for label, plot_col in [
            ("after_thermal_total", "thermal_total_displacement_plot"),
            ("uniform", "uniform_component_displacement"),
            ("height_dependent", "height_dependent_component_displacement"),
            ("differential", "differential_settlement_displacement"),
        ]:
            vals = pd.to_numeric(df[plot_col], errors="coerce").to_numpy(dtype=float)
            vals = vals[np.isfinite(vals)]
            if vals.size:
                row[f"{label}_max_abs_mm_p{args.map_percentile:.0f}"] = float(np.nanpercentile(np.abs(vals), args.map_percentile))
                row[f"{label}_max_abs_cm_p{args.map_percentile:.0f}"] = row[f"{label}_max_abs_mm_p{args.map_percentile:.0f}"] / 10.0
                row[f"{label}_min_mm"] = float(np.nanmin(vals))
                row[f"{label}_max_mm"] = float(np.nanmax(vals))
            else:
                row[f"{label}_max_abs_mm_p{args.map_percentile:.0f}"] = np.nan
                row[f"{label}_max_abs_cm_p{args.map_percentile:.0f}"] = np.nan
                row[f"{label}_min_mm"] = np.nan
                row[f"{label}_max_mm"] = np.nan

        closure = (
            df["thermal_total_displacement"]
            - df["uniform_component_displacement"]
            - df["height_dependent_component_displacement"]
            - df["differential_settlement_displacement"]
        )
        row["closure_rms_mm"] = float(np.sqrt(np.nanmean(np.asarray(closure, dtype=float) ** 2)))
        row["closure_max_abs_mm"] = float(np.nanmax(np.abs(np.asarray(closure, dtype=float))))
        rows.append(row)

    out_csv = out_prefix.with_name(out_prefix.name + "_component_summary.csv")
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    print(f"[OK] wrote component summary: {out_csv}")
    return out_csv


def build_arg_parser():
    p = argparse.ArgumentParser(description="Make 4-column building component maps from building_analysis_v11 output folders.")
    p.add_argument("--manifest", required=True, help="CSV with building_id,label,result_dir,order")
    p.add_argument("--original-csv", required=True, help="Original before-thermal-correction CSV")
    p.add_argument("--out", default="building_components_v3", help="Output directory/prefix")
    p.add_argument("--base-dir", default=".", help="Base directory for relative result_dir paths")
    p.add_argument("--title", default="Building component comparison")
    p.add_argument("--map-cmap", default="jet", help="Matplotlib cmap name or bluegreen, bluegreen_vivid, bluegreen_orange.")
    p.add_argument("--map-percentile", type=float, default=98.0)
    p.add_argument("--display-mode", choices=["signed", "settlement"], default="signed",
                   help="signed: show raw signed total fields. settlement: clip positive before/after total maps to 0.")
    p.add_argument("--colorbar-mode", choices=["column", "two"], default="two",
                   help="column: 4 colorbars, one per column. two: 2 grouped colorbars (columns 1-2 and columns 3-4).")
    p.add_argument("--before-vlim", type=parse_vlim, default=None)
    p.add_argument("--after-vlim", type=parse_vlim, default=None)
    p.add_argument("--uniform-vlim", type=parse_vlim, default=None)
    p.add_argument("--height-vlim", type=parse_vlim, default=None)
    p.add_argument("--differential-vlim", type=parse_vlim, default=None)
    p.add_argument("--add-basemap", action="store_true")
    p.add_argument("--basemap-provider", choices=sorted(BASEMAP_PROVIDERS.keys()), default="esri_gray",
                   help="Basemap provider. Use esri_satellite for imagery.")
    p.add_argument("--basemap-alpha", type=float, default=0.45, help="Basemap opacity, between 0 and 1.")
    p.add_argument("--point-size", type=float, default=13.0)
    p.add_argument("--point-alpha", type=float, default=1.0, help="Point opacity, 0 to 1.")
    p.add_argument("--point-edgecolor", default="none", help="Point outline color, e.g. none, black, white.")
    p.add_argument("--point-linewidth", type=float, default=0.0, help="Point outline linewidth.")
    p.add_argument("--point-marker", default="o", help="Matplotlib marker, e.g. o or s for square pixel-like markers.")
    p.add_argument("--n-edge", type=int, default=3)
    p.add_argument("--dpi", type=int, default=220)
    return p


def main(argv=None):
    args = build_arg_parser().parse_args(argv)

    out_arg = Path(args.out)
    if out_arg.suffix:
        out_prefix = out_arg.with_suffix("")
        out_prefix.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_arg.mkdir(parents=True, exist_ok=True)
        out_prefix = out_arg / out_arg.name

    base_dir = Path(args.base_dir).resolve()
    manifest = read_manifest(Path(args.manifest))
    original_all = pd.read_csv(args.original_csv)

    buildings = []
    for _, row in manifest.iterrows():
        b = read_building(row, base_dir)
        b["plot_df"] = prepare_components_for_building(b, original_all, args)
        buildings.append(b)

    print(f"[INFO] loaded {len(buildings)} buildings")
    make_component_maps(buildings, out_prefix, args)
    write_component_table(buildings, out_prefix, args)

    print("[OK] component map comparison completed")
    print(f"  output prefix: {out_prefix}")


if __name__ == "__main__":
    main()
