#!/usr/bin/env python3
"""Extract Dolphin / OPERA algorithm config YAML from a DISP-S1 NetCDF file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import h5py

DESCRIPTION = (
    "Extract Dolphin config YAML from an OPERA L3 DISP-S1 NetCDF. "
    "Prefers metadata/dolphin_workflow_config when present; otherwise "
    "metadata/algorithm_parameters_yaml (or similar). Ignores version-only datasets."
)
EXAMPLE = """Examples:
  extract_dolphin_config_yaml.py OPERA_L3_DISP-S1_IW_F38247_VV_*.nc
  extract_dolphin_config_yaml.py OPERA_L3_DISP-S1_IW_F38247_VV_*.nc -o dolphin_config.yaml
"""

# Exact HDF5 paths preferred first (OPERA DISP-S1 product layout).
PREFERRED_DATASET_PATHS = (
    "metadata/dolphin_workflow_config",
    "dolphin_workflow_config",
    "metadata/algorithm_parameters_yaml",
    "algorithm_parameters_yaml",
)

# Prefer these basename fragments when scanning (lower = higher priority).
PREFERRED_NAME_FRAGMENTS = (
    "dolphin_workflow_config",
    "algorithm_parameters_yaml",
    "algorithm_parameters",
    "dolphin_config",
    "pge_runconfig",
)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("nc_file", help="OPERA L3 DISP-S1 NetCDF file")
    parser.add_argument(
        "-o",
        "--output",
        default="DISP_dolphin_config.yaml",
        help="output YAML path (default: DISP_dolphin_config.yaml)",
    )
    return parser


def _decode_dataset(obj: h5py.Dataset) -> str | None:
    """Return decoded string content, or None if not a scalar string."""
    try:
        value = obj[()]
    except Exception:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if hasattr(value, "item"):
        value = value.item()
        if isinstance(value, bytes):
            return value.decode("utf-8")
    if isinstance(value, str):
        return value
    return None


def _looks_like_yaml(text: str) -> bool:
    """True if text looks like a multi-line YAML/config blob, not a version string."""
    stripped = text.strip()
    if not stripped or "\n" not in stripped:
        return False
    # Version strings are short and have no YAML structure.
    if len(stripped) < 40:
        return False
    return any(token in stripped for token in (":", "\n-", "phase_linking", "worker", "unwrap"))


def _is_version_dataset(name: str) -> bool:
    lname = name.lower().rsplit("/", 1)[-1]
    if lname.endswith("_version") or lname.endswith("version"):
        return True
    return "software_version" in lname


def _rank(name: str, text: str) -> tuple:
    """Lower tuple sorts first. Prefer dolphin_workflow_config over algorithm YAML."""
    lname = name.lower()
    preferred = next(
        (i for i, frag in enumerate(PREFERRED_NAME_FRAGMENTS) if frag in lname),
        len(PREFERRED_NAME_FRAGMENTS),
    )
    return (
        preferred,
        0 if _looks_like_yaml(text) else 1,
        -len(text),
        lname,
    )


def find_config_candidates(nc_file: Path) -> list[tuple[str, str]]:
    """Return (dataset_path, text) candidates that look like config YAML."""
    candidates: list[tuple[str, str]] = []
    with h5py.File(nc_file, "r") as handle:

        def visit(name: str, obj: object) -> None:
            if not isinstance(obj, h5py.Dataset):
                return
            lname = name.lower()
            if not any(
                tok in lname
                for tok in (
                    "dolphin",
                    "config",
                    "algorithm_parameters",
                    "runconfig",
                    "workflow_config",
                )
            ):
                return
            if _is_version_dataset(name):
                return
            text = _decode_dataset(obj)
            if text is None or not _looks_like_yaml(text):
                return
            candidates.append((name, text))

        handle.visititems(visit)
    return candidates


def extract_config_yaml(nc_file: Path) -> tuple[str, str]:
    """Return (dataset_path, yaml_text) from an OPERA DISP-S1 NetCDF.

    Prefers metadata/dolphin_workflow_config when present and valid YAML.
    """
    with h5py.File(nc_file, "r") as handle:
        for path in PREFERRED_DATASET_PATHS:
            if path not in handle:
                continue
            obj = handle[path]
            if not isinstance(obj, h5py.Dataset):
                continue
            text = _decode_dataset(obj)
            if text is not None and _looks_like_yaml(text):
                return path, text

    candidates = find_config_candidates(nc_file)
    if not candidates:
        raise ValueError(
            "Could not find metadata/dolphin_workflow_config or "
            "algorithm_parameters_yaml (or similar YAML) in NetCDF."
        )
    candidates.sort(key=lambda item: _rank(item[0], item[1]))
    return candidates[0]


def main(iargs: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(args=iargs)
    nc_file = Path(args.nc_file)
    if not nc_file.is_file():
        print(f"Error: file not found: {nc_file}", file=sys.stderr)
        return 1

    try:
        name, config = extract_config_yaml(nc_file)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    candidates = find_config_candidates(nc_file)
    candidates.sort(key=lambda item: _rank(item[0], item[1]))
    output = Path(args.output)

    print("Found configuration in:")
    print(f"  {name}")
    others = [c for c in candidates if c[0] != name]
    if others:
        print("Other YAML candidates:")
        for other_name, _ in others:
            print(f"  {other_name}")
    print(f"Writing: {output}")

    text = config if config.endswith("\n") else config + "\n"
    output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
