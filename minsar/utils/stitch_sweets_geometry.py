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
  stitch_sweets_geometry.py --sy 1 --sx 1 --overwrite
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("sweets_config.yaml"),
        help="sweets config YAML (default: sweets_config.yaml)",
    )
    parser.add_argument(
        "--sy",
        type=int,
        default=None,
        metavar="N",
        help="row/y stride for stitched geometry (default: sweets dolphin.strides)",
    )
    parser.add_argument(
        "--sx",
        type=int,
        default=None,
        metavar="N",
        help="column/x stride for stitched geometry (default: sweets dolphin.strides)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="overwrite existing geometry GeoTIFFs",
    )
    return parser


def stitch(
    work_dir: Path,
    config: Path,
    strides: tuple[int, int] | None = None,
    overwrite: bool = False,
) -> None:
    """Stitch existing static layers for Dolphin.

    Parameters
    ----------
    strides :
        Optional ``(y, x)`` looks passed to sweets ``stitch_geometry``. When
        omitted, uses ``workflow.dolphin.strides`` from the sweets config.
    """
    from minsar.utils.sweets_import import hide_argv_from_pyre

    with hide_argv_from_pyre():
        from dolphin._types import Bbox
        from sweets._geometry import stitch_geometry
        from sweets.core import Workflow

    workflow = Workflow.from_yaml(work_dir / config)
    static_files = workflow._existing_static_layers()
    looks = strides if strides is not None else workflow.dolphin.strides
    bbox = Bbox(*workflow.bbox) if workflow.bbox is not None else None
    stitch_geometry(
        geom_path_list=[Path(p) for p in static_files],
        geom_dir=workflow.geom_dir,
        dem_filename=workflow.dem_filename,
        looks=looks,
        bbox=bbox,
        overwrite=overwrite or bool(workflow.overwrite),
    )


def main(iargs: list[str] | None = None) -> int:
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    work_dir = Path.cwd().resolve()
    config_path = inps.config if inps.config.is_file() else work_dir / inps.config
    if not config_path.is_file():
        parser.error(f"sweets config not found: {inps.config}")
    if (inps.sy is None) ^ (inps.sx is None):
        parser.error("--sy and --sx must be given together")
    strides = (inps.sy, inps.sx) if inps.sy is not None else None
    message_rsmas.log(
        str(work_dir),
        os.path.basename(__file__) + " " + " ".join(iargs if iargs is not None else sys.argv[1:]),
    )
    try:
        stitch(work_dir, config_path, strides=strides, overwrite=inps.overwrite)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
