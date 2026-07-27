# Plan: calculate_bbox_for_miaplpy_subset_lalo.py

## Summary
CLI expands geographic AOI → `miaplpy.subset.lalo` for Asc/Desc using platform heading (MintPy HEADING).

## Defaults
- Asc **-13.0°**, Desc **-167.0°** (override with `--asc-heading` / `--desc-heading`; Etna A44 ~−13.275)
- Default mode **`asymmetric_lat`**: Asc pads south, Desc pads north by `Δlat = |Δlon·cos(φ)·tan(heading)|`
- Optional `--mode aabb`: full radar-aligned geo AABB (same for Asc/Desc on rectangular AOI)

## Status
- [x] Implemented
- [x] Tests
- [x] FILE_STRUCTURE.md
