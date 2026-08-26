# ISCE3 job resources foundation (opportunity 0)

Background: [ISCE3_HPC_opportunities.md](../ISCE3_HPC_opportunities.md) type **F** (+ type **B** defaults).

## Goal

Make all ISCE3 SLURM job headers use `minsar.job_submission.JOB_SUBMIT` so `set_job_queue_values` reads [queues.cfg](../../minsar/defaults/queues.cfg) for the selected queue (`CPUS_PER_NODE`, `MEM_PER_NODE`, `WALLTIME_FACTOR`, `MAX_NODES_PJ`, etc.). Cap walltime with `MAX_WALLTIME`. Set dolphin worker/unwrap parallel flags so a full-node `#SBATCH -n` is actually used on 1-node jobs.

## Scope

- [create_isce3_runfiles.py](../../minsar/src/minsar/cli/create_isce3_runfiles.py) `Isce3JobAdapter` only (plus dolphin `config` CLI flags in generated run files).
- Stage walltime/memory/threads still from [job_defaults_isce3.cfg](../../minsar/defaults/job_defaults_isce3.cfg).

## Out of scope

- Multi-node LAUNCHER for `create_cslc` (opportunity 1).
- Splitting dolphin into multiple SLURM steps (opportunity 2).
- GPU pixi env / GPU queues (opportunity 4).

## Steps

1. Build proper `inps` and call `JOB_SUBMIT(inps)` (not `__new__` + setattr).
2. Set `default_wall_time` / memory / threads from ISCE3 profiles; apply `wall_time_factor`; cap with `putils.get_queue_rerun_params`.
3. Delete `_queue_resources`; fail clearly if MinSAR job env is missing.
4. Extend `dolphin config` lines with worker/unwrap knobs derived from `CPUS_PER_NODE` (and burst count when known).
5. Smoke: regenerate project jobfiles on `skx-dev` and `pvc`; check `-n`, `-p`, `-t`.
