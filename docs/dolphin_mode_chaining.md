# Dolphin mode: single-run vs opera — ministack chaining and compressed SLCs

MinSAR ISCE3 CSLC workflows (`minsarIsce3App.bash --data-type cslc`) support two Dolphin paths via `--dolphin-mode {single-run, opera}` (see `create_isce3_runfiles.py`).

| Mode | Entry point | Output layout |
|------|-------------|---------------|
| **single-run** | One `dolphin run` over all CSLCs | `dolphin/` tree → timeseries HE5 |
| **opera** | `disp_s1_process.py` batches → `reformat_disp` | `disp_s1_produce/` → `*-stack.nc` → HE5 |

Both use the same Dolphin/DISP-S1 core algorithms, but they differ in **how time is segmented**, **how compressed SLCs (CCSLCs) are created and reused**, and **how displacement is rebased into a continuous stack**.

---

## 1. Single-run mode — one continuous run

### Workflow

1. Generate `dolphin_config.yaml` with the full `cslc_file_list`.
2. Run Dolphin once (`dolphin run` or MinSAR stage split: wrapped → unwrap → timeseries).
3. Convert `dolphin/timeseries/` to HE5.

Ministack logic lives **inside** Dolphin’s displacement workflow. The user sets policy once in YAML; Dolphin walks the stack in order.

### Compressed-SLC policy (Puna example)

From `PunaCSLCStandardSenD87/dolphin_standard_config.yaml`:

```yaml
phase_linking:
  ministack_size: 15
  max_num_compressed: 10
  output_reference_idx: 4
  compressed_slc_plan: always_first
```

- **`ministack_size: 15`** — at most 15 real SLCs per internal ministack window.
- **`max_num_compressed: 10`** — up to 10 prior compressed SLCs can be prepended when linking the next window.
- **`compressed_slc_plan: always_first`** — the compressed reference for each ministack is the **first** acquisition in that ministack group (OPERA/Dolphin “always first” plan).
- **`output_reference_idx: 4`** — phase-linked output is referenced to index 4 within each ministack (not index 0).

All 88 Puna CSLCs are in **one** config. Dolphin advances ministack windows internally; there is no separate “historical job” vs “forward job” in MinSAR.

### Partial final ministack (46 or 47 SLCs, `ministack_size: 15`)

Single-run mode still processes **every** date in the single run. Dolphin groups the stack into consecutive windows:

| Total SLCs | Full ministacks (×15) | Remainder dates | Behavior |
|------------|------------------------|-----------------|----------|
| **46** | 3 × 15 = 45 | **1** | Final window is a short ministack (1 real + compressed history from prior windows). Still processed in the same run. |
| **47** | 3 × 15 = 45 | **2** | Same: trailing 2-date window is a short ministack, not a separate workflow stage. |
| **88** (Puna) | 5 × 15 = 75 | **13** | One run; internal ministacks 0–4 are full; the last internal window covers the 13 trailing dates. |

There is **no** MinSAR guard that skips dates when fewer than 4 reals remain (that rule exists only in opera **forward** batches; see below).

### Default ministack size in single-run mode

MinSAR and OPERA DISP-S1 both default to **`ministack_size: 15`** (`DEFAULT_DISP_S1_MINISTACK_SIZE` in `create_isce3_runfiles.py`; Dolphin CSLC guide uses the same).

Use **15** unless you have a reason to change it:

- **Larger** (e.g. 20–30): fewer ministack boundaries, longer temporal context per link, higher memory and cost per window; compressed carry matters less.
- **Smaller** (e.g. 10): more boundaries, more reliance on compressed SLC quality, closer to “sequential” OPERA-style behavior inside one run.

For a full reprocess with no operational update cadence, **15 is the usual choice** and matches OPERA’s CLI default.

---

## 2. Opera mode — explicit batch chaining

### Workflow

1. **`disp_s1_process.py --stages process`** — sequential batches under `disp_s1_produce/`.
2. **`reformat_disp`** — `opera-utils disp-s1-reformat` rebases per-batch `.nc` products to one reference → `Project-stack.nc`.
3. Optional velocity/extra layers and HE5 export.

Implementation: `additions/disp-s1/disp_s1_process.py` (MinSAR patch of OPERA’s local produce path).

### Shared compressed-SLC store

```
disp_s1_produce/
  comp_slcs/              # shared CCSLC pool (renamed to OPERA convention)
  batch_000_historical/   # scratch + algorithm_parameters.yaml
  output_000/             # OPERA_L3_DISP-S1_*.nc products
  batch_001_historical/
  ...
  batch_005_forward/
  output_005/
  ...
```

After each **historical** batch, new compressed SLCs are copied into `comp_slcs/` and deduplicated. Later batches **read** from that pool; they do not recompute earlier history.

### Compressed-SLC policy (opera defaults in `make_cfg`)

Opera batches use OPERA production-style settings (written to each batch’s `algorithm_parameters.yaml`):

```yaml
phase_linking:
  max_num_compressed: 5
  compressed_slc_plan: last_per_ministack
  output_reference_idx: <varies by batch>
```

