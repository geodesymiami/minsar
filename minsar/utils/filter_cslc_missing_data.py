#!/usr/bin/env python3
"""Filter OPERA CSLCs to a burst×date-consistent subset before Dolphin."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from minsar.objects import message_rsmas

DESCRIPTION = (
    "Keep the largest spatially consistent OPERA CSLC subset (same dates on every burst). "
    "Partial-coverage files move to excluded_cslcs/ by default. Use after check_sweets_download."
)
EXAMPLE = """Examples:
  filter_cslc_missing_data.py --config sweets_config.yaml
  filter_cslc_missing_data.py --config sweets_config.yaml --dry-run
  filter_cslc_missing_data.py --config sweets_config.yaml --strict
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", type=Path, default=Path("sweets_config.yaml"), help="sweets config YAML (default: sweets_config.yaml)")
    parser.add_argument("--strict", action="store_true", help="exit 1 when partial burst×date coverage exists; do not move files")
    parser.add_argument("--dry-run", action="store_true", help="print subset options and files to exclude; do not move files")
    return parser


def _cslc_files(work_dir: Path, config: Path) -> tuple[Path, list[Path]]:
    """Return (data_dir, time-series CSLC paths) from a sweets Opera CSLC workflow."""
    from minsar.utils.sweets_import import hide_argv_from_pyre

    with hide_argv_from_pyre():
        from sweets.core import Workflow
        from sweets.download import OperaCslcSearch

    workflow = Workflow.from_yaml(work_dir / config)
    search = workflow.search
    if not isinstance(search, OperaCslcSearch):
        raise RuntimeError(
            f"filter_cslc_missing_data.py requires an opera-cslc sweets config; got {type(search).__name__}"
        )
    data_dir = search.out_dir.resolve()
    cslcs = sorted(data_dir.glob("OPERA_L2_CSLC-S1_*.h5"))
    return data_dir, cslcs


def filter_cslc_missing_data(
    work_dir: Path,
    config: Path,
    *,
    strict: bool = False,
    dry_run: bool = False,
) -> int:
    """Apply opera_utils missing-data filter to on-disk CSLCs."""
    from minsar.utils.sweets_import import hide_argv_from_pyre

    with hide_argv_from_pyre():
        from opera_utils.missing_data import get_missing_data_options, print_with_rich

    data_dir, cslc_files = _cslc_files(work_dir, config)
    if len(cslc_files) < 2:
        print(f"filter_cslc_missing_data: {len(cslc_files)} CSLC(s) in {data_dir}; nothing to filter")
        return 0

    try:
        options = get_missing_data_options(slc_files=[str(p) for p in cslc_files])
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: get_missing_data_options failed: {exc}", file=sys.stderr)
        return 2

    if not options:
        print("Error: get_missing_data_options returned no subset options", file=sys.stderr)
        return 2

    top = options[0]
    if top.num_candidate_bursts == top.total_num_bursts:
        print(
            f"filter_cslc_missing_data: complete stack — {top.total_num_bursts} CSLCs, "
            f"{top.num_burst_ids} burst(s) × {top.num_dates} date(s)"
        )
        return 0

    print(
        f"filter_cslc_missing_data: {top.num_candidate_bursts - top.total_num_bursts} "
        f"partial-coverage CSLC(s); keeping {top.num_burst_ids} burst(s) × {top.num_dates} date(s)"
    )
    print_with_rich(options, use_stderr=False)

    kept_set = {Path(p).resolve() for p in top.inputs}
    to_exclude = [p for p in cslc_files if p.resolve() not in kept_set]

    print("Excluded CSLCs:")
    for path in to_exclude:
        print(f"  {path.name}")

    if strict:
        print(
            "Error: incomplete burst×date coverage (use default mode to move partial CSLCs to excluded_cslcs/)",
            file=sys.stderr,
        )
        return 1

    if dry_run:
        print(f"dry-run: would move {len(to_exclude)} file(s) to {work_dir / 'excluded_cslcs'}")
        return 0

    excluded_dir = (work_dir / "excluded_cslcs").resolve()
    root = data_dir.resolve()
    for src in to_exclude:
        src = src.resolve()
        try:
            rel = src.relative_to(root)
        except ValueError:
            rel = Path(src.name)
        dst = excluded_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        print(f"Moving {rel} -> excluded_cslcs/{rel}")
        shutil.move(str(src), str(dst))

    if len(kept_set) < 2:
        print(
            f"Error: only {len(kept_set)} CSLC(s) remain after filter; need at least 2 for Dolphin",
            file=sys.stderr,
        )
        return 1

    print(
        f"filter_cslc_missing_data: kept {len(kept_set)} CSLC(s); "
        "regenerate dolphin_config.yaml if it was built before this step"
    )
    return 0


def main(iargs: list[str] | None = None) -> int:
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    work_dir = Path.cwd().resolve()
    config_path = inps.config if inps.config.is_file() else work_dir / inps.config
    if not config_path.is_file():
        parser.error(f"sweets config not found: {inps.config}")
    message_rsmas.log(
        str(work_dir),
        os.path.basename(__file__) + " " + " ".join(iargs if iargs is not None else sys.argv[1:]),
    )
    try:
        return filter_cslc_missing_data(
            work_dir,
            config_path,
            strict=inps.strict,
            dry_run=inps.dry_run,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
