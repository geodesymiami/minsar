#!/usr/bin/env python3
"""Run dolphin wrapped phase + stitch only (no unwrap / timeseries).

Forces unwrap and timeseries off even if the YAML still has run_unwrap /
run_inversion enabled (e.g. after a full-pipeline config rewrite).

Examples:
  run_dolphin_wrapped.py
  run_dolphin_wrapped.py --config dolphin_config.yaml
  run_dolphin_wrapped.py --config dolphin_standard_config.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run dolphin phase linking and stitch only (no unwrap).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("dolphin_config.yaml"),
        help="Dolphin displacement config (default: dolphin_config.yaml)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable dolphin debug logging",
    )
    return parser


def main(iargs: list[str] | None = None) -> int:
    parser = create_parser()
    inps = parser.parse_args(args=iargs)

    config_path = inps.config.expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"dolphin config not found: {config_path}")

    from minsar.utils.sweets_import import hide_argv_from_pyre

    with hide_argv_from_pyre():
        from dolphin.workflows import displacement
        from dolphin.workflows.config import DisplacementWorkflow

    cfg = DisplacementWorkflow.from_yaml(config_path)
    # Split stage: never unwrap or invert here (run_03 / run_04 own those).
    cfg.unwrap_options.run_unwrap = False
    cfg.timeseries_options.run_inversion = False
    cfg.timeseries_options.run_velocity = False

    displacement.run(cfg, debug=bool(inps.debug))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