- **`last_per_ministack`** — compressed reference is the **last** real acquisition of each historical ministack (not `always_first`). Valid only when a run is a **single** ministack (each opera batch). Dolphin forbids it for continuous multi-ministack `dolphin run`.
- **`max_num_compressed: 5`** — only the latest five CCSLCs per burst are carried into the next historical batch (`_pick_comp(min(ms_i, max_comp))`).
- **`output_reference_idx`** — set to `max(0, num_ccslc - 1)` so the linked stack is referenced to the newest compressed SLC in that batch.

These differ from Puna **standard** config even when `--half-window 6 12 --stride 3 6` match.

---

## 3. Historical processing vs forward processing

Opera mode splits the timeline into two **processing modes** (`ProcessingMode.HISTORICAL` vs `ProcessingMode.FORWARD` in the DISP-S1 PGE runconfig).

### Historical batches

**When:** Full groups of `ministack_size` consecutive real acquisition dates (same indices across bursts).

**Formula** (from `run_processing`):

```
n_hist = n_dates // ms_size
hist_count = n_hist * ms_size
```

**Each historical batch:**

| Input | Role |
|-------|------|
| Real CSLCs | Exactly `ms_size` dates (e.g. 15 per burst) |
| Compressed SLCs | Up to `min(batch_index, max_comp)` per burst from `comp_slcs/` |
| `ministack_size` in YAML | `num_ccslc + n_real + 1` (grows as CCSLC pool grows) |

**Outputs:**

- **`ms_size - 1`** displacement `.nc` products (one per secondary date in the ministack), except the first historical batch on Puna produced 14 products in `output_000` (reference/bootstrap edge).
- **New compressed SLC(s)** saved to `comp_slcs/` (`save_compressed_slc=True` only for historical).

**Puna (`PunaCSLCOperaSenD87`, 88 dates, `ms_size=15`):**

- 5 historical batches: `batch_000` … `batch_004`
- Date indices 0–74 consumed
- Products: 14 + 15 + 15 + 15 + 15 = **74** `.nc` files in `output_000`–`output_004`
- Growing `ministack_size` in saved YAML: 16 → 17 → 18 → 19 → 20 (1–4 CCSLCs + 15 reals + 1)

### Forward batches

**When:** Every acquisition index `n` from `hist_count` to `n_dates - 1` that cannot start another full historical ministack.

**Purpose:** Produce **one** displacement product for date `n` (the leading date of that forward window), using:

| Input | Role |
|-------|------|
| Real CSLCs | Indices `n` … `min(n + ms_size + 1, n_dates) - 1` (up to **`ms_size + 1`** reals per burst — same rule as OPERA `run_disp.py` `get_forward_batch`) |
| Compressed SLCs | **One** latest CCSLC per burst with reference date **before** the first real date (`_latest_comp_per_burst(..., k=1, ...)`) |
| `ministack_size` | `1 + n_real + 1` |
| `save_compressed_slc` | **False** — forward batches do not append to `comp_slcs/` |

**Products:** Exactly **1** `.nc` per successful forward batch.

**Puna forward summary:**

```
88 dates, ms_size=15  →  hist_count=75, n_forward=13 candidate runs
Successful forward batches: batch_005 … batch_014  (10 runs)
Products: 10 × 1 = 10 .nc files
Total .nc before reformat: 74 + 10 = 84  (not 88)
```

Three trailing dates (indices 85–87) had forward runs **skipped** (see next section).

### Conceptual diagram

```text
Timeline (88 dates, ms=15):

|←—— hist batch 0 ——→|←—— hist 1 ——→| ... |← hist 4 →|f|f|f|f|f|f|f|f|f|f|?|?|?|
 15 reals → 14 products   15→15        ...   15→15    10 forward OK   3 SKIPPED

comp_slcs/:  [CCSLC₀] → [CCSLC₀,₁] → ... → [up to 5 per burst] ──used──→ forward batches
```

Single-run mode covers the same 88 dates in **one** Dolphin run; it does not label batches “historical” or “forward,” and does not emit per-date `.nc` before reformat.

---

## 4. Edge case: only 1 or 2 (or 3) images since the last full ministack

### Opera forward guard

Forward mode uses a **nearest-neighbor interferogram network** with default size 3, which requires at least **4 real CSLCs per burst**:

```python
MIN_FORWARD_REALS = 4  # disp_s1_process.py
```

If `n_real_per_burst < 4`, the batch is **skipped** (logged, no product):

```text
SKIP: forward nearest-3 network needs >=4 reals/burst (disp-s1 error 2001), have N
```

**Examples with `ms_size=15`:**

| Remainder after historical | Forward start index | Reals in first forward window | Result |
|----------------------------|---------------------|-------------------------------|--------|
| 1 date | n=45 (46 total) | 1 | **SKIP** — no product for last date |
| 2 dates | n=45,46 (47 total) | 2, then 1 | **Both SKIP** |
| 3 dates | n=45..47 (48 total) | 3, 2, 1 | **All SKIP** |
| 13 dates (Puna) | n=75..87 | 13 down to 1 | Runs for n=75..84 (≥4 reals); **SKIP** n=85,86,87 |

