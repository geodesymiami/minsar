# ISCE3 unwrap scale-out (opportunity 3)

Background: [ISCE3_HPC_opportunities.md](../ISCE3_HPC_opportunities.md) types **A** / **B**. Depends on opportunity 2 (clean stitch→unwrap boundary).

## Goal

Shorten unwrap walltime after stitched ifgs exist. Stock dolphin only offers in-process `n_parallel_jobs` + snaphu tiles on **one node**. Multi-node (~16×48) needs MinSAR-owned LAUNCHER tasks.

## Options

1. **Fat node (type B)** — raise `n_parallel_jobs` / `ntiles` on pvc/h100; simplest.
2. **LAUNCHER per-ifg (type A)** — emit one snaphu (or thin wrapper) command per stitched ifg; `launcher_multiTask_multiNode`.
3. **Hybrid** — LAUNCHER across ifgs; modest tiles per ifg.

## Why dolphin alone is insufficient

No task-list export; no MPI; unwrap embedded as snaphu-py calls inside `DisplacementWorkflow`; pipeline couples stitch→unwrap→timeseries.

## Out of scope

- GPU unwrap (none available in stock snaphu path).
- Spatial end-to-end per-burst products without stitch.

## Steps

1. Pick strategy; document queue/CPU targets.
2. Implement job generation + skip completed unwrap outputs.
3. Integrate with stage-split unwrap step; smoke and compare walltime.
