# Plan: EGMS L2a → Insarmaps ingest

## Status

**Implemented 2026-07-20** (core path). Example data: `/data/HDF5EOS/egmsEtnaSenA44/egms/`.

| Item | Status |
|------|--------|
| `latitude`/`longitude` candidates (case-insensitive) in converter + `insarmaps_csv_geo.py` | Done |
| `egms_metadata.py` — XML + filename + track_angle helpers | Done |
| `egms2insarmaps.py` — convert → patch metadata → upload | Done |
| Optional quality: `temporal_coherence`→coherence, `height_ortho`→elevation, `pid`→point_ID | Done (in converter) |
| Unit tests | Done (`minsar/insarmaps_utils/tests/test_egms_metadata.py`) |
| Full 1 GB Etna upload | Operational (run manually; use `--num-workers 1`) |

## Usage

```bash
egms2insarmaps.py /data/HDF5EOS/egmsEtnaSenA44/egms/EGMS_L2a_044_0221_IW2_VV_2020_2024_1.csv --num-workers 1
egms2insarmaps.py EGMS_L2a_044_0221_IW2_VV_2020_2024_1.csv --step 1 --num-workers 1
egms2insarmaps.py EGMS_L2a_044_0221_IW2_VV_2020_2024_1.csv --step 2
egms2insarmaps.py EGMS_L2a_044_0221_IW2_VV_2020_2024_1.csv --skip-upload
egms2insarmaps.py EGMS_L2a_044_0221_IW2_VV_2020_2024_1.csv --flight-direction A --relative-orbit 44
```

Steps (same idea as `ingest_insarmaps.bash`):

| Flag | Effect |
|------|--------|
| (default) | Step 1 then step 2 |
| `--step 1` / `--hdfeos5_2json_mbtiles` / `--skip-upload` | CSV → JSON/MBTiles + metadata patch only |
| `--step 2` / `--json_mbtiles2insarmaps` | Upload only (requires prior step 1) |

Warn: ~1 GB CSV needs enough RAM; prefer `--num-workers 1`.

## Summary

Gap analysis for ingesting EGMS L2a CSV into insarmaps via `hdfeos5_or_csv_2json_mbtiles.py` plus orchestrator `egms2insarmaps.py`. Hard blocker was lowercase lat/lon column names; metadata enriched from companion XML / filename / CLI.

## Dataset facts

Path (note: directory is `/Users/famelung/scratch/Etna/`, not `Etna[513]`):

- `EGMS_L2a_044_0221_IW2_VV_2020_2024_1.csv` (~1.05 GB)
- companion `..._1.xml`

**Yes, it has a burst ID — but EGMS-specific, not ESA/ASF:**

| Field | Value | Source |
|-------|-------|--------|
| track (relative orbit) | `044` | XML `<track>`, filename |
| burst_id | `0221` | XML `<burst_id>` — *progressive index within track* (EGMS), not ESA 6-digit burst ID |
| sub_swath | `2` (IW2) | XML `<sub_swath>`, filename |
| orbit sense | **Ascending** | constant CSV `track_angle≈349.61°`; SLC sensing times ~16:56 UTC |

XML also lists hundreds of source `S1A/S1B_IW_SLC__...` `product_id`s. To pull SAFE/burst metadata you would download one of those SLCs (or use MintPy/MiaplPy for track 44), **not** treat `0221` as an ESA burst ID.

CSV already has usable geometry/time series:

- `latitude`, `longitude` (lowercase)
- date columns `YYYYMMDD` (211 dates, `20200104`–`20241226`) — displacements in **mm** (converter divides by 1000 → m)
- per-point `incidence_angle`, `track_angle`, `mean_velocity`, `temporal_coherence`, `height_ortho`, etc.

## How the converter works today

`tools/insarmaps_scripts/hdfeos5_or_csv_2json_mbtiles.py` CSV path (`read_from_csv_file`):

```python
lat_candidates = ["Y_geocorr", "Latitude", "Y", "ycoord"]
lon_candidates = ["X_geocorr", "Longitude", "X", "xcoord"]
...
if lat_col is None or lon_col is None:
    raise ValueError(...)
```

Date handling already accepts bare `YYYYMMDD` columns (non-SARvey branch) and scales mm→m.

`needed_attributes` (insarmaps DB popup/title fields) is large; CSV path fills some, then `add_dummy_attribute` injects **Galapagos placeholders** for the rest. Missing keys are simply omitted from the uploaded attribute list (not a hard crash).

`enrich_attributes_from_csv_filename` may fill mission/orbit from stems like `S1_044_...`. EGMS names do not match that pattern; use XML/CLI via `egms2insarmaps.py` instead.

## Hard blocker (must change code or rename columns)

| Issue | EGMS has | Converter expects |
|-------|----------|-------------------|
| Lat/lon names | `latitude`, `longitude` | `Latitude`/`Longitude` (or Y/X / geocorr) |

**Without this fix, ingest fails immediately** with `Could not find latitude/longitude columns`.

Same candidate lists are duplicated in `minsar/insarmaps_utils/insarmaps_csv_geo.py` / zoom helpers — keep them in sync.

Workaround without code: rename header columns to `Latitude`,`Longitude` (awkward for a 1 GB file). Prefer code fix.

## Attributes: present / auto-filled / missing / wrong dummies

```mermaid
flowchart LR
  egmsCsv[EGMS CSV plus XML]
  reader[read_from_csv_file]
  jsonMb[JSON plus mbtiles]
  upload[json_mbtiles2insarmaps]
  egmsCsv --> reader --> jsonMb --> upload
```

