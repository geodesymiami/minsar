#!/usr/bin/env python3
"""Stitch SWEETS static-layer geometry from sweets_config.yaml."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from minsar.objects import message_rsmas

DESCRIPTION = "Stitch static-layer geometry needed by Dolphin from a sweets config."
EXAMPLE = """Examples:
  stitch_sweets_geometry.py
  stitch_sweets_geometry.py --config sweets_config.yaml
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", type=Path, default=Path("sweets_config.yaml"), help="sweets config YAML (default: sweets_config.yaml)")
    return parser


def stitch(work_dir: Path, config: Path) -> None:
    """Stitch existing static layers for Dolphin."""
    from minsar.utils.sweets_import import hide_argv_from_pyre

    with hide_argv_from_pyre():
        from sweets.core import Workflow

    workflow = Workflow.from_yaml(work_dir / config)
    workflow._stitch_geometry(workflow._existing_static_layers())


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
        stitch(work_dir, inps.config)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
