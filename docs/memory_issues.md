# Memory issues

Observed out-of-memory cases and the numbers needed to eventually compute per-task memory from file size, and from that the number of tasks per node.

## Goal

Replace the fixed `c_memory` values in `minsar/defaults/job_defaults.cfg` with a memory estimate based on data size:

```text
task_memory = a_step + b_step * data_size        tasks_per_node = floor(usable_node_memory / task_memory)
```

Candidate unit for `data_size`: 0.1 GB, or one Sentinel-1 burst (roughly 0.25 GB as an unpacked cfloat SLC; to be measured).

## How memory is set today

- `job_submission.py` computes `task_memory = c_memory + num_memory_units * s_memory` (`putils.scale_memory`) from the step's row in `job_defaults.cfg`.
- **With `JOB_SUBMISSION_SCHEME=launcher_multiTask_multiNode` (the default in `setup/platforms_defaults.bash`) this memory is ignored.** `split_multi_node_jobs` uses only `num_threads`: `nodes = ceil(tasks * num_threads / cores_per_node)` and `LAUNCHER_PPN = cores_per_node // num_threads`. The only way to reduce tasks per node in `job_defaults.cfg` is to raise `num_threads`, which also sets `OMP_NUM_THREADS`.
- With the `multiTask_singleNode` schemes (`split_jobs`), tasks per job are limited to `max_memory_per_node * nodes / task_memory` (`max_memory_per_node` from `minsar/defaults/queues.cfg`).
- The future calculation therefore has to set tasks per node (`LAUNCHER_PPN`) from memory in `split_multi_node_jobs`, independent of `num_threads`.
- `num_memory_units` is the number of bursts for topsStack (`putils.get_number_of_bursts`). It is hard-coded to 8 for stripmap. For alosStack it is passed as 8 and every row has `s_memory = 0`, so memory is a constant per step regardless of scene size.

## What to record for each case

| Item | Where to find it |
|---|---|
| Step, number of tasks, nodes, tasks per node | `run_files/run_NN_*_0.job` (`#SBATCH -N`, `-n`), line count of `run_files/run_NN_*_0` |
| Peak memory per task | `Maximum resident set size` in `run_files/run_NN_*__*.time_log` (kB) |
| Task exit status | `Exit status` in the same `time_log` (0 does not prove success, see below) |
| Input and output data size per task | `width * length * 8` bytes (cfloat) from the `*.slc.xml` files, summed over frames and swaths |
| Number of frames and swaths, looks | `alosStack.xml`, task command line |
| Node memory and queue | `queues.cfg`, `sacct -o ReqMem` |
| Error signature | `out_run_NN_*.e` |

Peak memory measured in a job that ran out of memory is a lower bound: allocations failed, so the task would have used more. Use values from tasks that finished cleanly on a node with spare memory.

## Out-of-memory signatures

- `MemoryError` (Python), task exit status 1
- `ImportError: ... failed to map segment from shared object` (numpy cannot load), exit status 1
- `ERROR 2: ...gdalrasterblock.cpp, 1102: cannot allocate NNNNN bytes` and `ERROR 1: GetBlockRef failed ...` (GDAL). **The task still exits with status 0** and SLURM reports `COMPLETED`, but output blocks are missing. GDAL stops printing after 1000 messages.
- `check_job_outputs.py` does not detect the GDAL signature: plain `ERROR` is not in its `error_strings`.

## alos2Stack

### Cases (Stampede3, skx-dev, 48 cores and 192000 MB per node, 11/2026)

Both are ScanSAR (WBD) stacks with one frame, `c_memory = 4000` MB for all steps.