So with opera mode, a short tail after the last **full** historical ministack is **not** processed unless the forward window still contains ≥4 real SLCs. One or two new images alone are **never** enough for a forward product.

**Operational implication:** After adding 1–2 new CSLCs to an existing stack, opera mode may produce **zero** new forward products until enough trailing reals accumulate (or until a new full historical ministack is warranted — which would require re-architecting the batch schedule).

### Single-run mode

The trailing 1–2 dates are part of the **last internal ministack** in the single `dolphin run`. No `MIN_FORWARD_REALS` skip. Linking quality on a 1–2 date window may be poor, but the dates are not dropped by MinSAR.

### Historical bootstrap edge case

If **`n_dates < ms_size`**, opera mode **exits**:

```text
Only N date(s) (< ministack size 15); need at least one full historical ministack
to bootstrap compressed SLCs for forward mode.
```

Single-run mode can run with fewer than 15 dates (subject to Dolphin’s own minimum network requirements).

---

## 5. Why velocities differ even when “config parameters” match

Matching `--half-window`, `--stride`, and merged algorithm YAML is **not sufficient** for identical displacement or velocity. Structural differences remain:

| Factor | Single-run | Opera |
|--------|----------|-------|
| **Reference frame** | Single global ministack reference policy (`output_reference_idx: 4`, `always_first`) for the whole run | Moving reference **per batch**; `reformat_disp` rebases to one stack reference (`--reference-method`, e.g. BORDER, HIGH_COHERENCE) |
| **Time segmentation** | One continuous interferogram network (`max_bandwidth: 4` on Puna standard) | Many smaller networks per batch (`max_bandwidth: 3` in opera `make_cfg`) |
| **CCSLC plan** | `always_first`, up to 10 compressed | `last_per_ministack`, up to 5 compressed |
| **Missing dates** | All dates attempted in one run | Trailing forward skips (`MIN_FORWARD_REALS`) → gaps in `.nc` series before reformat |
| **Timeseries / velocity stage** | In-run inversion on unwrapped phases (`timeseries_options.run_inversion: true`; Puna standard has `run_velocity: false` in YAML — velocity may come from a later stage or HE5 export) | Per-batch products → rebase → `add_velocity_to_zarr` with coherence weighting on **rebased** displacement |
| **Masking** | Puna standard: `apply_mask_to_timeseries: false` | Opera batch YAML: masking / velocity flags on (from DISP-S1 defaults in `make_cfg`) |
| **Amplitude state** | Not carried across separate jobs | `amp_disp` / `amp_mean` tifs carried from latest historical batch into later batches |

Even the experiment configs on scratch illustrate the gap:

- **`dolphin_try1_config.yaml`** — opera algorithm params but **standard** CCSLC policy (`always_first`, `max_num_compressed: 10`, `output_reference_idx: 4`).
- **`dolphin_similar-opera_config.yaml`** — opera-like `max_num_compressed: 5` and `output_reference_idx: 0` in **one** continuous run. Uses `always_first` (not opera’s `last_per_ministack`): dolphin raises `ValueError: 'last_per_ministack' cannot be used for multiple ministacks` when `ministack_size < n_slcs`. Opera may use `last_per_ministack` only because each batch is a **single** ministack. Still no batch rebase or forward/historical split.

Neither is equivalent to true opera mode.

### Session examples

1. **Hawaii Puna short CSLC vs downloaded DISP-S1** (earlier in this Cursor session): `HawaiiPunaShortCSLCSenD87` standard Dolphin on **14 regular CSLCs only** vs OPERA L3 products built with **compressed history + forward products**. Velocities and posting differed (local produce at 10 m vs OPERA 30 m before `--stride 3 6` was wired into `disp_s1_process`).

2. **Puna full stack** (`PunaCSLCStandardSenD87` vs `PunaCSLCOperaSenD87`): Same 88 CSLCs and sweets config; standard uses one `dolphin_standard/` job; opera uses 5 historical + 10 forward batches and `reformat_disp`. Opera `reformat_disp` failed with `--reference-method BORDER` when `water_mask` was placeholder (255) — rebasing and border reference need valid land pixels; that affects stack-level displacement and any derived velocity.

---

## 6. YAML comparison — Puna dolphin configs (quality)

Scratch paths under `/scratch/05861/tg851601/`. Quality reflects how well algorithm knobs match OPERA DISP-S1 / local opera produce for Puna comparison work (not architecture alone).

