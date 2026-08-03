# Plan: Stronger PPN safety margin for unwrap resize

## Summary
Raise `PPN_SAFETY_MARGIN` from 1 → 2 in `resize_miaplpy_unwrap_jobfiles.py` so single-tile snaphu jobs stay farther from the SKX 192 GB concurrent-malloc cliff. Evidence: `miaplpy_Big1` with margin=1 used `LAUNCHER_PPN=25` (~87.5% node fill) and 1/64 tasks failed with snaphu `Out of memory`; larger `qBig6` used PPN=18 (~86% fill) and survived — same cliff, thin margin.

## Key Components Affected
- `minsar/scripts/resize_miaplpy_unwrap_jobfiles.py` — `PPN_SAFETY_MARGIN`, `compute_ppn()`
- `minsar/scripts/tests/test_resize_miaplpy_unwrap_jobfiles.py` — expected PPNs + Big1 regression
- `minsar/docs/miaplpy_unwrap_job_resize.md` — formula note (`- 2`)

## Action Items
- [x] Set `PPN_SAFETY_MARGIN = 2`
- [x] Update unit-test expectations (large-scene 9→8, Etna 17→16, tiled-2 20→19)
- [x] Add Big1 regression: 2851×6354 → PPN 24 (not 25)
- [x] Update docs formula
- [x] Run unit tests

## Execution Plan (Detailed Change Instructions)
1. In `resize_miaplpy_unwrap_jobfiles.py`, change `PPN_SAFETY_MARGIN` from 1 to 2; keep comment about simultaneous snaphu startups.
2. Update `test_resize_miaplpy_unwrap_jobfiles.py`:
   - `test_single_tile_memory_limited`: expect 8
   - `test_etna_sized_scene_avoids_cliff_ppn`: expect 16
   - `test_tiled_2_memory_and_cpu_cap`: `raw - 2` → expect 19
   - Add `test_big1_scene_uses_margin_two`: 2851×6354 → PPN 24
3. In `miaplpy_unwrap_job_resize.md`, change formulas from `- 1` to `- 2` and note Big1 evidence.
4. Run: `python -m unittest minsar.scripts.tests.test_resize_miaplpy_unwrap_jobfiles -v`

## Key Commands & Flows
```bash
# After fix, Big1 dry-run should show LAUNCHER_PPN=24 (was 25)
resize_miaplpy_unwrap_jobfiles.py miaplpy_Big1_201412_201512 --dry-run
# Re-apply before re-running unwrap:
resize_miaplpy_unwrap_jobfiles.py miaplpy_Big1_201412_201512
```

## Expected PPN impact (skx-dev 192 GB)
| Scene | Old PPN (margin 1) | New PPN (margin 2) |
|-------|--------------------|--------------------|
| Big1 2851×6354 | 25 | 24 |
| qBig6 3548×6988 | 18 | 17 |
| Etna 3558×7242 | 17 | 16 |

## TODO List
- [x] Update tests for new margin
- [x] Implement `PPN_SAFETY_MARGIN = 2`
- [x] Update docs
- [x] Run unit tests
