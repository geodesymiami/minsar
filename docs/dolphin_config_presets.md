# Dolphin config presets and workflow stages

MinSAR single-run CSLC/SAFE Dolphin uses one `dolphin_config.yaml`, but the workflow runs it in **three science layers** (`dolphin_wrapped`, `dolphin_unwrap`, `dolphin_timeseries`). The `--dolphin-config` preset only sets a **subset** of YAML keys at `dolphin config` time; other knobs come from `--half-window`, `--stride`, `--ministack-size`, or any leftover `--section.option` flags.

## `--dolphin-config` presets

| Preset | Project name token | HE5 `post_processing_method` | What the preset adds beyond Dolphin defaults |
|--------|-------------------|------------------------------|-----------------------------------------------|
| `disp-s1` (default) | *(none)* | `dolphin` (+ optional `Dry`/`Wet`/`Arctic`) | `amp_dispersion_threshold` 0.2; unwrap preprocess: `interpolation_cor_threshold` 0.3, `interpolation_similarity_threshold` **0.25**, `max_radius` 71 |
| `disp-s1-downloaded` | `DispS1Downloaded` | `dolphinDispS1Downloaded` | Same amp/interp_cor/max_radius as above; `interpolation_similarity_threshold` **0.4**; phase linking: `ministack_size` 100, `max_num_compressed` 100, `compressed_slc_plan` **ALWAYS_FIRST**, `output_reference_idx` 0 |
| `disp-s1-process` | `DispS1Process` | `dolphinDispS1Process` | `amp_dispersion_threshold` **0.25**; unwrap preprocess: `interpolation_cor_threshold` **0.001**, `interpolation_similarity_threshold` 0.4, `max_radius` **150** |
| `pydantic` | `Pydantic` | `dolphinPydantic` | No extra science flags (Dolphin package defaults only) |

Source: `minsar/utils/dolphin_presets.py` (`DOLPHIN_CONFIG_SCIENCE`).

### Related CLI (not part of `--dolphin-config`)

| Flag | Effect |
|------|--------|
| `--half-window Y X` / `--half-window-preset {standard,dry,wet,arctic}` | `phase_linking.half_window` (default standard = 6×12; dry = 5×11) |
| `--stride Y X` | `output_options.strides` (default 3×6) |
| `--ministack-size N` | Overrides `phase_linking.ministack_size` for any preset |
| `--unwrap-method NAME` | Shortcut for `unwrap_options.unwrap_method` |
| Any `--phase-linking.*`, `--unwrap-options.*`, `--timeseries-options.*` | Merged with preset; explicit flags win |

Worker keys (`n_parallel_bursts`, `threads_per_worker`, `n_parallel_jobs`, …) are set at config generation from node CPU count and burst count; they do not change science results.

### Downloaded OPERA vs local presets

`--data-type disp-s1` downloads OPERA L3 DISP-S1 products (`dispS1` HE5 tag). That path does **not** use `--dolphin-config`; science was fixed at ASF/JPL production time.

`disp-s1-downloaded` approximates the **algorithm_parameters** embedded in downloaded products for a **local** continuous single-run. OPERA products use `last_per_ministack` in per-batch historical processing; MinSAR uses `always_first` because Dolphin rejects `last_per_ministack` when `ministack_size < n_slcs`.

---

## Workflow steps (single-run CSLC)

```
download_cslc → dolphin_wrapped → dolphin_unwrap → dolphin_timeseries → dolphin_2_he5 → ingest_insarmaps → upload
```

