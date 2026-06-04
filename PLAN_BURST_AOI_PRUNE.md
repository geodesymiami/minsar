# Plan: Prune burst dates not covering AOI in burst_download.bash

## Summary
Move the AOI footprint check and per-date pruning logic into `minsar/scripts/burst_download.bash` so it runs **after** per-date `burst2stack` completes (when `*.tif*` and `.SAFE` exist). This avoids special-casing `minsarApp.bash` and makes standalone burst2stack runs behave consistently.

## Key Components Affected
- `minsar/scripts/burst_download.bash`
- `minsar/scripts/check_if_bursts_includeAOI.py` (already simplified: bbox + globs only; writes `dates_not_including_AOI.txt`)
- `docs/README_burst_download.md`, `architecture_docs/BURST_DOWNLOAD.md` (update to reflect new location/flow)
- (Optional) `tests/` for lightweight bash/unit coverage

## Action Items
- [ ] Derive bbox AOI (S:N,W:E) from `--intersectsWith='Polygon((...))'` using the same parsing approach as `process_utilities.convert_intersects_string_to_extent_string` / convert_bbox patterns.
- [ ] After the `xargs` burst2stack run completes, run:
  - `check_if_bursts_includeAOI.py "$bbox" "$slc_dir"/*.tif*`
- [ ] Remove failing dates listed in `"$slc_dir"/dates_not_including_AOI.txt` by deleting `"$slc_dir"/*${ymd}T*` (GeoTIFFs + `.SAFE`).
- [ ] Ensure the logic is safe if the file is empty/missing; avoid errors on no-glob matches (`nullglob`).
- [ ] Update docs to state the AOI pruning is owned by `burst_download.bash` (not `minsarApp.bash`).

## Execution Plan (Detailed Change Instructions)
1. In `minsar/scripts/burst_download.bash`, ensure `intersects_with` is available (it already is).
2. Convert Polygon WKT to bbox:
   - Use a small `python3 -c` snippet that calls `minsar.utils.process_utilities.convert_intersects_string_to_extent_string` on a synthetic flag `--intersectsWith='${intersects_with}'` and gets extent list `[W,S,E,N]`.
   - Convert to bbox string `LAT_S:LAT_N,LON_W:LON_E`.
3. After the parallel `burst2stack` execution completes, run `check_if_bursts_includeAOI.py`.
4. Read `dates_not_including_AOI.txt` and delete matching paths for each date.
5. Remove the AOI-prune block from `minsar/bin/minsarApp.bash` (so minsarApp stays unchanged).
6. Update docs and run targeted sanity checks.

## Key Commands & Flows
- Template mode (minsarApp): `minsarApp.bash <template> --download-method burst2stack`
- Standalone: `burst_download.bash --relativeOrbit N --intersectsWith 'Polygon((...))' --start-date ... --end-date ... --dir SLC`

## TODO List
- [ ] Implement changes in `burst_download.bash`
- [ ] Update docs
- [ ] Run targeted workflow sanity check on a small project directory (dry run or minimal date range)

