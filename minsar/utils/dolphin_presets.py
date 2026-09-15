"""Dolphin CSLC preset names and parameters (lightweight; no h5py)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

# Default half-window / stride (also CLI help defaults). --half-window-preset names half-window only.
DEFAULT_HALF_WINDOW: tuple[int, int] = (6, 12)
DEFAULT_STRIDES: tuple[int, int] = (3, 6)
DEFAULT_PRESET = "standard"

# Single-run science presets (--dolphin-config). pydantic: no extra flags (Dolphin CLI defaults).
DEFAULT_DOLPHIN_CONFIG = "disp-s1"
DOLPHIN_CONFIG_CHOICES = ("disp-s1", "disp-s1-downloaded", "disp-s1-process", "pydantic")
DOLPHIN_CONFIG_HELP = (
    "single-run science preset: disp-s1 (legacy unwrap knobs), "
    "disp-s1-downloaded (OPERA L3 science; ministack 100, interp-sim 0.4; "
    "always_first for continuous run), "
    "disp-s1-process (local opera make_cfg), pydantic (Dolphin package defaults)"
)

# Legacy single-run unwrap/PS knobs (does not set ministack / compressed-SLC plan).
DISP_S1_SCIENCE = {
    "amp_dispersion_threshold": 0.2,
    "interpolation_cor_threshold": 0.3,
    "interpolation_similarity_threshold": 0.25,
    "max_radius": 71,
}

# OPERA L3 downloaded product algorithm_parameters (frame F38247 / dolphin 0.37.0 epoch).
# OPERA YAML uses last_per_ministack per historical batch (one ministack per product).
# Continuous single-run dolphin run needs always_first when ministack_size < n_slcs.
DISP_S1_DOWNLOADED_SCIENCE = {
    "amp_dispersion_threshold": 0.2,
    "interpolation_cor_threshold": 0.3,
    "interpolation_similarity_threshold": 0.4,
    "max_radius": 71,
    "ministack_size": 100,
    "max_num_compressed": 100,
    "compressed_slc_plan": "ALWAYS_FIRST",
    "output_reference_idx": 0,
}

# additions/disp-s1/disp_s1_process.make_cfg local opera produce.
DISP_S1_PROCESS_SCIENCE = {
    "amp_dispersion_threshold": 0.25,
    "interpolation_cor_threshold": 0.001,
    "interpolation_similarity_threshold": 0.4,
    "max_radius": 150,
}

# Dolphin PsOptions / PreprocessOptions defaults (disp-s1-env; no flags passed for pydantic).
PYDANTIC_SCIENCE = {
    "amp_dispersion_threshold": 0.25,
    "interpolation_cor_threshold": 0.25,
    "interpolation_similarity_threshold": 0.3,
    "max_radius": 51,
}

DOLPHIN_CONFIG_SCIENCE: dict[str, dict[str, float | int | str]] = {
    "disp-s1": DISP_S1_SCIENCE,
    "disp-s1-downloaded": DISP_S1_DOWNLOADED_SCIENCE,
    "disp-s1-process": DISP_S1_PROCESS_SCIENCE,
    "pydantic": PYDANTIC_SCIENCE,
}

# Named phase-linking half-windows (Y, X). Stride is --stride (default 3 6).
DOLPHIN_PRESETS: dict[str, tuple[int, int]] = {
    "standard": DEFAULT_HALF_WINDOW,
    "dry": (5, 11),
    "wet": (9, 18),
    "arctic": (9, 19),
}

DOLPHIN_PRESET_CHOICES = tuple(DOLPHIN_PRESETS)

DOLPHIN_PRESET_HELP = (
    "phase-linking half-window: standard 6x12, dry 5x11, wet 9x18, arctic 9x19 "
    f"(Default: {DEFAULT_PRESET})"
)

NO_PRESET_NAMING_HELP = (
    "Omit half-window from HE5 method-string "
    "(default: dolphin / dolphinDispS1Downloaded / dolphinDispS1Process / …; "
    "with naming on, append Dry/Wet/Arctic)"
)

# HE5 label for downloaded --data-type disp-s1 (project token DISPS1).
OPERA_DISP_METHOD_STRING = "dispS1"
# HE5 label for --data-type {safe,cslc} --dolphin-mode opera (local DISP-S1 produce).
MODE_OPERA_DISP_METHOD_STRING = "dolphinModeOpera"

# Shared camelCase tokens for --dolphin-config (project name + HE5). Empty = default disp-s1.
DOLPHIN_CONFIG_METHOD_TOKENS: dict[str, str] = {
    "disp-s1": "",
    "disp-s1-downloaded": "DispS1Downloaded",
    "disp-s1-process": "DispS1Process",
    "pydantic": "Pydantic",
}

METHOD_STRING_HELP = (
    "HE5 post_processing_method label (e.g. dolphin, dolphinDispS1Downloaded, "
    "dolphinDispS1Process, dolphinDry, dispS1, dolphinModeOpera); used in .he5 filename "
    "and metadata (default: dolphin, dispS1, or dolphinModeOpera by input kind)"
)


def normalize_dolphin_config(value: str) -> str:
    token = str(value).strip().lower().replace("_", "-")
    if token not in DOLPHIN_CONFIG_CHOICES:
        raise ValueError(
            f"invalid --dolphin-config {value!r}; use {', '.join(DOLPHIN_CONFIG_CHOICES)}"
        )
    return token


def dolphin_config_passthrough_tokens(preset: str) -> list[str]:
    """Return dolphin config CLI tokens for a single-run science preset (empty for pydantic)."""
    key = normalize_dolphin_config(preset)
    if key == "pydantic":
        return []
    values = DOLPHIN_CONFIG_SCIENCE[key]
    tokens = [
        "--ps-options.amp-dispersion-threshold",
        str(values["amp_dispersion_threshold"]),
        "--unwrap-options.preprocess-options.interpolation-cor-threshold",
        str(values["interpolation_cor_threshold"]),
        "--unwrap-options.preprocess-options.interpolation-similarity-threshold",
        str(values["interpolation_similarity_threshold"]),
        "--unwrap-options.preprocess-options.max-radius",
        str(values["max_radius"]),
    ]
    if "ministack_size" in values:
        tokens.extend(["--phase-linking.ministack-size", str(values["ministack_size"])])
    if "max_num_compressed" in values:
        tokens.extend(["--phase-linking.max-num-compressed", str(values["max_num_compressed"])])
    if "compressed_slc_plan" in values:
        # dolphin config CLI expects enum names (LAST_PER_MINISTACK), not YAML snake_case.
        plan = str(values["compressed_slc_plan"]).upper()
        tokens.extend(["--phase-linking.compressed-slc-plan", plan])
    if "output_reference_idx" in values:
        tokens.extend(["--phase-linking.output-reference-idx", str(values["output_reference_idx"])])
    return tokens


def single_run_science_passthrough(
    preset: str,
    user_tokens: list[str] | None = None,
) -> list[str]:
    """Preset science flags for single-run; explicit user --section.option flags override."""
    from minsar.utils.isce3_dolphin_experiment import parse_passthrough_pairs

    defaults = dolphin_config_passthrough_tokens(preset)
    merged: dict[str, str | None] = dict(parse_passthrough_pairs(defaults))
    for key, val in parse_passthrough_pairs(user_tokens or []):
        merged[key] = val
    out: list[str] = []
    for key, val in merged.items():
        flag = f"--{key}"
        if val is None:
            out.append(flag)
        else:
            out.extend([flag, val])
    return out


def normalize_dolphin_preset(value: str) -> str:
    token = str(value).strip().lower().replace("_", "-")
    if token == "auto":
        raise ValueError("removed --half-window-preset auto; use --half-window 7 14 --stride 1 1")
    if token == "disp-s1":
        raise ValueError("removed --half-window-preset disp-s1; use --half-window 8 16")
    if token not in DOLPHIN_PRESETS:
        raise ValueError(f"invalid --half-window-preset {value!r}; use {', '.join(DOLPHIN_PRESET_CHOICES)}")
    return token


def dolphin_config_name_token(dolphin_config: str | None = None) -> str:
    """Project-name / HE5 middle token for --dolphin-config (empty for default disp-s1)."""
    key = normalize_dolphin_config(dolphin_config or DEFAULT_DOLPHIN_CONFIG)
    return DOLPHIN_CONFIG_METHOD_TOKENS[key]


def dolphin_method_string(
    preset: str,
    dolphin_config: str | None = None,
    *,
    preset_naming: bool = True,
) -> str:
    """HE5 post_processing_method for single-run Dolphin.

    Combines --dolphin-config and --half-window-preset: disp-s1 + standard → dolphin;
    disp-s1-downloaded → dolphinDispS1Downloaded; disp-s1-process → dolphinDispS1Process;
    wet → …Wet. preset_naming=False skips the half-window token only.
    """
    config_token = dolphin_config_name_token(dolphin_config)
    window_key = normalize_dolphin_preset(preset) if preset_naming else DEFAULT_PRESET
    window_token = "" if window_key == DEFAULT_PRESET else window_key.capitalize()
    return "dolphin" + config_token + window_token


def normalize_method_string(value: str) -> str:
    """Validate HE5 method label (alphanumeric, e.g. dolphin or dolphinModeOpera)."""
    token = str(value).strip()
    if not token or not re.fullmatch(r"[A-Za-z0-9]+", token):
        raise ValueError(
            f"invalid method-string {value!r}; use alphanumeric labels like dolphin, dolphinDry, dolphinModeOpera"
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

    Order: --half-window-preset half-window and default stride → imported YAML → explicit CLI.
    """
    key = normalize_dolphin_preset(preset)
    hw = DOLPHIN_PRESETS[key]
    st = DEFAULT_STRIDES
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
