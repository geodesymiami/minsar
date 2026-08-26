# ISCE3 CSLC multi-node LAUNCHER (opportunity 1)

Background: [ISCE3_HPC_opportunities.md](../ISCE3_HPC_opportunities.md) type **A**. Depends on opportunity 0 (queue-correct job headers).

## Goal

Use the existing COMPASS task list from [prepare_compass_runconfigs.py](../../minsar/utils/prepare_compass_runconfigs.py) as a true multi-node LAUNCHER job (e.g. ~16×48 on `skx`), matching ISCE2 topsStack practice.

## Scope

- `create_cslc` job generation and task restartability (skip existing outputs).
- Prefer production queues (`skx`) for large stacks; respect `skx-dev` `MAX_NODES_PJ` / `MAX_WALLTIME` for tests.

## Out of scope

- Dolphin multi-node or unwrap LAUNCHER (opportunities 2–3).
- GPU COMPASS (`isce3-cuda`) (opportunity 4).

## Steps

1. After task list is materialized, generate `.job` with `submission_scheme=launcher_multiTask_multiNode`, node count from tasks×threads vs `CPUS_PER_NODE`, capped by `MAX_NODES_PJ`.
2. Set `LAUNCHER_NHOSTS`, `#SBATCH -N`, `-n = N * CPUS_PER_NODE`.
3. Align with notebook skip-if-HDF5-exists behavior for productive TIMEOUT resubmit.
4. Smoke on a SAFE project; confirm task count drives `-N` and skx-dev stays within caps.
