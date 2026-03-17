# Proposal: Rerun Behavior (job_defaults.cfg + queues.cfg)

This document defines the planned changes for timeout rerun behavior: additional columns in `job_defaults.cfg`, new columns in `queues.cfg`, and removal of `copy_to_tmp` from `job_defaults.cfg`.

## Current Behavior (Hardcoded)

- **Walltime**: +20% on every rerun
- **On skx-dev when new walltime > 2h**: 
  - For `smallbaseline`, `download_burst2stack`: cap at 02:00:00, stay on skx-dev
  - All others: switch to skx (QUEUE_NORMAL)

## Desired Behavior (Config-Driven)

| Job type | Walltime factor | At queue walltime cap |
|----------|-----------------|------------------------|
| **Default** | 20% (1.2) | Switch queue, use rerun_walltime_factor_switch (1.2) |
| **run_08 miaplpy** (`miaplpy_invert_network`) | 100% (2.0) when switching | Switch queue, use 2.0 |
| **All other jobs** | 20% (1.2), cap at MAX_WALLTIME | Never switch |

## Plan: job_defaults.cfg Changes

### Add Rerun Columns (no separate rerun_jobs.cfg)

Add these columns to each job row in `minsar/defaults/job_defaults.cfg`:

| Column | Required | Type | Description |
|--------|----------|------|-------------|
| **rerun_walltime_factor** | Yes | float | Multiplier for walltime on rerun (1.2 = +20%, 2.0 = +100%). Default: 1.2. |
| **switch_queue** | Yes | yes/no | When computed new_walltime > queue's MAX_WALLTIME: `yes` = switch to QUEUE_AT_MAX_WALLTIME; `no` = cap at MAX_WALLTIME and stay on current queue. |
| **rerun_walltime_factor_switch** | No | float | When switching queue, use this factor instead of rerun_walltime_factor. Omit or n/a to use rerun_walltime_factor. |

**Rename**: `switch_dev_to_normal_at_cap` → `switch_queue` (shorter, queue-agnostic).

### Remove copy_to_tmp

Remove the `copy_to_tmp` column from `job_defaults.cfg`; it is no longer used.

### Example job_defaults.cfg Schema (after changes)

```
jobname   c_walltime  s_walltime  seconds_factor  c_memory  s_memory  num_threads  io_load  rerun_walltime_factor  switch_queue  rerun_walltime_factor_switch
default   02:00:00    0           0               3000      0         1            1        1.2                    yes                  1.2
miaplpy_invert_network  02:00:00  0  0  4000  0  1  1  1.2  yes  2.0
smallbaseline  01:20:00  00:02:00  0  all  0  1  1  1.2  no  n/a
download_burst2stack  02:00:00  0  0  3000  1  1  1  1.2  no  n/a
```

## Plan: queues.cfg Changes

### Add Two New Columns

| Column | Description | Example values |
|--------|-------------|----------------|
| **MAX_WALLTIME** | Max walltime for this queue. Used to determine whether rerun must cap or switch. | skx-dev: `02:00:00`; all others: `2-00:00:00` (or equivalent long limit) |
| **QUEUE_AT_MAX_WALLTIME** | Target queue when job hits MAX_WALLTIME and switch_queue=yes. | skx-dev: `skx`; all others: `n/a` |

### Logic

1. **MAX_WALLTIME**: Determines when the computed new walltime exceeds the queue limit.
   - skx-dev: `02:00:00` (2-hour limit)
   - Other queues: `2-00:00:00` (effectively no cap for rerun purposes)

2. **QUEUE_AT_MAX_WALLTIME**: Used when creating the rerun jobfile.
   - When new_walltime > MAX_WALLTIME and job's switch_queue=yes, replace the queue in the job file with QUEUE_AT_MAX_WALLTIME.
   - For skx-dev: use `skx`.
   - For others: `n/a` (no switch).

### Example queues.cfg Addition

```
PLATFORM_NAME  QUEUENAME  ...  MAX_WALLTIME  QUEUE_AT_MAX_WALLTIME
stampede3      skx        ...  2-00:00:00    n/a
stampede3      skx-dev    ...  02:00:00      skx
stampede3      icx        ...  2-00:00:00    n/a
...
```

## Resolved

- **Column order**: Optional columns last.
- **Default row**: `default` as catch-all in job_defaults.cfg.
- **Placement**: No separate rerun_jobs.cfg; use job_defaults.cfg and queues.cfg.
