#!/usr/bin/env python3
"""Extract Dolphin / OPERA algorithm config YAML from a DISP-S1 NetCDF file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import h5py

DESCRIPTION = (
    "Extract the Dolphin algorithm-parameters YAML stored in an OPERA L3 DISP-S1 "
    "NetCDF (metadata/algorithm_parameters_yaml). Ignores version-only datasets."
)
EXAMPLE = """Examples:
  extract_dolphin_config_yaml.py OPERA_L3_DISP-S1_IW_F38247_VV_*.nc
  extract_dolphin_config_yaml.py OPERA_L3_DISP-S1_IW_F38247_VV_*.nc -o dolphin_config.yaml
"""

# Prefer explicit config dataset names; reject version-only strings.
PREFERRED_NAME_FRAGMENTS = (
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
    """Lower tuple sorts first. Prefer named algorithm YAML over other config blobs."""
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
            if not any(tok in lname for tok in ("dolphin", "config", "algorithm_parameters", "runconfig")):
                return
            if _is_version_dataset(name):
                return
            text = _decode_dataset(obj)
            if text is None or not _looks_like_yaml(text):
                return
            candidates.append((name, text))

        handle.visititems(visit)
    return candidates


def main(iargs: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(args=iargs)
    nc_file = Path(args.nc_file)
    if not nc_file.is_file():
        print(f"Error: file not found: {nc_file}", file=sys.stderr)
        return 1

    candidates = find_config_candidates(nc_file)
    if not candidates:
        print(
            "ERROR: Could not find algorithm_parameters_yaml (or similar YAML) in NetCDF.",
            file=sys.stderr,
        )
        return 1

    candidates.sort(key=lambda item: _rank(item[0], item[1]))
    name, config = candidates[0]
    output = Path(args.output)

    print("Found configuration in:")
    print(f"  {name}")
    if len(candidates) > 1:
        print("Other YAML candidates:")
        for other_name, _ in candidates[1:]:
            print(f"  {other_name}")
    print(f"Writing: {output}")

    text = config if config.endswith("\n") else config + "\n"
    output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
