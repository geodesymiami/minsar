#!/usr/bin/env python3
"""Load / merge Dolphin algorithm YAML from a file or OPERA DISP-S1 NetCDF."""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any

DESCRIPTION = (
    "Load a dolphin_config.yaml or extract algorithm YAML from an OPERA DISP-S1 .nc, "
    "and merge algorithm fields into a generated Dolphin config "
    "(excluding ministack-related and MinSAR-owned fields)."
)
EXAMPLE = """Examples:
  merge_dolphin_algo_config.py --target dolphin_config.yaml --from algo.yaml --hwy 6 --hwx 12 --sy 3 --sx 6
  merge_dolphin_algo_config.py --target dolphin_standard_config.yaml --from product.nc --hwy 8 --hwx 16 --sy 3 --sx 6
"""

DOLPHIN_CONFIG_SUFFIXES = {".yaml", ".yml", ".nc"}

# Top-level keys taken from an imported algorithm YAML (deep-merged into target).
MERGE_TOP_LEVEL = (
    "ps_options",
    "phase_linking",
    "interferogram_network",
    "unwrap_options",
    "output_options",
    "similarity_options",
    "timeseries_options",
    "correction_options",
)

# Dropped from phase_linking (MinSAR / --ministack-size owns these).
PHASE_LINKING_DROP = frozenset(
    {
        "ministack_size",
        "max_num_compressed",
        "compressed_slc_plan",
    }
)

# Never overwrite these on the generated target.
TOP_LEVEL_KEEP_FROM_TARGET = frozenset(
    {
        "cslc_file_list",
        "work_directory",
        "input_options",
        "worker_settings",
        "log_file",
        "keep_paths_relative",
        "mask_file",
    }
)

OUTPUT_OPTIONS_KEEP_FROM_TARGET = frozenset(
    {
        "bounds",
        "bounds_wkt",
        "bounds_epsg",
    }
)


def is_dolphin_config_path(value: str | Path | None) -> bool:
    """True when path suffix is .yaml, .yml, or .nc."""
    if value is None:
        return False
    return Path(value).suffix.lower() in DOLPHIN_CONFIG_SUFFIXES


def _load_yaml_mapping(text: str) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        from ruamel.yaml import YAML

        data = YAML(typ="safe").load(text)
    else:
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("config YAML root must be a mapping")
    return data


def _dump_yaml_mapping(data: dict[str, Any], path: Path) -> None:
    try:
        import yaml
    except ImportError:
        from ruamel.yaml import YAML

        y = YAML()
        y.default_flow_style = False
        with path.open("w", encoding="utf-8") as handle:
            y.dump(data, handle)
    else:
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, default_flow_style=False, sort_keys=False)


def load_algo_mapping_from_yaml(path: Path) -> dict[str, Any]:
    """Load algorithm YAML mapping from a .yaml/.yml file."""
    return _load_yaml_mapping(path.read_text(encoding="utf-8"))


def load_algo_mapping_from_nc(path: Path) -> dict[str, Any]:
    """Extract algorithm YAML from an OPERA DISP-S1 NetCDF and parse it."""
    from minsar.utils.extract_dolphin_config_yaml import _rank, find_config_candidates

    candidates = find_config_candidates(path)
    if not candidates:
        raise ValueError(f"no algorithm_parameters_yaml (or similar) in {path}")
    candidates.sort(key=lambda item: _rank(item[0], item[1]))
    _name, text = candidates[0]
    return _load_yaml_mapping(text)


def load_algo_mapping(path: Path) -> dict[str, Any]:
    """Load algorithm mapping from .yaml/.yml or .nc."""
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return load_algo_mapping_from_yaml(path)
    if suffix == ".nc":
        return load_algo_mapping_from_nc(path)
    raise ValueError(f"unsupported dolphin config path {path}; use .yaml, .yml, or .nc")


