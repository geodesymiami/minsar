#!/usr/bin/env python3
"""Run dolphin unwrap only (after dolphin_wrapped produced stitched ifgs).

Examples:
  run_dolphin_unwrap.py
  run_dolphin_unwrap.py --n-parallel-jobs 8
  run_dolphin_unwrap.py --config dolphin_config.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run dolphin unwrap on stitched interferograms.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("dolphin_config.yaml"),
        help="Dolphin displacement config from dolphin_wrapped (default: dolphin_config.yaml)",
    )
    parser.add_argument(
        "--n-parallel-jobs",
        type=int,
        default=None,
        help="Concurrent unwrap jobs (default: value in config YAML)",
    )
    return parser


def _sorted_pairs(ifg_dir: Path, suffix: str) -> list[Path]:
    return sorted(ifg_dir.glob(suffix))


def main(iargs: list[str] | None = None) -> int:
    parser = create_parser()
    inps = parser.parse_args(args=iargs)

    config_path = inps.config.expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"dolphin config not found: {config_path}")

    from dolphin.workflows.config import DisplacementWorkflow
    from dolphin.workflows import unwrapping

    cfg = DisplacementWorkflow.from_yaml(config_path)
    if inps.n_parallel_jobs is not None:
        cfg.unwrap_options.n_parallel_jobs = int(inps.n_parallel_jobs)
    cfg.unwrap_options.run_unwrap = True

    ifg_dir = cfg.interferogram_network._directory
    ifg_paths = _sorted_pairs(ifg_dir, "*.int.tif")
    if not ifg_paths:
        raise FileNotFoundError(f"No stitched *.int.tif under {ifg_dir}")

    cor_paths: list[Path] = []
    for ifg in ifg_paths:
        # dolphin estimate_interferometric_correlations writes *.int.cor.tif
        cor = ifg.with_name(ifg.name.replace(".int.tif", ".int.cor.tif"))
        if not cor.is_file():
            raise FileNotFoundError(f"Missing correlation file for {ifg.name}: {cor}")
        cor_paths.append(cor)

    temp_coh_files = sorted(ifg_dir.glob("temporal_coherence*.tif"))
    if not temp_coh_files:
        temp_coh_files = sorted(ifg_dir.glob("auto*.tif"))
    avg_temp_coh = temp_coh_files[-1] if temp_coh_files else None

    similarity_files = sorted(ifg_dir.glob("*similarity*.tif"))
    full_similarity = similarity_files[-1] if similarity_files else None

    row_looks, col_looks = cfg.phase_linking.half_window.to_looks()
    nlooks = row_looks * col_looks

    unwrapping.run(
        ifg_file_list=ifg_paths,
        cor_file_list=cor_paths,
        temporal_coherence_filename=avg_temp_coh,
        similarity_filename=full_similarity,
        nlooks=nlooks,
        unwrap_options=cfg.unwrap_options,
        mask_file=cfg.mask_file,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
