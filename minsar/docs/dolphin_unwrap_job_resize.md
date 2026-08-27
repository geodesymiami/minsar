# Dolphin unwrap job resize

Set dolphin `n_parallel_jobs` from stitched interferogram size so unwrap does not OOM on memory-limited queues.

Script: `minsar/scripts/resize_dolphin_unwrap_jobfile.py` (on `PATH` via `minsar/scripts`).

## Why

Snaphu memory scales with image pixels (~420 bytes/pixel). The default `cpus // 4` concurrent unwrap jobs can exceed node RAM on large stitched products (e.g. Etna-scale stacks on `skx-dev`). By default, CSLC workflows split dolphin; the **dolphin_unwrap** run file calls this script at job start (after `dolphin_wrapped` produced stitched ifgs).

## When it runs

Inside `run_NN_dolphin_unwrap` (pixi heredoc), before `run_dolphin_unwrap.py`:

```bash
N_UNWRAP=$(resize_dolphin_unwrap_jobfile.py .)
run_dolphin_unwrap.py --n-parallel-jobs "$N_UNWRAP"
```

`run_isce3_workflow.bash` does not add a separate pre-step.

## Size source

First `dolphin/interferograms/*.int.tif` (stitched wrapped ifg from `dolphin_wrapped`).

## Formulas (snaphu)

Same model as [miaplpy_unwrap_job_resize.md](miaplpy_unwrap_job_resize.md); shared code in `minsar/utils/unwrap_memory.py`.

```text
mem_per_job_MiB = LENGTH * WIDTH * 420 / 1024^2 / (ntiles[0] * ntiles[1])
n_parallel_jobs = min(mem_cap, cpu_cap)
cpu_cap         = max(1, CPUS_PER_NODE // n_parallel_tiles)
```

Tile settings come from `dolphin_config.yaml` (`snaphu_options.ntiles`, `n_parallel_tiles`).

Non-snaphu methods: `spurt` → 1 job; `icu`/`phass` → 2× bytes/pixel (conservative); `whirlwind` → same as snaphu until measured.

## CLI

```bash
resize_dolphin_unwrap_jobfile.py .
resize_dolphin_unwrap_jobfile.py . --dry-run
resize_dolphin_unwrap_jobfile.py . --queue skx-dev --dolphin-config dolphin_config.yaml
```

Default stdout: one integer (`n_parallel_jobs`). Summary lines go to stderr. `--dry-run` prints the summary only.

## Stage split

Regenerate run files (split is default for CSLC):

```bash
create_isce3_runfiles.py $TE/<site>.template --data-type cslc
create_isce3_runfiles.py $TE/<site>.template --data-type cslc --no-dolphin-split
```

Then run the workflow as usual; each dolphin sub-stage has its own run/job file and queue profile from `job_defaults_isce3.cfg`.
