# Burst download (burst2safe and related)

This document complements [architecture_docs/BURST_DOWNLOAD.md](../architecture_docs/BURST_DOWNLOAD.md).

## burst_download.bash: AOI vs burst footprints

After all per-date `burst2stack` commands finish, `minsar/scripts/burst_download.bash` converts its AOI extent to S:N,W:E bounds and runs:

`check_if_bursts_includeAOI.py <bbox> 'SLC/*.tif*'`

This writes:

- **`SLC/dates_not_including_AOI.txt`** — one **`YYYYMMDD`** per line (sorted) for dates whose burst GeoTIFF footprint union does **not** fully cover the bbox AOI.

Then `burst_download.bash` removes matching paths under `SLC/` for each `YYYYMMDD` (pattern `*${ymd}T*`).

To skip this step (no `check_if_bursts_includeAOI.py`, no pruning), run `burst_download.bash` with **`--no-check-bursts-includeAOI`**.

### Other “removed date” logs (different meaning)

| File | Source | Meaning |
|------|--------|--------|
| `SLC/dates_removed.txt` | `check_SAFE_completeness.py` | Incomplete `.SAFE` directories (missing required internal files), not geometric AOI coverage. |
| `removed_dates_*.txt` | `check_burst2safe_job_outputs.py` | Dates inferred from burst2safe stderr problem strings; deletes matching paths under the job directory. |

## check_burst2safe_job_outputs.py

Used to validate burst2safe job outputs and optionally clean problem dates; see script help and [architecture_docs/BURST_DOWNLOAD.md](../architecture_docs/BURST_DOWNLOAD.md).