| MinSAR step | Scripts | Dolphin work |
|-------------|---------|--------------|
| **dolphin_wrapped** | `cleanup_dolphin_ministacks.py`, `dolphin config …`, `run_dolphin_wrapped.py` | Per-burst phase linking, PS detection, interferogram network at burst level. **No** stitch, unwrap, or timeseries. |
| **dolphin_unwrap** | `run_dolphin_stitch.py`, `resize_dolphin_unwrap_jobfile.py`, `run_dolphin_unwrap.py` | Stitch burst ifgs → **preprocess / interpolation** on wrapped phase → **SNAPHU (or other) unwrap**. |
| **dolphin_timeseries** | `run_dolphin_timeseries.py` | Network inversion, velocity, temporal coherence / similarity products used later for HE5. |
| **dolphin_2_he5** | `dolphin2he5.py` | Build HDF-EOS5; `-m recommended` mask from quality layers (separate from unwrap preprocess). |

Monolithic mode (`create_isce3_runfiles.py --no-dolphin-split`): one `dolphin run` job instead of the three steps above.

---

## Which YAML keys apply in which step

Classification follows `layer_for_key()` in `minsar/utils/isce3_dolphin_experiment.py`.

### Wrapped layer → `dolphin_wrapped`

| Key group | Examples | Role |
|-----------|----------|------|
| `phase_linking.*` | `half_window`, `ministack_size`, `max_num_compressed`, `compressed_slc_plan`, `output_reference_idx`, `shp_method`, `shp_alpha` | Sequential EMI / phase linking, compressed SLC plan, similarity rasters |
| `ps_options.*` | `amp_dispersion_threshold` | Persistent scatterer mask (`PS/ps_pixels.tif`) |
| `interferogram_network.*` | `max_bandwidth`, `reference_idx` | Which ifgs exist after linking |
| `output_options.strides` | `--stride` | Multilook stride for linked products |
| `mask_file` | `watermask.tif` | AOI / water mask for linking |

**Preset unwrap preprocess keys** (`unwrap_options.preprocess_options.*`) are written into YAML at config time but **are not executed** during `dolphin_wrapped`.

### Unwrap layer → `dolphin_unwrap`

| Key group | Examples | Role |
|-----------|----------|------|
| `unwrap_options.preprocess_options.*` | `interpolation_cor_threshold`, `interpolation_similarity_threshold`, `max_radius`, `alpha` | Fill/mask low-quality pixels on **wrapped** interferograms **before** unwrap |
| `unwrap_options.run_interpolation` | default on (`--unwrap-options.run-interpolation` at config) | Enable that preprocess step |
| `unwrap_options.run_goldstein` | optional Goldstein filter | Pre-unwrap filtering |
| `unwrap_options.unwrap_method`, `snaphu_options.*` | SNAPHU tiles, cost, init | Phase unwrapping |
| `unwrap_options.zero_where_masked` | | Zero phase/corr on mask before unwrap |
| `unwrap_options.n_parallel_jobs` | | Parallel unwrap jobs (worker sizing) |

**When interpolation runs:** inside `run_dolphin_unwrap.py` → `dolphin.workflows.unwrapping.run()`, **after** stitch, **before** SNAPHU. It is **not** applied during `dolphin_wrapped` and **not** after unwrap completes.

### Timeseries layer → `dolphin_timeseries`

| Key group | Examples | Role |
|-----------|----------|------|
| `timeseries_options.*` | `correlation_threshold`, `apply_mask_to_timeseries`, inversion method | Inversion mask and solver options |

### HE5 step (not a Dolphin run stage)

| Key | Role |
|-----|------|
| `dolphin2he5.py -m recommended` | OPERA-style mask from averaged TC + similarity (OR rule, 0.6 / 0.4); independent of unwrap preprocess thresholds |

---

## Are `dolphin_wrapped` results the same for `disp-s1` and `disp-s1-process`?

**No**, in general — but the difference is **small** between those two presets specifically.

| Parameter | `disp-s1` | `disp-s1-process` | Affects wrapped? |
|-----------|-----------|---------------------|------------------|
| `amp_dispersion_threshold` | 0.2 | 0.25 | **Yes** — different PS pixel set |
| `ministack_size` / compressed plan | Dolphin defaults (15, `always_first`) | same | No difference from preset alone |
| `interpolation_*` / `max_radius` | 0.3 / 0.25 / 71 | 0.001 / 0.4 / 150 | **No** at wrapped stage (stored in YAML only) |

