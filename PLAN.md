# Plan: Fix create_dolphin_files.py HDFEOS metadata for insarmaps ingest

## Summary

Popocatepetl Dolphin `.he5` files are missing UNAVCO/insarmaps metadata attributes that MintPy-produced files include. When `hdfeos5_2json_mbtiles.py` builds `metadata.pickle`, only 12 attribute keys are written (vs 29 for the working Galapagos MintPy dataset). Wrong `PROJECT_NAME` (`timeseries` instead of `Popocatepetl`) also yields a bad `region` value. We will populate the missing attributes from OPERA CSLC identification metadata and fix attribute overwrites in `create_hdfeos_output`.

## Key Components Affected

- `minsar/src/minsar/cli/create_dolphin_files.py` — add insarmaps metadata population; fix PROJECT_NAME/first_frame overwrites; read CSLC identification group
- `minsar/src/minsar/helper_functions.py` — reuse `extract_identification_metadata` (no changes expected)

## Root Cause (runtime evidence)

Comparison of `metadata.pickle` and `.he5` root attrs:

| Issue | Broken (Popocatepetl dolphin) | Working (Galapagos mintpy) |
|-------|------------------------------|----------------------------|
| `attribute_keys` count | 12 | 29 |
| `project_name` | `timeseries` | `unittestGalapagosSenD128` |
| `region` | `timeserie` | `unittestGalapagosSenD12` |
| `first_frame` | `' '` (space string) | `596` (int) |
| Missing insarmaps attrs | mission, relative_orbit, beam_mode, beam_swath, first_date, last_date, flight_direction, look_direction, prf, processing_type, REF_LAT, REF_LON, CENTER_LINE_UTC, history, atmos_correct_method, last_frame, mintpy.subset.lalo | present |

`create_hdfeos_output` overwrites `PROJECT_NAME` with `basename(dirname(output_path))` → `timeseries`, and sets `first_frame = ' '`.

CSLC identification group has the needed values (`track_number=143`, `orbit_pass_direction`, `look_direction`, `burst_id`, `wavelength`, `prf_raw_data`) but is not read — only nested `/metadata` scalars are loaded.

## Action Items

- [ ] Add `populate_insarmaps_metadata()` to set UNAVCO-format attributes from CSLC identification + date/bbox/ref coords
- [ ] Read CSLC identification group via `extract_identification_metadata`
- [ ] Fix `create_hdfeos_output`: preserve `PROJECT_NAME`; remove `first_frame = ' '` overwrite
- [ ] Add debug instrumentation; verify regenerated `.he5` / `metadata.pickle` match working pattern
- [ ] Run comparison script on regenerated output

## Execution Plan (Detailed Change Instructions)

1. Import `extract_identification_metadata`, `datetime` in `create_dolphin_files.py`.
2. Add `populate_insarmaps_metadata(metadata, date_list, latitude, longitude, ref_row, ref_col)`:
   - `mission` = S1 from platform_id/mission_id
   - `relative_orbit` = track_number (from identification or filename)
   - `beam_mode` = IW (from burst_id)
   - `beam_swath` = int from burst_id (e.g. iw3 → 3)
   - `processing_type` = LOS_TIMESERIES
   - `first_date` / `last_date` = ISO dates from date_list
   - `flight_direction` = first char of orbit_pass_direction (D/A)
   - `look_direction` = R/L from look_direction
   - `prf` = prf_raw_data
   - `wavelength` = float (from metadata or 0.05546576 for S1 C-band)
   - `history` = today ISO date
   - `atmos_correct_method` = None
   - `first_frame` / `last_frame` = burst_index or 0
   - `REF_LAT` / `REF_LON` = lat/lon at ref_row, ref_col
   - `CENTER_LINE_UTC` = seconds from midnight UTC of zero_doppler_start_time
   - `mintpy.subset.lalo` = `{lat_min}:{lat_max},{lon_min}:{lon_max}` from bbox
3. In CSLC branch of `main()`, merge identification metadata into metadata2.
4. Call `populate_insarmaps_metadata()` before `create_hdfeos_output()`.
5. In `create_hdfeos_output()`, only set `PROJECT_NAME` if not already present; do not set `first_frame = ' '`.

## Key Commands & Flows

```bash
cd /data/HDF5EOS/Popocatepetl
create_dolphin_files.py
hdfeos5_2json_mbtiles.py "timeseries/S1_desc_...he5" "timeseries/JSON" --num-workers 6
# Compare metadata.pickle attribute_keys count (expect ~29)
```

## TODO List

- [x] Implement metadata population
- [x] Fix sequential JSON upload in json_mbtiles2insarmaps.py
- [x] Verify with comparison script on regenerated files
