"""Shared snaphu memory estimates for unwrap job sizing (MiaplPy LAUNCHER PPN, dolphin n_parallel_jobs)."""

from __future__ import annotations

import math
import os
from pathlib import Path

BYTES_PER_PIXEL = 420
# Reserve slots below floor(mem/node) so concurrent snaphu startups
# (many large mallocs at once) do not fail at the node memory cliff.
PPN_SAFETY_MARGIN = 2


def load_queue_row(queue_name: str) -> dict:
    """Return queues.cfg row for PLATFORM_NAME and QUEUENAME."""
    minsar_home = os.getenv("MINSAR_HOME") or os.getenv("RSMASINSAR_HOME")
    if minsar_home:
        cfg = Path(minsar_home) / "minsar" / "defaults" / "queues.cfg"
    else:
        cfg = Path(__file__).resolve().parents[1] / "defaults" / "queues.cfg"
    if not cfg.is_file():
        raise FileNotFoundError(f"queues.cfg not found: {cfg}")

    platform = os.getenv("PLATFORM_NAME", "stampede3")
    with open(cfg, "r") as handle:
        lines = [ln.strip() for ln in handle if ln.strip() and not ln.startswith("#")]
    header = lines[0].split()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < len(header):
            continue
        row = dict(zip(header, parts))
        if row.get("PLATFORM_NAME") == platform and row.get("QUEUENAME") == queue_name:
            return {
                "queue": queue_name,
                "cpus_per_node": int(row["CPUS_PER_NODE"]),
                "mem_per_node_mb": int(row["MEM_PER_NODE"]),
                "max_nodes_pj": int(row["MAX_NODES_PJ"]),
                "max_walltime": row.get("MAX_WALLTIME", "n/a"),
            }
    raise RuntimeError(
        f"No queues.cfg row for PLATFORM_NAME={platform} QUEUENAME={queue_name} in {cfg}"
    )


def mem_per_task_mib(
    length: int,
    width: int,
    bytes_per_pixel: float = BYTES_PER_PIXEL,
    num_tiles: int = 1,
) -> float:
    """Estimate snaphu RSS per unwrap task (MiB).

    Single-tile: LENGTH*WIDTH*bytes_per_pixel.
    Tiled (num_tiles>1): divide by num_tiles (tile-local work).
    """
    full = length * width * bytes_per_pixel / (1024.0 ** 2)
    ntiles = max(1, int(num_tiles))
    if ntiles <= 1:
        return full
    return full / float(ntiles)


def compute_ppn(
    mem_mib: float,
    mem_per_node_mb: int,
    cpus_per_node: int,
    num_tiles: int = 1,
    safety_margin: int = PPN_SAFETY_MARGIN,
) -> int:
    """Parallel unwrap count from memory, capped by tile parallelism when num_tiles>1."""
    if mem_mib <= 0:
        mem_ppn = cpus_per_node
    else:
        raw_ppn = int(math.floor(mem_per_node_mb / mem_mib))
        mem_ppn = min(
            cpus_per_node,
            max(1, raw_ppn - safety_margin),
        )
    ntiles = max(1, int(num_tiles))
    if ntiles <= 1:
        return mem_ppn
    cpu_ppn = max(1, int(cpus_per_node // ntiles))
    return min(mem_ppn, cpu_ppn)


def max_width_for_ppn48(
    length: int,
    mem_per_node_mb: int,
    bytes_per_pixel: float = BYTES_PER_PIXEL,
    cpus_for_ref: int = 48,
) -> int:
    """Max WIDTH at fixed LENGTH for reference concurrent job count."""
    max_mem_per_task = mem_per_node_mb / float(cpus_for_ref)
    max_pixels = max_mem_per_task * (1024.0 ** 2) / bytes_per_pixel
    return max(1, int(math.floor(max_pixels / length)))
