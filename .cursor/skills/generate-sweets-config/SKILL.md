---
name: generate-sweets-config
description: >-
  Writes sweets.bash from a MinSAR template via generate_sweets_config.py
  (sweets config + sweets run). Use when working on sweets, sweets.bash,
  OPERA CSLC vs burst source, or generate_sweets_config.py.
---

# generate_sweets_config.py

Command: `minsar/utils/generate_sweets_config.py` (on `PATH` via `minsar/utils`).

```bash
generate_sweets_config.py $TE/HawaiiPunaSweetsSenA124.template
generate_sweets_config.py $TE/HawaiiPunaSweetsSenA124.template --source cslc
generate_sweets_config.py $TE/HawaiiPunaSweetsSenA124.template --source burst
```

Writes `sweets.bash` (two lines only):

```bash
sweets config --bbox -155.02 19.44 -154.80 19.50 --start 2018-10-01 --end 2026-08-17 --source opera-cslc --track 124 --out-dir ./data --work-dir . --output sweets_config.yaml
sweets run sweets_config.yaml
```

## Required command shape

- One-line `sweets config`, then one-line `sweets run <output>`.
- `--bbox west south east north` with spaces. Never `--bbox=`.
- `--source opera-cslc` or `--source safe` (bursts). Include `--swaths IW1 …` only for `safe`.
- `--track` from `ssaraopt.relativeOrbit` when present.

## Source selection

- Default: OPERA CSLC if any products exist for the AOI/dates; otherwise bursts (`safe`).
- `--source cslc` → `opera-cslc`. `--source burst` → `safe`. If `--source` is given, do not check CSLC availability.

## Track and swath

If the template omits track or swath, fill them with functions in `minsar/scripts/get_sar_coverage.py` (same helpers `create_template.py` uses). Map `topsStack.subswath` `1 2 3` to `IW1 IW2 IW3`. Infer flight direction from the template name (`SenA124` / `SenDT87`).

## Hygiene

Do not create a test file for this script unless the user asks.
