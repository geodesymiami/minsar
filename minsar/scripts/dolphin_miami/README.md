# Miami Dolphin workflow

Scripts to download Miami CSLC data from ASF and process with [Dolphin](https://github.com/isce-framework/dolphin) (PS/DS InSAR).

**Area:** `miaplpy.subset.lalo = 25.765:25.98,-80.147:-80.1146` (S:N, W:E)

## 1. Install Dolphin

```bash
cd "$(dirname "$0")"
bash install_dolphin.bash
# Optional: --install-dir /path/to/dolphin
```

Creates conda env `dolphin-env` and installs dolphin from GitHub. Then:

```bash
conda activate dolphin-env
```

## 2. Download CSLC data for Miami (2025)

Uses minsar’s `asf_search_args.py` (requires `asf_search`; use minsar conda env or install `asf_search`).

```bash
# From repo root or set MINSAR_ROOT to the minsar package root (dir containing src/ and scripts/)
conda activate minsar   # or env with asf_search
bash minsar/scripts/dolphin_miami/download_miami_cslc.bash

# Options:
#   --start 2025-01-01  --end 2025-12-31
#   --dir /path/to/CSLC
#   --parallel 4
#   --print-only   # search only, no download
```

After download, unzip any ASF product zips into the CSLC directory so GeoTIFF/HDF5 files are in (or under) that directory.

## 3. Run Dolphin

```bash
conda activate dolphin-env
bash minsar/scripts/dolphin_miami/run_dolphin_miami.bash

# Options:
#   --cslc-dir /path/to/CSLC
#   --work-dir /path/to/dolphin_miami
#   --config-only   # only write dolphin_config.yaml
```

Outputs go to the work directory (default `./dolphin_miami`).
