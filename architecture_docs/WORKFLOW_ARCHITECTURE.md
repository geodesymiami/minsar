# Workflow Architecture

This document describes the job orchestration system used by MinSAR.

## Overview

MinSAR uses a three-tier job submission system:

```
run_workflow.bash → submit_jobs.bash → sbatch_conditional.bash → SLURM sbatch
```

`minsarApp.bash` runs before this chain and resolves user/template options into the step flags and `run_workflow.bash` ranges that drive execution.

## Job Orchestration Scripts

### 0. `minsarApp.bash` - Option Resolution Entry Point

**Location**: `minsar/bin/minsarApp.bash`

**Purpose**: Convert CLI + template options into a deterministic execution plan (flags + ISCE/MintPy/MiaplPy ranges), then call `run_workflow.bash` and helper scripts.

**Resolution Order**:
1. Parse CLI options into explicit variables (`startstep`, `stopstep`, `isce_*_cli`, `miaplpy_*`, etc.).
2. Load template settings (for example `topsStack.coregistration`, `topsStack.workflow`, `minsar.*` flags).
3. Normalize inferred start mode:
   - `--miaplpy-start` without explicit `--start` implies `startstep=miaplpy`.
   - `--isce-start` without explicit `--start` implies `startstep=ifgram`.
4. Compute ISCE defaults:
   - geometry: full stop `12`, ifgram-only stop `8`
   - NESD/auto: full stop `16`, ifgram-only stop `12`
   - Sentinel only: if `--isce-start` is provided without `--isce-stop`, default to ifgram-only stop (`8`/`12`).
5. Apply policy overrides:
   - `mintpy_flag` is set to 0 only when workflow is `slc` or `--isce-stop` is given on the CLI
   - starting at `ifgram` or later disables orbit download
6. Execute selected step blocks (`download`, `jobfiles`, `ifgram`, `mintpy`, `miaplpy`, etc.).

**Examples**:
```bash
# Auto-select ifgram mode from --isce-start (no --start needed)
minsarApp.bash $TE/template.template --isce-start 6

# MiaplPy range auto-selects miaplpy start mode
minsarApp.bash $TE/template.template --miaplpy-start 6 --miaplpy-stop 7
```

### 1. `run_workflow.bash` - Main Orchestrator

**Location**: `minsar/bin/run_workflow.bash`

**Purpose**: Manages the submission, monitoring, and error handling of batch jobs.

**Key Responsibilities**:
- Parse command line arguments (`--start`, `--stop`, `--dostep`, `--miaplpy`, etc.)
- Determine the correct `run_files` directory
- Build the `globlist[]` array of job file patterns
- Submit jobs and monitor their states
- Handle TIMEOUT/NODE_FAIL by resubmitting
- Run `check_job_outputs.py` for validation

**Control Flow**:
```
┌─────────────────────────────────────────────────────────────────────┐
│                        run_workflow.bash                             │
├─────────────────────────────────────────────────────────────────────┤
│  1. Parse Arguments (--start, --stop, --dostep, --miaplpy, etc.)   │
│  2. Determine RUNFILES_DIR (run_files/ or miaplpy/.../run_files/)  │
│  3. Build globlist[] of job file patterns to submit                │
│  4. For each pattern in globlist:                                  │
│     ├─ Submit all matching jobs via submit_jobs.bash               │
│     ├─ Monitor job states (COMPLETED, RUNNING, PENDING, etc.)      │
│     ├─ Handle TIMEOUT/NODE_FAIL by resubmitting                    │
│     ├─ Exit on FAILED/CANCELLED                                    │
│     └─ Run check_job_outputs.py to validate results                │
└─────────────────────────────────────────────────────────────────────┘
```

**Usage Examples**:
```bash
# Run steps 1-11 (default ISCE workflow)
run_workflow.bash --start 1 --stop 11

# Run a single step
run_workflow.bash --dostep 5

# Run MintPy step
run_workflow.bash --dostep mintpy

# Run a single job file
run_workflow.bash --jobfile smallbaseline_wrapper.job

# Run MiaplPy workflow (requires template file)
run_workflow.bash $TE/template.template --miaplpy --start 1 --stop 9
```

### 2. `submit_jobs.bash` - Batch Submission

**Location**: `minsar/bin/submit_jobs.bash`

**Purpose**: Submit a batch of job files matching a pattern.

**Key Responsibilities**:
- Expand glob patterns to job file lists
- Optionally shuffle for random order
- Call `sbatch_conditional.bash` for each file
- Retry failed submissions with configurable wait time
- Return list of submitted job numbers

**Usage**:
```bash
# Submit all run_01 jobs
submit_jobs.bash run_01

# Submit with rapid retry (60s instead of 300s)
submit_jobs.bash run_01 --rapid

# Submit in random order
submit_jobs.bash run_01 --random
```

### 3. `sbatch_conditional.bash` - Resource-Checked Submission

**Location**: `minsar/bin/sbatch_conditional.bash`

**Purpose**: Wrapper around `sbatch` that enforces custom resource limits.

**Custom Resource Checks**:
1. **Job Count**: Total jobs per user in queue
2. **Step Task Count**: Tasks for current processing step
3. **Total Task Count**: Total tasks across all steps

**Configuration Sources**:
- `minsar/defaults/queues.cfg` - Queue-specific limits
- `minsar/defaults/job_defaults.cfg` - Job-specific parameters

**Flow**:
```
1. Parse job file to extract step name
2. Read resource limits from queues.cfg
3. Count current active jobs/tasks
4. Check if new job would exceed limits
5. Run sbatch --test-only for SLURM validation
6. Submit if all checks pass, exit 1 if not
```

