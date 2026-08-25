#!/usr/bin/env python3
"""Download SWEETS inputs (DEM, water mask, SAFE or OPERA CSLC) from sweets_config.yaml."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from minsar.objects import message_rsmas

DESCRIPTION = (
    "Download DEM, water mask, and SAFE or OPERA CSLC products for a sweets config. "
    "By default, skips products that are already complete on disk."
)
EXAMPLE = """Examples:
  sweets_download.py --config sweets_config.yaml
  sweets_download.py --config sweets_config.yaml --force
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", type=Path, default=Path("sweets_config.yaml"), help="sweets config YAML (default: sweets_config.yaml)")
    parser.add_argument("--force", action="store_true", help="re-download all products even when valid files exist")
    return parser


def download_products(work_dir: Path, config: Path, *, skip_existing: bool = True) -> None:
    """Download SWEETS inputs listed in config."""
    from minsar.utils.sweets_import import hide_argv_from_pyre
    from minsar.utils.sweets_product_download import download_cslcs, download_safes

    with hide_argv_from_pyre():
        from sweets.core import Workflow, create_dem, create_water_mask, get_burst_db, setup_nasa_netrc

    workflow = Workflow.from_yaml(work_dir / config)
    setup_nasa_netrc()
    workflow.work_dir.mkdir(parents=True, exist_ok=True)
    create_dem(workflow.dem_filename, workflow._dem_bbox)
    create_water_mask(workflow.water_mask_filename, workflow._water_mask_bbox)

    search = workflow.search
    kind = getattr(search, "kind", "")
    if kind == "safe":
        if not hasattr(search, "download_static_layers"):
            get_burst_db()
        download_safes(search, skip_existing=skip_existing)
        return
    if kind == "opera-cslc":
        download_cslcs(search, skip_existing=skip_existing)
        return

    if not hasattr(search, "download_static_layers"):
        get_burst_db()
    search.download()
    if hasattr(search, "download_static_layers"):
        search.download_static_layers()


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
        download_products(work_dir, inps.config, skip_existing=not inps.force)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
