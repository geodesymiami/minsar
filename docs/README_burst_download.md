# Burst download and burst2safe

This document describes how MinSAR builds **burst2safe** commands when using the **ASF burst** download path: downloading Sentinel-1 burst SLCs (`.tiff`), then converting them to ESA SAFE format so the rest of the stack (ISCE topsStack) can run unchanged.

## Overview

- **Download:** Bursts are downloaded (e.g. via `download_asf_burst.sh`) into a burst directory (typically `SLC/`) as `*BURST.tiff` files.
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

## Script and help

- **Script:** `minsar/scripts/bursts_to_burst2safe_jobfile.py`
- **Usage:**  
  `bursts_to_burst2safe_jobfile.py SLC`  
  (run from the project directory that contains `SLC/` and a `*.template` file)
- **Help:**  
  `bursts_to_burst2safe_jobfile.py --help`

The script creates `SLC/run_01_burst2safe` and (via job submission) the corresponding `.job` files for running burst2safe on the cluster.
