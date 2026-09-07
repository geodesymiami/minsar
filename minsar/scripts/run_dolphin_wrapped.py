#!/usr/bin/env python3
"""Run dolphin per-burst phase linking only (no stitch, unwrap, or timeseries).

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
        description="Run dolphin phase linking only (no stitch or unwrap).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  run_dolphin_wrapped.py
  run_dolphin_wrapped.py --config dolphin_config.yaml
  run_dolphin_wrapped.py --config dolphin_standard_config.yaml
""",
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

    from minsar.utils.dolphin_stage_run import (
        load_displacement_workflow,
        run_wrapped_phase_only,
        with_hidden_argv,
    )

    def _run() -> None:
        cfg = load_displacement_workflow(config_path)
        cfg.unwrap_options.run_unwrap = False
        cfg.timeseries_options.run_inversion = False
        cfg.timeseries_options.run_velocity = False
        run_wrapped_phase_only(cfg, debug=bool(inps.debug))

    with_hidden_argv(_run)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
