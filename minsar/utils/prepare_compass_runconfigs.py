#!/usr/bin/env python3
"""Download orbits, write COMPASS runconfigs, and fill run_02_create_cslc."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path

from minsar.objects import message_rsmas

DESCRIPTION = "Prepare COMPASS runconfigs after SAFE download and write the create_cslc task list."
EXAMPLE = """Examples:
  prepare_compass_runconfigs.py
  prepare_compass_runconfigs.py --config sweets_config.yaml
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", type=Path, default=Path("sweets_config.yaml"), help="sweets config YAML (default: sweets_config.yaml)")
    return parser


def _q(value: str | Path) -> str:
    return shlex.quote(str(value))


def materialize_compass_tasks(work_dir: Path) -> Path:
    """Write one s1_cslc.py / s1_static_layers.py command per runconfig into create_cslc."""
    cslc = sorted(work_dir.rglob("runconfigs/*.yaml"))
    if not cslc:
        raise RuntimeError("SWEETS did not create COMPASS CSLC runconfigs")
    sweets_bin = '"$MINSAR_HOME/tools/sweets/.pixi/envs/default/bin"'
    commands = [f"{sweets_bin}/s1_cslc.py {_q(path)}" for path in cslc]
    first_per_burst: dict[str, Path] = {}
    for path in cslc:
        parts = path.stem.split("_")
        key = "_".join(parts[3:]) if len(parts) > 3 else path.stem
        first_per_burst.setdefault(key, path)
    commands.extend(f"{sweets_bin}/s1_static_layers.py {_q(path)}" for path in first_per_burst.values())
    run_files = sorted((work_dir / "run_files").glob("run_*_create_cslc"))
    if len(run_files) != 1:
        raise RuntimeError("expected exactly one create_cslc run file")
    run_files[0].write_text("\n".join(commands) + "\n")
    return run_files[0]


def prepare(work_dir: Path, config: Path) -> None:
    """Create COMPASS runconfigs from downloaded SAFEs and write the create_cslc task list."""
    from minsar.utils.sweets_import import hide_argv_from_pyre

    with hide_argv_from_pyre():
        from sweets.core import Workflow, create_config_files, download_orbits, get_burst_db

    workflow = Workflow.from_yaml(work_dir / config)
    burst_db = get_burst_db()
    safes = workflow._existing_safes()
    download_orbits(workflow.search.out_dir, workflow.orbit_dir)
    create_config_files(
        slc_dir=safes[0].parent,
        burst_db_file=burst_db,
        dem_file=workflow.dem_filename,
        orbit_dir=workflow.orbit_dir,
        bbox=workflow.bbox,
        y_posting=workflow.slc_posting[0],
        x_posting=workflow.slc_posting[1],
        pol_type=workflow.pol_type,
        out_dir=workflow.gslc_dir,
        overwrite=True,
        using_zipped=safes[0].suffix == ".zip",
        gpu_enabled=workflow.gpu_enabled,
    )
    materialize_compass_tasks(work_dir)


def main(iargs: list[str] | None = None) -> int:
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    work_dir = Path.cwd().resolve()
    if not (work_dir / inps.config).is_file() and not inps.config.is_file():
        parser.error(f"sweets config not found: {inps.config}")
    message_rsmas.log(
        str(work_dir),
        os.path.basename(__file__) + " " + " ".join(iargs if iargs is not None else sys.argv[1:]),
    )
    try:
        prepare(work_dir, inps.config)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
