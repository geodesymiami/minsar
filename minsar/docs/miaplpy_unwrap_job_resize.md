# MiaplPy unwrap jobfile resize

Resize `run_05_miaplpy_unwrap_ifgram` launcher jobs from `inputs/slcStack.h5` so snaphu does not OOM when many unwraps share a node.

Script: `minsar/scripts/resize_miaplpy_unwrap_jobfiles.py` (on `PATH` via `minsar/scripts`).

## Why

Snaphu memory scales with image pixels (~420 bytes/pixel). With `LAUNCHER_PPN=48` on a 192 GB SKX node, large scenes sit at the memory limit. This script sets an integer `LAUNCHER_PPN` from node memory / estimated mem-per-task and, by default, increases the node number (splitting into multiple jobfiles if needed) so walltime stays short.

## Formulas

```text
mem_per_task_MiB = LENGTH * WIDTH * 420 / 1024^2
LAUNCHER_PPN     = min(CPUS_PER_NODE, floor(MEM_PER_NODE_MB / mem_per_task_MiB))
nodes_needed     = ceil(n_tasks / LAUNCHER_PPN)
```

If `nodes_needed > MAX_NODES_PJ` (16 on `skx-dev`), create multiple `run_05_miaplpy_unwrap_ifgram_*.job` files, each with at most `MAX_NODES_PJ` nodes.

Queue limits and memory come from `minsar/defaults/queues.cfg`.

## Phase 2 recipe (manual; wire into minsarApp later)

`slcStack.h5` exists after load_data (step 1). Resize then, then continue from step 2:

```bash
# 1) Jobfiles + load_data only
run_workflow.bash $TE/<site>.template --dir <miaplpy_dir> --start 1 --stop 1
#    equivalent names: --start load_data --stop load_data

# 2) Resize unwrap packing
resize_miaplpy_unwrap_jobfiles.py <miaplpy_dir>
#    example: resize_miaplpy_unwrap_jobfiles.py miaplpy_202001_202412

# 3) Continue from phase linking (step 2)
run_workflow.bash $TE/<site>.template --dir <miaplpy_dir> --start 2
#    or: --start phase_linking
```

### Later automation checklist

1. After miaplpy step 1 succeeds in `minsarApp.bash` / `run_workflow.bash`, call `resize_miaplpy_unwrap_jobfiles.py "$miaplpy_dir"`.
2. Then submit steps 2… as today.
3. Keep `--dry-run` for debugging; keep `--no-scale-node-number` to only lower PPN without raising nodes.

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
