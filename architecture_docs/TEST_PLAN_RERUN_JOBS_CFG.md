# Test Plan: Rerun Jobs Config (job_defaults.cfg + queues.cfg)

This document describes how to test the config-driven timeout rerun behavior (see `RERUN_JOBS_CFG_PROPOSAL.md`) without waiting for 2-hour job timeouts.

## Summary of behavior

- **job_defaults.cfg**: Each job has `rerun_walltime_factor`, `switch_queue_at_max_walltime`, `rerun_walltime_factor_switch`. On timeout, new walltime = current × factor; if new walltime > queue’s `MAX_WALLTIME`, either switch to `QUEUE_AT_MAX_WALLTIME` (using `rerun_walltime_factor_switch`) or cap at `MAX_WALLTIME`.
- **queues.cfg**: Each queue has `MAX_WALLTIME` and `QUEUE_AT_MAX_WALLTIME` (e.g. skx-dev: `02:00:00`, `skx`).
- **run_workflow.bash** calls `update_walltime_queuename.py` on TIMEOUT; that script (and the rerun block in `job_submission.py`) uses the config to update the job file and resubmit.

## Quick unit/config tests

```bash
cd /path/to/minsar
./run_all_tests.bash --python-only
# Or only cfg tests:
python -m unittest tests.test_queues_and_job_defaults_cfg -v
```

These check that `job_defaults.cfg` and `queues.cfg` load and have the required columns/fields.

## End-to-end test with short walltimes (1–2 minutes)

Goal: run `minsarApp.bash ... --start dem` so that jobs actually hit TIMEOUT after 1–2 minutes and the rerun logic (walltime increase and, where applicable, queue switch) is exercised.

### 1. Backup configs

```bash
cp minsar/defaults/job_defaults.cfg minsar/defaults/job_defaults.cfg.bak
cp minsar/defaults/queues.cfg minsar/defaults/queues.cfg.bak
```

### 2. Short walltimes for testing

Edit **minsar/defaults/job_defaults.cfg** and set **short** `c_walltime` for the steps you will run (so they timeout in 1–2 minutes):

- For a **dem**-only run: set `dem_rsmas` (and any step that runs) to e.g. `00:01:00` or `00:02:00`.
- For a run that includes **miaplpy** (e.g. Galapagos template with `--start dem` through miaplpy): set `dem_rsmas`, `create_runfiles`, `execute_runfiles`, and the miaplpy steps you expect to run to `00:01:00` or `00:02:00`.

Example (only for testing; revert after):

```text
dem_rsmas        00:02:00  0  0  1000  0  1  1  1.2  no  n/a
create_runfiles  00:02:00  0  0  1000  0  1  1  1.2  no  n/a
execute_runfiles 00:02:00  0  0  1000  0  1  1  1.2  no  n/a
# and miaplpy_* steps you need, e.g.:
miaplpy_invert_network  00:02:00  0  0  4000  0  1  1  1.2  yes  2.0
```

Keep the rerun columns (`rerun_walltime_factor`, `switch_queue_at_max_walltime`, `rerun_walltime_factor_switch`) as in the current schema.

### 3. Short queue cap so reruns switch queue

To test **queue switch** on timeout (e.g. skx-dev → skx), make the dev queue’s max walltime **short** so that after the first timeout the computed new walltime exceeds it and the job is resubmitted on the target queue.

Edit **minsar/defaults/queues.cfg** and set for **skx-dev** (or the dev queue you use):

- `MAX_WALLTIME` = `00:02:00` (or `00:01:00` for a 1-minute cap).
- `QUEUE_AT_MAX_WALLTIME` = `skx` (or your normal queue).

Example (testing only):

```text
stampede3  skx-dev  ...  02:00:00  skx
```

Change the skx-dev line to:

```text
stampede3  skx-dev  ...  00:02:00  skx
```

So: jobs on skx-dev will timeout at 2 minutes; after timeout, the script will see new walltime > 00:02:00 and (for jobs with `switch_queue_at_max_walltime=yes`) switch to `skx` and use `rerun_walltime_factor_switch` for the new walltime.

### 4. Run the workflow

Use the Galapagos template and start at **dem**, with the **dev** queue so jobs land on the short-cap queue first:

```bash
export QUEUENAME=skx-dev
# Optional: reduce wait between polls so the test finishes sooner
export SHORT_JOB_COMPLETION_WAITTIME=TRUE

minsarApp.bash /path/to/minsar/samples/unittestGalapagosSenD128.template --miaplpy --start dem
```

- Ensure the run uses the modified **job_defaults.cfg** and **queues.cfg** (no override to a different config path).
- Jobs should hit TIMEOUT after 1–2 minutes.
- `run_workflow.bash` will call `update_walltime_queuename.py` for each timed-out job, then resubmit.

### 5. What to check

- **rerun.log** in the run files directory (e.g. `run_files/rerun.log`): lines like  
  `YYYYMMDD:HH-MM: re-running: run_XX_stepname_N.job: HH:MM:SS --> HH:MM:SS`  
  and, when a queue switch happens, a line like  
  `queue switch: run_XX_stepname_N.job --> skx`.
- **Job files**: after timeout, the corresponding `.job` files should have updated `#SBATCH -t` (and, when applicable, `#SBATCH -p` to the target queue).
- **Resubmission**: the workflow should resubmit the updated jobs; they should run on the normal queue (e.g. skx) with the new walltime.

### 6. Restore configs

```bash
mv minsar/defaults/job_defaults.cfg.bak minsar/defaults/job_defaults.cfg
mv minsar/defaults/queues.cfg.bak minsar/defaults/queues.cfg
```

## Optional: job_defaults override for testing

If you prefer not to edit the main `job_defaults.cfg`, you can add a **test-only** config and point the code at it only when testing (e.g. via an env var that `get_config_defaults` or the rerun helpers check). That would require a small code change to support something like `MINSAR_JOB_DEFAULTS=job_defaults_test.cfg`. The plan above avoids that by temporarily editing the real configs and restoring them after the test.
