# Plan: Sentinel-1 full-coverage AOI counting and boundary diagnostics

## Summary
Extend `get_sar_coverage.py` so that, after identifying Sentinel-1 products intersecting the AOI, it uses Shapely geometry operations to:
- Count only dates where the product footprint fully covers the AOI (existing `--full-coverage-only` behavior, but using Shapely instead of bbox-only).
- Report, per orbit/direction when `--full-coverage-only` is used, whether any granules touch the AOI boundary, and otherwise report the minimum distance between the AOI boundary and the product footprints.

## Key Components Affected
- `minsar/scripts/get_sar_coverage.py`
  - `_s1_search_count_full_coverage()` logic
  - Geometry helper functions around product footprints
  - S1 count path in `fetch_orbit_counts()` / `_fetch_one_count()`

## Action Items
- [ ] Import Shapely and build AOI and footprint geometries from WKT/GeoJSON.
- [ ] Update `_s1_search_count_full_coverage()` to:
  - [ ] Use Shapely `covers`/`contains` to decide full AOI coverage.
  - [ ] Track whether any footprints touch the AOI boundary with `touches`.
  - [ ] Track the minimum AOI-boundary-to-footprint distance when none touch.
  - [ ] Emit a concise per-(orbit, direction) summary: either “some granules touch the AOI boundary” or “min distance from AOI boundary to footprint: X (in degrees)”.
- [ ] Keep the existing return value semantics (unique-date count) so callers remain unchanged.
- [ ] Ensure behavior is restricted to the `--full-coverage-only` S1 path and does not affect default counts or other platforms.

## Execution Plan (Detailed Change Instructions)
1. **Shapely imports**
   - Add imports near the top of `get_sar_coverage.py`:
     - `from shapely.geometry import shape as _shape`
     - `from shapely import wkt as _wkt`
   - Optionally guard with `try/except ImportError` and fall back to the existing bbox-only logic if Shapely is unavailable, but prefer to use Shapely when present.

2. **AOI geometry**
   - Inside `_s1_search_count_full_coverage()`, construct a Shapely polygon for the AOI from the WKT string:
     - `aoi_geom = _wkt.loads(wkt)`
     - Also get its boundary (`aoi_boundary = aoi_geom.boundary`) for distance calculations.

3. **Footprint geometry and full-coverage test**
   - Replace or augment the current `_product_bbox` / `_bbox_contains` usage with Shapely:
     - For each `product` in `results`, convert its GeoJSON geometry to a Shapely geometry with `_shape(product.geometry or product.properties.get('geometry'))`.
     - Define “full coverage” as `footprint.covers(aoi_geom)` (or equivalently `aoi_geom.within(footprint)`).
     - If full coverage is true, include that granule’s acquisition date in the `dates_full` set.

4. **Boundary-touch and distance diagnostics**
   - While iterating over footprints, also:
     - Track a boolean `any_touch_boundary` updated when `footprint.touches(aoi_geom)` is True.
     - Track `min_boundary_distance` as the minimum of `aoi_boundary.distance(footprint.boundary)` across non-touching footprints.
   - After processing all results, before returning the count:
     - If `any_touch_boundary` is True, print a single summary line like:
       - `S1 orbit=<orbit> dir=<direction>: some granules touch the AOI boundary`
     - Else if `min_boundary_distance` is not None, print:
       - `S1 orbit=<orbit> dir=<direction>: min distance from AOI boundary to footprint is <value> degrees`
   - Keep this logging lightweight and only active when `--full-coverage-only` is in use (i.e., inside `_s1_search_count_full_coverage()`).

5. **Preserve API and behavior for other paths**
   - Keep the signature and return type of `_s1_search_count_full_coverage()` as `int` (unique-date count), so `fetch_orbit_counts()` and `_fetch_one_count()` remain unchanged.
   - Do not change the default S1 count path (`_s1_search_count`) or any NISAR/ALOS-2 logic.

## Key Commands & Flows
- Run S1 coverage with full-coverage and boundary diagnostics:
  - `get_sar_coverage.py 36.33:36.485,25.32:25.502 --platforms S1 --count --full-coverage-only -v`
  - Expect per-orbit lines indicating whether any granules touch the AOI boundary, or the minimum boundary distance, plus the usual count table.

## TODO List
- [ ] Implement Shapely-based AOI/footprint geometry handling and coverage logic.
- [ ] Add boundary-touch and minimum-distance reporting inside `_s1_search_count_full_coverage()`.
- [ ] Manually test a few AOIs (including Santorini) to confirm that:
  - [ ] Full-coverage counts drop for partially covering tracks (e.g., descending track 36 if appropriate).
  - [ ] The summary messages about touching vs distance behave as requested.
- [ ] Run the relevant test suite / basic script invocations (e.g., `get_sar_coverage.py --help`) in an environment with `asf_search` and `shapely` installed.

