# Plan: Align horz/vert HDFEOS update naming with MintPy threshold logic

## Summary
Make `tools/PlotData/src/plotdata/helper_functions.py` use the same conditional `XXXXXXXX` end-date naming behavior as `additions/mintpy/save_hdfeos5.py`, so `XXXXXXXX` is only used when update mode is on and the dataset last date is recent enough.

## Key Components Affected
- `tools/PlotData/src/plotdata/helper_functions.py`
- Potentially tests in `tests/` if there is existing coverage for output naming paths
- Runtime behavior in `tools/PlotData/src/plotdata/cli/horzvert_timeseries.py` via `get_output_filename()`

## Action Items
- [ ] Add helper logic in PlotData for "recent-date" threshold decision.
- [ ] Update PlotData `get_output_filename()` to use thresholded `XXXXXXXX` behavior.
- [ ] Keep behavior and messages consistent with MintPy naming policy.
- [ ] Add/adjust focused tests (if present) for old-date vs recent-date update naming.
- [ ] Run relevant tests/lint checks.

## Execution Plan (Detailed Change Instructions)
1. In `tools/PlotData/src/plotdata/helper_functions.py`, add date-age decision helper(s) equivalent to:
   - parse `metadata['last_date']` (`YYYY-MM-DD`)
   - compare to current date
   - use `XXXXXXXX` only if age is within a fixed max-age threshold.
2. Define and use the same threshold value as MintPy policy (31 days) to avoid divergence.
3. Modify PlotData `get_output_filename()` so `update_flag` no longer forces unconditional `DATE2='XXXXXXXX'`.
4. Preserve existing output filename format and corner-subset suffix behavior.
5. Add/update tests covering:
   - update=yes with recent last date -> `XXXXXXXX`
   - update=yes with old last date -> real end date
   - update!=yes -> real end date
6. Run targeted tests first, then broader test command(s) if needed.

## Key Commands & Flows
- `python -m unittest ...` (targeted tests for naming logic, if test module exists)
- `bash tests/run_all_tests.bash --python-only` (if quick enough and relevant)

## TODO List
- [ ] Write tests for existing behavior
- [ ] Implement changes
- [ ] Add tests for new behavior
- [ ] Run full test suite
# Plan: Align horzvert LOS ingestion with ref-lalo workflow

## Summary
Update `horzvert_timeseries.bash` so LOS ingest uses asc/desc files that have already been re-referenced to the requested `--ref-lalo`, geocoded from those re-referenced files, and then ingested directly (without re-referencing during ingest). This prevents unintended ingestion of geocoded source products and enforces the intended sequence.

## Key Components Affected
- `minsar/bin/horzvert_timeseries.bash`
- Potentially a colocated/new test file under `tests/` for this script flow
- `architecture_docs/DEVELOPMENT_GUIDE.md` (testing/dev notes if needed)
- `architecture_docs/README.md` (quick reference update if behavior description changes materially)

## Action Items
- [x] Audit current Step 1/Step 4 behavior for LOS files and identify exact command path causing wrong ingest target.
- [x] Implement explicit re-reference step for original asc/desc inputs using `--ref-lalo`.
- [x] Ensure re-referenced asc/desc keep the same filename as original (per request), replacing in-place or controlled move.
- [x] Geocode the re-referenced asc/desc products and use those for horz/vert computation.
- [x] Ingest horz/vert outputs.
- [x] Ingest the re-referenced asc/desc products directly (no additional `--ref-lalo` during ingest).
- [x] Add or update tests that validate command flow and ingestion targets.
- [x] Run required tests and fix any regressions (bash suites pass; full `./run_all_tests.bash` may fail if Python env lacks `numpy` for unrelated `test_make_zero_elevation_dem`).
- [x] Update architecture docs to match new behavior.

## Execution Plan (Detailed Change Instructions)
1. Read `minsar/bin/horzvert_timeseries.bash` around:
   - file resolution (`resolve_he5_or_dataset`)
   - geocode step (`geocode_if_needed`)
   - ingestion step (`ingest_los_flag` block)
2. Introduce a LOS re-reference helper step before geocoding:
   - call the same reference-point mechanism currently triggered indirectly by `ingest_insarmaps.bash --ref-lalo`
   - apply it to both resolved original asc/desc inputs
   - ensure output filename remains the original filename (no suffix naming change)
