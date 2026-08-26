# ISCE3 GPU path (opportunity 4)

Background: [ISCE3_HPC_opportunities.md](../ISCE3_HPC_opportunities.md) type **D**. Independent of opportunities 1–3 but combines well with them (GPU linking → CPU unwrap).

## Goal

Use CUDA where it helps: COMPASS geocode (`isce3-cuda` via sweets `gpu` pixi env) and dolphin phase linking / timeseries (JAX+CUDA). Expect ~3–20× on linking and large scene-dependent gains on COMPASS; **snaphu unwrap has no GPU**.

## Scope

- Pixi/environment selection for GPU stages; queue selection (`h100`, `amd-rtx`, etc.).
- `worker_settings.gpu_enabled` for dolphin; memory fraction guidance for multi-burst GPU use.

## Out of scope

- GPU unwrap algorithms.
- Changing CPU LAUNCHER CSLC path (opportunity 1 remains valid on skx).

## Steps

1. Document install/activate (`pixi shell -e gpu`) and known Stampede constraints.
2. Wire optional GPU mode into run/job generation for `create_cslc` and dolphin linking.
3. Smoke and note rough walltime vs CPU baseline.
