# Plan: EGMS granule listing / download

## Status

**Updated 2026-07-21.** Search: [`egms_search.py`](egms_search.py). Wrapper: [`egms_download.bash`](egms_download.bash).  
Downloads via **curl** (`--write-curl` / bash); local filters after a minimal API search.

| Item | Status |
|------|--------|
| CLMS JWT auth via `password_config.clms_service_key` / `~/accounts/clms_service_key.json` | Done |
| `clms_get_access_token.py` + `minsar/utils/clms_auth.py` | Done |
| `egms_search.py`: `--print`, `--json-out`, `--write-curl` | Done |
| `filter_egms_hits.py`: local orbit/swath/direction filter | Done |
| `egms_download.bash`: search → filter → print/download; `--parallel` default 1 | Done |
| `test_egms_search_options.py`: live option timing TSV (not CI) | Done |
| Unit tests | Done (`test_egms_search.py`, `test_filter_egms_hits.py`) |

## Usage

```bash
egms_search.py --aoi="37.51:37.88,15.15:15.16" --releases 2020-2024 --json-out egms_hits.json --print
egms_download.bash --aoi='37.51:37.88,15.15:15.16' --releases=2020-2024 --swath=IW2 --relativeOrbit=44 --print
egms_download.bash --aoi='37.51:37.88,15.15:15.16' --releases=2020-2024 --swath=IW2 --relativeOrbit=44 --download --dir=./egms
egms_download.bash --aoi='37.51:37.88,15.15:15.16' --releases=2020-2024 --download --parallel=1
egms_download.bash --aoi='37.51:37.88,15.15:15.16' --releases=2020-2024 --download --no-unzip
test_egms_search_options.py --timeout 45 -o egms_search_options_report.tsv
```

**First-layer API args (provisional):** AOI + `--level` + `--releases` only.  
**Local filters:** `--relativeOrbit`, `--swath`, `--direction`.  
**After download:** unzip into `--dir` by default (`--no-unzip` to skip).

## Setup

1. CLMS API token → `~/accounts/clms_service_key.json`
2. Optional: `clms_service_key="..."` in `password_config.py`
3. `pip install PyJWT` if needed

## Related

- Insarmaps ingest: [`minsar/insarmaps_utils/PLAN_EGMS_insarmaps_ingest_DONE_2026-07-20.md`](../insarmaps_utils/PLAN_EGMS_insarmaps_ingest_DONE_2026-07-20.md)
