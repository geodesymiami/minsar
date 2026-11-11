# MintPy, MiaplPy, and horizontal/vertical date naming

MintPy and MiaplPy processing directories are named before their final time
series products exist. `horzvert_timeseries.bash` then uses those directories
and the dates actually stored in their HE5 products. These date ranges do not
necessarily match.

## MintPy and MiaplPy processing directories

Both processing-directory functions first calculate:

```text
date_str = YYYYMM_of_first_loaded_SLC_YYYYMM_of_last_loaded_SLC
```

The source is the sorted `merged/SLC/YYYYMMDD` directory list after applying
`miaplpy.load.startDate` and `miaplpy.load.endDate`. Non-date directories are
ignored. The calculation does not inspect the final MintPy or MiaplPy time
series, interferogram network, HE5, or dates rejected later in processing.
`ssaraopt.startDate` and `ssaraopt.endDate` affect the label only indirectly by
controlling which SLC directories are available.

An important current detail is that both `get_miaplpy_dir_name()` and
`get_mintpy_dir_name()` use the `miaplpy.load.*` bounds. MintPy-specific load
or network date limits do not change either directory's `date_str`.

| Template addition | MiaplPy directory | MintPy directory | Date behavior |
|---|---|---|---|
| Empty or `auto` | `miaplpy` | `mintpy` | No date text, although `date_str` is still calculated internally. |
| `date` | `miaplpy_202005_202610` | `mintpy_202005_202610` | Appends the first/last eligible SLC months. |
| `lalo` | `miaplpy_<S>_<N>_<W>_<E>_202005_202610` | `mintpy_<S>_<N>_<W>_<E>_202005_202610` | Appends subset bounds rounded to two decimals, then the SLC months. Each pipeline prefers its own `subset.lalo` and falls back to the other pipeline's value. |
| Custom value, such as `Big1` | `miaplpy_Big1_202005_202610` | `mintpy_Big1_202005_202610` | Appends the literal custom token and the SLC months. |

The controlling keys are `minsar.miaplpyDir.addition` and
`minsar.mintpyDir.addition`. Two optional suffixes are then appended in this
order:

1. `_exMMDD-MMDD` from `ssaraopt.excludeSeason`, based on the template value
   rather than a scan of quarantined SLCs.
2. A product suffix from `minsar.product.suffix`. A literal token becomes
   `_TOKEN`; `coherenceThreshold` becomes the three-digit coherence percentage,
   such as `_065`.

For example:

```text
miaplpy_Big1_202005_202610_ex0101-0630_065
mintpy_202005_202610_ex0101-0630
```

MiaplPy adds a nested network directory such as `network_delaunay_4`,
`network_sequential_3`, or `network_single_reference`. Its number describes a
network parameter, not a date. Processing-directory date labels remain fixed
when later acquisitions are rejected or when the HE5 export becomes stale.

## Horizontal/vertical date sources

| Date text | Example | Inferred from | Meaning |
|---|---|---|---|
| Input MiaplPy directory | `miaplpy_202005_202610` | First and last `merged/SLC/YYYYMMDD` directories that pass `miaplpy.load.startDate` / `miaplpy.load.endDate`, reduced to `YYYYMM` | Source-stack label. It is not recalculated from the final MiaplPy time series or interferogram network. |
| Input LOS HE5 filename | `..._miaplpy_20200515_XXXXXXXX_..._Del4DS.he5` | First and last dates in that HE5; recent last dates may become `XXXXXXXX` when update mode is enabled | Actual range stored in one selected LOS product. Read the internal date dataset to recover an `XXXXXXXX` date. |
| Requested window | `--start-date 20200601 --end-date 20240720` | Command line | Inclusive bounds applied separately to both LOS date lists before ascending/descending pairing. The bounds need not be acquisition dates. |
| Actual decomposition range | `20200617_20240714` | Minimum and maximum dates from the first member of the matched ascending/descending pairs | Dates encoded in horizontal/vertical HE5 filenames and stored in their date datasets. These are actual acquisitions, not requested bounds. |
| Horz/vert product directory | `Tambora/miaplpy_202005_202610_DS/` | The input `mintpy*` / `miaplpy*` directory having the longer date-label span; ties use the first input; dataset token is appended | Source-product label. `--start-date`, `--end-date`, and actual matched dates do not currently affect this directory name. |
| Dataset token | `_DS`, `_filtDS`, or `_PS` | Selected input HE5 basenames | Keeps dataset families in separate product directories and filenames. |
| Corner block | `S0836E11792_..._S0836E11809` | Output `data_footprint` | Spatial footprint, unrelated to dates. |
| QGIS filename | Same stem with `.gpkg` | Corresponding HE5 selected by `--save-qgis` | Date text is inherited unchanged from its HE5. |

