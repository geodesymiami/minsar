---
paths:
  - "**/generate_sweets_config.py"
  - "**/sweets.bash"
---

# generate_sweets_config.py

`minsar/utils/generate_sweets_config.py` writes `sweets.bash` from a MinSAR template: exactly two lines, a one-line `sweets config` and then `sweets run sweets_config.yaml`.

```bash
generate_sweets_config.py $TE/HawaiiPunaSweetsSenA124.template
generate_sweets_config.py $TE/HawaiiPunaSweetsSenA124.template --source cslc
generate_sweets_config.py $TE/HawaiiPunaSweetsSenA124.template --source burst
```

```bash
sweets config --bbox -155.02 19.44 -154.80 19.50 --start 2018-10-01 --end 2026-08-17 --source opera-cslc --track 124 --out-dir ./data --work-dir . --output sweets_config.yaml
sweets run sweets_config.yaml
```

- `--bbox` is space-separated (west south east north). Never `--bbox=`.
- Default source is `opera-cslc` if any CSLC products exist for the AOI and dates; otherwise bursts (`--source safe`). Include `--swaths IW1 …` only for `safe`.
- `--source cslc` maps to `opera-cslc` and `--source burst` to `safe`; giving `--source` skips the CSLC availability check.
- Track and swath come from the template (`ssaraopt.relativeOrbit`, `topsStack.subswath`). If missing, compute them with the `get_sar_coverage.py` helpers, as `create_template.py` does.
- Do not add a test file for this script unless asked.