| File | Quality | Role |
|------|---------|------|
| `PunaCSLCStandardSenD87/dolphin_similar-opera_config.yaml` | **good** | Continuous `dolphin run` with local-opera algorithm params (CCSLC plan forced to `always_first`) |
| `PunaCSLCOperaSenD87/disp_s1_produce/batch_003_historical/algorithm_parameters.yaml` | **good** | Local opera historical batch (single ministack; `last_per_ministack` valid here) |
| `PunaDISPSenD87/subsets/OPERA_L3_DISP-S1_IW_F23211_VV_20240620T161648Z_20241205T161646Z_v1.0_20250622T173349Z.nc` | **good** | Downloaded ASF L3 — two embedded algorithm YAMLs (see columns below) |

### Which YAML inside an ASF `DISP-S1` `.nc` was used?

ASF products embed **three** metadata blobs (`product.py`):

| HDF5 dataset | What it is | Use for comparison |
|--------------|------------|--------------------|
| **`metadata/dolphin_workflow_config`** | Full `DisplacementWorkflow` Dolphin ran for that batch | **What phase linking / unwrap actually used** |
| **`metadata/algorithm_parameters_yaml`** | PGE `AlgorithmParameters` file text | Algorithm + product-quality fields (`spatial_wavelength_cutoff`, `recommended_*`); may **diverge** from the workflow config |
| **`metadata/pge_runconfig`** | OPERA job wrapper (inputs, `DISP_S1_HISTORICAL` / `FORWARD`) | Provenance / file lists, not dolphin knobs |

`extract_dolphin_config_yaml.py` prefers **`dolphin_workflow_config`**. Both ASF columns appear in the parameter table below because they disagree on this granule.

### Parameter table

ASF source granule: `OPERA_L3_DISP-S1_IW_F23211_VV_20240620T161648Z_20241205T161646Z_v1.0_20250622T173349Z.nc`.

| Parameter | `dolphin_similar-opera` **(good)** | `batch_003` local opera **(good)** | ASF `dolphin_workflow_config` **(good)** | ASF `algorithm_parameters_yaml` **(good)** |
|-----------|------------------------------------|------------------------------------|------------------------------------------|--------------------------------------------|
| Config kind | DisplacementWorkflow | AlgorithmParameters (one batch) | DisplacementWorkflow (ran) | AlgorithmParameters (PGE file) |
| `half_window` (y, x) | 6, 12 | 6, 12 | **5, 11** | **5, 11** |
| `strides` (y, x) | 3, 6 | 3, 6 | 3, 6 | 3, 6 |
| `ministack_size` | 15 | **19** (3 CCSLC + 15 reals + 1) | **100** | **100** |
| `max_num_compressed` | **5** | **5** | **100** | **100** |
| `compressed_slc_plan` | always_first | **last_per_ministack** | **last_per_ministack** | **last_per_ministack** |
| `output_reference_idx` | **0** | **2** (`num_ccslc − 1`) | **4** | **0** |
| `max_bandwidth` | **3** | **3** | **3** | **3** |
| `amp_dispersion_threshold` | **0.25** | **0.25** | **0.2** | **0.2** |
| `interpolation_cor_threshold` | **0.001** | **0.001** | **0.3** | **0.3** |
| `interpolation_similarity_threshold` | **0.4** | **0.4** | **0.1** | **0.4** |
| `max_radius` | 150 | 150 | **71** | **71** |
| `single_tile_reoptimize` | **false** | **false** | **true** | **true** |
| SNAPHU `ntiles` | [1, 1] | [1, 1] | **[5, 5]** | **[5, 5]** |
| `run_velocity` | **true** | **true** | **false** | **false** |
| `apply_mask_to_timeseries` | **true** | **true** | (absent) | (absent) |
| `timeseries` `correlation_threshold` | **0.2** | **0.2** | 0.0 | 0.0 |
| `spatial_wavelength_cutoff` | — | (local make_cfg: 50) | — | **30000** |
| Work / product | `dolphin_similar_opera/` | `batch_003_historical/` + `output_003/` | ASF L3 (HISTORICAL; 200 CSLC inputs) | same granule |

Bold cells highlight divergences (especially **unwrap interpolation** and ASF workflow vs algo disagreements).

### Interpolation: why ASF DISP vs `dolphin_similar-opera` can differ

Even when posting is ~30 m (`strides` 3×6), the ASF production product used a **different unwrap-interpolation policy** than local opera / `dolphin_similar-opera`:

| Knob | ASF `dolphin_workflow_config` (ran) | ASF `algorithm_parameters_yaml` | `dolphin_similar-opera` / local `batch_003` |
|------|-------------------------------------|----------------------------------|-----------------------------------------------|
| `interpolation_cor_threshold` | **0.3** | **0.3** | **0.001** |
| `interpolation_similarity_threshold` | **0.1** | **0.4** | **0.4** |
| `max_radius` | **71** | **71** | **150** |
| `half_window` | **5×11** | **5×11** | **6×12** |
| SNAPHU tiles / reoptimize | **5×5**, reoptimize **on** | same | **1×1**, reoptimize **off** |

For “what did unwrap actually use?”, trust **`dolphin_workflow_config`** (`similarity` **0.1**). The algo YAML’s **0.4** matches local opera / `dolphin_similar-opera` on that one knob but not on cor threshold, radius, half-window, or SNAPHU tiling.

