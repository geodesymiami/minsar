# `--start-date` and `--end-date`

Accepted forms are `YYYYMMDD` and `YYYY-MM-DD`. A flag that is present is applied. The omitted side stays open. What "open" means depends on the command, and is listed below.

Directory names such as `miaplpy_YYYYMM_YYYYMM` are not the literal bounds. They are the first and last SLC months that pass `miaplpy.load.startDate` / `miaplpy.load.endDate`. That naming, and how it differs from horizontal/vertical HE5 dates, is in [HORZVERT_DATE_NAMING.md](HORZVERT_DATE_NAMING.md).

`--start` is a processing step (`download`, `miaplpy`, …). It is not a date.

## Stack window

These commands set the acquisition window used for search, download, and MiaplPy loading.

| Command | Given flag | Omitted side |
| --- | --- | --- |
| `minsarApp.bash` on an existing template | Writes `ssaraopt.startDate` or `endDate` and the matching `miaplpy.load.*` date | `auto` |
| `create_template.py` | Same two pairs in the new template. Concrete dates are also passed to `get_sar_coverage.py --select` and `create_opposite_orbit_template.bash` | `auto` on the template keys. `get_sar_coverage.py` fills its own open side (below) |
| `get_sar_coverage.py` | Discovery, acquisition counts, and the Vertex URL all use the filled window | S1 start `2016-01-01`, end today. NISAR start `2026-01-01`. ALOS-2 start `2020-01-01`, end `2022-12-31` |
| `create_opposite_orbit_template.bash` | Forwarded to `get_sar_coverage.py --select` | Not sent, so `get_sar_coverage.py` fills it |

`ssaraopt` `auto` is expanded at download time: start becomes `20010101`, end becomes today (`correct_for_ssara_date_format`). `miaplpy.load` `auto` means no clip: every `merged/SLC/YYYYMMDD` directory is eligible.

`--period`, `--quick-run`, and `--last-year` on `create_template.py` set both sides. They write the same `ssaraopt` and `miaplpy.load` keys. They cannot be combined with `--start-date` / `--end-date`.

With neither date flag, `get_sar_coverage.py` keeps a split default: S1 discovery starts `2016-01-01`, while counts and the catalog window start `2014-10-01`. `--startDate` / `--endDate` (no hyphen) adjust only that count window, and only when `--start-date` / `--end-date` are absent.

### `minsarApp.bash`

On a template that already exists:

```bash
minsarApp.bash $TE/TamboraSenD134.template --start-date 20240101 --start miaplpy
```

That writes `ssaraopt.startDate = 20240101`, `ssaraopt.endDate = auto`, `miaplpy.load.startDate = 20240101`, and `miaplpy.load.endDate = auto` before the directory name is chosen. The MiaplPy directory then starts at the first SLC on or after `20240101` and runs through the latest SLC on disk. Both flags together keep both bounds.

AOI mode (`minsarApp.bash AOI NAME …`) sends `--start-date` / `--end-date` to `create_template.py`, which writes the same keys. The later template run does not need the flags again.

`--miaplpy.load.startDate` and `--miaplpy.load.endDate` still set only the load window (YYYYMMDD). They do not change `ssaraopt`. If one of those is combined with `--start-date` or `--end-date`, the two values must be the same date.

## Other commands that honor the flags

A given flag replaces that side for that run. An omitted flag keeps the command's own fallback. These do not rewrite `miaplpy.load`.

| Command | Given flag | Omitted side |
| --- | --- | --- |
| `create_isce3_runfiles.py`, `minsarIsce3App.bash` | Overrides `ssaraopt.startDate` / `endDate` for that run | Template `ssaraopt` value |
| `generate_disp-s1_commands.py` | Same override | Template `ssaraopt` value (`auto` already expanded) |
| `generate_sweets_config.py` | Date on the `sweets config` line. `--start` / `--end` are aliases here | Start `2014-10-01`, end today. The template date keys are not read |
| `horzvert_timeseries.bash` | Inclusive filter on the LOS date lists before ascending/descending pairing | No extra clip on that side |

`horzvert_timeseries.bash` does not change the MiaplPy or MintPy directory label. See [HORZVERT_DATE_NAMING.md](HORZVERT_DATE_NAMING.md).

## `asf_search_args.py`

`--start-date` and `--end-date` (and `--start` / `--end`) are ASF search options. They are passed through to ASF. They are not copied onto MinSAR template keys.

## MintPy

There is no `mintpy.load.startDate`, no `mintpy.load.endDate`, and no MintPy date flag on `minsarApp.bash`. `get_mintpy_dir_name()` uses the same `miaplpy.load.*` window as `get_miaplpy_dir_name()`, so a `--start-date` that sets `miaplpy.load.startDate` also changes a `mintpy_YYYYMM_YYYYMM` directory.

`mintpy.plot` is a separate yes/no choice. `create_template.py` sets it from the `ssaraopt` span (yes when that span is 365 days or less). `--mintpy-plot` and `--mintpy-no-plot` override that. It does not select which dates are loaded.
