# Burst testing with annual templates

This document describes how to test burst-processing behavior (e.g. `bursts_to_burst2safe_jobfile.py`) across multiple annual datasets using generated template files and a runner script.

## Overview

- **create_annual_template_files.bash** (in `minsar/utils/`) creates year-shifted template copies from a base template and writes **run_templates.sh** into `$SCRATCHDIR`.
- **run_templates.sh** is generated (overwritten each run), not version-controlled. It runs `minsarApp.bash` on each annual template in order with `--no-mintpy --no-insarmaps --no-upload`; on first failure it exits with a clear error. It is kept simple so you can edit it manually.

## create_annual_template_files.bash

**Location:** `minsar/utils/create_annual_template_files.bash`

**Usage:**

```bash
create_annual_template_files.bash TEMPLATE_FILE [--years N]
```

- **TEMPLATE_FILE** (required): path to the base template (e.g. `burstsg0HawaiiSenD87.template`).
- **--years N** (optional): **integer**; number of annual variants to create (e.g. default 5). Creates files with the first digit in the basename set to 1, 2, … N.

**Date logic:**

- Base template (digit 0) keeps its `ssaraopt.startDate` and `ssaraopt.endDate`.
- For each next variant (1..N): **startDate** = previous template’s **endDate + 1 day**; **endDate** = previous template’s **endDate + 1 year**. No clamping to today (last year may be in the future).

**First digit:** The first digit (0–9) in the template basename is replaced with 1..N for each new file (e.g. `burstsg0HawaiiSenD87` → `burstsg1...`, `burstsg2...`). Output templates are written to the same directory as the input.

**run_templates.sh:** After creating the annual template files, the script writes `$SCRATCHDIR/run_templates.sh` (overwrite). That script runs `minsarApp.bash "$TE/<basename>.template" --no-mintpy --no-insarmaps --no-upload` for the base and each variant (0..N) in order; on first failure it prints the failing template path and exits. You may edit `run_templates.sh` by hand (e.g. change which templates run).

**Validation:** Template path must exist; both `ssaraopt.startDate` and `ssaraopt.endDate` must be present and YYYYMMDD; basename must contain at least one digit.

**--help:** Use `--help` or `-h` for usage and an example.

## run_templates.sh (generated)

- **Location:** `$SCRATCHDIR/run_templates.sh` (written by create_annual_template_files.bash; not in the repo).
- **Execution:** Run from `$SCRATCHDIR` after sourcing the minsar environment; `$TE` must be set.
- **Content:** Simple list of minsarApp.bash invocations for templates 0..N; minimal --help and comments.

## Testing bursts_to_burst2safe_jobfile.py

1. Run `create_annual_template_files.bash` with your base template (e.g. `burstsg0HawaiiSenD87.template`) and `--years N` (integer).
2. Run `$SCRATCHDIR/run_templates.sh` to process each annual template with minsarApp (download/unpack through the pipeline with --no-mintpy --no-insarmaps --no-upload). The first failure indicates which template (dataset variant) failed.
3. For each project, you can run or inspect `bursts_to_burst2safe_jobfile.py` (e.g. after download/unpack) to verify burst2safe runfile generation across the annual variants.

## Reference

- Plan: annual template and run scripts (create_annual_template_files.bash, run_templates.sh).
- Script under test: `minsar/scripts/bursts_to_burst2safe_jobfile.py`.
