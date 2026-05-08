# Plan: Fix horzvert re-reference for long-name MiaplPy HE5 inputs

## Summary
When `horzvert_timeseries.bash` resolves to a long-name (corner-suffix) MiaplPy HE5
file, `reference_point_hdfeos5.bash` writes the re-referenced output to a
short-name sibling (because `save_hdfeos5.py` constructs the output filename from
metadata + `--update --suffix <X>`, with no `--subset`). Step 0d's helper
`hv_promote_miaplpy_short_he5_to_corner_filename` only fires when the input is
already the short form, so the long file on disk remains stale and downstream
geocode/horzvert/ingest read stale REF.

## Components Affected
- `minsar/lib/horzvert_timeseries_utils.sh`
  (extend `hv_promote_miaplpy_short_he5_to_corner_filename` for long-form input)
- `minsar/bin/reference_point_hdfeos5.bash`
  (print the file `save_hdfeos5.py` actually wrote, both at Step 3 and the final
  "Done! Output file:" footer)
- `tests/test_horzvert_timeseries.bash` (extend coverage)

## Execution Plan
1. Extend `hv_promote_miaplpy_short_he5_to_corner_filename` so that when the
   input matches the long-name pattern (`_miaplpy_<8>_<8|XXXXXXXX>_N…_N…_N…_N…_<suffix>`):
   - Derive the expected short-name sibling: `<prefix>_<suffix>.he5` in the same dir.
   - If the short sibling exists and is strictly newer than the long file
     (`[[ $short -nt $long ]]`), `rm -f $long && mv $short $long`.
   - Otherwise leave both files alone (preserves current "long unchanged" behavior).
   - Always echo the long path and return 0.
2. In `reference_point_hdfeos5.bash`, capture `save_hdfeos5.py` stdout via
   `tee` and parse the `finished writing to <path>` line to get the real output
   path. Use that path (resolved against `$INPUT_DIR` if relative) for the Step 3
   "HDFEOS5 file reconstructed:" message and the final "Done! Output file:"
   footer. Fall back to `$OUTPUT_FILE` if parsing fails (defensive only).
3. Tests:
   - Add `test_hv_promote_corner_with_newer_short_sibling_promotes`: long + short
     coexist, short is newer → after call, long contains short's bytes and short
     is gone.
   - Add `test_hv_promote_corner_with_older_short_sibling_keeps_long`: long +
     short coexist, long is newer → both files unchanged.
   - Existing "long unchanged" tests already cover the no-sibling case.

## Confirmed Decisions (from chat)
- Scope: both `horzvert_timeseries_utils.sh` and `reference_point_hdfeos5.bash`.
- Newness check: only `mv short → long` when short is strictly newer than long.
- No backwards-compatibility shims needed; this is a bug fix.

## Validation
- `bash tests/test_horzvert_timeseries.bash`
- `bash -n minsar/bin/reference_point_hdfeos5.bash`
