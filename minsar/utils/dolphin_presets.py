"""Dolphin CSLC preset names and parameters (lightweight; no h5py)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
# auto: dolphin package defaults (no --sy/--sx/--hwy/--hwx on CLI).
DOLPHIN_PRESETS: dict[str, dict[str, tuple[int, int] | None]] = {
    "auto": {"strides": None, "half_window": None},
    "standard": {"strides": (3, 6), "half_window": (8, 16)},
    "dry": {"strides": (3, 6), "half_window": (6, 12)},
    "wet": {"strides": (3, 6), "half_window": (9, 18)},
    "arctic": {"strides": (3, 6), "half_window": (9, 19)},
}

DOLPHIN_PRESET_CHOICES = tuple(DOLPHIN_PRESETS)

DOLPHIN_PRESET_HELP = (
    "{auto, standard, dry, wet, arctic}, default: auto. "
    "Strides: auto 1x1, others 3x6. hw: 7x14, 8x16, 6x12, 9x18, 9x19."
)

NO_PRESET_NAMING_HELP = (
    "Use method-string dolphin (not dolphinAuto/dolphinStandard) in HE5 filename; preset naming is on by default"
)

OPERA_DISP_METHOD_STRING = "operaDisp"

METHOD_STRING_HELP = (
    "HE5 post_processing_method label (e.g. dolphinAuto, dolphinStandard, operaDisp); "
    "used in .he5 filename and metadata (default: dolphin or operaDisp by input kind)"
)


def normalize_dolphin_preset(value: str) -> str:
    token = str(value).strip().lower().replace("_", "-")
    if token not in DOLPHIN_PRESETS:
        raise ValueError(f"invalid preset {value!r}; use {', '.join(DOLPHIN_PRESET_CHOICES)}")
    return token


def dolphin_method_string(preset: str) -> str:
    """HE5 post_processing_method label for a dolphin CSLC preset (e.g. dolphinStandard)."""
    key = normalize_dolphin_preset(preset)
    return "dolphin" + key.capitalize()


def normalize_method_string(value: str) -> str:
    """Validate HE5 method label (alphanumeric, e.g. dolphinStandard)."""
    token = str(value).strip()
    if not token or not re.fullmatch(r"[A-Za-z0-9]+", token):
        raise ValueError(
            f"invalid method-string {value!r}; use alphanumeric labels like dolphin, dolphinAuto, dolphinStandard"
        )
    return token


_OPERA_BURST_TAG_RE = re.compile(r"T\d+-\d+-IW\d+", re.IGNORECASE)


def count_opera_cslc_bursts(data_dir: Path | str = "data") -> int:
    """Return distinct OPERA burst count under data/ (frame + IW, minimum 1)."""
    burst_tags: set[str] = set()
    root = Path(data_dir)
    for path in sorted(root.glob("OPERA_L2_CSLC-S1_*.h5")):
        match = _OPERA_BURST_TAG_RE.search(path.name)
        if match:
            burst_tags.add(match.group(0).upper())
    return max(1, len(burst_tags))


def dolphin_worker_counts(cpus_per_node: int, n_bursts_aoi: int) -> tuple[int, int, int]:
    """Return (n_parallel_bursts, threads_per_worker, n_parallel_jobs)."""
    cpus = max(1, int(cpus_per_node))
    n_bursts = max(1, int(n_bursts_aoi))
    n_parallel = max(1, min(n_bursts, cpus // 4))
    threads = max(1, cpus // n_parallel)
    n_unwrap = max(1, cpus // 4)
    return n_parallel, threads, n_unwrap


def dolphin_worker_cli_flags(cpus_per_node: int, n_bursts_aoi: int) -> str:
    """dolphin config CLI flags for burst/thread parallelism on one node."""
    n_parallel, threads, n_unwrap = dolphin_worker_counts(cpus_per_node, n_bursts_aoi)
    return (
        f"--n-parallel-bursts {n_parallel} "
        f"--worker-settings.threads-per-worker {threads} "
        f"--unwrap-options.n-parallel-jobs {n_unwrap}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Dolphin preset and worker-flag helpers.")
    parser.add_argument("--count-bursts", action="store_true", help="print burst count from --data-dir")
    parser.add_argument("--data-dir", default="data", help="OPERA CSLC directory (default: data)")
    parser.add_argument("--cpus", type=int, help="node CPUs for worker CLI flags")
    parser.add_argument("--n-bursts", type=int, help="burst count (default: from --data-dir)")
    args = parser.parse_args()
    if args.count_bursts:
        print(count_opera_cslc_bursts(args.data_dir))
        return 0
    if args.cpus is None:
        parser.error("--cpus is required unless --count-bursts is set")
    n_bursts = args.n_bursts if args.n_bursts is not None else count_opera_cslc_bursts(args.data_dir)
    print(dolphin_worker_cli_flags(args.cpus, n_bursts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
