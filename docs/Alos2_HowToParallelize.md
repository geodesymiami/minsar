# ALOS-2 stack without ionosphere correction

Conventional `alosStack` run with ionosphere turned off. `cmd_3.sh` is not used. Each binary product is accompanied by a `.vrt` and a `.xml`.

Run the three scripts from the project directory, in order. Later scripts read products of earlier ones.

```bash
./alos2_cmds/cmd_1.sh
./alos2_cmds/cmd_2.sh
./alos2_cmds/cmd_4.sh
```

Dates are `YYMMDD`. Pairs are `YYMMDD-YYMMDD`. On the Cameroon stack the reference date is `180102`, there are 6 dates and 14 pairs (4 subsequent dates). Looks are 1×14 then 5×2, so the final grid is 5 range looks by 28 azimuth looks.

## Steps

| Step | Program | Runs on | Files produced |
|---|---|---|---|
| 1 | `read_data.py` | all dates, once | `dates/YYMMDD/YYMMDD.track.xml`, `f*_FRAME/s*/YYMMDD.slc.vrt` and `.xml` (virtual SLC; the binary stays in `SLC/`) |
| 2 | `compute_baseline.py` | all secondary dates, once | `baseline/REF-SEC.rmg`, `baseline/baseline_center.txt` |
| 3 | `compute_burst_sync.py` | the stack, once | `burst_synchronization.txt` |
| 4 | `estimate_slc_offset.py` | each secondary date | `dates/SEC/f*_FRAME/s*/cull.off` |
| 5 | `estimate_swath_offset.py` | reference date | `dates/REF/f*_FRAME/mosaic/swath_offset.txt` |
| 6 | `estimate_frame_offset.py` | reference date | `frame_offset.txt` for the reference date |
| 7 | `resample_common_grid.py` | each date | `dates_resampled/YYMMDD/f*_FRAME/s*/YYMMDD.slc` |
| 8 | `mosaic_parameter.py` | all dates, then the reference in `dates_resampled` | `*.frame.xml`, `*.track.xml` |
| 9 | `rdr2geo.py` | reference date | `dates_resampled/REF/insar/REF_1rlks_14alks.lat`, `.lon`, `.hgt`, `.wbd` |
| 10 | `geo2rdr.py` | each secondary date | `dates_resampled/SEC/insar/SEC_1rlks_14alks_rg.off`, `_az.off` |
| 11 | `pair_up.py` | all pairs, once | `pairs/PAIR/f*_FRAME/s*/` symlinks to the two resampled `.slc` files, plus copied `.vrt` and `.xml` |
| 12 | `form_interferogram.py` | each pair | `pairs/PAIR/f*_FRAME/s*/PAIR_1rlks_14alks.int`, `.amp` |
| 13 | `mosaic_interferogram.py` | each pair | `pairs/PAIR/insar/PAIR_1rlks_14alks.int`, `.amp` |
| 14 | `radar_dem_offset.py` | once, using one pair that includes the reference (`180102-180213`) | `dates_resampled/REF/insar/affine_transform.txt` |
| 15 | `rect_range_offset.py` | each secondary date | `dates_resampled/SEC/insar/SEC_1rlks_14alks_rg_rect.off` |
| 16 | `diff_interferogram.py` | each pair | `pairs/PAIR/insar/diff_PAIR_1rlks_14alks.int` |
| 17 | `look_coherence.py` | each pair | `pairs/PAIR/insar/PAIR_5rlks_28alks.amp`, `.cor`, `.phsig`, `diff_PAIR_5rlks_28alks.int` |
| 18 | `look_geom.py` | reference date | `dates_resampled/REF/insar/REF_5rlks_28alks.lat`, `.lon`, `.hgt`, `.wbd`, `.los` |
| 19 | `filt.py` | each pair | `pairs/PAIR/insar/filt_PAIR_5rlks_28alks.int` |
| 20 | `unwrap_snaphu.py` | each pair | `filt_PAIR_5rlks_28alks.unw`, `filt_PAIR_5rlks_28alks_msk.unw`, `.conncomp`, `snaphu.conf` |
| 21 | `geocode.py` | each pair, three inputs, then the reference line-of-sight file once | geocoded coherence, unwrapped phase, masked unwrapped phase, and `REF_5rlks_28alks.los` |

`cmd_1.sh` is steps 1–10. `cmd_2.sh` is steps 11–18. `cmd_4.sh` is steps 19–21. `cmd_3.sh` is one line, `#no pairs for estimating ionosphere.`, and returns immediately.

## Measured parallel run

`parCameroonAlos2D89` on 14 Nov 2026. The date and pair loops had already been backgrounded. Times are wall clock from product mtimes. A parallel step ends when its slowest date or pair finishes. Geocode wrote nothing. `geocode.py` raises `ValueError` on `-bbox /` as soon as it starts, so the chain ends at the last masked unwrap, 14:50:23.

```bash
./alos2_cmds/cmd_1.sh && ./alos2_cmds/cmd_2.sh && ./alos2_cmds/cmd_3.sh && ./alos2_cmds/cmd_4.sh
```

| Script | Wall clock | Clock time |
|---|---|---|
| `cmd_1.sh` | 1 h 14 min | 10:23:49–11:37:34 |
| `cmd_2.sh` | 9 min | 11:37:34–11:46:14 |
| `cmd_3.sh` | none | ionosphere stub |
| `cmd_4.sh` | 3 h 4 min | 11:46:14–14:50:23 |
| chain | 4 h 27 min | 10:23:49–14:50:23 |

A leading `*` is a date or pair loop that can be split across jobs.