3. Adjust Step 1 geocoding inputs so geocode runs from the re-referenced asc/desc files.
4. Keep Step 2 horz/vert computation using geocoded asc/desc products.
5. Update Step 4 LOS ingest:
   - ingest the re-referenced asc/desc files directly
   - remove `--ref-lalo` from LOS ingest invocation so reference is not re-applied and no extra unintended ingest path is triggered
6. Update inline help/comments in `horzvert_timeseries.bash` to reflect the new sequencing and filenames.
7. Add/adjust test coverage:
   - verify ingest commands target re-referenced asc/desc and do not pass `--ref-lalo`
   - verify horz/vert ingest remains unchanged
8. Run:
   - `bash tests/test_run_workflow.bash`
   - `bash tests/run_all_tests.bash`
9. Update architecture docs with the adjusted horzvert LOS workflow behavior.

## Key Commands & Flows
- Reproduce current behavior:
  - `horzvert_timeseries.bash <desc_dir_or_file> <asc_dir_or_file> --ref-lalo <LAT> <LON>`
- Validate flow in logs:
  - confirm explicit re-reference step occurs before geocode
  - confirm geocode uses re-referenced asc/desc
  - confirm ingest for LOS is direct (no `--ref-lalo`)

## TODO List
- [x] Write tests for existing behavior (capture current command path)
- [x] Implement changes
- [x] Add tests for new behavior
- [x] Run full test suite (bash OK; Python needs env with numpy for all modules)
# Plan: Extend `--flight-dir` list forms

## Summary
Extend `create_template.py` (and AOI-through-`minsarApp.bash` usage) to accept comma-list forms `--flight-dir asc,desc` and `--flight-dir desc,asc`, and change the default from `both` to `asc,desc`.

## Key Components Affected
- `minsar/scripts/create_template.py`
- `tests/test_create_template_flight_dir.py`
- `architecture_docs/README.md`

## Action Items
- [ ] Update CLI parsing/normalization for `--flight-dir` to accept: `asc`, `desc`, `both`, `asc,desc`, `desc,asc`.
- [ ] Change default `--flight-dir` behavior to `asc,desc`.
- [ ] Keep behavior equivalent: list forms should behave as current `both` (write primary + opposite template).
- [ ] Add tests for the new accepted values and new default.
- [ ] Update architecture docs help/quick-reference text for new default and accepted values.
- [ ] Run targeted tests for create-template flight-dir behavior.

## Execution Plan (Detailed Change Instructions)
1. In `create_parser()` within `minsar/scripts/create_template.py`:
   - Expand accepted `--flight-dir` choices to include `asc,desc` and `desc,asc`.
   - Change default from `both` to `asc,desc`.
   - Update help text to document all accepted forms and new default.
2. In `main()` in `create_template.py`:
   - Normalize `inps.flight_dir` into canonical modes:
     - single-pass: `asc` / `desc`
     - dual-pass: `both`, `asc,desc`, `desc,asc`
   - Preserve existing write behavior:
     - dual-pass => primary asc template + opposite template generation.
     - single-pass => only selected pass template.
3. In `tests/test_create_template_flight_dir.py`:
   - Add parser/default assertions for `asc,desc` default.
   - Add tests verifying `asc,desc` and `desc,asc` trigger dual-pass behavior (`_run_create_opposite_orbit` called once).
4. Update `architecture_docs/README.md` to reflect accepted `--flight-dir` values and the new default.
5. Run:
   - `python3 -m unittest tests.test_create_template_flight_dir -v`
   - Optionally any nearby create-template tests if needed.

## Key Commands & Flows
- `python3 -m unittest tests.test_create_template_flight_dir -v`

## TODO List
- [ ] Write tests for existing behavior
- [ ] Implement changes
- [ ] Add tests for new behavior
- [ ] Run full/targeted test suite

# Plan: Add --flight-dir to create_template.py

## Summary
Add a new CLI option `--flight-dir` to `minsar/scripts/create_template.py` with allowed values `{both, asc, desc}` and default `both`. Use this option to control which flight direction/orbit is selected when generating the primary template.