## Job File Structure

### ISCE Run Files

Location: `$WORKDIR/run_files/`

Naming convention: `run_XX_<step_name>_N.job`

Example:
```
run_01_unpack_topo_reference_0.job
run_02_unpack_secondary_slc_0.job
run_02_unpack_secondary_slc_1.job    # Multiple jobs per step
run_03_average_baseline_0.job
...
run_11_unwrap_0.job
run_11_unwrap_1.job
```

### MiaplPy Run Files

Location: `$WORKDIR/miaplpy/network_<type>/run_files/`

Where `<type>` can be:
- `single_reference` (default)
- `sequential_N` (N = connNum)
- `delaunay_N` (N = baselineRatio)

Steps:
1. `load_data`
2. `phase_linking`
3. `concatenate_patches`
4. `generate_ifgram`
5. `unwrap_ifgram`
6. `load_ifgram`
7. `ifgram_correction`
8. `invert_network`
9. `timeseries_correction`

### Special Job Files

| File | Purpose | Location |
|------|---------|----------|
| `smallbaseline_wrapper.job` | MintPy processing | `$WORKDIR/` |
| `insarmaps.job` | InsarMaps ingestion | `$WORKDIR/` |
| `create_miaplpy_jobfiles.job` | Generate MiaplPy jobs | `$WORKDIR/` |

## Job State Handling

| State | Action |
|-------|--------|
| `COMPLETED` | Increment counter, proceed to next |
| `RUNNING` | Continue monitoring |
| `PENDING` | Continue monitoring |
| `TIMEOUT` | Update walltime via `update_walltime_queuename.py`, resubmit |
| `NODE_FAIL` | Resubmit immediately |
| `FAILED` | Exit with error |
| `CANCELLED` | Exit with error |

### Timeout and Rerun Logic

Rerun logic is implemented in `run_workflow.bash` and `update_walltime_queuename.py`. **minsarApp.bash** does not contain this logic; it calls `run_workflow.bash` for ifgram/mintpy/miaplpy steps, and rerun happens inside the job monitoring loop.

**Flow**:
1. `run_workflow.bash` monitors jobs via `sacct`. When state is `TIMEOUT`, it calls `update_walltime_queuename.py` on the job file, then resubmits via `submit_jobs.bash`.
2. Resubmissions are logged to `$RUNFILES_DIR/rerun.log`.

**Implementations**:

| Location | Lines | Behavior |
|----------|-------|----------|
| `minsar/bin/run_workflow.bash` | 476–509 | Detect TIMEOUT, call `update_walltime_queuename.py`, resubmit |
| `minsar/scripts/update_walltime_queuename.py` | 24–40 | 20% walltime increase; skx-dev → skx switch when needed |

**update_walltime_queuename.py behavior**:
- **Walltime**: Increases by 20% (`putils.multiply_walltime(wall_time, factor=1.2)`).
- **skx-dev → skx switch** (Stampede3): On `QUEUE_DEV` (skx-dev), if the new walltime would exceed 2:00:00, the job is moved to `QUEUE_NORMAL` (skx), because skx-dev has a 2-hour walltime limit.
- **Exceptions**: For job names containing `smallbaseline` or `download_burst2stack`, walltime is capped at 02:00:00 instead of switching queues.

Queue names come from `setup/platforms_defaults.bash` (`QUEUE_DEV=skx-dev`, `QUEUE_NORMAL=skx` for Stampede3).

## Configuration Files

### `job_defaults.cfg`

Defines default walltime, memory, and other parameters per job type:

```
jobname                c_walltime  s_walltime  seconds_factor  c_memory  s_memory  num_threads  copy_to_tmp  io_load
unpack_topo_reference  00:03:00    00:02:15    0               4000      0         8            yes          1
unpack_secondary_slc   00:05:00    00:00:15    0               4000      0         2            yes          1
```

Walltime calculation: `walltime = c_walltime + (num_memory_units * s_walltime) * num_data * seconds_factor`

### `queues.cfg`

Defines queue-specific resource limits, including `MAX_NODES_PER_JOB`. When using `multiTask_multiNode` or `launcher_multiTask_multiNode`, if `number_of_nodes` exceeds `MAX_NODES_PER_JOB`, `job_submission.py` splits the batch into multiple jobs (each with at most `MAX_NODES_PER_JOB` nodes) via `split_multi_node_jobs`.

```
PLATFORM  QUEUENAME  CPUS_PER_NODE  THREADS_PER_CORE  ...  MAX_NODES_PER_JOB  MAX_JOBS  STEP_MAX_TASKS  TOTAL_MAX_TASKS
stampede2 skx        48             2                 ...  20                 3         400             100
```

## Shared Utilities

**Location**: `minsar/lib/workflow_utils.sh`

| Function | Purpose |
|----------|---------|
| `abbreviate` | Truncate long strings with ellipsis |
| `convert_array_to_comma_separated_string` | Array to CSV |
| `remove_from_list` | Remove item from array |
| `clean_array` | Remove empty elements from array |

## Testing

Test suite: `tests/test_run_workflow.bash` (73 tests)

```bash
# Run all workflow tests
bash tests/test_run_workflow.bash

# Expected: 73/73 tests passing
```

Test categories:
- Help & Usage
- Utility Functions
- Globlist Construction
- MiaplPy step mapping
- Single Job Mode
- Argument Parsing
- Regression Tests

## Logging

- **Workflow logs**: `$WORKDIR/workflow.N.log`
- **Job stdout/stderr**: `run_files/*.o`, `run_files/*.e`
- **Main log**: `$WORKDIR/log`
- **Resubmission log**: `$RUNFILES_DIR/rerun.log`
