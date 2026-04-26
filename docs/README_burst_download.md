# Burst download and burst2safe

This document describes how MinSAR builds **burst2safe** commands when using the **ASF burst** download path: downloading Sentinel-1 burst SLCs (`.tiff`), then converting them to ESA SAFE format so the rest of the stack (ISCE topsStack) can run unchanged.

## Overview

- **Download:** Bursts are downloaded (e.g. via `download_burst2safe.sh`) into a burst directory (typically `SLC/`) as `*BURST.tiff` files. For burst2safe, **generate_download_command.py** produces two scripts: **download_burst2safe.sh** (download only: listing + two download runs) and **pack_bursts.sh** (burst2safe jobfile, run_workflow, check_burst2safe_job_outputs, rerun timeouts). The pack step is intended to be replaced by **scripts/pack_bursts.bash** when that exists.
- **burst2stack path:** **burst_download.bash** runs `asf_download.sh --print` to get a burst listing, parses it for dates, writes one burst2stack command per date, and runs them in parallel. This path uses burst2stack (which downloads from ASF and creates SAFEs) instead of burst tiff → burst2safe.
- **burst2safe:** Each burst2safe invocation converts a **group** of bursts into one ESA SAFE product. The script **bursts_to_burst2safe_jobfile.py** creates the runfile that lists one burst2safe command per group.
- **ISCE:** The resulting `.SAFE` products are then unpacked and processed by ISCE (Sentinel1_TOPS) in the same way as SLC `.zip` products; multiple SAFEs per date are supported (see below).

## How groups are formed (checks and priority)

The script groups bursts so that **each burst2safe call receives a valid set of bursts** and **prefers one SAFE per date** (all subswaths in one product) when possible, so ISCE finds all annotation XMLs in a single SAFE. The rules, in priority order:

### 1. Same source product (hash)

- Burst filenames include a **hash** (e.g. `S1_185679_IW1_20251112T161529_VV_**8864**-BURST`). The hash identifies the source SLC granule.
- **Rule:** Never mix bursts from different hashes in one burst2safe call. Different hashes mean different source SLCs; mixing them causes burst2safe to fail (e.g. "Products from subswaths ... do not overlap").

### 2. Prefer one SAFE per (date, hash); split by subswath only when overlap would fail

- Burst2safe allows multiple subswaths (IW1, IW2, IW3) in one SAFE only if **adjacent subswaths’ burst ID ranges overlap** (min and max burst ID difference ≤ 1). When they don’t, burst2safe raises:  
  `ValueError: Products from subswaths IW2 and IW3 do not overlap`
- **Rule:** For each (date, hash), the script checks whether the burst ID ranges of adjacent subswaths satisfy this overlap rule. If **yes**, it emits **one** burst2safe line with all bursts for that (date, hash) — **one SAFE with IW1+IW2+IW3**, so ISCE finds all annotation XMLs and unpack/topo work. If **no** (e.g. AOI spans two SLC frames and ranges don’t align), it splits by subswath and emits one line per (date, hash, subswath); that produces multiple SAFEs per date, which can cause "No annotation xml file found" and topo failures unless the stack is adapted for per-subswath SAFEs.

### 3. Minimum number of bursts

- **Rule:** Only emit a runfile line for a group that has **more than one burst**. Single-burst groups are skipped (downstream ISCE steps such as run_07_merge* expect more than one burst).

### 4. Excluded dates

- **Rule:** Dates in a fixed exclusion list (e.g. known bad orbits) are skipped and do not produce any burst2safe line.

## Summary: one SAFE per (date, hash) when overlap allows; else per (date, hash, subswath)

- **Grouping:** Bursts are grouped by (date, hash). For each group, if adjacent subswaths’ burst ID ranges overlap (≤1), the script writes **one** burst2safe line (all subswaths) → **one SAFE per date** for that hash, which ISCE can unpack and use. If overlap fails, it writes one line per (date, hash, subswath).
- **Output:** The runfile (e.g. `SLC/run_01_burst2safe`) has one line per group with at least two bursts and not on an excluded date.
- **Result:** When the AOI is covered by one SLC (one hash, overlapping subswaths), you get one `.SAFE` per date with all subswaths (annotation for IW1, IW2, IW3 in one product). When the AOI spans two SLCs or overlap fails, you get multiple SAFEs per date (one per subswath), which may require workflow changes for ISCE.

