# MiaplPy unwrap jobfile resize

Resize `run_05_miaplpy_unwrap_ifgram` launcher jobs from `inputs/slcStack.h5` so snaphu does not OOM when many unwraps share a node.

Script: `minsar/scripts/resize_miaplpy_unwrap_jobfiles.py` (on `PATH` via `minsar/scripts`).

## Why

Snaphu memory scales with image pixels (~420 bytes/pixel). With `LAUNCHER_PPN=48` on a 192 GB SKX node, large scenes sit at the memory limit. This script sets an integer `LAUNCHER_PPN` from node memory / estimated mem-per-task and, by default, increases the node number (splitting into multiple jobfiles if needed) so walltime stays short.

When unwrap commands use `--num_tiles N` with **N > 1**, MiaplPy/SNAPHU also runs with `--nproc N`. Each concurrent unwrap can use that many cores, so PPN is capped by CPU as well as memory (OPERA-like 5×5 / `N=25` → `LAUNCHER_PPN=1` on 48-core SKX).

## Formulas

```text
# Single-tile (num_tiles == 1)
mem_per_task_MiB = LENGTH * WIDTH * 420 / 1024^2
LAUNCHER_PPN     = min(CPUS_PER_NODE, max(1, floor(MEM_PER_NODE_MB / mem_per_task_MiB) - 2))

# Tiled (num_tiles = N > 1); N parsed from unwrap_ifgram.py --num_tiles
mem_per_task_MiB = (LENGTH * WIDTH * 420 / 1024^2) / N
mem_ppn          = min(CPUS_PER_NODE, max(1, floor(MEM_PER_NODE_MB / mem_per_task_MiB) - 2))
cpu_ppn          = max(1, CPUS_PER_NODE // N)
LAUNCHER_PPN     = min(mem_ppn, cpu_ppn)

nodes_needed     = ceil(n_tasks / LAUNCHER_PPN)
```

If `nodes_needed > MAX_NODES_PJ` (16 on `skx-dev`), create multiple `run_05_miaplpy_unwrap_ifgram_*.job` files, each with at most `MAX_NODES_PJ` nodes.

The `- 2` safety margin avoids snaphu `malloc` failures when many unwraps start on the same node at once (launcher first wave). Margin 1 was still too thin for Etna `miaplpy_Big1` (PPN=25 → 1/64 OOM).

Queue limits and memory come from `minsar/defaults/queues.cfg`.

Tile count itself comes from the template:

```text
ntiles = num_pixels // miaplpy.unwrap.snaphu.tileNumPixels   # (min 1)
```

OPERA-like ~2 Mpx tiles for a ~45 Mpx scene: `tileNumPixels ≈ 1790000` → `ntiles=25` → MiaplPy `--tile 5 5 400 400`.

## Automation in `minsarApp.bash`

When `--miaplpy` starts at step 1, `minsarApp.bash` runs:

1. `run_workflow.bash … --start 1 --stop 1` (load_data → `inputs/slcStack.h5`)
2. `resize_miaplpy_unwrap_jobfiles.py <miaplpy_dir>`
3. `run_workflow.bash … --start 2 --stop <miaplpy_stop>` (skipped if `--miaplpy-stop 1`)

If `--miaplpy-start` is greater than 1, the resize step is skipped (resume path).

## Manual recipe (same sequence)

```bash
run_workflow.bash $TE/<site>.template --dir <miaplpy_dir> --start 1 --stop 1
resize_miaplpy_unwrap_jobfiles.py <miaplpy_dir>
run_workflow.bash $TE/<site>.template --dir <miaplpy_dir> --start 2
```

Use `--dry-run` for debugging; `--no-scale-node-number` to only lower PPN without raising nodes.

## CLI

```bash
resize_miaplpy_unwrap_jobfiles.py miaplpy_202001_202412
resize_miaplpy_unwrap_jobfiles.py miaplpy_202001_202412 --dry-run
resize_miaplpy_unwrap_jobfiles.py miaplpy_202001_202412 --no-scale-node-number
resize_miaplpy_unwrap_jobfiles.py miaplpy_202001_202412 --queue skx
```

First status line example:

```text
Queue skx-dev with node memory 192 GB, file size 2221x4786. For 48 simultaneous jobs max file size is 2221xWWW
```

Tiled example:

```text
num_tiles=25 (SNAPHU --nproc=25): cpu_ppn_cap=1, using tiled mem estimate
... LAUNCHER_PPN=1 ...
```
