#!/usr/bin/env python3
"""Check SWEETS SAFE or OPERA CSLC downloads; optionally delete corrupt products."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from minsar.objects import message_rsmas
from minsar.utils.sweets_product_download import (
    _hdf5_has_datasets,
    _result_name,
    _safe_is_readable,
    expected_safe_keys,
    safe_acquisition_key,
    valid_safe_keys,
)

DESCRIPTION = (
    "Check products listed in sweets_config.yaml. Without --delete, fail if any "
    "are missing or corrupt. With --delete, remove corrupt products and exit 0. "
    "With --redownload, fetch only missing products after optional cleanup."
)
EXAMPLE = """Examples:
  check_sweets_download.py --config sweets_config.yaml
  check_sweets_download.py --config sweets_config.yaml --delete
  check_sweets_download.py --config sweets_config.yaml --kind cslc --delete --redownload
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--kind", choices=("cslc", "safe"), help="workflow kind; inferred from sweets_config.yaml by default")
    parser.add_argument("--delete", action="store_true", help="remove corrupt products and exit 0")
    parser.add_argument("--redownload", action="store_true", help="download only missing or deleted products")
    parser.add_argument("--config", type=Path, default=Path("sweets_config.yaml"), help="sweets config YAML (default: sweets_config.yaml)")
    return parser


def infer_kind(search: object) -> str:
    name = type(search).__name__.lower()
    if "cslc" in name or "opera" in name:
        return "cslc"
    return "safe"


def check_safe_download(work_dir: Path, config: Path, delete: bool) -> int:
    """Check expected SAFE absolute orbits and optionally delete bad products."""
    from minsar.utils.sweets_import import hide_argv_from_pyre

    with hide_argv_from_pyre():
        from sweets.core import Workflow, setup_nasa_netrc

    workflow = Workflow.from_yaml(work_dir / config)
    search = workflow.search
    setup_nasa_netrc()
    expected = expected_safe_keys(search)
    bad: list[tuple[Path, str]] = []
    for path in sorted(search.out_dir.glob("S1[ABCD]_*.SAFE")):
        key = safe_acquisition_key(path)
        readable, reason = _safe_is_readable(path)
        if not key:
            readable, reason = False, "absolute orbit missing from SAFE name"
        if not readable:
            bad.append((path, reason))

    for path, reason in bad:
        print(f"Invalid SAFE: {path.name}: {reason}", file=sys.stderr)
        if delete:
            shutil.rmtree(path)
            print(f"Deleted {path}", file=sys.stderr)

    valid = valid_safe_keys(search.out_dir)
    missing = sorted(expected - valid)
    if missing:
        print(
            "Missing SAFE acquisitions: "
            + ", ".join(f"{date}/orbit-{orbit:06d}" for orbit, date in missing),
            file=sys.stderr,
        )
    if bad or missing:
        return 0 if delete else 1
    print(f"check-safe: {len(valid)} complete SAFE products")
    return 0


def check_cslc_download(work_dir: Path, config: Path, delete: bool) -> int:
    """Check expected OPERA CSLC and static-layer products."""
    from minsar.utils.sweets_import import hide_argv_from_pyre

    with hide_argv_from_pyre():
        from opera_utils.download import L2Product, search_cslcs
        from sweets.core import Workflow, setup_nasa_netrc

    workflow = Workflow.from_yaml(work_dir / config)
    search = workflow.search
    setup_nasa_netrc()
    burst_ids = search._resolve_burst_ids()
    cslc_results = search_cslcs(start=search.start, end=search.end, track=search.track, burst_ids=burst_ids)
    static_results = search_cslcs(burst_ids=burst_ids, product=L2Product.CSLC_STATIC)

    expected_cslc = {_result_name(result) for result in cslc_results}
    expected_static = {_result_name(result) for result in static_results}
    if not expected_cslc or not expected_static:
        raise RuntimeError("check-cslc found no expected CSLC or static-layer products")

    checks = [
        (
            search.out_dir,
            expected_cslc,
            ("/data/VV", "/data/x_coordinates", "/data/y_coordinates", "/data/projection"),
        ),
        (
            search.static_layers_dir,
            expected_static,
            (
                "/data/los_east",
                "/data/los_north",
                "/data/local_incidence_angle",
                "/data/layover_shadow_mask",
            ),
        ),
    ]
    failures = False
    for directory, expected, datasets in checks:
        on_disk = {path.name: path for path in directory.glob("*.h5")}
        missing: list[str] = []
        for name in sorted(expected):
            path = on_disk.get(name)
            if path is None:
                missing.append(name)
                continue
            readable, reason = _hdf5_has_datasets(path, datasets)
            if not readable:
                failures = True
                print(f"Invalid CSLC product: {path}: {reason}", file=sys.stderr)
                if delete:
                    path.unlink()
                    print(f"Deleted {path}", file=sys.stderr)
                    missing.append(name)
        if missing:
            failures = True
            print(f"Missing {len(missing)} product(s) in {directory}:", file=sys.stderr)
            for name in missing:
                print(f"  {name}", file=sys.stderr)
    if failures:
        return 0 if delete else 1
    print(f"check-cslc: {len(expected_cslc)} CSLC and {len(expected_static)} static-layer products")
    return 0


def check_download(work_dir: Path, delete: bool, kind: str | None = None, config: Path | None = None) -> int:
    """Check SAFE or CSLC downloads for a sweets config in work_dir."""
    from minsar.utils.sweets_import import hide_argv_from_pyre

    with hide_argv_from_pyre():
        from sweets.core import Workflow

    config_path = config or Path("sweets_config.yaml")
    workflow = Workflow.from_yaml(work_dir / config_path)
    resolved = kind or infer_kind(workflow.search)
    if resolved == "cslc":
        return check_cslc_download(work_dir, config_path, delete)
    return check_safe_download(work_dir, config_path, delete)


def redownload_missing(work_dir: Path, config: Path) -> None:
    """Download only SAFE or CSLC products that are still missing on disk."""
    from minsar.utils.sweets_download import download_products

    download_products(work_dir, config, skip_existing=True)


def main(iargs: list[str] | None = None) -> int:
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    work_dir = Path.cwd().resolve()
    config = inps.config
    if not (work_dir / config).is_file() and not config.is_file():
        parser.error(f"sweets config not found: {config}")
    message_rsmas.log(
        str(work_dir),
        os.path.basename(__file__) + " " + " ".join(iargs if iargs is not None else sys.argv[1:]),
    )
    try:
        status = check_download(work_dir, inps.delete, kind=inps.kind, config=config)
        if inps.redownload:
            redownload_missing(work_dir, config)
            return 0
        return status
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
