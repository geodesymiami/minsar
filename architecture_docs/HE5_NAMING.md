# HDF-EOS5 (`.he5`) output naming

MinSAR uses MintPy’s `save_hdfeos5.py` (`additions/mintpy/save_hdfeos5.py`) for both **MintPy** and **MiaplPy** radar HE5 exports. Naming is built in **`get_output_filename()`** from stack metadata plus template flags.

## Base pattern

```text
{mission}_{asc|desc}_{orbit}_{method}_{start}_{end}[_{corners}][_{suffix}].he5
```

| Token | Source |
|-------|--------|
| `mission` | `sensor.get_unavco_mission_name()` → e.g. `S1` |
| `asc` / `desc` | `get_orbit_direction_str()` from `ORBIT_DIRECTION` or `HEADING` |
| `orbit` | `relative_orbit`, zero-padded 3 digits → `124` |
| `method` | `post_processing_method` lowercased → `mintpy`, `miaplpy`, or `sarvey` (SARvey Insarmaps ingest) |
| `start` | first acquisition date → `YYYYMMDD` |
| `end` | last acquisition date → `YYYYMMDD` or `XXXXXXXX` (see below) |
| `corners` | optional subset footprint (see below) |
| `suffix` | optional dataset tag (MiaplPy PS/DS; CLI `--suffix`) |

**Functions:** `prep_metadata()` → `metadata_mintpy2unavco()` → `get_output_filename()` → `write_hdf5_file()`.

`post_processing_method` comes from input metadata when set; otherwise inferred from cwd / geometry path (`miaplpy` → `MiaplPy`, else `MintPy`).

## Template flags (`mintpy.save.hdfEos5.*`)

| Key | Effect |
|-----|--------|
| `mintpy.save.hdfEos5.update = yes` | **Update mode:** if last SAR date is ≤ **31 days** before today, `end` → `XXXXXXXX`; else real `YYYYMMDD`. Logic: `use_x_placeholder_for_update()`. |
| `mintpy.save.hdfEos5.subset = yes` | **Subset mode:** insert corner string from `data_footprint` WKT via `polygon_corners_string()`. |

Both are read in `read_template2inps()` and passed to `get_output_filename()`.

## Corner / subset suffix

When `subset = yes`, four footprint corners are encoded as:

```text
_N01314E12362_N01317E12378_N01333E12375_N01330E12360
```

- Lat: `N`/`S` + 4 digits (abs lat × 100, rounded)
- Lon: `E`/`W` + 5 digits (abs lon × 100, rounded)
- Order: polygon vertices CCW from SW (from `data_footprint` WKT)

Corners are inserted **before** the optional dataset suffix:

```text
…_{start}_{end}_{corners}_{suffix}.he5
```

## MintPy vs MiaplPy

**MintPy** (step in `smallbaselineApp.py`): one HE5 per run, usually **no** `--suffix`.

```text
S1_desc_124_mintpy_20141031_20151231_N0151W07849_…_N0034W07849.he5
S1_desc_124_mintpy_20140904_20240904_XXXXXXXX.he5          # update mode, recent stack
```

**MiaplPy** (step 10 via `save_miaplpy_hdfeos5.bash`): three parallel `save_hdfeos5.py` calls with `--suffix` from network type (`get_network_prefix()` on `network_*` dirname):

| Network dir | Prefix | Suffix examples |
|-------------|--------|-----------------|
| `network_delaunay_4` | `Del4` | `Del4PS`, `Del4DS`, `filtDel4DS` |
| `network_single_reference` | `Sing` | `SingPS`, `SingDS`, `filtSingDS` |
| `network_sequential_N` | `SeqN` | `SeqNPS`, … |

```text
S1_asc_069_miaplpy_20141010_20180104_N1314E12362_…_filtDel4DS.he5
S1_asc_142_miaplpy_20250414_XXXXXXXX_filtDel4DS.he5          # short (no corners)
S1_asc_142_miaplpy_20250414_XXXXXXXX_N1397E12097_…_filtDel4DS.he5   # with corners
```

Filtered DS uses prefix `filt` + network prefix: `--suffix "filt${prefix}DS"`.

## Geocoded HE5

`geocode_hdfeos5.py` writes sibling files with **`geo_`** prepended to the radar basename:

```text
geo_S1_desc_124_miaplpy_20141010_20180104_…_filtDel4DS.he5
```

Aux products under `geo/` from `geocode.py` use `geo_` prefix on `.h5` names (separate from HE5 export).

## Update mode: short vs long names

With `--update`, reruns often write a **short** basename (no corner block). If a **long** corner-suffix file already exists, `hv_promote_short_he5_to_corner_filename()` in `minsar/lib/horzvert_timeseries_utils.sh` moves the newer short file onto the long path so InsarMaps / horzvert keep a stable filename.

MintPy short forms may include `…_mintpy_YYYYMMDD_XXXXXXXX.he5` or `…_XXXXXXXX_XXXXXXXX.he5` before promotion.

## Related entry points

| Script | Role |
|--------|------|
| `save_hdfeos5.py` | Build radar `.he5` name and write file |
| `save_miaplpy_hdfeos5.bash` | MiaplPy step 10: PS/DS/filtDS + geocode aux |
| `create_save_hdfeos5_jobfile.py` | SLURM job for step 10 |
| `reference_point_hdfeos5.bash` | Re-reference in-memory; may write short name |
| `geocode_hdfeos5.py` | `geo_` + radar basename |
| `extract_hdfeos5.py` | Reverse export (not naming) |
| `sarvey2insarmaps.py` | SARvey CSV/MBTiles ingest; same base pattern via `get_output_filename()`, corners always from CSV bbox |

Horz/vert products (`*vert*.he5`, `*horz*.he5`) use a separate pipeline in `horzvert_timeseries.bash`, not the patterns above.
