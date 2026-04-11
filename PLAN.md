# Plan: Select only robust AOI-covering orbits in get_sar_coverage

## Summary
Update `get_sar_coverage.py --select` so it does not pick an orbit solely by maximum incidence angle when that orbit has poor full-AOI consistency. The new selection policy prioritizes robust AOI coverage across dates and only then uses incidence angle as a tie-breaker.

## Status
**Implemented** (see `minsar/scripts/get_sar_coverage.py`, `tests/test_get_sar_coverage_select.py`, `architecture_docs/README.md`).

## Key Components Affected
- `minsar/scripts/get_sar_coverage.py`
- `tests/test_get_sar_coverage_select.py`
- `architecture_docs/README.md`

## Action Items
- [x] Add Sentinel-1 selection scoring/filter logic that prefers full-AOI consistency
- [x] Wire Sentinel-1 coverage metrics into `--select` best-orbit pick
- [x] Keep existing behavior for NISAR/ALOS2 unchanged
- [x] Add/adjust Python tests for selection behavior
- [x] Update architecture docs for the new selection rule

## Selection policy (Sentinel-1 `--select`)
1. Maximize fraction of intersecting acquisition dates that have full AOI cover (`kept / n_intersecting`).
2. Minimize dropped intersecting dates (`n_acquisitions_removed`).
3. Maximize min distance AOI boundary → SLC footprint edge (m).
4. Maximize incidence angle (tie-break).

NISAR / ALOS-2: unchanged (max incidence).
