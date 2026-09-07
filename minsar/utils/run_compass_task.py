#!/usr/bin/env python3
"""Run COMPASS s1_cslc.py or s1_static_layers.py; skip complete HDF5s; ignore browse-only GDAL failures."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import h5py
import yaml

DESCRIPTION = (
    "Run one COMPASS CSLC or static-layers task. Skips when the output HDF5 is already complete. "
    "If COMPASS fails after writing a valid product (browse-image GDAL NETCDF), exit 0."
)
EXAMPLE = """Examples:
  run_compass_task.py s1_cslc.py gslcs/runconfigs/geo_runconfig_20220919_t029_060354_iw3.yaml
  run_compass_task.py s1_static_layers.py gslcs/runconfigs/geo_runconfig_20200103_t029_060354_iw3.yaml
"""
_RUNCONFIG_STEM_RE = re.compile(r"^geo_runconfig_(\d{8})_(.+)$")
CSLC_DATASETS = ("data/VV", "data/VH")
STATIC_DATASETS = ("data/los_east", "data/los_north", "data/local_incidence_angle")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("tool", choices=("s1_cslc.py", "s1_static_layers.py"), help="COMPASS executable name")
    parser.add_argument("runconfig", type=Path, help="COMPASS runconfig YAML")
    return parser


def _pixi_bin() -> Path:
    minsar_home = os.environ.get("MINSAR_HOME")
    if not minsar_home:
        raise RuntimeError("MINSAR_HOME is not set")
    return Path(minsar_home) / "tools/sweets/.pixi/envs/default/bin"


def _load_runconfig(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    try:
        return data["runconfig"]["groups"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"invalid COMPASS runconfig: {path}") from exc


def _burst_date(runconfig: Path) -> tuple[str, str]:
    match = _RUNCONFIG_STEM_RE.match(runconfig.stem)
    if not match:
        raise RuntimeError(f"cannot parse date/burst from {runconfig.name}")
    return match.group(2), match.group(1)


def product_path(tool: str, runconfig: Path) -> Path:
    """Return the expected CSLC or static-layers HDF5 path for a runconfig."""
    groups = _load_runconfig(runconfig)
    product_dir = Path(groups["product_path_group"]["product_path"])
    burst_id, date = _burst_date(runconfig)
    if tool == "s1_static_layers.py":
        return product_dir / burst_id / date / f"static_layers_{burst_id}.h5"
    return product_dir / burst_id / date / f"{burst_id}_{date}.h5"


def _h5_has_any_dataset(path: Path, datasets: tuple[str, ...]) -> bool:
    if not path.is_file() or path.stat().st_size < 1024 * 1024:
        return False
    try:
        with h5py.File(path, "r") as handle:
            for dataset in datasets:
                if dataset not in handle:
                    continue
                value = handle[dataset]
                if value.size >= 1:
                    return True
    except OSError:
        return False
    return False


def product_is_complete(tool: str, runconfig: Path) -> bool:
    """Return whether the COMPASS HDF5 for this runconfig is already usable."""
    path = product_path(tool, runconfig)
    datasets = STATIC_DATASETS if tool == "s1_static_layers.py" else CSLC_DATASETS
    return _h5_has_any_dataset(path, datasets)


def main(iargs: list[str] | None = None) -> int:
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    runconfig = inps.runconfig.expanduser()
    if not runconfig.is_file():
        parser.error(f"runconfig not found: {runconfig}")
    if product_is_complete(inps.tool, runconfig):
        print(f"Skipping complete {inps.tool} product: {product_path(inps.tool, runconfig)}")
        return 0
    exe = _pixi_bin() / inps.tool
    if not exe.is_file():
        print(f"Error: COMPASS executable not found: {exe}", file=sys.stderr)
        return 1
    completed = subprocess.run([str(exe), str(runconfig)], check=False)
    if completed.returncode == 0:
        return 0
    if product_is_complete(inps.tool, runconfig):
        print(
            f"Warning: {inps.tool} exited {completed.returncode} but product is valid; treating as success: "
            f"{product_path(inps.tool, runconfig)}",
            file=sys.stderr,
        )
        return 0
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
