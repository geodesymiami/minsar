# Burst download (burst2safe and related)

This document complements [architecture_docs/BURST_DOWNLOAD.md](../architecture_docs/BURST_DOWNLOAD.md).

## burst_download.bash: AOI vs burst footprints

After all per-date `burst2stack` commands finish, `minsar/scripts/burst_download.bash` converts the **original** AOI extent (`extent_orig` from your polygon, not the overlap-extension padding) to S:N,W:E bounds and runs:

`check_if_bursts_includeAOI.py <bbox> 'SLC/*.tif*'`

This writes:

- **`SLC/dates_not_including_AOI.txt`** — one **`YYYYMMDD`** per line (sorted) for dates whose burst GeoTIFF footprint union does **not** fully cover the bbox AOI.

Then `burst_download.bash` removes matching paths under `SLC/` for each `YYYYMMDD` (pattern `*${ymd}T*`).

To skip this step (no `check_if_bursts_includeAOI.py`, no pruning), run `burst_download.bash` with **`--no-check-bursts-includeAOI`**.

## burst_download.bash: subswath coverage repair

After the main `burst2stack` pass (and the uniform AOI-extension loop for overlap errors), `burst_download.bash` runs **`check_burst_stack_coverage.py`** unless **`--no-check-subswath-coverage`** is set.

It inspects each `SLC/*.SAFE` against the **original** AOI bbox (`extent_orig`):

| Check | Output file |
|-------|-------------|
| Missing IW subswath vs modal/reference set | `SLC/dates_missing_subswath.txt` (`YYYYMMDD missing=IW1`) |
| Burst count differs from modal | `SLC/dates_inconsistent_burst_count.txt` |
| Measurement TIFF footprints outside AOI (along-track extras) | `SLC/dates_extra_azimuth_bursts.txt` |

**Repair:**

1. **Lon-only extension** — widen W and E only (lat unchanged) in steps of `0.02` deg up to `0.15` deg; re-fetch ASF listing; remove and re-run `burst2stack` for affected dates. Log: `SLC/burst2stack_lon_extension.log`. Final stacking extent: `SLC/extent_stack.txt`.
2. **Azimuth trim / homogenize** — re-run `burst2stack` for dates with extra azimuth bursts or inconsistent burst counts using `extent_final` (lon from `extent_stack`, lat from `extent_orig`).
3. **`check_file_size.py SLC`** — report remaining burst-count outliers.

Dates still missing a subswath after max lon extension are listed in **`SLC/dates_unfixable_partial_swath.txt`**, then **removed from `SLC/`** automatically (same as AOI-pruned dates). Each removed date is also appended to **`SLC/removed_bursts_missing.txt`** with the missing IW subswath(s), e.g. `20260320 missing=IW2`. Before stack steps, **`minsarApp.bash`** also removes those dates from **`secondarys/`**, **`coreg_secondarys/`**, matching **`configs/`** / **`baselines/`**, and prunes **`run_files/`** (from run step 2 onward) when present.

Skip with **`--no-check-subswath-coverage`**. Lon repair requires re-fetching the ASF listing (do not use `--skip-listing`).

### Other “removed date” logs (different meaning)

| File | Source | Meaning |
|------|--------|--------|
| `SLC/removed_bursts_missing.txt` | `burst_download.bash`, `minsarApp.bash`, `check_job_outputs.py` | Dates removed from the stack because required IW subswath(s) were missing (`YYYYMMDD missing=IWn`). |
| `SLC/dates_removed.txt` | `check_SAFE_completeness.py` | Incomplete `.SAFE` directories (missing required internal files), not geometric AOI coverage. |
| `removed_dates_*.txt` | `check_burst2safe_job_outputs.py` | Dates inferred from burst2safe stderr problem strings; deletes matching paths under the job directory. |

## check_burst2safe_job_outputs.py

Used to validate burst2safe job outputs and optionally clean problem dates; see script help and [architecture_docs/BURST_DOWNLOAD.md](../architecture_docs/BURST_DOWNLOAD.md).
