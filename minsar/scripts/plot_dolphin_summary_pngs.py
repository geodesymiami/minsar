#!/usr/bin/env python3
"""Generate MintPy-named summary PNGs from Dolphin GeoTIFF outputs."""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib import cm

from minsar.objects import message_rsmas
from minsar.utils.dolphin_plot_utils import TC_VMIN, read_geotiff, resolve_plot_files, resolve_run_paths

DESCRIPTION = (
    "Generate MintPy-style summary PNGs from Dolphin GeoTIFFs into dolphin/pic/. "
    "Skips per-interferogram plots. timeseries.png is optional (--timeseries)."
)
EXAMPLES = """Examples:
  plot_dolphin_summary_pngs.py --dir dolphin
  plot_dolphin_summary_pngs.py --dir dolphin --timeseries --dpi 120
  plot_dolphin_summary_pngs.py --dir dolphin --dry-run
  plot_dolphin_summary_pngs.py --dir dolphin --no-network
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dir", dest="dolphin_dir", type=Path, default=Path("dolphin"), help="Dolphin work directory (default: dolphin)")
    parser.add_argument("--outdir", type=Path, default=Path("pic"), help="Output directory relative to --dir (default: pic → dolphin/pic)")
    parser.add_argument("--dpi", type=int, default=150, help="Figure DPI (default: 150)")
    parser.add_argument("--timeseries", action="store_true", help="Also create timeseries.png (slow on long stacks)")
    parser.add_argument("--no-network", dest="plot_network", action="store_false", help="Skip network.png and coherenceMatrix.png")
    parser.add_argument("--dry-run", action="store_true", help="Print source → PNG mapping only")
    parser.add_argument("--tc-vmin", type=float, default=TC_VMIN, help=f"Temporal-coherence cutoff for maskTempCoh.png (default: {TC_VMIN})")
    parser.set_defaults(plot_network=True)
    return parser


def _subsample(data: np.ndarray, stride: int) -> np.ndarray:
    if stride <= 1:
        return data
    return data[::stride, ::stride]


def _read_preview(path: Path, stride: int) -> np.ndarray:
    with rasterio.open(path) as src:
        if stride <= 1:
            return np.ma.masked_equal(src.read(1, masked=True), src.nodata)
        out_h = max(1, math.ceil(src.height / stride))
        out_w = max(1, math.ceil(src.width / stride))
        data = src.read(
            1,
            out_shape=(out_h, out_w),
            resampling=rasterio.enums.Resampling.average,
            masked=True,
        )
        if src.nodata is not None:
            data = np.ma.masked_equal(data, src.nodata)
        return data


def _stride_for_shape(height: int, width: int, target: int = 512) -> int:
    longest = max(height, width)
    if longest <= target:
        return 1
    return max(1, int(math.ceil(longest / target)))


def _save_raster_png(
    out_path: Path,
    data: np.ndarray,
    *,
    cmap: str = "jet",
    vmin: float | None = None,
    vmax: float | None = None,
    title: str | None = None,
    cbar_label: str | None = None,
    dpi: int = 150,
) -> None:
    masked = np.ma.masked_invalid(np.asarray(data, dtype=float))
    if masked.count() == 0:
        print(f"Warning: no valid data for {out_path.name}; skipping", file=sys.stderr)
        return
    if vmin is None:
        vmin = float(np.nanpercentile(masked.compressed(), 2))
    if vmax is None:
        vmax = float(np.nanpercentile(masked.compressed(), 98))
    if vmin == vmax:
        vmax = vmin + 1.0

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(masked, cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
    ax.set_axis_off()
    if title:
        ax.set_title(title)
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    if cbar_label:
        cbar.set_label(cbar_label)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    print(f"Wrote {out_path}")


def _ifg_key(path: Path) -> str | None:
    stem = path.stem
    if stem.endswith(".int"):
        stem = stem[: -len(".int")]
    elif stem.endswith(".int.cor"):
        stem = stem[: -len(".int.cor")]
    if re.fullmatch(r"\d{8}_\d{8}", stem):
        return stem
    return None


def _ifg_pairs(interferograms: list[Path]) -> list[tuple[datetime, datetime, Path]]:
    pairs: list[tuple[datetime, datetime, Path]] = []
    for path in interferograms:
        key = _ifg_key(path)
        if key is None:
            continue
        d1 = datetime.strptime(key.split("_")[0], "%Y%m%d")
        d2 = datetime.strptime(key.split("_")[1], "%Y%m%d")
        pairs.append((d1, d2, path))
    pairs.sort(key=lambda item: (item[0], item[1]))
    return pairs


def _plot_network(out_path: Path, pairs: list[tuple[datetime, datetime, Path]], dpi: int) -> None:
    if not pairs:
        print("Warning: no interferogram pairs for network.png; skipping", file=sys.stderr)
        return
    dates = sorted({d for pair in pairs for d in pair[:2]})
    date_to_x = {d: i for i, d in enumerate(dates)}
    fig, ax = plt.subplots(figsize=(8, 5))
    for d1, d2, _path in pairs:
        ax.plot([date_to_x[d1], date_to_x[d2]], [0, (d2 - d1).days], "o-", color="steelblue", markersize=3, linewidth=0.8)
    ax.set_xlabel("Acquisition index")
    ax.set_ylabel("Temporal baseline (days)")
    ax.set_title("Interferogram network")
    tick_idx = np.linspace(0, len(dates) - 1, num=min(8, len(dates)), dtype=int)
    ax.set_xticks(tick_idx)
    ax.set_xticklabels([dates[i].strftime("%Y-%m-%d") for i in tick_idx], rotation=30, ha="right")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {out_path}")


def _plot_coherence_matrix(
    out_path: Path,
    pairs: list[tuple[datetime, datetime, Path]],
    cor_paths: list[Path],
    dpi: int,
) -> None:
    if not pairs or not cor_paths:
        print("Warning: skipping coherenceMatrix.png (missing IFGs or coherence rasters)", file=sys.stderr)
        return
    cor_by_key = {}
    for cor_path in cor_paths:
        key = _ifg_key(cor_path)
        if key is not None:
            cor_by_key[key] = cor_path
    means: list[float] = []
    for d1, d2, path in pairs:
        key = _ifg_key(path)
        cor_path = cor_by_key.get(key) if key else None
        if cor_path is None:
            continue
        data = read_geotiff(cor_path)
        valid = data[np.isfinite(data)]
        if valid.size == 0:
            continue
        means.append(float(np.nanmean(valid)))
    if not means:
        print("Warning: no coherence values for coherenceMatrix.png; skipping", file=sys.stderr)
        return
    n = len(means)
    side = int(math.ceil(math.sqrt(n)))
    matrix = np.full((side, side), np.nan, dtype=float)
    for idx, value in enumerate(means):
        matrix[idx // side, idx % side] = value
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(matrix, cmap="gray", vmin=0, vmax=1, interpolation="nearest")
    ax.set_title("Mean spatial coherence")
    ax.set_axis_off()
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {out_path}")


def _select_timeseries_panels(paths: list[Path], max_panels: int = 20) -> list[Path]:
    if len(paths) <= max_panels:
        return paths
    indices = np.linspace(0, len(paths) - 1, num=max_panels, dtype=int)
    return [paths[i] for i in indices]


def _plot_timeseries_png(out_path: Path, pair_paths: list[Path], dpi: int) -> None:
    if not pair_paths:
        print("Warning: no cumulative timeseries rasters; skipping timeseries.png", file=sys.stderr)
        return
    selected = _select_timeseries_panels(pair_paths)
    n = len(selected)
    ncols = int(math.ceil(math.sqrt(n)))
    nrows = int(math.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(2.5 * ncols, 2.5 * nrows))
    axes_arr = np.atleast_1d(axes).ravel()
    wrap_cm = cm.get_cmap("jet").copy()
    wrap_cm.set_bad(alpha=0)
    for ax, path in zip(axes_arr, selected):
        with rasterio.open(path) as src:
            stride = _stride_for_shape(src.height, src.width)
            data = _read_preview(path, stride)
        if isinstance(data, np.ma.MaskedArray):
            arr = data.filled(np.nan)
        else:
            arr = np.asarray(data, dtype=float)
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            ax.set_axis_off()
            continue
        vmax = max(abs(float(np.nanpercentile(finite, 2))), abs(float(np.nanpercentile(finite, 98))), 0.01)
        ax.imshow(arr, cmap=wrap_cm, vmin=-vmax, vmax=vmax, interpolation="nearest")
        ax.set_title(path.stem.split("_", 1)[-1], fontsize=8)
        ax.set_axis_off()
    for ax in axes_arr[n:]:
        ax.set_axis_off()
    fig.suptitle("Cumulative displacement (cm)", fontsize=10)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {out_path} ({n} panel(s))")


def _mean_coherence_preview(cor_paths: list[Path], stride: int, max_files: int = 40) -> np.ndarray | None:
    """Mean spatial coherence from subsampled IFG coherence rasters."""
    arrays: list[np.ndarray] = []
    for path in cor_paths[:max_files]:
        preview = _read_preview(path, stride)
        if isinstance(preview, np.ma.MaskedArray):
            arrays.append(preview.filled(np.nan).astype(np.float32))
        else:
            arrays.append(np.asarray(preview, dtype=np.float32))
    if not arrays:
        return None
    return np.nanmean(np.stack(arrays), axis=0)


def _plot_jobs(files: dict, *, plot_timeseries: bool, plot_network: bool, tc_vmin: float) -> list[tuple[str, str]]:
    jobs: list[tuple[str, str]] = []
    if files.get("velocity"):
        jobs.append((str(files["velocity"]), "velocity.png"))
    if files.get("temporal_coherence"):
        jobs.append((str(files["temporal_coherence"]), "temporalCoherence.png"))
        jobs.append((f"derived from {files['temporal_coherence']} (>= {tc_vmin})", "maskTempCoh.png"))
    if files.get("avg_spatial_paths"):
        jobs.append((f"mean of {len(files['avg_spatial_paths'])} *.int.cor.tif", "avgSpatialCoh.png"))
    if files.get("conncomp"):
        jobs.append((str(files["conncomp"]), "maskConnComp.png"))
    if files.get("height"):
        jobs.append((str(files["height"]), "geometryRadar.png"))
    if plot_network and files.get("interferograms"):
        jobs.append((f"{len(files['interferograms'])} IFGs", "network.png"))
        if files.get("avg_spatial_paths"):
            jobs.append(("IFG coherence means", "coherenceMatrix.png"))
    if plot_timeseries and files.get("timeseries_pairs"):
        jobs.append((f"{len(files['timeseries_pairs'])} pair rasters", "timeseries.png"))
    return jobs


def plot_dolphin_summary_pngs(
    dolphin_dir: Path,
    out_dir: Path,
    *,
    dpi: int = 150,
    plot_timeseries: bool = False,
    plot_network: bool = True,
    dry_run: bool = False,
    tc_vmin: float = TC_VMIN,
) -> int:
    """Create MintPy-named summary PNGs under out_dir."""
    _, dolphin_dir, ts_dir = resolve_run_paths(dolphin_dir)
    files = resolve_plot_files(dolphin_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = _plot_jobs(files, plot_timeseries=plot_timeseries, plot_network=plot_network, tc_vmin=tc_vmin)
    if dry_run:
        print(f"plot_dolphin_summary_pngs: would write to {out_dir}/")
        for src, name in jobs:
            print(f"  {name} <- {src}")
        return 0
    if not jobs:
        print("Error: no Dolphin rasters found to plot", file=sys.stderr)
        return 1

    ref_path = files.get("velocity") or files.get("temporal_coherence")
    if ref_path is None:
        candidates = list(ts_dir.glob("*.tif"))
        if not candidates:
            print("Error: no reference raster found under timeseries/", file=sys.stderr)
            return 1
        ref_path = candidates[0]
    with rasterio.open(ref_path) as src:
        stride = _stride_for_shape(src.height, src.width)

    if files.get("velocity"):
        vel = _read_preview(files["velocity"], stride)
        if isinstance(vel, np.ma.MaskedArray):
            vel_arr = vel.filled(np.nan)
        else:
            vel_arr = np.asarray(vel, dtype=float)
        finite = vel_arr[np.isfinite(vel_arr)]
        if finite.size and np.nanmax(np.abs(finite)) < 5:
            vel_arr = vel_arr * 100.0
            cbar = "cm/yr"
        else:
            cbar = "velocity"
        _save_raster_png(
            out_dir / "velocity.png",
            vel_arr,
            cmap="jet",
            title="Velocity",
            cbar_label=cbar,
            dpi=dpi,
        )

    if files.get("temporal_coherence"):
        tc = _read_preview(files["temporal_coherence"], stride)
        _save_raster_png(
            out_dir / "temporalCoherence.png",
            tc,
            cmap="gray",
            vmin=0,
            vmax=1,
            title="Temporal coherence",
            cbar_label="coherence",
            dpi=dpi,
        )
        if isinstance(tc, np.ma.MaskedArray):
            tc_arr = tc.filled(np.nan)
        else:
            tc_arr = np.asarray(tc, dtype=float)
        mask = np.where(np.isfinite(tc_arr) & (tc_arr >= tc_vmin), 1.0, 0.0)
        mask = np.ma.masked_where(~np.isfinite(tc_arr), mask)
        _save_raster_png(
            out_dir / "maskTempCoh.png",
            mask,
            cmap="gray",
            vmin=0,
            vmax=1,
            title=f"Mask (temporal coherence >= {tc_vmin})",
            cbar_label="mask",
            dpi=dpi,
        )

    if files.get("avg_spatial_paths"):
        avg = _mean_coherence_preview(files["avg_spatial_paths"], stride)
        if avg is not None:
            _save_raster_png(
                out_dir / "avgSpatialCoh.png",
                _subsample(avg, 1),
                cmap="gray",
                vmin=0,
                vmax=1,
                title="Average spatial coherence",
                cbar_label="coherence",
                dpi=dpi,
            )

    if files.get("conncomp"):
        conn = _read_preview(files["conncomp"], stride)
        _save_raster_png(
            out_dir / "maskConnComp.png",
            conn,
            cmap="gray",
            vmin=0,
            vmax=1,
            title="Connected-component intersection",
            cbar_label="label",
            dpi=dpi,
        )

    if files.get("height"):
        dem = _read_preview(files["height"], stride)
        _save_raster_png(
            out_dir / "geometryRadar.png",
            dem,
            cmap="terrain",
            title="Height",
            cbar_label="m",
            dpi=dpi,
        )

    if plot_network and files.get("interferograms"):
        pairs = _ifg_pairs(files["interferograms"])
        _plot_network(out_dir / "network.png", pairs, dpi=dpi)
        if files.get("avg_spatial_paths"):
            _plot_coherence_matrix(
                out_dir / "coherenceMatrix.png",
                pairs,
                files["avg_spatial_paths"],
                dpi=dpi,
            )

    if plot_timeseries and files.get("timeseries_pairs"):
        start = time.time()
        _plot_timeseries_png(out_dir / "timeseries.png", files["timeseries_pairs"], dpi=dpi)
        print(f"timeseries.png elapsed: {time.time() - start:.1f}s")

    return 0


def main(iargs: list[str] | None = None) -> int:
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    dolphin_dir = inps.dolphin_dir.expanduser()
    if not dolphin_dir.is_absolute():
        dolphin_dir = (Path.cwd() / dolphin_dir).resolve()
    out_dir = inps.outdir if inps.outdir.is_absolute() else (dolphin_dir / inps.outdir).resolve()

    message_rsmas.log(
        str(Path.cwd()),
        os.path.basename(__file__) + " " + " ".join(iargs if iargs is not None else sys.argv[1:]),
    )
    try:
        return plot_dolphin_summary_pngs(
            dolphin_dir,
            out_dir,
            dpi=inps.dpi,
            plot_timeseries=inps.timeseries,
            plot_network=inps.plot_network,
            dry_run=inps.dry_run,
            tc_vmin=inps.tc_vmin,
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