**Already OK or auto-computed from CSV**

- Time series dates, displacements (mm→m)
- `WIDTH`/`LENGTH` (fake grid reshape), `REF_LAT`/`REF_LON`, `first_date`/`last_date`, `history`
- `data_footprint` / `scene_footprint` from point bbox
- `processing_type`, `look_direction=R`, `mission`/`PLATFORM` default `S1`
- `data_type` = LOS Displacement (filename has no `VERT`)

**Missing for correct Insarmaps title/metadata (give manually or derive)**

These are the ones that matter for display naming (see `sarvey2insarmaps.merge_into_metadata_pickle`):

| Attribute | EGMS-derived value | How |
|-----------|-------------------|-----|
| `relative_orbit` | `44` | XML `<track>` / filename `_044_` |
| `flight_direction` / `ORBIT_DIRECTION` | `A` / ASCENDING | `track_angle≈350°` or SLC time ~1656Z |
| `beam_mode` | `IW` | known S1 IW; dummy already `IW` |
| `beam_swath` | `2` | XML `<sub_swath>` (dummy wrongly sets `1`) |
| `CENTER_LINE_UTC` | ~`60800` (16:56:xx) | from any XML `product_id` sensing time, or MintPy `CENTER_LINE_UTC` |
| `wavelength` | `0.05546576` | S1 C-band (dummy already correct) |

**Present in EGMS but ignored by converter (optional quality popup fields)**

- `temporal_coherence`, `mean_velocity`, `height_ortho`/`height_ellipse`, `incidence_angle`, `pid` — quality map only wires `dem_error`/`coherence`/`omega`/`st_consist`/`point_ID`

**Filled with misleading Galapagos dummies (harmless if overwritten; wrong if left)**

- `first_frame`/`last_frame` (556/557), hardcoded `scene_footprint` (overwritten by real bbox), `prf`, `processing_software=isce`, `post_processing_method=MintPy`
- Prefer setting `post_processing_method=EGMS` (or similar) and `PROJECT_NAME` from stem instead of `CSV_IMPORT`

**Not required to ingest (often omitted)**

- `min_baseline_perp`, `max_baseline_perp`, `unwrap_method`, `frame`, `downloadUnavcoUrl`, `referencePdfUrl`, `areaName`, `referenceText`, `insarmaps_download_flag`, `mintpy.subset.lalo`, `X_STEP`/`Y_STEP`/`X_FIRST`/`Y_FIRST` (dropped in high-res/CSV mode)

## Burst / MintPy metadata path

- **EGMS `burst_id=0221`**: track-local progressive index; do **not** use directly as ESA/ASF burst ID for download.
- **Practical SAFE path**: download one XML-listed SLC (e.g. `S1A_IW_SLC__1SDV_20200110T165613_...`) and read IW2 burst annotation for heading / `CENTER_LINE_UTC` / orbit direction — redundant if you already accept A + track 44 from CSV/XML.
- **MintPy/MiaplPy path**: if you have track-44 Etna products, copy `ORBIT_DIRECTION`, `CENTER_LINE_UTC`, `RELATIVE_ORBIT`, `WAVELENGTH`, etc. from `.he5`. No Etna track-44 stack was found under `/Users/famelung/scratch` in a quick search; confirm your project path if you want that wired in.

## Recommended modifications (concrete approach)

Target: `tools/insarmaps_scripts/hdfeos5_or_csv_2json_mbtiles.py` (nested repo) + sync lat/lon candidates in `minsar/insarmaps_utils/insarmaps_csv_geo.py`.

1. **Lat/lon**: add case-insensitive match (or add `latitude`/`longitude` to candidates).
2. **EGMS XML sidecar**: if `same_stem.xml` exists, set `relative_orbit`, `beam_swath`, optional burst tag for naming; set `flight_direction` from mean `track_angle` (e.g. >270 or <90 → A, else D) or from first `product_id` hour.
3. **Filename fallback**: parse `EGMS_L2a_(\d+)_(\d+)_IW(\d)_`.
4. **CLI overrides** (manual fill): `--flight-direction A|D`, `--relative-orbit`, `--center-line-utc`, `--project-name`, `--post-processing-method` — only these; do not expand dummy list further.
5. **Quality (optional, small)**: map `temporal_coherence`→coherence-like popup; `height_ortho`→elevation; skip full velocity overlay unless requested.
6. **Docs**: note EGMS ingest in architecture / insarmaps README; warn ~1 GB CSV needs low `--num-workers` / enough RAM.
7. **Tests**: unit-test lat/lon detection + XML/filename attribute enrichment on a tiny fixture CSV/XML (not the 1 GB file).

**Manual values sufficient for a first Etna upload (if XML parse not done yet):**

```text
relative_orbit=44
flight_direction=A
beam_mode=IW
beam_swath=2
mission=S1
wavelength=0.05546576
CENTER_LINE_UTC=60800   # approx from 16:56 UTC
post_processing_method=EGMS
```

**Ingest command shape (after lat/lon fix):**

```bash
hdfeos5_or_csv_2json_mbtiles.py \
  /Users/famelung/scratch/Etna/EGMS_L2a_044_0221_IW2_VV_2020_2024_1.csv \
  /Users/famelung/scratch/Etna/JSON --num-workers 2
# then json_mbtiles2insarmaps / ingest_insarmaps.bash step 2
```

## Out of scope unless requested

- Full ESA burst download automation
- Wiring MintPy `.he5` attribute copy (needs your Etna project path)
- Changing displacement units (already mm→m)
- Subsetting the 1 GB CSV before ingest (advisable operationally, separate task)