Local MinSAR opera (`disp_s1_process.make_cfg`) matches `dolphin_similar-opera` on unwrap thresholds, **not** ASF production. Matching downloaded ASF L3 requires importing **`dolphin_workflow_config`** from the `.nc`.

ASF-only product fields (in `algorithm_parameters_yaml`): `spatial_wavelength_cutoff: 30000`, `recommended_temporal_coherence_threshold: 0.6`, `recommended_similarity_threshold: 0.4`.

### How to read the quality labels

- **`dolphin_similar-opera` (good)** — continuous-run twin of **local** opera unwrap/timeseries/PS/network params. Cannot set `last_per_ministack` (dolphin multi-ministack error); uses `always_first` instead. **Not** a twin of ASF production interpolation (see table).
- **`batch_003_historical/algorithm_parameters.yaml` (good)** — ground truth for one **local** opera historical batch. `ministack_size: 19` and `output_reference_idx: 2` are batch-local. Aligns with `dolphin_similar-opera` on unwrap thresholds.
- **ASF `.nc` (good)** — ground truth for **published** OPERA L3. Prefer `dolphin_workflow_config` for what ran; keep `algorithm_parameters_yaml` when fields disagree (`output_reference_idx`, `interpolation_similarity_threshold` on this granule).

### Shared (local configs)

- Local similar-opera / `batch_003`: half-window **6×12**, strides **3×6**.
- ASF granule above: same strides, but half-window **5×11** and very different ministack / unwrap settings.

---

## 7. Preferred approach (no operational constraints)

**For scientific consistency on a fixed, complete stack (full reprocess):**

- **Prefer single-run mode** — one reference framework, one network inversion, no per-batch rebase artifacts, no forward skip gaps, simpler interpretation.

**When results must match OPERA DISP-S1 production or published L3 products:**

- **Prefer opera mode** — same historical/forward split, CCSLC carry, and reformat pipeline as OPERA’s local produce (`tools/disp-s1` / `disp_s1_process.py`).

**For incremental updates (new acquisitions every 12 days):**

- **Opera mode** is designed for this: new forward batches after historical bootstrap; compressed SLCs in `comp_slcs/` encode prior history without reprocessing the entire stack.

**For comparing algorithm knobs (unwrap, timeseries) while isolating CCSLC policy:**

- Use scratch experiment YAMLs (e.g. `dolphin_try1_config.yaml` vs `dolphin_similar-opera_config.yaml` on `PunaCSLCStandardSenD87`) — still standard **architecture**, not opera chaining.

---

## 8. Processing time — which mode is faster?

**Short answer:** For a **full reprocess of the same stack**, **`--dolphin-mode single-run` is expected to be faster**. Opera mode is faster only when **incremental** updates or **batch-level resume** matter more than total walltime.

### Why single-run wins on total walltime (full stack)

| Factor | Single-run | Opera |
|--------|----------|-------|
| Job count | 1 Dolphin displacement run (optionally split into wrapped/unwrap/timeseries stages) | 5 historical + 10 forward batches on Puna (15+ separate Dolphin/DISP runs) + `reformat_disp` |
| Overlap | Each date linked/unwrap once in one network | Same dates re-enter overlapping batch windows; forward batches reuse trailing reals |
| Startup / I/O | One `dolphin_config.yaml`, one work tree | Per-batch scratch, CCSLC copy to `comp_slcs/`, many `output_*/OPERA*.nc`, stack merge |
| Threading (Puna configs) | `threads_per_worker: 48` | `threads_per_worker: 8` per batch in `disp_s1_process.make_cfg` |
| Post-process | Direct timeseries → HE5 | Reformat/rebase all `.nc` before velocity/HE5 |

Walltime scales roughly as:

- **Single-run:** `T ≈ T_dolphin(all dates)`
- **Opera:** `T ≈ Σ T_batch(i) + T_reformat` (batches run **in series** inside `disp_s1_process`; see `architecture_docs/ISCE3_HPC_opportunities.md` §7)

On Puna (88 CSLCs), opera runs **15** batch jobs where single-run runs **1**. Even if each opera batch is smaller, the sum of batch runtimes plus reformat typically exceeds one monolithic run, unless individual batches are parallelized on separate nodes (MinSAR’s default opera path does **not** do that — batches are sequential in one `disp_s1_process` job).

### When opera can be “faster” operationally

| Scenario | Why opera helps |
|----------|-----------------|
| **New acquisitions only** | Add forward batches for new dates; skip completed `output_NNN` on re-run |
| **Failure recovery** | Re-run from failed batch only (`_batch_outputs_complete`) |
| **Memory limit** | Each batch holds ≤ `ms_size + 1` reals + ≤ 5 CCSLCs, not the full 88-date stack |
| **Matching ASF L3** | No need to redo produce if you only download/reformat |

These are **operational** wins, not raw compute efficiency on a from-scratch reprocess.

### Single-run mode — usually faster for a **full** reprocess

