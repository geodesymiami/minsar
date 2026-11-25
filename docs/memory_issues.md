# Memory issues

Out-of-memory cases, kept to eventually compute per-task memory from data size and from it the number of tasks per node (candidate unit: 0.1 GB or one Sentinel-1 burst).

## alos2Stack

Stampede3 skx-dev: 48 cores and 191 GB per node. All steps have `c_memory = 4000` MB in `job_defaults.cfg`.

| Dataset | Dates | Swaths | SLC in per date | Step 4 `resample_common_grid`: tasks, nodes, tasks per node | Peak per task (step 4) | Memory needed per node | Result |
|---|---|---|---|---|---|---|---|
| CameroonAlos2D89 | 88 | 1 | 5.4 GB | 88, 2, 44 | 5.5 GB median, 5.7 max | 242 GB | 26 of 88 tasks exit 1 (`MemoryError`, numpy import, GDAL) |
| q20TamboraAlos2D26 | 18 | 1 | 5.2 GB | 18, 1, 18 | 9.8 GB median, 10.3 max | 176 GB or more | all exit 0, but 16 tasks logged GDAL `cannot allocate`; output suspect |

Peak memory of other steps (Cameroon / Tambora D26): step 2 `estimate_slc_offset` 3.1 / 2.6 GB, step 3 `estimate_swath_frame_offset` 0.07 / 0.1 GB, step 5 `mosaic_rdr2geo` not run / 0.4 GB, step 6 `geo2rdr` not run / 1.2 GB. Steps 7 to 16 not measured. Peaks from tasks that were short of memory are lower bounds.

Findings:

- Only step 4 runs out of memory.
- Peak memory is not simply proportional to the input SLC: 1.0 x the input for Cameroon but 1.6 to 2.0 x for Tambora D26, with similar input size and the same looks (1 range, 14 azimuth). The cause is not yet known. More cases are needed.
- Raw data size in `SLC/` is useless as a predictor (it holds all swaths and polarizations).
- Tambora D26 ran with `num_threads = 2` (24 tasks per node), which does not help because 18 tasks are fewer than 24: all 18 run at once on one node. It needs at most 12 tasks per node (`num_threads = 4`).

## topsStack

No out-of-memory case yet. Memory already scales with the number of bursts (`num_memory_units`, per-burst slopes `s_memory` in MB per burst in `job_defaults.cfg`). To do: measure the size of one burst SLC and express the slopes per 0.1 GB.

## How memory is set today

- `job_submission.py`: `task_memory = c_memory + num_memory_units * s_memory`. For alosStack `num_memory_units` is a fixed 8 and `s_memory = 0`.
- **With** `launcher_multiTask_multiNode` **(default) this memory is ignored.** `split_multi_node_jobs` uses only `num_threads`: `LAUNCHER_PPN = cores_per_node // num_threads`, `nodes = ceil(tasks * num_threads / cores_per_node)`. The only lever in `job_defaults.cfg` is `num_threads`, which also sets `OMP_NUM_THREADS`.
- The `multiTask_singleNode` schemes do use `max_memory_per_node / task_memory`.
- Current `resample_common_grid` row: `c_memory = 6500`, `num_threads = 2`. This fixes Cameroon (24 tasks per node, 136 GB) but not Tambora D26.

## Out-of-memory signatures

- Python `MemoryError`, or numpy `failed to map segment from shared object`: task exits 1.
- GDAL `ERROR 2: ...gdalrasterblock.cpp, 1102: cannot allocate N bytes` and `GetBlockRef failed`: **task exits 0**, SLURM says `COMPLETED`, output blocks are missing. Printing stops after 1000 messages.
- `check_job_outputs.py` does not detect the GDAL signature (plain `ERROR` is not in `error_strings`).

## To do

- Per step, peak memory (`Maximum resident set size` in `run_files/run_NN_*__*.time_log`) against data size (`width * length * 8` bytes from the `*.slc.xml` files, summed over swaths and frames), including multi-swath, multi-frame and stripmap stacks.
- Steps 7 to 16, and dependence on looks.
- Make `split_multi_node_jobs` set tasks per node from memory, and give alosStack a real data size instead of `--numMemoryUnits 8`.
