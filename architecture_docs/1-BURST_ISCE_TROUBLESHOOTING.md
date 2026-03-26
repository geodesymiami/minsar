# Single-burst (1-burst) ISCE TOPS troubleshooting

## Symptom

- `SentinelWrapper.py -c /path/to/config_misreg_REF_SEC` fails when only one burst is available in the cropped region.
- Error: `Exception: Atleast 2 bursts must be present in the cropped region for TOPS processing.`

## Cause

ISCE’s TOPS Sentinel-1 processing (used by SentinelWrapper and the stack) assumes **at least two bursts** in the cropped region when combining multiple slices (e.g. reference and secondary for an interferometric pair). The sensor code needs a **burst start interval** (time between consecutive burst starts) to align and stitch bursts from different SAFEs. It computes this interval from either:

1. Two bursts in the first slice (`firstSlice.product.bursts[1].burstStartUTC - firstSlice.product.bursts[0].burstStartUTC`), or  
2. The first burst of two different slices.

If the region of interest (ROI) leaves only one burst available for that calculation (e.g. first slice has one burst and only one slice remains after cropping), the interval cannot be computed and the code raises the exception above.

**Relevant code:** `additions/isce2/components/isceobj/Sensor/TOPS/Sentinel1.py`, in `_parseMultiSlice()` (lines 471–479).

## Related behavior in MinSAR

- **Burst2safe runfile:** `minsar/scripts/bursts_to_burst2safe_jobfile.py` only emits runfile lines for groups with **more than one burst**; single-burst groups are skipped because downstream ISCE steps (e.g. `run_07_merge*`) expect more than one burst.
- **Docs:** `docs/README_burst_download.md` describes the “minimum number of bursts” rule and points to this expectation.

## Practical implications

- Stacks with only one burst in the cropped ROI are not supported by the current ISCE TOPS / SentinelWrapper logic.
- To avoid the error: use an AOI or burst selection that results in at least two bursts in the cropped region, or avoid running SentinelWrapper (and thus the TOPS merge/stitch path) for single-burst configurations.

---

## Can ISCE be fixed to support single-burst?

**Short answer:** Yes, in principle. The limitation is in how the TOPS stitch path computes `burstStartInterval`, not in a fundamental need for two bursts everywhere.

**Why two bursts are used today:** In `_parseMultiSlice()`, the interval is used to compute integer burst offsets between slices (`offset = int(np.rint((aslice.product.bursts[0].burstStartUTC - t0).total_seconds() / burstStartInterval.total_seconds()))`). With two or more bursts (in one slice or across two slices), that interval is derived from actual burst timestamps.

**Possible fixes (for ISCE / additions maintainers):**

1. **Single slice, single burst:** When `_numSlices == 1` and that slice has one burst, the code already returns early (lines 456–460) and never needs `burstStartInterval`. So the failure occurs when multiple slices are involved but the effective “first” slice ends up with only one burst and there is no second slice to derive the interval from. A fix could: when only one burst is available in the cropped region, use a **nominal burst interval** (Sentinel-1 TOPS burst period is ~1.2 s and is fixed by the instrument) from the annotation or a constant, and proceed with the single-burst product instead of raising.

2. **Use annotation when one burst:** The annotation XML contains burst timing; a single burst’s duration or the product’s burst list timing could be used to infer a nominal interval so the stitch logic does not require a second burst.

3. **Bypass stitch for single-burst:** If after cropping there is only one slice with one burst, treat it like the existing `_numSlices == 1` early return (use that product as-is) even when the parser was originally invoked for “multi-slice” input.

**Caveats:** Any change lives in `additions/isce2/` (or upstream ISCE). Downstream steps (e.g. `run_07_merge*`, interferogram formation) may assume multiple bursts; single-burst support would require checking those steps as well. The MinSAR burst-download and runfile generation would also need to be updated if single-burst SAFEs are to be produced and processed end-to-end.

---

## Which ISCE scripts need to be patched?

**Must patch (raises the “Atleast 2 bursts” error):**

