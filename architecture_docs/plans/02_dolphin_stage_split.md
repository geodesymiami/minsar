# ISCE3 dolphin stage split (opportunity 2)

Background: [ISCE3_HPC_opportunities.md](../ISCE3_HPC_opportunities.md) type **C**. Best after opportunity 0; enables opportunity 3.

## Goal

Replace the single `run_dolphin` SLURM step with sequential MinSAR stages that match dolphin’s internal pipeline boundaries, so skx-dev 2h (and queue switches) work without losing finished work.

## Proposed stages

1. **Wrapped + stitch** — `unwrap_options.run_unwrap: false` (and typically no timeseries).
2. **Unwrap** — unwrap-only config or dedicated entry (still 1-node ThreadPool until opportunity 3).
3. **Timeseries** — inversion/velocity then existing `create_hdfeos5` / ingest as today.

## Scope

- [create_isce3_runfiles.py](../../minsar/src/minsar/cli/create_isce3_runfiles.py), [run_isce3_workflow.bash](../../minsar/src/minsar/cli/run_isce3_workflow.bash), [job_defaults_isce3.cfg](../../minsar/defaults/job_defaults_isce3.cfg), validation JSON as needed.

## Out of scope

- Multi-node LAUNCHER unwrap taskfile (opportunity 3).
- OPERA-disp ministack product pattern (opportunity 5).

## Steps

1. Confirm dolphin CLI/config knobs for stop-after-stitch and unwrap-only (reuse skip-if-exists).
2. Generate separate run/job files and workflow stage list for SAFE and CSLC.
3. Document operator flow and TIMEOUT resubmit per stage.
4. Smoke on a small stack.
