# Plan: EGMS granule listing / download

## Status

**Implemented 2026-07-20.** Script: [`minsar/scripts/egms_download.py`](egms_download.py).

| Item | Status |
|------|--------|
| CLMS JWT auth via `password_config.clms_service_key` (path to JSON service key) | Done |
| Standalone token refresh: `clms_get_access_token.py` + `minsar/utils/clms_auth.py` | Done |
| `--aoi` accepts S:N,W:E and WKT POLYGON; `--intersectsWith` alias | Done |
| `--print` list granules; `--download` / `--dir`; `--level` default L2A | Done |
| Default `--releases` = latest from API `/releases` | Done |
| Unit tests (mocked API) | Done (`minsar/scripts/tests/test_egms_download.py`) |
| Docs: `docs/accounts_info.md`, `architecture_docs/FILE_STRUCTURE.md` | Done |
| `PyJWT` in `pip_requirements.txt`; `minsar/scripts/tests` in `run_all_tests.bash` | Done |

## Usage

```bash
egms_download.py --aoi="37.525:37.825,15.050:15.210" --print
egms_download.py --aoi="Polygon((14.75 37.51, 15.25 37.51, 15.25 37.88, 14.75 37.88, 14.75 37.51))" --print
egms_download.py --intersectsWith="Polygon((14.75 37.51, 15.25 37.51, 15.25 37.88, 14.75 37.88, 14.75 37.51))" --print
egms_download.py --aoi="37.525:37.825,15.050:15.210" --level L2A --download --dir=./egms
```

## Setup

1. Create a CLMS API token at [land.copernicus.eu](https://land.copernicus.eu) (profile → API Tokens); save the one-time JSON as e.g. `~/accounts/clms_service_key.json`.
2. In `$SSARAHOME/password_config.py`:
   ```python
   clms_service_key="/path/to/clms_service_key.json"
   ```
3. `pip install PyJWT` if needed.

Auth is **not** `tsxuser`/`tsxpass`. Listing and downloading both need the CLMS service key.

## Summary

CLI to search and download European Ground Motion Service products via  
`https://egms.land.copernicus.eu/insar-api/archive` (CLMS Bearer token from JWT service key).

AOI → `_input_to_bounds` → EGMS `bbox` (max 5° span). Search requires `levels` + `releases`.

## Related (not this work)

- Insarmaps ingest of downloaded EGMS CSV: [`minsar/insarmaps_utils/PLAN_EGMS_insarmaps_ingest_DONE_2026-07-20.md`](../insarmaps_utils/PLAN_EGMS_insarmaps_ingest_DONE_2026-07-20.md)
