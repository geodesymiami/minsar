# minsarIsce3App.bash

`minsarIsce3App.bash` is the user command for ISCE3 SAFE, CSLC, and DISP-S1 processing. It always identifies the dataset the same way as `create_isce3_runfiles.py`: a MinSAR template, or AOI plus project name (and `--flight-dir` when the first argument is an AOI). Science flags alone are invalid.

Work directory is `$SCRATCHDIR/<project>` from that template stem or AOI name. AOI `HawaiiPuna` becomes `HawaiiPunaSenD87`, `HawaiiPunaCSLCSenD87`, `HawaiiPunaCSLCOperaSenD87` (`--dolphin-mode opera`), or `HawaiiPunaDISPSenD87` from `--data-type` / `--dolphin-mode` and `--flight-dir`. The app writes ISCE3 run/job files under `run_files_isce3/`, then runs `run_isce3_workflow.bash run_files_isce3` from the project directory. `upload` is a separate last step (`.he5` and `insarmaps.log`). A full run includes it. `--dostep` stops at that step and does not upload. `--dostep upload` uploads existing products and prints the last new `insarmaps.log` line.

Optional alias: `run_isce3.bash` → `minsarIsce3App.bash`.

Use `--start-date` / `--end-date` for dates. `--start` / `--end` / `--dostep` are processing steps (not dates).

## Commands

```bash
minsarIsce3App.bash 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --start-date 20220101 --end-date 20241212
minsarIsce3App.bash 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --start-date 20220101 --end-date 20241212
minsarIsce3App.bash 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --dolphin-mode opera --start-date 20220101 --end-date 20241212
minsarIsce3App.bash 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --half-window-preset dry --start-date 20220101 --end-date 20241212
minsarIsce3App.bash 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type disp-s1 --start-date 20220101 --end-date 20241212
minsarIsce3App.bash 18.985:19.054,-98.686:-98.58 Popo --flight-dir desc --start-date 20170101 --end-date 20211231
minsarIsce3App.bash 18.985:19.054,-98.686:-98.58 Popo --flight-dir desc --data-type cslc --dolphin-mode opera --half-window-preset dry --start-date 20170101 --end-date 20211231
```

```bash
create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --start-date 20220101 --end-date 20241212 --phase download
create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --start-date 20220101 --end-date 20241212 --phase dolphin --dolphin-dir dolphin_interp --unwrap-options.run-interpolation true
create_isce3_runfiles.py 18.985:19.054,-98.686:-98.58 Popo --flight-dir desc --start-date 20170101 --end-date 20211231
```

## What the app passes to the generator

| App command | Generator step args | Run files written | Then `run_isce3_workflow.bash run_files_isce3` |
|---|---|---|---|
| template only (no `--start` / `--dostep`) | (none; all stages) | all | `--start download --end ingest_insarmaps`, then `upload` |
| `--start download` | `--start download --end download` | download only | `--start download --end download`. No upload. |
| `--start dolphin_wrapped` | `--start dolphin_wrapped` | from that step through `ingest_insarmaps` | same range, then `upload` |
| `--dostep disp_s1_process` | `--dostep disp_s1_process` | that step only | that step only |
| `--dostep dolphin_2_hdfeos5` / `dolphin2hdfeos5` | `--dostep dolphin_2_hdfeos5` | `dolphin_2_hdfeos5` only | that step only. No upload. |
| `--dostep upload` | skipped | — | `upload_data_products.py` only |

The app passes the same workflow step flags to `create_isce3_runfiles.py` (`--start`, `--end`, `--dostep`) that it uses for `run_isce3_workflow.bash`. Dates use `--start-date` / `--end-date` only. The generator writes run files only for the requested steps. Inferred `--data-type` / `--dolphin-mode` are not forwarded unless you set them explicitly; the generator infers them from the project name.

Dolphin science steps (`dolphin_wrapped`, `disp_s1_process`, …) write `{DIR}_config.yaml` from on-disk CSLCs/GSLCs and fail with “run `--start download` first” when those files are missing. `dolphin_2_hdfeos5` and `ingest_insarmaps` do not need CSLCs. Dolphin science flags (`--half-window`, `--unwrap-options.*`, …) are omitted when the requested range does not include dolphin science steps.

Legacy `create_isce3_runfiles.py --phase download|dolphin|post|all` still works for direct generator calls. Do not pass `--phase` to the app.

A template or project name that contains `SAFE`, `CSLC`, `DISPS1`/`DISP`, and `Opera` sets `--data-type` and `--dolphin-mode` when those flags are omitted. `$TE/unittestHawaiiPunaCSLCOperaSenD87.template --dostep dolphin_2_hdfeos5` is CSLC opera, not the SAFE default.

DISP: `--phase download` is download plus reformat; `--phase post` is he5 plus ingest; `--dolphin-dir` does not apply. `--start reformat_disp` still runs through ingest.

## Configs before jobs

