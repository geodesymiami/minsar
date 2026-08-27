#!/usr/bin/env python3
"""Print memory-aware dolphin unwrap n_parallel_jobs from stitched ifg size.

Reads LENGTH x WIDTH from dolphin/interferograms/*.int.tif (after dolphin_wrapped).
Uses the same snaphu memory model as resize_miaplpy_unwrap_jobfiles.py.

Examples:
  resize_dolphin_unwrap_jobfile.py .
  resize_dolphin_unwrap_jobfile.py . --dry-run
  resize_dolphin_unwrap_jobfile.py . --queue skx-dev --dolphin-config dolphin_config.yaml
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from minsar.utils.unwrap_memory import (
    BYTES_PER_PIXEL,
    compute_ppn,
    load_queue_row,
    max_width_for_ppn48,
    mem_per_task_mib,
)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compute dolphin unwrap n_parallel_jobs from stitched ifg size.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "project_dir",
        type=str,
        help="ISCE3 project directory containing dolphin/ and dolphin_config.yaml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary line(s); do not print bare integer on stdout",
    )
    parser.add_argument(
        "--queue",
        type=str,
        default=None,
        help="Queue name (default: from run_*_dolphin_unwrap.job #SBATCH -p, else QUEUENAME)",
    )
    parser.add_argument(
        "--dolphin-config",
        type=Path,
        default=Path("dolphin_config.yaml"),
        help="Dolphin YAML for unwrap_method and snaphu tile settings (default: dolphin_config.yaml)",
    )
    parser.add_argument(
        "--bytes-per-pixel",
        type=float,
        default=BYTES_PER_PIXEL,
        help=f"Snaphu memory model in bytes/pixel (default: {BYTES_PER_PIXEL})",
    )
    return parser


def resolve_project_dir(path_str: str) -> Path:
    path = Path(path_str).expanduser().resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"project directory not found: {path}")
    return path


def find_representative_ifg(project_dir: Path) -> Path:
    ifg_dir = project_dir / "dolphin" / "interferograms"
    if not ifg_dir.is_dir():
        raise FileNotFoundError(
            f"Missing {ifg_dir}. Run dolphin_wrapped first."
        )
    candidates = sorted(ifg_dir.glob("*.int.tif"))
    if not candidates:
        raise FileNotFoundError(
            f"No stitched *.int.tif under {ifg_dir}. Run dolphin_wrapped first."
        )
    return candidates[0]


def read_ifg_size(ifg_path: Path) -> tuple[int, int]:
    try:
        from dolphin.io import get_raster_xysize
    except ImportError as exc:
        raise RuntimeError(
            "dolphin is required to read ifg dimensions; run inside the SWEETS pixi environment"
        ) from exc
    width, length = get_raster_xysize(ifg_path)
    return int(length), int(width)


def infer_queue_from_jobfiles(project_dir: Path) -> str | None:
    run_dir = project_dir / "run_files"
    if not run_dir.is_dir():
        return None
    for job in sorted(run_dir.glob("run_*_dolphin_unwrap.job")):
        text = job.read_text(errors="replace")
        match = re.search(r"^#SBATCH\s+-p\s+(\S+)", text, re.M)
        if match:
            return match.group(1)
    return None


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


def _unwrap_settings(config_path: Path) -> tuple[str, int, int]:
    """Return (unwrap_method, num_snaphu_tiles, cpu_tile_parallelism)."""
    cfg = _load_yaml(config_path)
    unwrap = cfg.get("unwrap_options") or {}
    method = str(unwrap.get("unwrap_method", "snaphu")).lower()
    snaphu = unwrap.get("snaphu_options") or {}
    ntiles_raw = snaphu.get("ntiles", (1, 1))
    if isinstance(ntiles_raw, int):
        ntiles = (ntiles_raw, ntiles_raw)
    elif isinstance(ntiles_raw, (list, tuple)) and len(ntiles_raw) >= 2:
        ntiles = (int(ntiles_raw[0]), int(ntiles_raw[1]))
    else:
        ntiles = (1, 1)
    num_tiles = max(1, ntiles[0] * ntiles[1])
    n_parallel_tiles = max(1, int(snaphu.get("n_parallel_tiles", 1)))
    return method, num_tiles, n_parallel_tiles


def compute_n_parallel_jobs(
    length: int,
    width: int,
    queue_info: dict,
    unwrap_method: str,
    num_snaphu_tiles: int,
    cpu_tile_parallelism: int,
    bytes_per_pixel: float,
) -> tuple[int, float]:
    method = unwrap_method.lower()
    if method == "spurt":
        return 1, 0.0
    if method in {"icu", "phass"}:
        mem_mib = mem_per_task_mib(length, width, bytes_per_pixel * 2.0, num_tiles=1)
        n_jobs = compute_ppn(
            mem_mib,
            queue_info["mem_per_node_mb"],
            queue_info["cpus_per_node"],
            num_tiles=1,
        )
        return max(1, min(n_jobs, max(1, queue_info["cpus_per_node"] // 4))), mem_mib

    # snaphu and whirlwind: same 420 B/pixel model (whirlwind TBD by measurement)
    mem_mib = mem_per_task_mib(
        length, width, bytes_per_pixel, num_tiles=num_snaphu_tiles
    )
    n_jobs = compute_ppn(
        mem_mib,
        queue_info["mem_per_node_mb"],
        queue_info["cpus_per_node"],
        num_tiles=cpu_tile_parallelism,
    )
    return n_jobs, mem_mib


def main(iargs: list[str] | None = None) -> int:
    parser = create_parser()
    inps = parser.parse_args(args=iargs)

    project_dir = resolve_project_dir(inps.project_dir)
    ifg_path = find_representative_ifg(project_dir)
    length, width = read_ifg_size(ifg_path)

    config_path = inps.dolphin_config
    if not config_path.is_absolute():
        config_path = project_dir / config_path
    unwrap_method, num_snaphu_tiles, cpu_tile_parallelism = _unwrap_settings(config_path)

    queue_name = (
        inps.queue
        or infer_queue_from_jobfiles(project_dir)
        or os.getenv("QUEUENAME")
        or "skx-dev"
    )
    queue_info = load_queue_row(queue_name)
    queue_info["queue"] = queue_name

    n_jobs, mem_mib = compute_n_parallel_jobs(
        length,
        width,
        queue_info,
        unwrap_method,
        num_snaphu_tiles,
        cpu_tile_parallelism,
        inps.bytes_per_pixel,
    )
    mem_gb = int(round(queue_info["mem_per_node_mb"] / 1000.0))
    www = max_width_for_ppn48(
        length,
        queue_info["mem_per_node_mb"],
        inps.bytes_per_pixel,
        cpus_for_ref=queue_info["cpus_per_node"],
    )

    summary = (
        f"Queue {queue_name} with node memory {mem_gb} GB, ifg size {length}x{width}. "
        f"For {queue_info['cpus_per_node']} simultaneous jobs max ifg width is {length}x{www}"
    )
    detail = (
        f"unwrap_method={unwrap_method}  snaphu_tiles={num_snaphu_tiles}  "
        f"cpu_tile_parallelism={cpu_tile_parallelism}  bytes_per_pixel={inps.bytes_per_pixel:g}  "
        f"mem_per_job={mem_mib:.1f} MiB  n_parallel_jobs={n_jobs}"
    )

    if inps.dry_run:
        print(summary)
        print(detail)
        return 0

    print(summary, file=sys.stderr)
    print(detail, file=sys.stderr)
    print(n_jobs)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