| Advantage | Why |
|-----------|-----|
| Single job startup | One Dolphin config load, one workspace tree |
| No cross-batch I/O | No copy/harvest of CCSLCs between 15+ separate batch runs |
| Higher parallelism on Puna | `threads_per_worker: 48` vs opera batch default `8` |
| No reformat pass | No second pass to rebase hundreds of `.nc` files into `*-stack.nc` |
| Less redundant work | Phase linking and unwrap are not re-run on overlapping date windows across batch boundaries |

Walltime is roughly **one** Dolphin displacement run (subject to queue limits; long stacks may hit TIMEOUT and need stage split or longer queue — see `architecture_docs/ISCE3_HPC_opportunities.md`).

### Opera mode — tradeoffs

| Cost | Why |
|------|-----|
| Serialized batches | Walltime ≈ **sum** of batch runtimes + reformat (`architecture_docs/plans/05_opera_disp_style.md`) |
| Repeated bootstrap | Each batch rebuilds a ministack context; overlapping reals re-enter linking/unwrap |
| Extra I/O | CCSLC harvest to `comp_slcs/`, many `output_*/OPERA*.nc`, stack merge |
| Lower threads per batch | Default 8 threads vs 48 in Puna standard config |

| Benefit | Why |
|---------|-----|
| Resume at batch boundary | Completed `output_NNN` skipped on re-run (`_batch_outputs_complete`) |
| Bounded memory per batch | Smaller date windows than monolithic 88-date run |
| Incremental forward | New dates only need new forward batches (when ≥4 reals allow) |
| OPERA-compatible intermediates | Direct comparison to ASF/NASA L3 DISP-S1 |

**Rule of thumb:** Full-stack reprocess with no ops constraints → **single-run is more efficient**. Long-running operational stream with periodic new acquisitions → **opera is more efficient** (and may be the only practical option without redoing the entire stack).

---

## 9. Quick reference — Puna CSLC (this session)

| Item | Standard (`PunaCSLCStandardSenD87`) | Opera (`PunaCSLCOperaSenD87`) |
|------|-------------------------------------|-------------------------------|
| CSLCs | 88 | 88 (same `data/`) |
| Ministack size CLI | 15 (default) | 15 (default) |
| CCSLC plan | `always_first`, max 10 | `last_per_ministack`, max 5 |
| Batches | 1 Dolphin run | 5 historical + 10 forward (3 dates skipped) |
| Work dir | `dolphin_standard/` | `disp_s1_produce/` |
| Stack product | HE5 under `dolphin_standard/timeseries/` | `PunaCSLCOperaSenD87-stack.nc` (reformat) |
| Experiment configs | `dolphin_try1_config.yaml`, `dolphin_similar-opera_config.yaml` | N/A (use batch `algorithm_parameters.yaml`) |

### Counting products (opera, 88 dates, ms=15)

```text
n_hist = 88 // 15 = 5
Historical products ≈ 5×15 − 1 = 74  (first batch 14 observed)
Forward candidates = 88 − 75 = 13
Forward successes = 10  (indices 75–84; each with ≥4 reals in window)
Forward skipped = 3     (indices 85–87; <4 reals)
Total .nc ≈ 84 before reformat
```

---

## 10. Configuration YAML — which file, what goes where

MinSAR and OPERA DISP-S1 use several YAML layers. They are **not** interchangeable copies of the same file.

### Single-run mode (`--dolphin-mode single-run`)

| File | When created | Role |
|------|--------------|------|
| **`dolphin_config.yaml`** (or `dolphin_standard_config.yaml`) | `create_isce3_runfiles.py` / `dolphin config` | **The** config for one continuous run: full `cslc_file_list`, `work_directory`, worker settings, and all algorithm blocks (`phase_linking`, `unwrap_options`, …). |
| **`.minsar_imported_algo.yaml`** | Runfile generation when a third positional `.nc` or `.yaml` is passed | Stripped algorithm overlay merged into the generated config (ministack/CCSLC keys removed — see below). |

Single-run mode has **one** YAML per project run. Ministack/CCSLC policy is set once in `phase_linking` and applied internally by Dolphin.

### Opera mode (`--dolphin-mode opera`)

| File | Location | Role |
|------|----------|------|
| **`algorithm_parameters.yaml`** | Each `batch_NNN_historical/` or `batch_NNN_forward/` scratch dir | Algorithm knobs for **that batch only**, written by `make_pge_runconfig()` from the batch’s `DisplacementWorkflow`. |
| *(no single project `dolphin_config.yaml`)* | — | Each batch builds its own full Dolphin config in memory; only the algorithm subset is persisted as `algorithm_parameters.yaml` on disk. |

**Opera batch YAMLs are not identical.** On Puna, `ministack_size` and `output_reference_idx` grow with the CCSLC pool:

| Batch | `ministack_size` | `output_reference_idx` |
|-------|------------------|------------------------|
| `batch_000_historical` | 16 (0 CCSLC + 15 reals + 1) | 0 |
| `batch_001_historical` | 17 | 0 |
| `batch_004_historical` | 20 | 3 |
| `batch_005_forward` | 15 | 0 |
| `batch_014_forward` | 6 | 0 |