| File | Location of logic |
|------|--------------------|
| `additions/isce2/components/isceobj/Sensor/TOPS/Sentinel1.py` | `_parseMultiSlice()`: lines 471–479. This is the only place that raises the exception. The fix is to compute or substitute `burstStartInterval` when only one burst is present (e.g. nominal S1 burst period or annotation-derived value) and continue, or to treat single-slice single-burst like the existing early return at 456–460. |

**Review (may need changes for edge cases):**

| File | Why review |
|------|------------|
| `additions/isce2/TOPSSwathSLCProduct.py` | `getBurstOffset()` / `getCommonBurstLimits()` use `numberOfBursts` and `np.clip(mind, 0, self.numberOfBursts - 1)`. With one burst this yields `mind = 0` and is safe; worth confirming behavior when both reference and secondary have a single burst. |
| `additions/Stack.py` | Calls `mergeBurst` and writes config for merge steps; no direct “2 bursts” check, but merge/igram steps assume a burst dimension—verify with single-burst products. |
| `additions/stackSentinel.py` | Invokes `burstIgram_mergeBurst` / `igram_mergeBurst`; confirm these do not assume multiple bursts. |

**No change needed for 1-burst:**

- `additions/isce2/VRTManager.py` — only formats `numberOfBursts` for output.
- `Sentinel1.py` uses `bursts[0]` and `bursts[-1]` elsewhere; with one burst both refer to the same burst and are valid. `bursts[numberBursts//2]` (line 935) with one burst is `bursts[0]`, which is valid.

---

## countbursts shows 1 for geom_reference but 0 for coreg_secondarys (1-burst)

### Why it happens

With **one burst**, ISCE may write coregistered secondaries differently:

- **geom_reference** usually has `hgt_*.rdr` or `lat_*.rdr` per burst under `geom_reference/IW*/`, so `_minsar_count_bursts_one_iw_dir` returns **1** per swath that has geometry.
- **coreg_secondarys** for each date may have only **overlap** output: `coreg_secondarys/DATE/overlap/IW1_top.xml`, `IW1_bottom.xml`, and an empty or absent `overlap/IW1/` with no `burst_01.slc.xml` / `hgt*rdr` in `date/IW*/`. Then every per-`IW*` count is **0** until the overlap fallback runs.

So you see: `geom_reference/YYYYMMDD #of_bursts: 1` and `coreg_secondarys/YYYYMMDD #of_bursts: 0` for every secondary date.

### MinSAR fix: countbursts overlap fallback

**File:** `minsar/lib/minsarApp_specifics.sh` (function `countbursts`).

After summing per-`IW*` counts with **`_minsar_count_bursts_one_iw_dir`**, if **`total -eq 0`** for that secondary date but `date/overlap` exists and (a) `date/overlap/IW1` is a directory, or (b) `date/overlap/IW1_top.xml` or `date/overlap/IW1_bottom.xml` exists, then set `total=1` and `array=(1)`. That keeps burst counts consistent with the reference (1 burst) and avoids downstream logic (e.g. `check_bursts`) treating secondaries as missing.

---

## countbursts: geom_reference vs coreg_secondarys (unified counting)

### Same rule everywhere

`countbursts` (`minsar/lib/minsarApp_specifics.sh`) uses one helper **`_minsar_count_bursts_one_iw_dir`** for every `IW*` directory under **`geom_reference`**, **`coreg_secondarys/<date>`**, or **`coreg_secondarys/<date>/overlap`**. Per directory, the **first** of these that yields a positive count wins:

1. `hgt*rdr`
2. `lat_*.rdr`
3. `burst*xml`
4. `range_*.off.xml`
5. `burst_*.slc`

Subswaths are visited in **`IW*`** order (`sort -V`). So reference and secondary lines are **comparable**: if totals still differ, one tree really lacks burst indicators in that `IW*` (not a counting-method mismatch).

### 1-burst overlap fallback (unchanged)

If the per-`IW*` total is **0** but `coreg_secondarys/<date>/overlap` has the usual IW1 overlap markers, `countbursts` still sets that date to **1** (see the 1-burst section above).