## Using the resulting SAFEs with ISCE

- **Sentinel1_TOPS** accepts both `.SAFE` and `.zip` products; the interface is the same.
- When the script outputs **one SAFE per (date, hash)** (subswaths overlap), that SAFE contains all subswaths (IW1, IW2, IW3) and their annotation XMLs. ISCE unpack and topo then work without change. This is the preferred case (e.g. AOI within one SLC frame).
- When the script outputs **multiple SAFEs per date** (one per subswath, overlap failed), each SAFE has only one subswath’s annotation. Passing multiple such SAFEs in `dirname` can lead to "No annotation xml file found" and topo failures; handling that would require stack or ISCE changes.

## burst_download.bash (burst2stack path)

- **Script:** `minsar/scripts/burst_download.bash`
- **Purpose:** Run `asf_download.sh --print` to get the burst listing, parse it for unique dates, write one burst2stack command per date (with per-date stderr to `burst2stack_YYYYMMDD.e`), and run them in parallel via xargs. After the main pass, runs `check_SAFE_completeness.py` (removes incomplete SAFEs), verifies which dates lack a complete SAFE, writes `burst2stack_failures.txt` and `run_burst2stack_rerun`, runs one retry pass, runs `check_SAFE_completeness.py` again (so incomplete SAFEs from failed retries are removed and failures are correctly recorded), then re-verifies. If failures include "Products from swaths * do not overlap", an **AOI extension loop** runs: extends the search polygon, re-fetches the listing, retries only the overlap-failed dates, and repeats until success or threshold.
- **Prerequisites:** Run `generate_download_command.py` first (template mode), or pass `--relativeOrbit` and `--intersectsWith` (standalone mode).
- **Usage:** `burst_download.bash [--work-dir DIR] [--slc-dir SLC] [--parallel N] [--skip-listing] [--exclude-season MMDD-MMDD]` (run from work dir or pass `--work-dir`). The AOI extension loop is disabled when `--skip-listing` is used (re-fetch requires a fresh listing).
- **Seasonal exclusion:** `--exclude-season 1005-0320` excludes all acquisitions between Oct 05 and Mar 20 (inclusive, wrapping New Year). The same filter is forwarded to `asf_download.sh` so both listing and download phases apply it consistently.
- **Output files (under SLC/):** `burst2stack_failures.txt` (one line per failed date: `YYYY-MM-DD  reason; err_summary`, where `err_summary` is extracted from `burst2stack_YYYYMMDD.e` when available), `run_burst2stack_rerun` (burst2stack commands for manual rerun), `burst2stack_YYYYMMDD.e` (per-date stderr, e.g. burst2stack_20141022.e), `burst2stack_aoi_extension.log` (one line per AOI extension attempt when the overlap loop runs).

### AOI extension loop (overlap errors)

When burst2stack fails with `ValueError: Products from swaths IW1 and IW2 do not overlap` (or IW2/IW3), the AOI may be too tight. The script detects these overlap errors in `burst2stack_failures.txt`, extends the search polygon and extent by a configurable buffer, re-fetches the burst listing from ASF, and retries only the overlap-failed dates. It repeats up to `AOI_EXTENSION_ITER_MAX` iterations (default 5) or until total extension reaches `AOI_EXTENSION_MAX` (default 0.05 deg). Constants at the top of the script: `AOI_EXTENSION_INIT` (degrees per step, default 0.01), `AOI_EXTENSION_MAX`, `AOI_EXTENSION_ITER_MAX`. If overlap errors remain at threshold, the script exits with an error.

**Documentation of extension runs:**

| What | Where | Format / content |
|------|-------|------------------|
| Console output | stdout | `AOI extension attempt N: extending by X deg (total Y)`, `Re-fetching burst listing with extended AOI ...`, `Running burst2stack for M overlap-failed date(s) with extended AOI ...` |
| Extension log | `SLC/burst2stack_aoi_extension.log` | One line per attempt: `iteration total_extension extent dates_retried` (created when loop runs) |
| Failure entries | `burst2stack_failures.txt` | Reason suffix `no SAFE produced (AOI ext N)` when failure occurs during extension attempt N |
| Rerun commands | `run_burst2stack_rerun` | burst2stack commands use the **extended** extent (W S E N) for manual rerun |