Shared across batches on Puna: `max_num_compressed: 5`, `compressed_slc_plan: last_per_ministack`, `half_window: {y: 6, x: 12}`, unwrap/timeseries defaults from `disp_s1_process.make_cfg`.

Forward batches additionally differ in `ministack_size` (`1 + n_real + 1`) and in the **input file list** (1 CCSLC + variable reals).

### Inside each OPERA L3 `DISP-S1` `.nc` product

When `disp_s1_process` / OPERA SAS writes a product, three metadata datasets are embedded (`additions/disp-s1/product.py`):

| HDF5 path | Source | Contents |
|-----------|--------|----------|
| **`metadata/dolphin_workflow_config`** | Full `DisplacementWorkflow` for **this product’s batch** | Complete Dolphin config: `cslc_file_list` (CCSLCs + reals for that batch), `work_directory`, `worker_settings`, `phase_linking`, `unwrap_options`, `output_options`, `timeseries_options`, … |
| **`metadata/algorithm_parameters_yaml`** | Text of `batch_*/algorithm_parameters.yaml` | **AlgorithmParameters** subset: `ps_options`, `phase_linking`, `interferogram_network`, `unwrap_options`, `output_options`, `timeseries_options`, plus PGE fields (`spatial_wavelength_cutoff`, `recommended_*_threshold`, `browse_image_vmin_vmax`, …). **No** `cslc_file_list` or `work_directory`. |
| **`metadata/pge_runconfig`** | OPERA `RunConfig` | Job wrapper: `input_file_group.cslc_file_list`, `primary_executable.product_type` (`DISP_S1_HISTORICAL` or `DISP_S1_FORWARD`), `product_path_group`, pointer to `algorithm_parameters_file`, frame id. |

**Are `metadata/algorithm_parameters_yaml` and the batch `algorithm_parameters.yaml` identical?**

**Yes** — for a locally produced product, the NetCDF field is a copy of the batch scratch file written for that run. Verified on Puna: `batch_004_historical/algorithm_parameters.yaml` matches `metadata/algorithm_parameters_yaml` inside an `output_004` product (all of `ps_options`, `phase_linking`, `interferogram_network`, `unwrap_options`, `timeseries_options` identical).

**Are `metadata/algorithm_parameters_yaml` and `metadata/dolphin_workflow_config` identical?**

**No — different scope.**

| | `dolphin_workflow_config` | `algorithm_parameters_yaml` |
|--|---------------------------|-----------------------------|
| **Size** | ~21 KB on Puna example | ~16 KB |
| **Includes** | `cslc_file_list`, paths, workers, mask, corrections | Algorithm + PGE quality/browse fields only |
| **Shared sections** | `phase_linking`, `unwrap_options`, `interferogram_network`, `ps_options`, `output_options`, `timeseries_options` (same values for that batch) | same |
| **Only here** | `input_options`, `work_directory`, `cslc_file_list`, `amplitude_*_files`, `correction_options`, `worker_settings` | `spatial_wavelength_cutoff`, `recommended_*`, `browse_image_vmin_vmax`, `forward_mode_network_size`, `num_parallel_products` |

`dolphin_workflow_config` is what Dolphin actually executed; `algorithm_parameters_yaml` is the DISP-S1 “algorithm parameters” record plus OPERA product metadata fields.

**`metadata/pge_runconfig`** is a third layer: OPERA job structure, not a duplicate of either file above (though it repeats `cslc_file_list` and references the algorithm file path).

### `extract_dolphin_config_yaml.py` behavior

```bash
extract_dolphin_config_yaml.py OPERA_L3_DISP-S1_IW_F23211_VV_20241123T161649Z_20241205T161648Z_v0.10_20260906T183836Z.nc
```

Output (from `minsar/utils/extract_dolphin_config_yaml.py`):

1. **Prefers** `metadata/dolphin_workflow_config` when present and valid YAML.
2. Falls back to `metadata/algorithm_parameters_yaml`, then scans for other config-like datasets.
3. Writes **`DISP_dolphin_config.yaml`** (full preferred blob).
4. Lists other candidates (`algorithm_parameters_yaml`, `pge_runconfig`) but does **not** merge them.

So the extracted file is the **batch-local full Dolphin config**, not a project-wide standard config.

### Using a downloaded ASF `DISP-S1` `.nc` with `--dolphin-mode single-run`

A single ASF L3 product reflects **one** historical or forward batch (moving reference, specific CCSLC+real inputs). You cannot paste it verbatim as a standard-mode config for a full-stack run. Use it for **algorithm parameters** only.

**Recommended MinSAR path** — pass the `.nc` as the optional third positional; MinSAR merges algorithm fields into the generated config:

```bash
create_isce3_runfiles.py $TE/Puna.template --data-type cslc --dolphin-mode single-run \
  /path/to/OPERA_L3_DISP-S1_*.nc --half-window 6 12 --stride 3 6
```

