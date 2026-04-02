# NASA Earthdata Status Check Script

This document describes the NASA Earthdata status check feature: scripts that verify Earthdata availability before ASF downloads, with configurable retry intervals and max wait time via environment variables.

## Goal

Add `check_nasa_earthdata_status.py` (status check only) and `check_nasa_earthdata_status.bash` (check + optional wait loop). Integrate the wait step into the download workflow so it blocks until Earthdata is OK, with configurable interval and max wait via environment variables. Ensure status output is visible on the terminal when run from minsarApp.bash.

## 1. check_nasa_earthdata_status.py (status check only)

**Location:** `minsar/scripts/check_nasa_earthdata_status.py`

**Logic:**

- Fetch `https://status.earthdata.nasa.gov` with a timeout (e.g. 30 s). Use `urllib.request` (no extra deps).
- Parse the HTML/text: if "All Applications OK" -> success; if "Outage"/"Issue" or fetch fails -> failure.
- **Success:** print `NASA Earthdata status: OK` to stdout; exit 0.
- **Failure:** print a short message to stderr; exit 1.
- No wait/loop logic in the Python script.

## 2. check_nasa_earthdata_status.bash (check + wait loop)

**Location:** `minsar/scripts/check_nasa_earthdata_status.bash`

**Usage:** `check_nasa_earthdata_status.bash [--wait [interval] [max_wait]]`

- Without `--wait`: runs `check_nasa_earthdata_status.py` once and exits with its code.
- With `--wait [interval] [max_wait]`: loops calling the Python script every `interval` seconds until it returns 0, or until `max_wait` seconds have elapsed, then exits 1. On each failure, print a message to stderr and sleep. Example: `--wait 300 36000` = check every 5 min, give up after 10 hours.

**Environment variables** (optional overrides; used when `--wait` is given):

| Variable                   | Meaning                                        | Default       |
| -------------------------- | ---------------------------------------------- | ------------- |
| `EARTHDATA_CHECK_INTERVAL` | Seconds between checks                         | 300           |
| `EARTHDATA_MAX_WAIT`       | Max total wait time (seconds) before exiting 1 | 86400 (1 day) |

Use these for debugging (e.g. `EARTHDATA_CHECK_INTERVAL=60 EARTHDATA_MAX_WAIT=600` for a 10‑min test). If `--wait` is given with explicit args, those override the env vars.

## 3. Integration: where to run the check so output is visible

**Problem:** `minsar/bin/minsarApp.bash` runs the download script with redirects, e.g.:

```bash
run_command "./download_burst2safe.sh  2>out_download_burst2safe.e 1>out_download_burst2safe.o"
```

All stdout/stderr from the download script goes to files, so the status would not appear on the terminal.

**Solution:** Run the Earthdata check **inside minsarApp.bash** as a separate step, before the download, **without redirecting** its output. Then the user sees the status on the terminal.

**Changes to minsarApp.bash** (around lines 461–468):

- For `burst2safe` and `burst2stack`, before running the download script, run:

```bash
run_command "check_nasa_earthdata_status.bash --wait"
```

(no `2>...` or `1>...`; `run_command` passes stdout/stderr through to the terminal).

- Then run the download script as before.

**Generated scripts** (`download_burst2safe.sh`, `burst2stack_cmd.sh`) do **not** need to call the check; minsarApp.bash handles it. That keeps the check outside the redirected download output and guarantees visibility.

## 4. Integration into generate_download_command.py (alternative)

If you prefer the check to live inside the generated scripts (e.g. for standalone runs of those scripts), add at the start of each:

```bash
check_nasa_earthdata_status.bash --wait || exit 1
```

To see output when run via minsarApp.bash, minsarApp.bash would need to run the download script without redirecting (or use `tee`). Since minsarApp.bash currently redirects, the cleanest approach is **section 3**: run the check in minsarApp.bash before the download, with no redirect.

## 5. Timing Examples

- `--wait 300 3600`: check every 5 min, give up after 1 hour.
- `--wait 300 36000`: check every 5 min, give up after 10 hours.
- `--wait` (no args): use env vars or defaults (interval=300, max=86400 = 1 day).

## 6. Making the Script Discoverable

`check_nasa_earthdata_status.bash` invokes `check_nasa_earthdata_status.py` (same directory). Ensure minsar/scripts is on PATH, or use full path from minsarApp.bash.

## 7. Files to Create/Modify

| File | Action |
|------|--------|
| `minsar/scripts/check_nasa_earthdata_status.py` | Create: fetch status page, parse, exit 0/1 (no wait) |
| `minsar/scripts/check_nasa_earthdata_status.bash` | Create: calls Python; with `--wait` loops using EARTHDATA_CHECK_INTERVAL / EARTHDATA_MAX_WAIT (defaults 300, 86400) |
| `minsar/bin/minsarApp.bash` | Modify: for burst2safe and burst2stack, run `check_nasa_earthdata_status.bash --wait` before download (no redirect so output appears on terminal) |

## 8. Optional: Skip Check

Add `--no-earthdata-check` to minsarApp.bash to bypass the check. Defer unless requested.