`--period START:END` is another way to supply a window. Multiple periods are
combined as a union. If both period and start/end options are supplied, all
resulting intervals are combined; they are not intersected.

## Tambora example

Command:

```bash
horzvert_timeseries.bash TamboraSenA83/miaplpy_202005_202605 TamboraSenD134/miaplpy_202005_202610 --ref-lalo -8.20614 117.97632 --lat-step 0.00015 --save_qgis --dataset DS --submit --queue pvc --start-date 20200601 --end-date 20240720
```

The script selects the newest `network_*` directory by modification time when
the supplied MiaplPy path does not end in `network_*`. For these inputs, it
selects `network_delaunay_4` and the newest non-filtered DS HE5 in each network
directory.

| Stage | A83 | D134 |
|---|---|---|
| Input directory label | `202005_202605` | `202005_202610` |
| Selected DS HE5 internal range | `20200512–20250215` | `20200515–20261030` |
| Dates inside requested bounds | `20200605–20240714` | `20200620–20240717` |
| First/last matched pair | `20200617–20240714` | `20200620–20240717` |

With the current files and default `--intervals 2`, 85 pairs are found. They
have a three-day A83-to-D134 shift. The expected product directory is:

```text
$SCRATCHDIR/Tambora/miaplpy_202005_202610_DS/
```

The expected horizontal and vertical basenames contain:

```text
S1_vert_083_134_miaplpy_20200617_20240714_<corners>_DS.he5
S1_horz_083_134_miaplpy_20200617_20240714_<corners>_DS.he5
```

The corresponding GeoPackages use the same stems and `.gpkg`. The selected
ascending/descending radar and `geo_` LOS products retain their existing
filenames and remain in their input network directories.

The first output date comes from the first input after any automatic input
swap. PlotData swaps only when doing so produces more pairs, so the orbit whose
dates appear in the output name can matter when acquisitions differ by several
days.

## Why ranges differ

The differences are expected under the current naming rules:

1. A MiaplPy directory label describes SLCs eligible for loading, not dates
   surviving into a final HE5.
2. MiaplPy network construction, failed or excluded interferograms, network
   inversion, and an HE5 that was not regenerated after new SLCs arrived can
   all shorten the actual LOS time series.
3. The horizontal/vertical window removes dates outside the requested bounds.
4. Pairing keeps only dates having a counterpart within the shift blocks
   selected by `--intervals`. With the default value `2` for Sentinel-1, the
   searched shifts are `0..+6` and `-1..-6` days.
5. Requested bounds are usually not acquisition dates, so filenames use the
   nearest surviving matched acquisitions rather than the literal bounds.

`--intervals` belongs to the ascending/descending pairing step. It is
independent of MiaplPy's Delaunay temporal and perpendicular baseline
thresholds.

## Recommended naming changes

The current product directory can contain products from different requested
windows. A later run recomputes because the cache fingerprint includes the
window, but old differently named HE5 files can remain beside the new files.
This is correct but easy to misread.

Recommended logic:

1. Keep HE5 filename dates as the exact first/last matched acquisition dates.
2. Add a deterministic requested-window suffix to the product directory, for
   example `miaplpy_202005_202610_DS_win20200601_20240720`.
3. Put `image_pairs_DS.txt` in that product directory instead of the shared
   site directory, where another window currently overwrites it.
4. Write a small provenance file in the product directory containing the two
   selected input HE5 paths, their internal date ranges, requested bounds,
   actual matched range, pair count, pairing shifts, and whether inputs were
   swapped.
5. Print the requested and actual ranges together before submission and after
   pairing.
6. Validate date syntax and reject a start date later than the end date.

The requested-window suffix is preferable to deriving the directory from
actual matched dates: it is known before the batch job runs, gives each cache a
stable location, and still lets exact acquisition dates remain authoritative
in the HE5 filenames and provenance file.

## Delaunay thresholds

Do not change MiaplPy thresholds solely to make names agree. The standard
automatic Delaunay values are a baseline ratio of 4, temporal threshold of 120
days, and perpendicular threshold of 200 m. `network_delaunay_4` records the
ratio, not the actual date coverage.

Before changing thresholds, compare:

- dates in `slcStack.h5` with dates in the DS HE5;
- the generated Delaunay pair list and its connected components;
- failed or missing unwrapping products;
- dropped interferograms and excluded acquisitions in `ifgramStack.h5`; and
- whether the HE5 export was rerun after the newest MiaplPy steps.

Increase a threshold only when those diagnostics show otherwise valid
acquisitions are disconnected specifically by that limit. A denser network
costs more unwrapping time and can add low-quality long-baseline
interferograms; it does not improve horizontal/vertical date matching when the
required LOS acquisitions are already present.