| Step | Program | Runs on | Wall clock | Clock time |
|---|---|---|---|---|
| 1 | `read_data.py` | all dates | 1 min 18 s | 10:23:49–10:25:07 |
| 2 | `compute_baseline.py` | all secondary dates | 17 s | 10:25:07–10:25:24 |
| 3 | `compute_burst_sync.py` | the stack | 1 s | 10:25:24–10:25:25 |
| 4 | `estimate_slc_offset.py` | * each secondary date | 17 s | 10:25:25–10:25:42 |
| 5 | `estimate_swath_offset.py` | reference date | 4 min 57 s | 10:25:42–10:30:39 |
| 6 | `estimate_frame_offset.py` | reference date | — | one frame; no `frame_offset.txt` |
| 7 | `resample_common_grid.py` | * each date | 45 min 50 s | 10:30:39–11:16:29 |
| 8 | `mosaic_parameter.py` | all dates, then the reference date | 2 s | 11:16:29–11:16:31 |
| 9 | `rdr2geo.py` | reference date | 12 min 31 s | 11:16:31–11:29:02 |
| 10 | `geo2rdr.py` | * each secondary date | 8 min 32 s | 11:29:02–11:37:34 |
| 11 | `pair_up.py` | all pairs | 3 s | 11:37:34–11:37:37 |
| 12 | `form_interferogram.py` | * each pair | 5 min 36 s | 11:37:37–11:43:13 |
| 13 | `mosaic_interferogram.py` | * each pair | 19 s | 11:42:54–11:43:13 |
| 14 | `radar_dem_offset.py` | one reference pair (`180102-180213`) | 35 s | 11:43:13–11:43:48 |
| 15 | `rect_range_offset.py` | * each secondary date | 21 s | 11:43:48–11:44:09 |
| 16 | `diff_interferogram.py` | * each pair | 44 s | 11:44:09–11:44:53 |
| 17 | `look_coherence.py` | * each pair | 55 s | 11:44:53–11:45:48 |
| 18 | `look_geom.py` | reference date | 26 s | 11:45:48–11:46:14 |
| 19 | `filt.py` | * each pair | 51 s | 11:46:14–11:47:05 |
| 20 | `unwrap_snaphu.py` | * each pair | 3 h 3 min | 11:47:05–14:50:23 |
| 21 | `geocode.py` | * each pair, then the reference date once | — | failed at 14:50:23 |

Unwrap is the long step. All 14 pairs ran together. The first finished at 12:34 (`180508-180717`); the last at 14:50 (`180213-180619`). Resample of all 6 dates together took 46 min. On the serial run that step was about 40 min per date.

The loops were backgrounded with `make_alos2_cmds_parallel.py alos2_cmds` before this run. After the geocode failure, the empty box flag in `cmd_4.sh` was replaced with the template box:

```bash
sed -i 's|-bbox /|-bbox 4.19/4.25/9.158/9.221|g' alos2_cmds/cmd_4.sh alos2_cmds/sections/20_geocode.bash
```

## How to parallelize

The `for` loops in the command files already have a group test. It is commented out. A loop task `i` runs only when

```text
(group_i - 1) * group_n  <=  i  <=  group_n - 1 + (group_i - 1) * group_n
```

`group_i` starts at 1. `group_n` is how many dates or pairs that one job takes, as a contiguous slice of the array at the top of the script (`dates`, `dates2`, or `insarpair`).

Copy one loop into its own script. Set `parallel=1`, `group_n`, and a different `group_i` in each copy. Submit those scripts as separate jobs. Leave the steps that are not inside a loop in a single job.

Do not launch several copies of a whole `cmd_*.sh`. The steps outside the loops would run again in every job.

### Worth splitting

These loops dominate the Cameroon run (6 dates, 14 pairs, one `pvc` node, serial):

| Loop | Cameroon time | Split |
|---|---|---|
| `resample_common_grid.py` | about 40 min per date, 4 h 24 min total | one job per date (`group_n=1`) |
| `geo2rdr.py` | about 8.5 min per secondary date | one job per secondary date |
| `form_interferogram.py` through `mosaic_interferogram.py` | about 4 min per pair to form | one job per pair, form then mosaic |
| `diff_interferogram.py` through `geocode.py` | per pair | one job per pair for steps 16–17 and 19–21 |

`estimate_slc_offset.py` is also per date, but on this stack it finished in about a minute. Leave it serial.

### Keep serial

These steps run once and the next parallel block needs their output:

1. `read_data.py`, `compute_baseline.py`, `compute_burst_sync.py`
2. `estimate_swath_offset.py` and `estimate_frame_offset.py` on the reference date, before any resample
3. `mosaic_parameter.py`, after every date has been resampled
4. `rdr2geo.py` on the reference date, before any `geo2rdr.py`
5. `pair_up.py`, after every `geo2rdr.py`
6. `radar_dem_offset.py`, after the reference pair has been mosaicked, before any `rect_range_offset.py`
7. `look_geom.py` and the final line-of-sight `geocode.py` can run once beside the pair jobs. The pair geocodes need `look_geom.py` only for the shared geometry they do not rewrite.

### Job sequence

1. One job: steps 1–6.
2. One job per date: step 7. Wait until all of them finish.
3. One job: steps 8–9.
4. One job per secondary date: step 10. Wait until all of them finish.
5. One job: step 11.
6. One job per pair: steps 12–13. Wait until the pair that includes the reference (`180102-180213`) has been mosaicked.
7. One job: step 14, then one job per secondary date for step 15. Wait until those finish.
8. One job per pair: steps 16–17 and 19–21. Step 18 can be that same wave or a single extra job.

On a `pvc` node, one resample of these ScanSAR frames is the memory-heavy task. Put one resample in each job. Several pair jobs can share a node after the SLCs exist, because forming one interferogram is much smaller than resampling one date.
