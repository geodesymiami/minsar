#!/usr/bin/env python3
"""Run dolphin timeseries inversion/velocity only (after dolphin_unwrap).

Examples:
  run_dolphin_timeseries.py
  run_dolphin_timeseries.py --config dolphin_config.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run dolphin timeseries inversion and velocity estimation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("dolphin_config.yaml"),
        help="Dolphin displacement config (default: dolphin_config.yaml)",
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
        from dolphin import timeseries
        from dolphin.workflows.config import DisplacementWorkflow

    cfg = DisplacementWorkflow.from_yaml(config_path)
    # Wrapped stage may have written no-run-inversion / no-run-velocity; force on here.
    cfg.timeseries_options.run_inversion = True
    cfg.timeseries_options.run_velocity = True
    ts_opts = cfg.timeseries_options

    unw_dir = cfg.unwrap_options._directory
    unw_paths = sorted(
        p for p in unw_dir.glob("*.unw.tif") if ".zeroed." not in p.name
    )
    if not unw_paths:
        raise FileNotFoundError(f"No unwrapped *.unw.tif under {unw_dir}")

    conncomp_candidates = [
        unw.with_name(unw.name.replace(".unw.tif", ".unw.conncomp.tif"))
        for unw in unw_paths
    ]
    conncomp_paths = conncomp_candidates if all(p.is_file() for p in conncomp_candidates) else None

    ifg_dir = cfg.interferogram_network._directory
    cor_paths = [
        ifg.with_name(ifg.name.replace(".int.tif", ".int.cor.tif"))
        for ifg in sorted(ifg_dir.glob("*.int.tif"))
    ]
    temp_coh_files = sorted(ifg_dir.glob("temporal_coherence*.tif"))
    if not temp_coh_files:
        temp_coh_files = sorted(ifg_dir.glob("auto*.tif"))
    avg_temp_coh = temp_coh_files[-1] if temp_coh_files else None

    timeseries.run(
        unwrapped_paths=unw_paths,
        conncomp_paths=conncomp_paths,
        corr_paths=cor_paths,
        reference_point=ts_opts.reference_point,
        quality_file=avg_temp_coh,
        reference_candidate_threshold=0.95,
        output_dir=ts_opts._directory,
        method=timeseries.InversionMethod(ts_opts.method),
        run_velocity=ts_opts.run_velocity,
        velocity_file=ts_opts._velocity_file,
        mask_path=cfg.mask_file if ts_opts.apply_mask_to_timeseries else None,
        correlation_threshold=ts_opts.correlation_threshold,
        num_threads=ts_opts.num_parallel_blocks,
        wavelength=cfg.input_options.wavelength,
        add_overviews=cfg.output_options.add_overviews,
        extra_reference_date=cfg.output_options.extra_reference_date,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
