# Burst download and burst2safe

This document describes how MinSAR builds **burst2safe** commands when using the **ASF burst** download path: downloading Sentinel-1 burst SLCs (`.tiff`), then converting them to ESA SAFE format so the rest of the stack (ISCE topsStack) can run unchanged.

## Overview

- **Download:** Bursts are downloaded (e.g. via `download_asf_burst.sh`) into a burst directory (typically `SLC/`) as `*BURST.tiff` files.
- **burst2safe:** Each burst2safe invocation converts a **group** of bursts into one ESA SAFE product. The script **bursts_to_burst2safe_jobfile.py** creates the runfile that lists one burst2safe command per group.
- **ISCE:** The resulting `.SAFE` products are then unpacked and processed by ISCE (Sentinel1_TOPS) in the same way as SLC `.zip` products; multiple SAFEs per date are supported (see below).

## How groups are formed (checks and priority)

The script groups bursts so that **each burst2safe call receives a valid set of bursts**. The rules, in priority order:

### 1. Same source product (hash)

- Burst filenames include a **hash** (e.g. `S1_185679_IW1_20251112T161529_VV_**8864**-BURST`). The hash identifies the source SLC granule.
- **Rule:** Never mix bursts from different hashes in one burst2safe call. Different hashes mean different source SLCs; mixing them causes burst2safe to fail (e.g. "Products from subswaths ... do not overlap").

### 2. One subswath per burst2safe call

- Burst2safe allows multiple subswaths (IW1, IW2, IW3) in one SAFE only if **adjacent subswaths’ burst ID ranges overlap** (within 1). When they don’t (e.g. different frames or orbits under the same date), burst2safe raises:  
  `ValueError: Products from subswaths IW2 and IW3 do not overlap`
- **Rule:** Group by **subswath** as well. Each burst2safe call gets bursts from a single **(date, hash, subswath)**. That way the overlap check is never triggered (one subswath per call), and every SAFE is valid.
- In ISCE, subswaths are processed independently and then merged; one SAFE per subswath per date is compatible with the existing merge step.

### 3. Minimum number of bursts

- **Rule:** Only emit a runfile line for a group that has **more than one burst**. Single-burst groups are skipped (downstream ISCE steps such as run_07_merge* expect more than one burst).

### 4. Excluded dates

- **Rule:** Dates in a fixed exclusion list (e.g. known bad orbits) are skipped and do not produce any burst2safe line.

## Summary: one SAFE per (date, hash, subswath)

- **Grouping key:** `(date, hash, subswath)` — date from the burst filename (YYYYMMDD), hash from the last segment before `-BURST`, subswath (IW1, IW2, or IW3) from the third segment.
- **Output:** The runfile (e.g. `SLC/run_01_burst2safe`) has **one line per group** that has at least two bursts and is not on an excluded date. Each line is a single `burst2safe ...` command.
- **Result:** You get one `.SAFE` per (date, hash, subswath). For a given date there may be several SAFEs (e.g. one per subswath, or per hash if multiple source SLCs).

## Using the resulting SAFEs with ISCE

- **Sentinel1_TOPS** accepts both `.SAFE` and `.zip` products; the interface is the same. The stack can pass **multiple paths per date** in `dirname` (e.g. two zips or several SAFEs for the same date).
- The existing merge step in topsStack merges subswaths after per-subswath processing. So one SAFE per subswath per date fits the current workflow: each SAFE is unpacked, processed per subswath, and then merged with the others for that date.
- No change is required to the ISCE workflow; only the runfile that lists burst2safe commands is built differently (by date+hash+subswath).

## Script and help

- **Script:** `minsar/scripts/bursts_to_burst2safe_jobfile.py`
- **Usage:**  
  `bursts_to_burst2safe_jobfile.py SLC`  
  (run from the project directory that contains `SLC/` and a `*.template` file)
- **Help:**  
  `bursts_to_burst2safe_jobfile.py --help`

The script creates `SLC/run_01_burst2safe` and (via job submission) the corresponding `.job` files for running burst2safe on the cluster.
