"""Dolphin CSLC preset names and parameters (lightweight; no h5py)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

# Default half-window / stride when --window-preset standard (also CLI help defaults).
DEFAULT_HALF_WINDOW: tuple[int, int] = (6, 12)
DEFAULT_STRIDES: tuple[int, int] = (3, 6)
DEFAULT_PRESET = "standard"

# auto: dolphin package defaults (no --sy/--sx/--hwy/--hwx on CLI).
# disp-s1: OPERA DISP-S1 base algorithm_parameters (tools/disp-s1/configs).
DOLPHIN_PRESETS: dict[str, dict[str, tuple[int, int] | None]] = {
    "auto": {"strides": None, "half_window": None},
    "standard": {"strides": DEFAULT_STRIDES, "half_window": DEFAULT_HALF_WINDOW},
    "dry": {"strides": DEFAULT_STRIDES, "half_window": (5, 11)},
    "wet": {"strides": DEFAULT_STRIDES, "half_window": (9, 18)},
    "arctic": {"strides": DEFAULT_STRIDES, "half_window": (9, 19)},
    "disp-s1": {"strides": DEFAULT_STRIDES, "half_window": (8, 16)},
}

DOLPHIN_PRESET_CHOICES = tuple(DOLPHIN_PRESETS)

DOLPHIN_PRESET_HELP = (
    "auto, standard, dry, wet, arctic, disp-s1 (default: standard). "
    "hw: auto 7x14, standard 6x12, dry 5x11, wet 9x18, arctic 9x19, disp-s1 8x16. "
    "stride: auto 1x1, others 3x6 (override with --stride)."
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
        raise ValueError(f"invalid --window-preset {value!r}; use {', '.join(DOLPHIN_PRESET_CHOICES)}")
    return token


def dolphin_method_string(preset: str) -> str:
    """HE5 post_processing_method label for a dolphin CSLC preset (e.g. dolphinStandard)."""
    key = normalize_dolphin_preset(preset)
    if key == "disp-s1":
        return "dolphinDispS1"
    return "dolphin" + key.capitalize()


def normalize_method_string(value: str) -> str:
    """Validate HE5 method label (alphanumeric, e.g. dolphinStandard)."""
    token = str(value).strip()
    if not token or not re.fullmatch(r"[A-Za-z0-9]+", token):
        raise ValueError(
            f"invalid method-string {value!r}; use alphanumeric labels like dolphin, dolphinAuto, dolphinStandard"
        )
    return token


def half_window_yx_from_mapping(data: dict) -> tuple[int, int] | None:
    """Return (y, x) from phase_linking.half_window, or None."""
    pl = data.get("phase_linking")
    if not isinstance(pl, dict):
        return None
    hw = pl.get("half_window")
    if not isinstance(hw, dict):
        return None
    if "y" not in hw or "x" not in hw:
        return None
    return int(hw["y"]), int(hw["x"])


def strides_yx_from_mapping(data: dict) -> tuple[int, int] | None:
    """Return (y, x) from output_options.strides, or None."""
    out = data.get("output_options")
    if not isinstance(out, dict):
        return None
    strides = out.get("strides")
    if not isinstance(strides, dict):
        return None
    if "y" not in strides or "x" not in strides:
        return None
    return int(strides["y"]), int(strides["x"])


def resolve_half_window_strides(
    preset: str,
    *,
    half_window: tuple[int, int] | None = None,
    strides: tuple[int, int] | None = None,
    imported: dict | None = None,
) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """Resolve effective (half_window_yx, strides_yx).

    Order: preset → imported YAML → explicit CLI overrides.
    None means omit on dolphin CLI (package defaults for ``auto``).
    """
    key = normalize_dolphin_preset(preset)
    spec = DOLPHIN_PRESETS[key]
    hw = spec["half_window"]
    st = spec["strides"]
    if imported is not None:
        imp_hw = half_window_yx_from_mapping(imported)
        imp_st = strides_yx_from_mapping(imported)
        if imp_hw is not None:
            hw = imp_hw
        if imp_st is not None:
            st = imp_st
    if half_window is not None:
        hw = half_window
    if strides is not None:
        st = strides
    return hw, st


def dolphin_window_cli_flags(
    half_window: tuple[int, int] | None,
    strides: tuple[int, int] | None,
    *,
    run_interpolation: bool = True,
) -> str:
    """CLI flags for run_interpolation plus optional strides and half-window."""
    parts: list[str] = []
    if run_interpolation:
        parts.append("--unwrap-options.run-interpolation")
    if strides is not None:
        sy, sx = strides
        parts.append(f"--sy {sy} --sx {sx}")
    if half_window is not None:
        hwy, hwx = half_window
        parts.append(f"--hwy {hwy} --hwx {hwx}")
    return " ".join(parts)


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
