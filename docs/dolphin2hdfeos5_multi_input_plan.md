# Plan: HE5 masking (dolphin + OPERA DISP)

Goal: write MintPy-style `.he5` from sweets/dolphin GeoTIFFs or OPERA `*-stack.nc`, with shared masking for `dolphin2hdfeos5.py` and `remask_hdfeos5.py`. Default mask matches OPERA DISP-S1 `recommended_mask` (TC 0.6 / similarity 0.4). `-m recommendedDensity` and `-m psDensity` are OPERA only.

Do **not** invent a Dolphin per-date recommended stack for sweets in this work. MintPy notebook HDF5s are optional; prefer `*-stack.nc`.

CLI: `minsar/utils/dolphin2hdfeos5.py`, `minsar/utils/remask_hdfeos5.py`  
Logic: `minsar/utils/dolphin_hdfeos5_utils.py`

---

## Inputs

| Kind | Detect | Fundamental file |
|---|---|---|
| dolphin | `timeseries/*.tif` | GeoTIFF stack |
| opera-disp | `*-stack.nc` in run dir or `.nc` argument | NetCDF stack |

---

## Defaults

Both CLIs: `-m recommended` = fixed OPERA cutoffs 0.6 / 0.4 (no `--vmin` / `--vmin-sim`), plus water ≠ 0 and finite displacement. Conncomp is stored in the HE5, not in the default rule.

```bash
dolphin2hdfeos5.py dolphin
dolphin2hdfeos5.py dolphin -m recommended
```

are the same. Same OR rule with custom cutoffs:

```bash
dolphin2hdfeos5.py dolphin -m tc+sim --vmin 0.7 --vmin-sim 0.5
```

---

## Shared mask CLI (`mask.py` style)

| Flag | Meaning |
|---|---|
| `-m` / `--mask-source MASK` | `{recommended,tc,similarity,tc+sim,recommendedDensity,psDensity}` |
| `--vmin` | TC / density cutoff (not allowed with `recommended`) |
| `--vmin-sim` | similarity cutoff for `tc+sim` only |

| `-m` | Quality test | defaults | Sweets | OPERA |
|---|---|---|---|---|
| `recommended` | OPERA OR rule; fixed 0.6 / 0.4 (rejects `--vmin` / `--vmin-sim`) | 0.6 / 0.4 | yes | yes |
| `tc+sim` | same OR rule; tunable via `--vmin` / `--vmin-sim` | 0.6 / 0.4 | yes | yes |
| `tc` | `tc > vmin` | 0.6 | yes | yes |
| `similarity` | `sim > cutoff` | 0.4 | yes | yes |
| `recommendedDensity` | `quality/recommendedDensity >= vmin` | 0.9 | error | yes |
| `psDensity` | PS on more than `--vmin` of dates (`0` = at least once; `0.5` = more than half) | 0 | error | yes |

`recommendedDensity` needs OPERA `quality/recommendedDensity` (from `*-stack.nc`). `psDensity` needs `quality/persistentScattererDensity` (from `persistent_scatterer_mask`). Sweets has neither per-date stack, so both error. `--vmin 0.95` on density keeps pixels good in ≥95% of dates. Default `-m psDensity` (`--vmin 0`) keeps pixels that were PS on at least one date. `--vmin 0.5` keeps pixels that were PS on more than half of the dates.

Filename mask suffixes (same for converter and remask): none for `-m recommended`; otherwise one extra `_`-separated token encoding cutoffs (`_tc060`, `_sim040`, `_tc070sim050`, `_dens090`, …). `remask_hdfeos5.py` refuses to overwrite the input when the resolved output path is identical.

---

## HE5 quality / geometry layers

Always when present: `quality/mask`, `quality/temporalCoherence`, `quality/phaseSimilarity`, `quality/waterMask`, `quality/conncomp`, `geometry/shadowMask`. OPERA also: `quality/recommendedDensity`, `quality/persistentScattererDensity`.

---

## Examples

`dolphin2hdfeos5.py --help`:

```bash
dolphin2hdfeos5.py dolphin
dolphin2hdfeos5.py dolphin -m recommended
dolphin2hdfeos5.py dolphin -m tc --vmin 0.7
dolphin2hdfeos5.py dolphin -m similarity --vmin 0.5
dolphin2hdfeos5.py dolphin -m tc+sim --vmin 0.7 --vmin-sim 0.5
dolphin2hdfeos5.py dolphin -m recommendedDensity
dolphin2hdfeos5.py dolphin -m recommendedDensity --vmin 0.95
dolphin2hdfeos5.py stack.nc --method-string operaDisp -m psDensity
dolphin2hdfeos5.py stack.nc --method-string operaDisp -m psDensity --vmin 0.5
```

`remask_hdfeos5.py --help`:

```bash
remask_hdfeos5.py S1_….he5 -m tc --vmin 0.7
remask_hdfeos5.py S1_….he5 -m similarity --vmin 0.5
remask_hdfeos5.py S1_….he5 -m tc+sim --vmin 0.7 --vmin-sim 0.5
remask_hdfeos5.py S1_….he5 -m recommendedDensity
remask_hdfeos5.py S1_….he5 -m recommendedDensity --vmin 0.95
remask_hdfeos5.py S1_….he5 -m psDensity
remask_hdfeos5.py S1_….he5 -m psDensity --vmin 0.5
remask_hdfeos5.py S1_…_tc070sim050.he5 -m recommended
```
OPERA run dirs still work as input (e.g. `nb_runs/FA_opera-disp_HawaiiPuna`); not listed in `--help`.

---

## Later (not this work)

- Per-date recommended mask for sweets (ministack broadcast) and sweets `recommendedDensity`
- Full MintPy-dir reader without NC