| | CameroonAlos2D89 | q23TamboraAlos2D25 |
|---|---|---|
| Dates | 88 | 13 |
| Swaths | 1 (s4) | 2 (s4, s5) |
| SLC size per swath (width x length) | 5746 x 118070 | s4 5842 x 118070, s5 6450 x 146704 |
| Input SLC per date | 5.4 GB | 13.1 GB (5.5 + 7.6) |
| Resampled SLC per date | 5.4 GB | 11.1 GB (5.5 + 6.1), reference date 14.2 GB |
| Raw data per date in `SLC/` | 57 GB (all swaths, both polarizations) | 57 GB |
| `run_04_resample_common_grid` tasks / nodes | 88 / 2 (44 per node) | 13 / 1 |
| Peak memory per task | 5.5 GB median, 5.66 GB max (tasks that finished) | 10.9 to 14.9 GB (lower bound) |
| Memory needed per node | 44 x 5.5 = 242 GB | 13 x 13.6 = 177 to 194 GB |
| Result | 26 of 88 tasks exit 1 (`MemoryError`, numpy import, GDAL) | all exit 0, 10 of 13 with GDAL `cannot allocate`; output suspect |

### Peak memory per step

| Step | Cameroon (1 swath) | Tambora (2 swaths) |
|---|---|---|
| `run_01_read_baseline_burst` | 0.30 GB | 0.29 GB |
| `run_02_estimate_slc_offset` | 3.1 GB | 2.9 GB |
| `run_03_estimate_swath_frame_offset` | 0.07 GB | 5.9 GB |
| `run_04_resample_common_grid` | 5.7 GB | 14.9 GB or more |
| `run_05_mosaic_rdr2geo` | not run | 0.75 GB |
| steps 06 to 16 | not measured | not measured |

### Findings

- `resample_common_grid` holds about one full date of SLC data in memory. Peak memory is about 1.05 to 1.15 x the input SLC size summed over swaths (Cameroon 5.66 / 5.42, Tambora 14.92 / 13.1), so memory scales with `sum over frames and swaths of width * length * 8 bytes`.
- `estimate_slc_offset` is roughly constant (about 3 GB) and does not scale with the number of swaths.
- `estimate_swath_frame_offset` is small for one swath and about 6 GB for two.
- The raw data size in `SLC/` is not a usable predictor: it is the same (57 GB per date) for both cases because it contains all five swaths, while memory depends on the swaths selected.

### Current setting

`resample_common_grid` has `num_threads = 2` and `c_memory = 6500` MB. `num_threads = 2` is what takes effect: 24 tasks per skx node instead of 48 (Cameroon: 88 tasks on 4 nodes, 24 x 5.7 = 136 GB per node). `c_memory` records the measured one-swath need and is used only by the singleNode schemes.

This is too little for two or more swaths: 13 Tambora tasks at about 15 GB still land on one node. Tambora needs at most 12 tasks per node (`num_threads = 4`).

### Still needed

- Clean peak-memory values for a multi-swath stack (rerun Tambora with enough memory), and for multi-frame and stripmap stacks.
- Peak memory for steps 06 to 16, in particular `form_interferogram`, `diff_look_filt` and `unwrap`, and how they depend on the looks.
- A way for `job_submission.py` to get the data size for alosStack (number of swaths and frames from `alosStack.xml`, dimensions from `dates/*/f*/s*/*.slc.xml`) instead of the fixed `--numMemoryUnits 8`.

## topsStack

No out-of-memory case recorded yet.

- Memory already scales with the number of bursts: `num_memory_units = putils.get_number_of_bursts`, and several rows in `job_defaults.cfg` have a per-burst slope `s_memory` (e.g. `generate_burst_igram` 2000 + 790 per burst, `merge_burst_igram` 2000 + 334, `filter_coherence` and `unwrap` 2000 + 300).
- The slopes are in MB per burst. To move to a file-size unit, measure the size of one burst SLC (`width * length * 8` bytes) and re-express the slopes per 0.1 GB.

### Still needed

- For each step: peak memory from the `time_log` files against the number of bursts, for a few stacks of different size, to check the existing `c_memory` and `s_memory` values.
- Dependence of the merged-product steps (`merge_burst_igram`, `filter_coherence`, `unwrap`) on the range and azimuth looks.
- Any out-of-memory case, recorded with the items in the table above.
