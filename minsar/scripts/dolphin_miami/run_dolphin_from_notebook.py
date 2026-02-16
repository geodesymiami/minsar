#!/usr/bin/env python3
"""
Run Dolphin workflow extracted from the official walkthrough notebook.

Based on: https://github.com/isce-framework/dolphin/blob/main/docs/notebooks/walkthrough-basic.ipynb

Workflow:
  1. Find CSLC files in data_dir (OPERA CSLC-S1 *.h5 or *.nc).
  2. Run `dolphin config` with --slc-files, --subdataset "/data/VV", --work-directory.
  3. Run `dolphin run dolphin_config.yaml`.

Usage:
  python run_dolphin_from_notebook.py [--data-dir PATH] [--process-dir PATH]
  Defaults: --data-dir /work2/05861/tg851601/dolphin_test_data
            --process-dir /work2/05861/tg851601/dolphin_run
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Dolphin config + run from walkthrough notebook workflow."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("/work2/05861/tg851601/dolphin_test_data"),
        help="Directory containing CSLC files (*.h5, *.nc)",
    )
    parser.add_argument(
        "--process-dir",
        type=Path,
        default=Path("/work2/05861/tg851601/dolphin_run"),
        help="Working directory for dolphin config and outputs",
    )
    parser.add_argument(
        "--subdataset",
        type=str,
        default="/data/VV",
        help='Subdataset for OPERA CSLC (default: "/data/VV")',
    )
    args = parser.parse_args()

    data_dir: Path = args.data_dir.resolve()
    process_dir: Path = args.process_dir.resolve()

    if not data_dir.is_dir():
        print(f"Error: data directory not found: {data_dir}", file=sys.stderr)
        return 1

    # Collect SLC files (notebook uses input_slcs/*.h5; OPERA CSLC-S1 are .h5 or .nc)
    patterns = ["*.h5", "*.nc", "*.hdf5"]
    slc_files: list[Path] = []
    for p in patterns:
        slc_files.extend(data_dir.glob(p))
    # Also check one level down (e.g. unpacked granules)
    if not slc_files:
        for sub in data_dir.iterdir():
            if sub.is_dir():
                for p in patterns:
                    slc_files.extend(sub.glob(p))

    slc_files = sorted(set(slc_files))
    if not slc_files:
        print(f"Error: No CSLC files ({patterns}) in {data_dir}", file=sys.stderr)
        return 1

    print(f"Found {len(slc_files)} SLC file(s)")
    process_dir.mkdir(parents=True, exist_ok=True)
    config_path = process_dir / "dolphin_config.yaml"

    # dolphin config --slc-files <each> --subdataset "/data/VV" --work-directory <dir>
    # Run from process_dir so dolphin_config.yaml is written there
    cmd_config = [
        "dolphin",
        "config",
        *[str(f) for f in slc_files],
        "--subdataset",
        args.subdataset,
        "--work-directory",
        str(process_dir),
    ]
    print("Running:", " ".join(cmd_config))
    try:
        r = subprocess.run(cmd_config, cwd=str(process_dir))
    except FileNotFoundError:
        print("Error: 'dolphin' not found. Activate the dolphin conda env, e.g. conda activate dolphin-env", file=sys.stderr)
        return 1
    if r.returncode != 0:
        return r.returncode

    # dolphin run dolphin_config.yaml (from process_dir so paths in config resolve)
    cmd_run = ["dolphin", "run", str(config_path)]
    print("Running:", " ".join(cmd_run))
    r = subprocess.run(cmd_run, cwd=str(process_dir))
    if r.returncode != 0:
        return r.returncode

    # Summarize outputs (as in notebook: timeseries/*.tif)
    ts_dir = process_dir / "timeseries"
    if ts_dir.is_dir():
        tifs = sorted(ts_dir.glob("*.tif"))
        print(f"Done. Found {len(tifs)} timeseries files in {ts_dir}")
    else:
        print(f"Done. Outputs in {process_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