## Key Components Affected
- `minsar/scripts/create_template.py`
- `minsar/utils/bbox_cli_argv.py` (`--flight-dir` in `CREATE_TEMPLATE_ARGV_KW`)
- `tests/test_create_template_flight_dir.py`
- `architecture_docs/README.md` (env/quick reference)

## Action Items
- [x] Add parser argument `--flight-dir` with choices `both`, `asc`, `desc` and default `both`.
- [x] Update orbit-selection logic so `both` keeps current selection behavior, while `asc` and `desc` force direction-specific orbit/label values; only `both` runs `create_opposite_orbit_template.bash`.
- [x] Add/extend tests for argument parsing and selection behavior.
- [x] Run relevant tests and ensure they pass.

## Execution Plan (Detailed Change Instructions)
1. Update `create_parser()` in `minsar/scripts/create_template.py`:
   - Add `--flight-dir` with `choices=["both", "asc", "desc"]`, `default="both"`, and clear help text.
2. Update `main()` orbit-selection section after `coverage = _run_get_sar_coverage(aoi)`:
   - For `both` keep existing primary behavior (ascending orbit as currently implemented).
   - For `asc`, explicitly pick `asc_relorbit` and `asc_label`.
   - For `desc`, pick `desc_relorbit` and `desc_label`.
   - Keep output naming consistent (`{name}{label}.template`).
3. Add tests:
   - Verify parser accepts all valid `--flight-dir` values and defaults to `both`.
   - Verify selected orbit/label switches correctly for `asc` and `desc` using a mocked coverage response.
4. Run targeted tests:
   - `python -m unittest tests/test_create_template_last_year.py` (and any new create-template tests added).

## Key Commands & Flows
- `python -m unittest tests/test_create_template_last_year.py`
- `python -m unittest <new_or_updated_test_module>`
- (If needed) `bash tests/run_all_tests.bash --python-only`

## TODO List
- [x] Write tests for existing behavior
- [x] Implement changes
- [x] Add tests for new behavior
- [x] Run full test suite (targeted unittest; full `run_all_tests.bash` may need numpy in env)
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

# Plan: Fix step-range print for MiaplPy start

## Summary
Adjust `minsar/bin/minsarApp.bash` so ISCE step ranges are printed only when ISCE/ifgram processing is enabled. Also update the user-facing print format to:
- `ISCE steps to process: <start>-<stop>`
- `MiaplPy steps to process: <start>-<stop>`

This avoids misleading output when running `--start miaplpy` (where `ifgram_flag=0`).

## Key Components Affected
- `minsar/bin/minsarApp.bash`
- `tests/` (only if a suitable existing test covers this print path; otherwise no new test expected for this small log-only fix)

## Action Items
- [ ] Locate current step-range print block in `minsar/bin/minsarApp.bash`.
- [ ] Gate ISCE printout on `ifgram_flag == 1`.
- [ ] Gate MiaplPy printout on `miaplpy_flag == 1`.
- [ ] Replace old `Step ranges: isce: ... miaplpy: ...` style with requested two-line format.
- [ ] Run targeted verification command and confirm output for `--start miaplpy`.

## Execution Plan (Detailed Change Instructions)
1. In `minsar/bin/minsarApp.bash`, replace the `step_ranges` string assembly block with conditional per-pipeline lines:
   - If `ifgram_flag==1`, print `ISCE steps to process: ${isce_start}-${isce_stop}`.
   - If `miaplpy_flag==1`, print `MiaplPy steps to process: ${miaplpy_startstep}-${miaplpy_stopstep}`.
2. Keep surrounding spacing/output structure consistent with existing logs.
3. Verify by running:
   - `minsarApp.bash <template> --start miaplpy`
   and checking that only MiaplPy line appears (no ISCE line).

## Key Commands & Flows
- `minsarApp.bash $TE/qunittestGalapagosSenD128.template --start miaplpy`
- Optional additional sanity:
  - `minsarApp.bash $TE/qunittestGalapagosSenD128.template --start ifgram`
  - `minsarApp.bash $TE/qunittestGalapagosSenD128.template --start miaplpy --miaplpy-step 3`

## TODO List
- [ ] Write tests for existing behavior (if practical for this log output path)
- [ ] Implement changes
- [ ] Add tests for new behavior (if practical)
- [ ] Run full test suite (or justify targeted verification for log-only change)