- `--phase download`: write `sweets_config.yaml` on the login node; download run files start at `sweets_download.py --config sweets_config.yaml`.
- `--phase dolphin` with CSLCs/GSLCs on disk: write `{DIR}_config.yaml` on the login node (`dolphin` → `dolphin_config.yaml`); run files are `dolphin run` / unwrap / timeseries / he5 / ingest against `DIR` (opera: `disp_s1_process` through ingest).
- `--phase post`: write he5 and ingest run files (and opera `reformat_disp`) without Dolphin YAML or CSLCs.
- `--phase all` before data exist: first Dolphin job may still run `dolphin config`.

SAFE Dolphin uses `dolphin config --slc-files` plus `dolphin run` on GSLC HDF5s (not `sweets run --starting-step 3`).

## Auto `--dolphin-dir`

Compare forwarded science flags to the source YAML (`--from-dolphin-dir`, default `dolphin/` + `dolphin_config.yaml`). Worker keys (`n_parallel_jobs`, `threads_per_worker`, `n_parallel_bursts`, `num_parallel_blocks`, `block_shape`) do not create a new dir.

| Situation | Directory |
|---|---|
| No science overrides | `dolphin` |
| Overrides equal source YAML | stay on source dir |
| Overrides differ, no `--dolphin-dir` | auto-name from the diff |
| `--dolphin-dir` given | that name always wins |

Auto-name: `dolphin_` + short tokens joined by `_`, order wrapped, unwrap, timeseries.

- `unwrap-options.unwrap-method whirlwind` → `whirlwind`
- `unwrap-options.run-interpolation true` → `interp`
- `unwrap-options.run-goldstein true` → `goldstein`
- `phase-linking.ministack-size 50` → `ms50`
- `timeseries-options.correlation-threshold 0.3` → `corr0p3`
- `timeseries-options.apply-mask-to-timeseries false` → `nomaskts`
- `ps-options.amp-dispersion-threshold 0.2` → `ampdisp0p2`
- unknown key → last dotted component + compacted value (`true` omitted for boolean-on, `.` → `p`)

`$TE/HawaiiPunaSenD87.template --unwrap-options.run-interpolation true` → `$SCRATCHDIR/HawaiiPunaSenD87`, dir `dolphin_interp`. Same template with `--unwrap-method whirlwind` → `dolphin_whirlwind`. Both flags → `dolphin_whirlwind_interp`.

If the auto dir exists, reuse it. The app prints the project path and `DIR` before submit. Use `--dolphin-dir`, not `--work-directory`. Leftover `--section.option` tokens go to `dolphin config`.

## Layer-aware reruns

Classify each science override; start at the earliest layer. Always run he5 and ingest on `DIR`.

| Layer | Typical keys | Inputs from `--from-dolphin-dir` (default `dolphin`) | Jobs |
|---|---|---|---|
| wrapped | `phase_linking.*`, `ps_options.*`, strides, network, `mask_file` | none | wrapped + unwrap + timeseries |
| unwrap | `unwrap_options.*` except worker counts | `interferograms/` | unwrap + timeseries |
| timeseries/mask | `apply_mask_to_timeseries`, `correlation_threshold`, `method`, `reference_point` | `interferograms/` and `unwrapped/` | timeseries |

Those trees are **symlinked** into `DIR/`. Do not link `unwrapped/` or `timeseries/` into an unwrap experiment.

## Masking options

- Top-level `mask_file` (default `watermask.tif`) — 0 = ignore
- `ps_options.amp_dispersion_threshold` — PS selection (wrapped)
- `phase_linking.mask_input_ps`
- `unwrap_options.zero_where_masked` — zero wrapped phase/corr on mask before unwrap
- `unwrap_options.run_interpolation` plus `preprocess_options.interpolation_cor_threshold`, `interpolation_similarity_threshold`, `max_radius`, `zero_correlation_where_interpolating` — mask+fill low-quality wrapped pixels before unwrap
- `timeseries_options.apply_mask_to_timeseries` — apply `mask_file` to the time series
- `timeseries_options.correlation_threshold` — mask low-corr pixels in the inversion (default 0.2)

Interpolation is unwrap preprocess, not a timeseries mask.

## Coarse step aliases

`run_isce3_workflow.bash` (and the app `--start` / `--end` / `--dostep`) accept:

- `download` / `download_create_cslc` — through `create_cslc` (SAFE), `download_cslc` (CSLC), or `reformat_disp` (DISP-S1 only; opera `reformat_disp` is not part of download)
- `dolphin` — `dolphin_wrapped` through `dolphin_timeseries` (or monolithic `dolphin`)
- `hdfeos5` — `dolphin_2_hdfeos5`
- `ingest` — `ingest_insarmaps`
- `dolphin2hdfeos5` — `dolphin_2_hdfeos5`
- `upload` — app step only (not a `run_files_isce3` job). `--dostep` does not include it unless the step is `upload` or `--end upload`