This calls `load_algo_mapping()` → prefers `metadata/dolphin_workflow_config` → `merge_dolphin_algo_config.py` overlays allowlisted sections into `dolphin_config.yaml`.

**What gets imported** (`dolphin_config_import.py`):

- `ps_options`, `phase_linking`, `interferogram_network`, `unwrap_options`, `output_options`, `timeseries_options`, `correction_options`, `similarity_options`

**What is stripped or kept from your project** (not overwritten from the `.nc`):

| From product | Action |
|--------------|--------|
| `ministack_size`, `max_num_compressed`, `compressed_slc_plan` | **Dropped** — single-run mode uses MinSAR defaults (`ministack_size` 15, `always_first`, etc.) or `--ministack-size` |
| `output_reference_idx` | **Dropped** with other ministack keys |
| `cslc_file_list`, `work_directory`, `worker_settings`, `input_options`, `mask_file` | **Kept from generated target** |
| `output_options.bounds`, `bounds_epsg`, `bounds_wkt` | **Kept from target** (your AOI) |
| `half_window`, `strides` | Imported unless overridden by `--half-window` / `--stride` CLI |

**Manual workflow** (without runfile generator):

```bash
extract_dolphin_config_yaml.py OPERA_L3_DISP-S1_*.nc -o imported.yaml
# Edit imported.yaml: replace cslc_file_list with all project CSLCs; set work_directory;
# reset phase_linking to standard policy (ministack_size 15, max_num_compressed 10,
# compressed_slc_plan always_first, output_reference_idx 4) if you want standard chaining.
merge_dolphin_algo_config.py --target dolphin_standard_config.yaml --from OPERA_L3_DISP-S1_*.nc --hwy 6 --hwx 12 --sy 3 --sx 6
```

**Parameters to match OPERA production** (from any recent ASF `.nc` or `batch_004_historical/algorithm_parameters.yaml` on a full-stack local opera run):

- `phase_linking.half_window`: `{y: 6, x: 12}` (with `--stride 3 6` for ~30 m posting)
- `output_options.strides`: `{y: 3, x: 6}`
- `interferogram_network.max_bandwidth`: `3` (opera) vs `4` (Puna standard default)
- `unwrap_options.preprocess_options`: `interpolation_cor_threshold: 0.001`, `interpolation_similarity_threshold: 0.4`
- `unwrap_options.snaphu_options.single_tile_reoptimize`: `false`
- `ps_options.amp_dispersion_threshold`: `0.25`
- `timeseries_options.apply_mask_to_timeseries`: `true`, `run_velocity`: `true` (opera defaults)

**Do not copy from the `.nc` if you want standard architecture:**

- Batch-specific `ministack_size` (e.g. 20) or `output_reference_idx` (e.g. 3)
- `compressed_slc_plan: last_per_ministack` — invalid for continuous multi-ministack `dolphin run` (use `always_first`; opera-like experiment keeps `max_num_compressed: 5` only)
- `cslc_file_list` (lists CCSLCs + 15 reals for one batch only)

**Session example:** Hawaii Puna downloaded L3 vs short CSLC standard run differed partly because the standard run never imported unwrap/timeseries/strides from the product; after wiring `--stride 3 6` into `disp_s1_process` and using `extract_dolphin_config_yaml.py` / `--config` merge, posting and algorithm knobs align, but **architecture** (single run vs batch+reformat) still dominates velocity differences.

---

## 11. Related code and docs

| Path | Topic |
|------|--------|
| `additions/disp-s1/disp_s1_process.py` | Historical/forward batch loop, `MIN_FORWARD_REALS`, CCSLC harvest |
| `minsar/src/minsar/cli/create_isce3_runfiles.py` | `--dolphin-mode`, `_disp_s1_process_command`, standard dolphin stages |
| `architecture_docs/plans/05_opera_disp_style.md` | OPERA-style produce spike / tradeoffs |
| `architecture_docs/ISCE3_HPC_opportunities.md` §7 | Sequential ministack walltime |
| `docs/dolphin_guides/CSLC_processing.md` | Standard `dolphin config` / `dolphin run` |
| `minsar/utils/extract_dolphin_config_yaml.py` | Extract YAML from OPERA L3 `.nc` |
| `minsar/utils/dolphin_config_import.py` | Merge algorithm YAML from `.nc` into standard config |
| `additions/disp-s1/product.py` | Writes `metadata/*` datasets into products |

---

## 12. Commands (Puna)

Standard:

```bash
minsarIsce3App.bash $TE/Puna.template --data-type cslc --dolphin-mode single-run --half-window 6 12 --stride 3 6
```

Opera:

```bash
minsarIsce3App.bash $TE/Puna.template --data-type cslc --dolphin-mode opera --half-window 6 12 --stride 3 6 --reference-method HIGH_COHERENCE
```

Experiment (standard architecture, opera-like YAML):

```bash
cd /scratch/05861/tg851601/PunaCSLCStandardSenD87 && dolphin config run dolphin_similar-opera_config.yaml
```