So `dolphin_wrapped` outputs differ mainly through **PS selection** (`amp_dispersion_threshold`). Phase linking, ministacks, and similarity rasters are otherwise the same unless you change `--half-window`, `--ministack-size`, or other wrapped-layer flags.

`disp-s1-downloaded` **does** change wrapped outputs strongly (`ministack_size` 100, `max_num_compressed` 100, `output_reference_idx` 0, different sequential linking).

---

## Rerunning with different options (without redoing everything)

MinSAR already splits unwrap from wrapped. Layer-aware reruns use `--from-dolphin-dir` and optional auto `--dolphin-dir` naming (see `docs/README_minsarIsce3App.md`).

| Change | Earliest step to rerun | Inputs symlinked from source dir |
|--------|------------------------|----------------------------------|
| `phase_linking.*`, `ps_options.*`, strides, network | `dolphin_wrapped` | none |
| `unwrap_options.*` (including preprocess / interpolation) | `dolphin_unwrap` | `interferograms/` |
| `timeseries_options.*` | `dolphin_timeseries` | `interferograms/`, `unwrapped/` |

Example — same wrapped products, stricter unwrap preprocess:

```bash
minsarIsce3App.bash AOI NAME --data-type cslc --from-dolphin-dir dolphin --unwrap-options.preprocess-options.interpolation-similarity-threshold 0.4 --start dolphin_unwrap
```

Example — new preset on existing CSLCs (full rerun from wrapped):

```bash
minsarIsce3App.bash AOI NAME --data-type cslc --dolphin-config disp-s1-process --half-window 5 11 --start dolphin
```

### Can `dolphin_unwrap` be split further?

**Today:** `dolphin_unwrap` = **stitch** + **unwrap job** (preprocess + SNAPHU in one `unwrapping.run()` call). There is **no** separate MinSAR step for “interpolation only” or “unwrap only after interpolation.”

| Sub-step | Script today | Separate SLURM job? |
|----------|--------------|---------------------|
| Stitch burst ifgs | `run_dolphin_stitch.py` | Runs at start of `dolphin_unwrap` job |
| Preprocess / interpolation | inside `run_dolphin_unwrap.py` | Same job as unwrap |
| SNAPHU unwrap | inside `run_dolphin_unwrap.py` | Same job |

To try **different preprocess options after unwrapping** you would need **post-unwrap** logic (not in Dolphin preprocess); that lives in **timeseries** (`timeseries_options.correlation_threshold`, etc.) or HE5 remasking (`remask_he5.py`), not in `unwrap_options.preprocess_options`.

To try **different preprocess without redoing wrapped**: rerun from `dolphin_unwrap` with new `unwrap_options.preprocess_options.*` (new `dolphin_dir` or edited YAML). That **re-runs** stitch + preprocess + unwrap together; stitch is cheap relative to unwrap.

Adding a dedicated “preprocess-only” or “unwrap-only” MinSAR step would require new wrapper scripts around Dolphin’s workflow API; it is not implemented now.

---

## Quick reference: preset → stage impact

| Preset | `dolphin_wrapped` | `dolphin_unwrap` | `dolphin_timeseries` | HE5 name token |
|--------|-------------------|------------------|----------------------|----------------|
| `disp-s1` | PS threshold | preprocess 0.25 sim | defaults | `dolphin` |
| `disp-s1-downloaded` | ministack 100, ref idx 0, PS 0.2 | preprocess 0.4 sim | defaults | `dolphinDispS1Downloaded` |
| `disp-s1-process` | PS 0.25 | preprocess 0.001 cor, 0.4 sim, radius 150 | defaults | `dolphinDispS1Process` |
| `pydantic` | Dolphin defaults | Dolphin defaults | Dolphin defaults | `dolphinPydantic` |