### ISCE steps (context)

- **Step 7** is **`pairs_misreg`**; full burst SLC/XML under `coreg_secondarys/<date>/IW*/` is mainly **steps 9–10** (`fullBurst_geo2rdr` / `fullBurst_resample`). Incomplete secondaries can still show lower counts until those steps finish.

### What to run on disk

For a mismatch, list the same patterns under each `IW*`: `hgt*rdr`, `lat_*.rdr`, `burst*xml`, `range_*.off.xml`, `burst_*.slc`.

---

## generateIgram with --overlap fails: "Reference has no bursts" (1-burst)

### Why it happens

The **misregistration** step runs `generateIgram` with **--overlap**. That loads products from `reference/overlap/IW*_top.xml` (and `_bottom.xml`) and `coreg_secondarys/<date>/overlap/...`. Overlap products describe the boundary between **consecutive** bursts (e.g. burst 1–2, 2–3). With **one burst** there are no such boundaries, so the overlap XMLs may exist but have **0 bursts**. `countbursts` reports 1 because of the **overlap fallback** when all per-`IW*` counts are zero (see above), not because it reads burst count inside the overlap products.

### MinSAR fix: generateIgram overlap skip

**File:** `additions/isce2/contrib/stack/topsStack/generateIgram.py`.

When run with **--overlap**, if the loaded reference or secondary **overlap** product has no bursts (e.g. 1-burst stack), the script **skips that swath** and continues instead of raising. It prints:

`Skipping overlap interferograms for IW<n>: reference or secondary overlap has no bursts (1-burst stack has no overlap regions). ...`

The run then completes. No overlap interferograms are produced for that swath.

**MinSAR 1-burst patches for downstream misreg steps:**

| Script | Patch (in `additions/isce2/contrib/stack/topsStack/`) | Behavior |
|--------|--------------------------------------------------------|----------|
| `overlap_withDEM.py` | Skip swath when overlap interferogram files (`IW*_top.xml`, `_bottom.xml`) are missing. | No ESD output for that swath; script exits successfully. |
| `estimateAzimuthMisreg.py` | If no ESD swaths or no coherent points, write dummy azimuth misreg file (median/mean/std 0.0) and return. | Misreg step completes; downstream uses zero correction. |
| `estimateRangeMisreg.py` | If overlap products have no bursts, skip swath; if no range offsets collected, write dummy range misreg file (0.0) and return. After the loop, range scaling must use **`referenceRangePixelSize`** from the last **processed** swath (set inside the loop after the skip check). Using **`referenceTop.bursts[0]`** is wrong when the last swath in the list was skipped — `referenceTop` was reloaded for that swath and has **empty** `bursts`, causing `IndexError`. | Misreg step completes; downstream uses zero correction. |

After applying these patches (via `install_minsar.bash` symlinks), `SentinelWrapper.py -c config_misreg_REF_SEC` completes successfully for 1-burst stacks.

---

## mergeBursts: "Skipping processing of swath 1" then ValueError: min() arg is an empty sequence

### Why it happens

`mergeBursts.py` (used for merging reference SLC, geom_reference lat/lon/etc., and interferograms) used to **skip** any swath where `minBurst == maxBurst` (i.e. a single burst). For 1-burst stacks every swath has one burst, so all were skipped, leaving `frames` and `referenceFrames` empty. The code then calls `mergeBurstsVirtual(frames, referenceFrames, fileList, ...)`, which does `topSwath = min(refSwaths, key=...)` and raises `ValueError: min() arg is an empty sequence` when `refSwaths` is empty.

### MinSAR fix: mergeBursts single-burst

**File:** `additions/isce2/contrib/stack/topsStack/mergeBursts.py`.

The skip for `minBurst == maxBurst` was removed. Single-burst swaths are now processed: one burst is appended to `frames` / `referenceFrames` / `fileList`, and `mergeBurstsVirtual` builds a VRT that contains that single burst. Merge steps (reference SLC, geom_reference lat/lon, interferograms, etc.) then complete for 1-burst stacks.
