# Dolphin config presets and workflow stages

MinSAR single-run CSLC/SAFE Dolphin writes one `dolphin_config.yaml`, then runs it in three layers: **`dolphin_wrapped`** → **`dolphin_unwrap`** → **`dolphin_timeseries`**.

**Default bundle:** `--dolphin-config disp-s1`

Presets compose. Later wins: **`--dolphin-config` → `--phase-linking-preset` → `--unwrap-preset` → explicit flags** (`--ministack-size`, `--no-watermask`, …).

Values: [`minsar/utils/dolphin_presets.py`](../minsar/utils/dolphin_presets.py).  
**Planned (not in code yet):** `--phase-linking-preset`, `--unwrap-preset`, `--no-watermask`, stage-aware `--link-project-dir`.

---

## Global settings (all presets)

These apply independently of `--dolphin-config` / layer presets.

| Setting | Default | Flag |
|---------|---------|------|
| Half-window | 6×12 (Y×X) | `--half-window-preset standard` or `--half-window Y X` (dry 5×11, wet 9×18, arctic 9×19) |
| Strides | 3×6 | `--stride Y X` |
| Water mask | `watermask.tif` | default; **`--no-watermask`** (planned) omits mask |
| Worker counts | from node CPUs | not science; set at config generation |

Used in **`dolphin_wrapped`** (phase linking). Unwrap preprocess runs **after stitch, before SNAPHU** in **`dolphin_unwrap`**.

---

## `--dolphin-config` (bundled preset)

Default: **`disp-s1`**. Bundles **`--phase-linking-preset`** + **`--unwrap-preset`** (same name) + project/HE5 naming. Unwrap preprocess values are in [**`--unwrap-preset`**](#--unwrap-preset-planned-dolphin_unwrap-only) below.

### Phase linking + PS (`dolphin_wrapped`)

| Preset | ministack | max compressed | compressed plan | output ref idx | PS amp disp |
|--------|-----------|----------------|-----------------|--------------|-------------|
| **disp-s1** (default) | 15† | 10† | always_first† | null† | **0.2** |
| **disp-s1-downloaded** | **100** | **100** | **ALWAYS_FIRST** | **0** | **0.2** |
| **disp-s1-process** | 15† | 10† | always_first† | null† | **0.25** |

†Dolphin default — MinSAR does not pass these flags for this preset.

### Project / HE5 naming

| Preset | Project token | HE5 `post_processing_method` |
|--------|---------------|------------------------------|
| **disp-s1** | *(none)* | `dolphin` (+ optional Dry/Wet/Arctic from half-window) |
| **disp-s1-downloaded** | `DispS1Downloaded` | `dolphinDispS1Downloaded` |
| **disp-s1-process** | `DispS1Process` | `dolphinDispS1Process` |

### Bundle = layer presets combined

| `--dolphin-config` | Same as |
|--------------------|---------|
| `disp-s1` | `--phase-linking-preset default` + `--unwrap-preset disp-s1` |
| `disp-s1-downloaded` | `--phase-linking-preset downloaded` + `--unwrap-preset disp-s1-downloaded` |
| `disp-s1-process` | `--phase-linking-preset default` + `--unwrap-preset disp-s1-process` |

---

## `--phase-linking-preset` (planned; `dolphin_wrapped` only)

Not **`--link-project-dir`**. Not **`--half-window-preset`**.

| Value | ministack | max compressed | compressed plan | output ref idx |
|-------|-----------|----------------|-----------------|--------------|
| **default** (omit flag) | 15† | 10† | always_first† | null† |
| **downloaded** | **100** | **100** | **ALWAYS_FIRST** | **0** |

†No extra flags passed; Dolphin package defaults.

Override: `--ministack-size N`.  
Alone with `--link-project-dir`: restart **`dolphin_wrapped`**, link inputs only (no source dolphin work tree).

---

## `--unwrap-preset` (planned; `dolphin_unwrap` only)

| Value | interp cor | interp sim | max radius |
|-------|------------|------------|------------|
| **disp-s1** | **0.3** | **0.25** | **71** |
| **disp-s1-downloaded** | **0.3** | **0.4** | **71** |
| **disp-s1-process** | **0.001** | **0.4** | **150** |

Alone with `--link-project-dir`: restart **`dolphin_unwrap`**, link source `dolphin/interferograms/` (or burst trees).

---

## Other flags

| Flag | Layer | Effect |
|------|-------|--------|
| `--ministack-size N` | wrapped | Overrides `--phase-linking-preset` |
| `--unwrap-method NAME` | unwrap | `unwrap_options.unwrap_method` |
| `--no-watermask` (planned) | wrapped | No mask; restart **dolphin_wrapped** |
| `--link-project-dir DIR` (planned) | — | Symlink from source; auto restart from earliest changed layer |
| `--phase-linking.*`, `--unwrap-options.*`, `--timeseries-options.*` | varies | Explicit override; wins over presets |

---

## Workflow timeline

```text
dolphin_wrapped     phase_linking, ps_options, mask, strides
dolphin_unwrap      stitch → preprocess (unwrap preset) → SNAPHU
dolphin_timeseries  timeseries_options
dolphin_2_he5       recommended mask (TC/sim); not unwrap preprocess
```

---

## `--link-project-dir` (planned)

Infer earliest changed layer; **`--start` optional override**.

| Change | Link from SOURCE | Also link SOURCE/dolphin/ | Restart |
|--------|------------------|---------------------------|---------|
| Wrapped | data/, geometry/, sweets, watermask*, geometry/ | — | dolphin_wrapped |
| Unwrap | same | interferograms/ or t143_* bursts | dolphin_unwrap |
| Timeseries | same | interferograms/ + unwrapped/ | dolphin_timeseries |

\*Skip watermask with `--no-watermask`.

---

## Examples

```bash
minsarIsce3App.bash AOI NAME --data-type cslc --dolphin-config disp-s1 --half-window-preset dry
minsarIsce3App.bash AOI NAME --data-type cslc --link-project-dir ../PopoCSLCSenD143 --unwrap-preset disp-s1-downloaded
minsarIsce3App.bash AOI NAME --data-type cslc --dolphin-config disp-s1 --phase-linking-preset downloaded --unwrap-preset disp-s1-process
```

---

## Appendix: `--dolphin-config pydantic`

For completeness only. Passes **no** extra science flags; Dolphin package defaults apply. Project token `Pydantic`; HE5 `dolphinPydantic`. Rarely used in production.

---

## Downloaded OPERA vs local presets

`--data-type disp-s1` downloads OPERA L3 products (`dispS1` HE5 tag) — no local presets.

Local `disp-s1-downloaded` / `--phase-linking-preset downloaded` approximate OPERA embedded parameters for continuous single-run (`ALWAYS_FIRST`, not batch `LAST_PER_MINISTACK`).

---

## Related docs

- [`docs/README_minsarIsce3App.md`](README_minsarIsce3App.md)
- [`docs/dolphin_mode_chaining.md`](dolphin_mode_chaining.md)
