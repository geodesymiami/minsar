# minsarIsce3App.bash

`minsarIsce3App.bash` is the user command for ISCE3 SAFE, CSLC, and DISP-S1 processing. It always identifies the dataset the same way as `create_isce3_runfiles.py`: a MinSAR template, or AOI plus project name (and `--flight-dir` when the first argument is an AOI). Science flags alone are invalid.

Work directory is `$SCRATCHDIR/<project>` from that template stem or name. The app writes ISCE3 run/job files under `run_files_isce3/`, then runs `run_isce3_workflow.bash run_files_isce3` from the project directory.

Optional alias: `run_isce3.bash` → `minsarIsce3App.bash`.

Use `--start-date` / `--end-date` for dates. `--start` / `--end` / `--dostep` are processing steps (not dates).

## Commands

```bash
minsarIsce3App.bash $TE/HawaiiPunaSenD87.template
minsarIsce3App.bash $TE/HawaiiPunaSenD87.template --data-type cslc --start download
minsarIsce3App.bash $TE/HawaiiPunaSenD87.template --unwrap-options.run-interpolation true
minsarIsce3App.bash $TE/HawaiiPunaSenD87.template --start dolphin_unwrap --unwrap-method whirlwind
minsarIsce3App.bash $TE/HawaiiPunaSenD87.template --start ingest_insarmaps
minsarIsce3App.bash 19.45:19.5,-154.915:-154.852 HawaiiPuna --flight-dir desc
minsarIsce3App.bash 19.45:19.5,-154.915:-154.852 HawaiiPuna --flight-dir desc --unwrap-options.run-interpolation true
```

```bash
create_isce3_runfiles.py $TE/HawaiiPunaSenD87.template --data-type cslc --phase download
create_isce3_runfiles.py $TE/HawaiiPunaSenD87.template --data-type cslc --phase dolphin --dolphin-dir dolphin_interp --unwrap-options.run-interpolation true
create_isce3_runfiles.py 19.45:19.5,-154.915:-154.852 HawaiiPuna --flight-dir desc --data-type cslc --phase all
```

## What the app passes to the generator

| App command | Generator extras | Then `run_isce3_workflow.bash run_files_isce3` |
|---|---|---|
| template only | `--phase all` | step 1 through last |
| `--start download` | `--phase download` | `--start download --end download` (SAFE: `download_safe` through `create_cslc`) |
| `--start dolphin_wrapped` | `--phase dolphin --dolphin-dir dolphin` | `dolphin_wrapped` through ingest |
| `--unwrap-options.run-interpolation true` | `--phase dolphin` plus the flag (auto `DIR=dolphin_interp`) | unwrap through ingest |
| `--start dolphin_unwrap --unwrap-method whirlwind` | `--phase dolphin --unwrap-method whirlwind` (auto `DIR=dolphin_whirlwind`) | unwrap through ingest |
| `--start ingest_insarmaps` | `--phase dolphin` | `--dostep ingest_insarmaps` |

`--phase download` does not rewrite existing Dolphin `DIR/` trees. `--phase dolphin` requires CSLCs or GSLCs on disk; if they are missing, the generator exits with “run `--start download` first”.

`--phase download` includes `create_cslc` for SAFE. Alias `download_create_cslc` is the same as `download`. Fine step `create_cslc` is still targetable.

DISP: `--phase download` is download plus reformat; `--phase dolphin` is he5 plus ingest; `--dolphin-dir` does not apply.

## Configs before jobs

- `--phase download`: write `sweets_config.yaml` on the login node; download run files start at `sweets_download.py --config sweets_config.yaml`.
- `--phase dolphin` with CSLCs/GSLCs on disk: write `{DIR}_config.yaml` on the login node (`dolphin` → `dolphin_config.yaml`); run files only `dolphin run` / unwrap / timeseries / he5 / ingest against `DIR`.
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

Default **symlink** those trees into `DIR/`; `--copy-dolphin-inputs` for copies. Do not link `unwrapped/` or `timeseries/` into an unwrap experiment.

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

- `download` / `download_create_cslc` — download through `create_cslc` (SAFE) or the last download/reformat stage
- `dolphin` — `dolphin_wrapped` through `dolphin_timeseries` (or monolithic `dolphin`)
- `hdfeos5` — `dolphin_2_hdfeos5`
- `ingest` — `ingest_insarmaps`