def strip_ministack_keys(algo: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of algo with ministack-related phase_linking keys removed."""
    out = copy.deepcopy(algo)
    pl = out.get("phase_linking")
    if isinstance(pl, dict):
        for key in PHASE_LINKING_DROP:
            pl.pop(key, None)
    return out


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge overlay into base (dicts only); lists/scalars replace."""
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def algorithm_overlay_for_merge(imported: dict[str, Any]) -> dict[str, Any]:
    """Build the allowlisted overlay from an imported algorithm YAML."""
    cleaned = strip_ministack_keys(imported)
    overlay: dict[str, Any] = {}
    for key in MERGE_TOP_LEVEL:
        if key not in cleaned:
            continue
        value = cleaned[key]
        if key == "output_options" and isinstance(value, dict):
            trimmed = {k: v for k, v in value.items() if k not in OUTPUT_OPTIONS_KEEP_FROM_TARGET}
            if trimmed:
                overlay[key] = trimmed
        elif value is not None:
            overlay[key] = value
    return overlay


def apply_window_and_ministack(
    data: dict[str, Any],
    *,
    half_window: tuple[int, int] | None = None,
    strides: tuple[int, int] | None = None,
    ministack_size: int | None = None,
    run_interpolation: bool = True,
) -> dict[str, Any]:
    """Force half-window, strides, optional ministack, and run_interpolation on data."""
    out = copy.deepcopy(data)
    if half_window is not None:
        pl = out.setdefault("phase_linking", {})
        if not isinstance(pl, dict):
            pl = {}
            out["phase_linking"] = pl
        hwy, hwx = half_window
        pl["half_window"] = {"y": int(hwy), "x": int(hwx)}
    if strides is not None:
        oo = out.setdefault("output_options", {})
        if not isinstance(oo, dict):
            oo = {}
            out["output_options"] = oo
        sy, sx = strides
        oo["strides"] = {"y": int(sy), "x": int(sx)}
    if ministack_size is not None:
        pl = out.setdefault("phase_linking", {})
        if not isinstance(pl, dict):
            pl = {}
            out["phase_linking"] = pl
        pl["ministack_size"] = int(ministack_size)
    if run_interpolation:
        uo = out.setdefault("unwrap_options", {})
        if isinstance(uo, dict):
            uo["run_interpolation"] = True
    return out


def merge_imported_into_dolphin_yaml(
    target_path: Path,
    imported: dict[str, Any],
    *,
    half_window: tuple[int, int] | None = None,
    strides: tuple[int, int] | None = None,
    ministack_size: int | None = None,
) -> None:
    """Merge imported algorithm fields into target dolphin YAML on disk."""
    target = load_algo_mapping_from_yaml(target_path)
    kept = {k: copy.deepcopy(target[k]) for k in TOP_LEVEL_KEEP_FROM_TARGET if k in target}
    kept_bounds = {}
    oo = target.get("output_options")
    if isinstance(oo, dict):
        kept_bounds = {k: copy.deepcopy(oo[k]) for k in OUTPUT_OPTIONS_KEEP_FROM_TARGET if k in oo}

    merged = _deep_merge(target, algorithm_overlay_for_merge(imported))
    for key, value in kept.items():
        merged[key] = value
    if kept_bounds:
        oo2 = merged.setdefault("output_options", {})
        if isinstance(oo2, dict):
            oo2.update(kept_bounds)

    # Always drop ministack keys from import; restore target ministack unless overridden.
    pl_target = target.get("phase_linking") if isinstance(target.get("phase_linking"), dict) else {}
    pl = merged.setdefault("phase_linking", {})
    if isinstance(pl, dict):
        for key in PHASE_LINKING_DROP:
            if key in pl_target:
                pl[key] = copy.deepcopy(pl_target[key])
            else:
                pl.pop(key, None)

    merged = apply_window_and_ministack(
        merged,
        half_window=half_window,
        strides=strides,
        ministack_size=ministack_size,
        run_interpolation=True,
    )
    _dump_yaml_mapping(merged, target_path)


def write_stripped_algo_yaml(imported: dict[str, Any], dest: Path) -> Path:
    """Write allowlisted stripped algo YAML for later merge in run files."""
    overlay = algorithm_overlay_for_merge(imported)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _dump_yaml_mapping(overlay, dest)
    return dest


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--target", type=Path, required=True, help="generated dolphin config YAML to update")
    parser.add_argument("--from", dest="source", type=Path, required=True, help="algorithm .yaml/.yml or DISP-S1 .nc")
    parser.add_argument("--hwy", type=int, help="half-window y (azimuth)")
    parser.add_argument("--hwx", type=int, help="half-window x (range)")
    parser.add_argument("--sy", type=int, help="stride y")
    parser.add_argument("--sx", type=int, help="stride x")
    parser.add_argument("--ministack-size", type=int, dest="ministack_size", help="keep/set phase_linking.ministack_size")
    return parser


def main(iargs: list[str] | None = None) -> int:
    args = create_parser().parse_args(args=iargs)
    if not args.target.is_file():
        print(f"Error: target not found: {args.target}", file=sys.stderr)
        return 1
    if not args.source.is_file():
        print(f"Error: source not found: {args.source}", file=sys.stderr)
        return 1
    half_window = None
    if args.hwy is not None or args.hwx is not None:
        if args.hwy is None or args.hwx is None:
            print("Error: --hwy and --hwx must be given together", file=sys.stderr)
            return 1
        half_window = (args.hwy, args.hwx)
    strides = None
    if args.sy is not None or args.sx is not None:
        if args.sy is None or args.sx is None:
            print("Error: --sy and --sx must be given together", file=sys.stderr)
            return 1
        strides = (args.sy, args.sx)
    imported = load_algo_mapping(args.source)
    merge_imported_into_dolphin_yaml(
        args.target,
        imported,
        half_window=half_window,
        strides=strides,
        ministack_size=args.ministack_size,
    )
    print(f"Merged algorithm fields into {args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
