# Masking invalid pixels

How MinSAR and MintPy hide bad pixels: where the mask lives, what InsarMaps ingest actually uses, how `view.py` / `tsview.py` decide to mask, radar vs geocoded `.he5`, then ISCE3 product remask.

Figures: drop screenshots in [`images/masking_invalid_pixels/`](images/masking_invalid_pixels/). Paste an image into Cursor chat and ask to place it; filenames are listed under [Figures](#figures).

## Current practices

Three different masks can exist for the same stack. Tools do **not** all use the same one.

| Mask | Typical file | Written by |
|---|---|---|
| MintPy display mask (radar) | `mintpy/maskTempCoh.h5` | `generate_mask.py` from `temporalCoherence.h5` using `mintpy.networkInversion.minTempCoh` |
| MintPy display mask (geo) | `mintpy/geo/geo_maskTempCoh.h5` | `geocode.py` of `maskTempCoh.h5` |
| HE5 product mask | `HDFEOS/GRIDS/timeseries/quality/mask` inside `S1_*.he5` | `save_hdfeos5.py` (copy of `maskTempCoh` / `geo_maskTempCoh`) or `dolphin2hdfeos5.py` (`-m recommended` by default) |

MintPy **does not** NaN-fill `observation/displacement` from that mask. ISCE3 `dolphin2hdfeos5.py` matches that: it writes the **source displacement cube** and a separate `quality/mask`. InsarMaps ingest and `view.py` (when plotting displacement) apply `quality/mask` at read time.

### 0 vs NaN (not a reliability flag)

Whether a sample is stored as **0** or **NaN** is a sentinel convention, not a reason the pixel is bad.

| Value | Meaning |
|---|---|
| **NaN** | Almost always “no sample.” Mask it. |
| **0** | Ambiguous. Can be the **reference date** (valid pixels are 0), real ~0 m motion, Dolphin **GDAL nodata = 0**, or a MintPy pixel that was never inverted. |

Dolphin unwrap/timeseries GeoTIFFs mark invalid with **nodata 0**, while valid land on the reference date is **also 0**. `dolphin2hdfeos5.py` does **not** treat `value == 0` as invalid (`np.isfinite(0)` is true). It uses water, NaNs already in the cube, and the TC/similarity (or density) rule.

MintPy `timeseries.h5` often keeps 0 in unused pixels; display/export uses **`maskTempCoh.h5`**. `tsview.py` dropping all-zero stacks is a heuristic, not “0 m means bad.”

After HE5 write, invalid-for-publish is **`quality/mask == False`**. Displacement may still hold a number (or a source NaN) there so `remask_hdfeos5.py` can change the mask without reconverting.

### InsarMaps ingest (`hdfeos5_2json_mbtiles.py`)

The converter **does** use the HE5 mask. It is not unused.

```text
displacement = HDFEOS.read('displacement')
mask = HDFEOS.read('mask')           # quality/mask
displacement = mask_matrix(displacement, mask)   # mask==0 → NaN on all dates
keep pixel if first-date value is not NaN
write all dates for that pixel into JSON
```

`should_mask = True` is hardcoded. Lat/lon come from `geometry/latitude` and `geometry/longitude` (radar or geo). If `X_STEP` / `Y_FIRST` are missing, tippecanoe runs in “high res” mode; a regular geo grid uses those attributes.

Pixel inclusion is **first date not NaN** after masking. A later-date NaN still gets written into JSON and can break ingest. That is why `dolphin2hdfeos5.py` also drops pixels that are non-finite on **any** date.

Changing ingest is still reasonable (skip a pixel if **any** date is NaN; optional `--no-mask`), but you do **not** need that change for “apply `quality/mask`.” The HE5 displacement cube plus `quality/mask` already gives the same InsarMaps points, as long as surviving pixels are finite on every date.

### `view.py` and `tsview.py`

Both take `-m FILE` and `-m no` (turn masking off). Auto-mask is file-type specific.

**`view.py`** (`mintpy.utils.plot.read_mask`):

| What you plot | Auto mask |
|---|---|
| `velocity.h5` / `timeseries.h5` (radar) | Sibling `maskTempCoh.h5` (else `maskResInv.h5`) |
| `geo_velocity.h5` / `geo_timeseries*.h5` (basename starts with `geo_`) | Sibling `geo_maskTempCoh.h5` |
| `S1_….he5` default (`displacement`) | **`quality/mask` inside the `.he5`** |
| `S1_….he5 temporalCoherence` / `height` / `mask` / other non-displacement | **No** HE5 mask |
| `temporalCoherence.h5`, `avgSpatialCoh.h5`, geometry | **No** auto mask |
| Filename contains `msk` | Skip auto sibling search |
| `-m no` or `--zero-mask` without `-m FILE` | No file mask |

**`tsview.py`:**

1. If you did not pass `-m` and the path does not contain `msk`: look next to the file for `geo_maskTempCoh.h5` if `Y_FIRST` is set, else `maskTempCoh.h5`.
2. If that file is missing, `mask_file` is cleared.
3. Then `read_mask(..., datasetName='displacement')`. For a `.he5` that means **`quality/mask`**. For `timeseries.h5` with no sibling mask, only NaNs / all-zero samples are dropped.

Neither viewer walks the MintPy tree. They do **not** look in `mintpy/` when you are in `geo/`, or the other way around. They only check **the same directory as the file you named** (plus, for `.he5` displacement, the mask **inside** that file).

### Why MintPy sometimes shows no mask

Usual causes:

1. **You plotted a quality layer.** `view.py S1_….he5 temporalCoherence` and `view.py temporalCoherence.h5` do not apply `maskTempCoh` / `quality/mask`.
2. **Radar vs geo mix.** `view.py geo_velocity.h5 -m maskTempCoh.h5` (or auto-picked sibling with the wrong size) prints `input file has different size from mask file` and continues **unmasked**.
3. **Wrong directory.** `tsview.py geo/geo_timeseries_demErr.h5` looks for `geo/geo_maskTempCoh.h5`. `tsview.py timeseries_demErr.h5` looks for `./maskTempCoh.h5`. A geocoded `.he5` in `timeseries/` looks for `timeseries/geo_maskTempCoh.h5` (usually absent) and then falls back to HE5 `quality/mask` only because FILE_TYPE is HDFEOS.
4. **No mask file yet.** You opened `velocity.h5` before `generate_mask.py` / `smallbaselineApp` finished `maskTempCoh.h5`.
5. **You turned it off.** `-m no`, `--zero-mask`, or a `*msk*` filename.
6. **You skipped the mask on a MintPy cube.** `view.py velocity.h5 -m no` shows the full field. ISCE3 HE5s also keep displacement outside `quality/mask`; without the mask, noisy pixels appear.

Force the mask you want:

```bash
view.py velocity.h5 -m maskTempCoh.h5
view.py geo/geo_velocity.h5 -m geo/geo_maskTempCoh.h5
view.py S1_….he5 displacement
view.py S1_….he5 temporalCoherence
tsview.py timeseries_demErr.h5 -m maskTempCoh.h5
tsview.py S1_….he5
```

### Radar vs geocoded `.he5`

| | Radar HE5 | Geo HE5 |
|---|---|---|
| Typical source | MintPy / MiaplPy `save_hdfeos5.py` + `geometryRadar.h5` | MintPy `geo_*` + `geometryGeo.h5`, `geocode_hdfeos5.py` (`geo_` prefix), or ISCE3 `dolphin2hdfeos5.py` |
| `Y_FIRST` / `X_STEP` | usually absent | present |
| `quality/mask` | copy of `maskTempCoh.h5` | copy of `geo_maskTempCoh.h5`, or ISCE3 `-m` rule |
| Displacement NaN-filled from mask | no (MintPy) | no (MintPy and ISCE3 `dolphin2hdfeos5`) |
| Ingest | same: `quality/mask` + 2D lat/lon | same |
| `view.py` auto mask | HE5 `quality/mask` if plotting displacement | same |
| Sibling `maskTempCoh` | must match radar size | must match geo size (`geo_maskTempCoh.h5`) |

ISCE3 OPERA/Dolphin products are already geographic. There is no separate radar HE5 on that path.

MiaplPy export (`save_miaplpy_hdfeos5.bash`) writes **radar** HE5s: PS uses `../maskPS.h5`, DS uses `maskTempCoh.h5`, filtered DS uses `maskTempCoh_lowpass_gaussian.h5` at `--mask-thresh` (template `mintpy.networkInversion.minTempCoh`).

## ISCE3 product mask (`dolphin2hdfeos5` / `remask_hdfeos5`)

OPERA DISP-S1 skips Dolphin processing masks. The published mask is built at HE5 time.

Default `-m recommended`: keep unless **both** temporal coherence and phase similarity are below cutoffs (TC 0.6 **or** similarity 0.4), plus water ≠ 0 and finite displacement on all dates. That rule is stored in `quality/mask` only; **displacement is not NaN-filled** so `remask_hdfeos5.py` can tighten or loosen the mask from the same file.

### Example: Miami OPERA DISP (`qMiamiMiaDISPSenA48`)

```bash
minsarIsce3App.bash 25.783:25.809,-80.308:-80.263 qMiamiMia --data-type disp-s1 --flight-dir asc --end-date 2021-01-28
```

```bash
dolphin2hdfeos5.py qMiamiMiaDISPSenA48-stack.nc --method-string operaDisp --watermask qMiamiMiaDISPSenA48-stack.nc
```

No `-m` flag means `-m recommended`. Template `mintpy.networkInversion.minTempCoh` is unused on this path.

Stronger mask without re-download (`remask_hdfeos5.py` writes a new file):

```bash
cd $SCRATCHDIR/qMiamiMiaDISPSenA48
remask_hdfeos5.py timeseries/S1_asc_048_operaDisp_20160927_20210104_N2578W08031_N2581W08031_N2581W08026_N2578W08026.he5 -m tc+sim --vmin 0.7 --vmin-sim 0.5
ingest_insarmaps.bash timeseries/S1_asc_048_operaDisp_20160927_20210104_N2578W08031_N2581W08031_N2581W08026_N2578W08026_tc070sim050.he5
```

```bash
remask_hdfeos5.py timeseries/S1_….he5 -m tc --vmin 0.7
remask_hdfeos5.py timeseries/S1_….he5 -m recommendedDensity --vmin 0.9
remask_hdfeos5.py timeseries/S1_….he5 -m recommendedDensity --vmin 0.95
remask_hdfeos5.py timeseries/S1_….he5 -m psDensity
remask_hdfeos5.py timeseries/S1_….he5 -m psDensity --vmin 0.5
```

`-m recommended` is an **OR** rule. `-m tc` at the same 0.6 is already stronger. `recommendedDensity` (OPERA only) keeps pixels good in ≥ `--vmin` of dates (default 0.9). `psDensity` (OPERA only) keeps pixels classified as persistent scatterers on **more than `--vmin` of dates**: default `0` = PS at least once; `--vmin 0.5` = PS on more than half of the dates.

### Product-mask CLI (`-m`)

Shared by `dolphin2hdfeos5.py` and `remask_hdfeos5.py`. Every mode also requires water ≠ 0 (when present) and finite displacement on all dates.

| `-m` | Keep pixel if | Defaults | Sweets / Dolphin | OPERA DISP |
|---|---|---|---|---|
| `recommended` | TC ≥ 0.6 **or** similarity ≥ 0.4 (fixed; no `--vmin`) | 0.6 / 0.4 | yes | yes |
| `tc+sim` | same OR rule, tunable | 0.6 / 0.4 | yes | yes |
| `tc` | TC > `--vmin` | 0.6 | yes | yes |
| `similarity` | similarity > `--vmin` | 0.4 | yes | yes |
| `recommendedDensity` | `recommendedDensity` ≥ `--vmin` | 0.9 | error | yes |
| `psDensity` | PS on more than `--vmin` of dates (`0` = at least once; `0.5` = more than half) | 0 | error | yes |

```bash
dolphin2hdfeos5.py dolphin
dolphin2hdfeos5.py stack.nc --method-string operaDisp --watermask stack.nc -m tc --vmin 0.7
remask_hdfeos5.py S1_….he5 -m tc --vmin 0.7
remask_hdfeos5.py S1_….he5 -m tc+sim --vmin 0.7 --vmin-sim 0.5
remask_hdfeos5.py S1_….he5 -m recommendedDensity --vmin 0.95
remask_hdfeos5.py S1_….he5 -m psDensity
remask_hdfeos5.py S1_….he5 -m psDensity --vmin 0.5
remask_hdfeos5.py S1_…_tc070sim050.he5 -m recommended
```

```bash
view.py timeseries/S1_….he5 mask
view.py timeseries/S1_….he5 temporalCoherence
view.py timeseries/S1_….he5 phaseSimilarity
info.py timeseries/S1_….he5
```

### What is stored in the ISCE3 `.he5`

| Dataset | Role |
|---|---|
| `quality/mask` | Ingest + `view.py`/`tsview.py` when plotting displacement |
| `quality/temporalCoherence` | `-m recommended`, `tc`, `tc+sim` |
| `quality/phaseSimilarity` | `-m recommended`, `similarity`, `tc+sim` |
| `quality/waterMask` | water ≠ 0 |
| `quality/recommendedDensity` | `-m recommendedDensity` (OPERA) |
| `quality/persistentScattererDensity` | `-m psDensity` (OPERA; from `persistent_scatterer_mask`) |
| `quality/conncomp` | stored, not in current `-m` rules |
| `observation/displacement` | Source cube (Dolphin/OPERA values, including pixels outside `quality/mask`) |
| `geometry/shadowMask` | stored, not in `-m` rules |

`remask_hdfeos5.py` rewrites **`quality/mask` only**. Ingest / `view.py` displacement still apply the new mask. **Older HE5s** that were NaN-filled at write time cannot be loosened; reconvert with current `dolphin2hdfeos5.py` (or keep `*-stack.nc`). Water stays out of `quality/mask` even when the cube has a number there.

Dolphin ministack TC/similarity vary by batch; the HE5 stores the **averaged** 2-D layers, not per-ministack masks.

## Processing-time masks (SAFE / CSLC Dolphin)

These change the inversion. They do not apply to `--data-type disp-s1`. See [README_minsarIsce3App.md](README_minsarIsce3App.md).

| Option | Effect |
|---|---|
| `mask_file` (default `watermask.tif`, 0 = ignore) | Water / geometry through the workflow |
| `ps_options.amp_dispersion_threshold` | PS selection (wrapped) |
| `unwrap_options.run_interpolation` + interpolation corr/similarity thresholds | Fill low-quality wrapped pixels **before** unwrap |
| `timeseries_options.apply_mask_to_timeseries` | Apply `mask_file` in the inversion |
| `timeseries_options.correlation_threshold` (default 0.2) | Drop low-corr pixels in the inversion |
| `--half-window-preset` | Phase-linking window (quality), not a display mask |

HE5 conversion still uses `-m recommended` unless you change that run file.

```bash
dolphin2hdfeos5.py dolphin --method-string dolphinStandard --watermask dolphin/unwrapped/warped_watermask.tif -m tc --vmin 0.7
```

## Code

| Piece | Path |
|---|---|
| Convert | `minsar/utils/dolphin2hdfeos5.py` |
| Remask | `minsar/utils/remask_hdfeos5.py` |
| Shared rules | `minsar/utils/dolphin_hdfeos5_utils.py` |
| Ingest mask | `tools/insarmaps_scripts/hdfeos5_2json_mbtiles.py` (`mask_matrix`) |
| Viewer auto mask | `tools/MintPy/src/mintpy/utils/plot.py` (`read_mask`) |
| MintPy HE5 mask copy | `save_hdfeos5.py` `-m maskTempCoh.h5` / `geo_maskTempCoh.h5` |

## Figures

Put PNGs in `docs/images/masking_invalid_pixels/`.

| File | Caption |
|---|---|
| `01_miami_recommended.png` | InsarMaps, default `-m recommended` |
| `02_miami_tc070_sim050.png` | `-m tc+sim --vmin 0.7 --vmin-sim 0.5` |
| `03_miami_tc070.png` | `-m tc --vmin 0.7` |
| `04_miami_dens090.png` | `-m recommendedDensity --vmin 0.9` |
| `05_temporalCoherence.png` | `view.py … temporalCoherence` (no auto mask) |
| `06_phaseSimilarity.png` | `view.py … phaseSimilarity` |
| `07_mask.png` | `view.py … mask` |
| `08_view_unmasked.png` | `view.py velocity.h5 -m no` vs `-m maskTempCoh.h5` |

After a file is in that folder, reference it with `![caption](images/masking_invalid_pixels/01_miami_recommended.png)`.