## Script and help (burst2safe path)

- **Script:** `minsar/scripts/bursts_to_burst2safe_jobfile.py`
- **Usage:**  
  `bursts_to_burst2safe_jobfile.py SLC`  
  (run from the project directory that contains `SLC/` and a `*.template` file)
- **Help:**  
  `bursts_to_burst2safe_jobfile.py --help`

The script creates `SLC/run_01_burst2safe` and (via job submission) the corresponding `.job` files for running burst2safe on the cluster.

---

## check_burst2safe_job_outputs.py

**When to run:** After the burst2safe job(s) have run (e.g. via `run_workflow.bash --jobfile .../run_01_burst2safe`). The script inspects non-zero `run_01_burst2safe_*.e` stderr files in the SLC directory and classifies failures.

**What it does:**

1. **Preserves the original run file**  
   Copies `run_01_burst2safe` (or `run_01_burst2safe_0`) to **run_01_burst2safe_0_orig** before any changes.

2. **Classifies errors**  
   Each non-zero `.e` file is classified as:
   - **Timeout** (e.g. CMR/ASF timeout) → lines go into `run_01_burst2safe_timeout_0` for rerun via `rerun_burst2safe.sh`.
   - **Data problem** (known stderr strings, e.g. `AttributeError: 'NoneType' object has no attribute 'tag'`, `ValueError: min() arg is an empty sequence`) → those dates are removed (see below) and can be listed for rerun.
   - **Other** → any other stderr content; lines go into `run_01_burst2safe_rerun_0` (for optional burst2stack or manual handling).

3. **SAFE-aware summaries**  
   For each error, the script checks whether a `.SAFE` directory already exists for that date in the SLC dir:
   - **errors_redundant.txt** — one line per error where a SAFE already exists (date + short error summary). The failure is redundant in the sense that the date is already covered by an existing SAFE.
   - **errors_eliminated.txt** — one line per error where no SAFE exists (date + short summary). Those burst2safe calls are treated as eliminated (no SAFE produced).

4. **BURST2SAFE_ERRORS.txt**  
   A summary file that groups errors by type (timeout, data_problem, other) and lists the burst2safe command (or a short form) that was eliminated for each.

5. **run_01_burst2safe_0_clean**  
   The run file with all problem burst2safe lines removed (i.e. only lines that did not produce an error). The original is kept in `run_01_burst2safe_0_orig`.

6. **Timeout and rerun lists**  
   Writes `run_01_burst2safe_timeout_0` (and `.job`) when there are timeouts; writes `run_01_burst2safe_rerun_0` (and `.job`) when there are non-timeout errors. The download script can rerun timeouts via `rerun_burst2safe.sh`; the rerun list can be used for burst2stack or manual fixes.

7. **Data-problem dates**  
   For dates matching **data_problem_strings_stderr**, the script removes matching `*tiff` and `*SAFE` files from the SLC dir and logs to `removed_dates_*.txt`.

**Output files (all under SLC/):**

| File | Description |
|------|-------------|
| run_01_burst2safe_0_orig | Copy of the original run file before any modifications |
| run_01_burst2safe_0_clean | Run file with problem burst2safe lines removed |
| errors_redundant.txt | One line per error where a SAFE already exists (date + summary) |
| errors_eliminated.txt | One line per error where no SAFE exists (date + summary) |
| BURST2SAFE_ERRORS.txt | Summary of error types and eliminated burst2safe commands |
| run_01_burst2safe_timeout_0 | Lines to re-run for timeouts (optional) |
| run_01_burst2safe_rerun_0 | Lines to re-run for non-timeout errors (optional) |
| timeout.txt | Reference list of timeout run lines |

**Usage:**  
`check_burst2safe_job_outputs.py SLC`  
(from the project directory). Use `--help` for options and a link to this doc on GitHub.

**Note for maintainers and AI:** When changing `check_burst2safe_job_outputs.py` (e.g. adding or changing error strings, output files, or behavior), update this section and the table above so the doc stays in sync with the script.
