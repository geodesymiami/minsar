# ISCE3 job resources foundation (opportunity 0) — done

Background: [ISCE3_HPC_opportunities.md](../ISCE3_HPC_opportunities.md) type **F** (+ type **B** defaults).

## Goal

All ISCE3 SLURM job headers use `minsar.job_submission.JOB_SUBMIT` so `set_job_queue_values` reads [queues.cfg](../../minsar/defaults/queues.cfg). Cap walltime with `MAX_WALLTIME`. CSLC `run_dolphin` sets worker/unwrap flags from node CPUs (and, as a follow-on, from burst count at run time).

## Implemented in

[create_isce3_runfiles.py](../../minsar/src/minsar/cli/create_isce3_runfiles.py):

- `_require_job_env`, `_make_job_submit`, `_cap_walltime_for_queue`
- `Isce3JobAdapter` → `JOB_SUBMIT(inps)` (not `__new__`)
- CSLC `_cslc_dolphin_script`: runtime burst count → `n_parallel_bursts` / `threads_per_worker` / `n_parallel_jobs`

Stage walltime/memory/threads still from [job_defaults_isce3.cfg](../../minsar/defaults/job_defaults_isce3.cfg).

## Verify (skx-dev vs pvc)

| | skx-dev | pvc |
|--|---------|-----|
| `#SBATCH -n` | 48 | 96 |
| `#SBATCH -p` | skx-dev | pvc |
| `#SBATCH -t` (`run_dolphin` profile 2h) | capped 02:00:00 | 02:00:00 under 48h max |
| Worker flags (after burst-aware) | depend on `n_bursts` and 48 CPUs | depend on `n_bursts` and 96 CPUs |

Grep `run_files/*run_dolphin.job` for `#SBATCH -[npt]` and the run script for `dolphin workers:` / `n-parallel-bursts`.

## Out of scope

- Multi-node LAUNCHER for `create_cslc` (opportunity 1)
- Splitting dolphin into multiple SLURM steps (opportunity 2)
- GPU pixi env / GPU queues (opportunity 4)
