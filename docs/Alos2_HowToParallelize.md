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

| Step | Program | Parallelizable | Runs on | Wall clock |
|---|---|---|---|---|
| 1 | `read_data.py` | no | all dates | 1 min 18 s |
| 2 | `compute_baseline.py` | no | all secondary dates | 17 s |
| 3 | `compute_burst_sync.py` | no | the stack | 1 s |
| 4 | `estimate_slc_offset.py` | yes | each secondary date | 17 s |
| 5 | `estimate_swath_offset.py` | no | reference date | 4 min 57 s |
| 6 | `estimate_frame_offset.py` | no | reference date | — |
| 7 | `resample_common_grid.py` | yes | each date | 45 min 50 s |
| 8 | `mosaic_parameter.py` | no | all dates, then the reference date | 2 s |
| 9 | `rdr2geo.py` | no | reference date | 12 min 31 s |
| 10 | `geo2rdr.py` | yes | each secondary date | 8 min 32 s |
| 11 | `pair_up.py` | no | all pairs | 3 s |
| 12 | `form_interferogram.py` | yes | each pair | 5 min 36 s |
| 13 | `mosaic_interferogram.py` | yes | each pair | 19 s |
| 14 | `radar_dem_offset.py` | no | one reference pair (`180102-180213`) | 35 s |
| 15 | `rect_range_offset.py` | yes | each secondary date | 21 s |
| 16 | `diff_interferogram.py` | yes | each pair | 44 s |
| 17 | `look_coherence.py` | yes | each pair | 55 s |
| 18 | `look_geom.py` | no | reference date | 26 s |
| 19 | `filt.py` | yes | each pair | 51 s |
| 20 | `unwrap_snaphu.py` | yes | each pair | 3 h 3 min |
| 21 | `geocode.py` | yes | each pair, then the reference date once | — |

Unwrap is the long step. All 14 pairs ran together. The first finished at 12:34 (`180508-180717`); the last at 14:50 (`180213-180619`). Resample of all 6 dates together took 46 min. On the serial run that step was about 40 min per date.

The loops were backgrounded with `make_alos2_bash_cmds_parallel.py alos2_cmds` before this run. After the geocode failure, the empty box flag in `cmd_4.sh` was replaced with the template box:

```bash
sed -i 's|-bbox /|-bbox 4.19/4.25/9.158/9.221|g' alos2_cmds/cmd_4.sh alos2_cmds/sections/20_geocode.bash
```

## Run files

Each run file is one job. The next run file starts after every line in the current file has finished. A line is one date or one pair. Programs that share that date or pair are one line, joined with `&&`. A task that changes directory more than once is a bash file, and the run-file line calls it:

```bash
bash run_files/tasks/run_16_geocode_180102-180213.bash
```

Most run files go to `skx-dev`: 2 hour limit, 15 nodes per job, 2 jobs per user. One job holds every line of the run file. Resample is one date per node. Unwrap requests more than 2 hours and runs on `pvc`. On this stack the slowest unwrap was 3 h 3 min (`180213-180619`); the fastest was about 47 min (`180508-180717`).

`look_geom.py` reads the 1-look reference geometry from step 9 and writes `180102_5rlks_28alks.lat`, `.lon`, `.hgt`, `.los`, and `.wbd`. Steps 16, 17, and 19 do not read those files. The Cameroon `filt.py` command has no `-wbd_msk`. `unwrap_snaphu.py` is called with `-wbd_msk` and reads `180102_5rlks_28alks.wbd`, so `run_13_look_geom` finishes before `run_15_unwrap`. The reference line-of-sight geocode reads `180102_5rlks_28alks.los`, so it also waits for `run_13_look_geom`. Pair geocodes use the track XML, the DEM, and the pair file, and wait for unwrap.

Step 14 runs once, after `180102-180213` has been mosaicked. Step 15 is one line per secondary date, and every date finishes before any step 16.

| Run file | Steps | Lines | Wall clock |
|---|---|---|---|
| `run_01_read_baseline_burst` | 1 `&&` 2 `&&` 3 | 1 | 1.5 min |
| `run_02_estimate_slc_offset` | 4 | each secondary date | 17 s |
| `run_03_estimate_swath_frame_offset` | 5 `&&` 6 | 1 | 5 min |
| `run_04_resample_common_grid` | 7 | each date | 40 min per date |
| `run_05_mosaic_rdr2geo` | 8 `&&` 9 | 1 | 13 min |
| `run_06_geo2rdr` | 10 | each secondary date | 9 min |
| `run_07_pair_up` | 11 | 1 | 3 s |
| `run_08_form_interferogram` | 12 | each pair | 6 min |
| `run_09_mosaic_interferogram` | 13 | each pair | 19 s |
| `run_10_radar_dem_offset` | 14 | 1 | 35 s |
| `run_11_rect_range_offset` | 15 | each secondary date | 21 s |
| `run_12_diff_look_filt` | 16 `&&` 17 `&&` 19 | each pair | under 3 min |
| `run_13_look_geom` | 18 | 1 | 26 s |
| `run_14_geocode_los` | 21, reference line-of-sight | 1 | — |
| `run_15_unwrap` | 20 | each pair | 3 h 3 min |
| `run_16_geocode` | 21, three commands `&&` | each pair | — |

Wall clock is from the measured run. For a loop, it is the slowest date or pair. `run_12_diff_look_filt` is the sum of the three loop times, which is longer than one pair. `run_14_geocode_los` and `run_16_geocode` wrote nothing.

## Unwrapping with whirlwind

Whirlwind is the default unwrapper (`alos2Stack.unwMethod = auto` or `whirlwind`; set `snaphu` for the stock `unwrap_snaphu.py`). `run_15_unwrap` then calls `unwrap_whirlwind.py` (MinSAR addition, `additions/isce2/contrib/stack/alosStack/`) in place of `unwrap_snaphu.py`. It takes the same arguments and writes the same files (`filt_PAIR_*.unw`, `filt_PAIR_*_msk.unw`, `.conncomp`), so geocode and MintPy are unchanged. It uses [whirlwind-insar](https://github.com/scottstanie/whirlwind-insar) with the `.phsig` file as coherence. For Sentinel-1 the matching option is `topsStack.unwMethod` (also whirlwind by default). Both call `minsar/utils/unwrap_whirlwind.py`.

## Number of looks (ScanSAR)

`alos2Stack.rangeLooks` and `alos2Stack.azimuthLooks` are the final looks. `auto` leaves the ISCE ScanSAR default, 5 x 28 (looks 1 = 1 x 14 when the interferogram is formed, looks 2 = 5 x 2 before filtering and unwrapping), about 60-90 m ground range (far to near swath) by 73 m azimuth. With numbers, MinSAR keeps looks 1 at 1 x 14 and writes looks 2 = final / looks 1 to `alosStack.xml`, so `azimuthLooks` is a multiple of 14. Example: 2 and 14 give about 25-35 m by 36 m.
