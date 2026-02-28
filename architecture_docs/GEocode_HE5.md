# Geocode HDFEOS5 (.he5) Architecture

## Summary

Geocode radar-coordinate S1*.he5 (HDF-EOS5) files to geographic coordinates via a thin wrapper over MintPy's geocode. The wrapper delegates .he5 input to `geocode_hdfeos5` (Full in-place B2: read HDFEOS5 → geocode → write HDFEOS5) and all other input to `geocode_orig` (unmodified MintPy).

---

## Option A (B1): Thin Wrapper with Extract → Geocode → Save [Deprecated]

**Idea:** Thin wrapper in `cli/geocode.py` detects .he5 input and delegates to `geocode_hdfeos5.main()`, which runs extract → geocode (each component) → save_hdfeos5. Otherwise delegates to `geocode_orig.main()` (unmodified MintPy). **Superseded by Option B2.**

**Files:**
- `additions/mintpy/cli/geocode.py` – Wrapper: .he5 → geocode_hdfeos5, else → geocode_orig
- `additions/mintpy/geocode_hdfeos5.py` – Extract → geocode each → save_hdfeos5
- `additions/mintpy/cli/geocode_orig.py` – Copy of MintPy cli/geocode.py; replace when upgrading MintPy

**Workflow (for .he5 input):**
1. Extract: `extract_hdfeos5.py <he5> --all` → timeseries.h5, temporalCoherence.h5, mask.h5, geometryRadar.h5, etc.
2. Geocode each: `geocode.py timeseries.h5 -l inputs/geometryRadar.h5 ...` → geo/geo_*
3. Repack: `save_hdfeos5.py geo/geo_timeseries*.h5 --tc ... --asc ... -m ... -g ...` → geocoded .he5

**Upstream maintenance:** When MintPy updates, replace `geocode_orig.py` with the new MintPy cli/geocode.py. Keep `geocode.py` and `geocode_hdfeos5.py` unchanged.

**Symlinks (required):** Run `setup/install_minsar.bash` or create manually:

```bash
ln -sf $MINSAR_HOME/additions/mintpy/geocode_hdfeos5.py $MINSAR_HOME/tools/MintPy/src/mintpy
ln -sf $MINSAR_HOME/additions/mintpy/cli/geocode.py $MINSAR_HOME/tools/MintPy/src/mintpy/cli
ln -sf $MINSAR_HOME/additions/mintpy/cli/geocode_orig.py $MINSAR_HOME/tools/MintPy/src/mintpy/cli
```

---

## HDFEOS5 File Structure

```
/                                    # Root
  Attributes                          # Metadata (UNAVCO/MintPy)

  HDFEOS/GRIDS/timeseries/
    observation/
      displacement                    # 3D float32 (numDate, length, width)
      date, bperp
    quality/
      temporalCoherence, avgSpatialCoherence, mask
    geometry/
      height, incidenceAngle, latitude, longitude, slantRangeDistance, ...
```

Defined in `additions/mintpy/save_hdfeos5.py`; read by `minsar/utils/extract_hdfeos5.py`.

---

## Memory Considerations

**Requirement:** MintPy geocode.py handles large timeseries.h5 files without memory problems. Geocoding .he5 files must behave the same for large .he5 files.

### How MintPy geocode handles large timeseries.h5

- Uses `--ram` / `--memory` (default 4 GB) to cap memory
- Block-based I/O in `run_geocode()` – large timeseries (e.g. 300 dates × 8000 × 5000) are processed in blocks without loading the full 3D array

### B1 (current) memory behavior

| Step | Memory behavior | Status |
|------|-----------------|--------|
| extract_hdfeos5.extract_timeseries | Loads full 3D displacement via `readfile.read(file_path, datasetName=dataset_name_list)` | **Risk** – OOM for large files (e.g. 300×8000×5000 float32 ≈ 48 GB) |
| geocode | Uses `--ram` and block I/O (passed from geocode_hdfeos5 line 99) | **Safe** |
| save_hdfeos5 | Writes displacement date-by-date: `for i: dset[i,:,:] = readfile.read(...)` | **Safe** |

### Ways to avoid memory problems on large .he5

1. **Option A (B1 fix):** Make extract_timeseries read displacement date-by-date (e.g. via h5py `dset[i,:,:]` or one readfile.read per date) instead of loading all dates at once.
2. **Option B (B2):** Full in-place HDFEOS5 I/O in geocode_hdfeos5 – read → geocode → write date-by-date with no extract step.

### geocode_hdfeos5 forwards --ram

Users can pass `--ram 8` (or similar) to raise the memory limit for the geocode step; this does not affect the extract step.

---

## Key Commands

```bash
# Geocode .he5 (radar → geo)
geocode.py S1_radar.he5 [-l geometryRadar.h5] [-t smallbaselineApp.cfg]

# Geocode .h5 (original MintPy behavior)
geocode.py timeseries.h5 -l inputs/geometryRadar.h5 -t smallbaselineApp.cfg --outdir geo
```

---

## Files Referenced

| File | Purpose |
|------|---------|
| `additions/mintpy/cli/geocode.py` | Thin wrapper |
| `additions/mintpy/geocode_hdfeos5.py` | .he5 workflow |
| `additions/mintpy/cli/geocode_orig.py` | Unmodified MintPy geocode |
| `additions/mintpy/save_hdfeos5.py` | HDFEOS5 write |
| `minsar/utils/extract_hdfeos5.py` | HDFEOS5 read |
| `additions/mintpy/tests/test_geocode_wrapper.py` | Tests |

---

## Option B2 (Implemented): Full in-place HDFEOS5 Geocoding

**Idea:** `geocode_hdfeos5.main()` reads HDFEOS5 directly, geocodes block-by-block in memory (using MintPy `resample`), writes HDFEOS5 directly. No extract step, no temp directory (minimal temp for lookup only when `-l` not provided).

**Flow:**
1. Lookup: use `-l geometryRadar.h5` if given; else extract geometry only (symlink he5 into temp dir, run `extract_hdfeos5`, copy geometryRadar.h5 out).
2. Init MintPy `resample` with lookup and geometryRadar as `src_file` for dimensions.
3. Read displacement date-by-date from input .he5; for each block, run `res_obj.run_resample()`; write to output .he5.
4. Same for quality (temporalCoherence, avgSpatialCoherence, mask) and geometry datasets.
5. Uses `--ram` for block size (same as MintPy geocode).

**Memory:** Date-by-date and block-based I/O; scales like MintPy geocode for large files.

---

## Other Options (Not Implemented)

- **Standalone wrapper:** Separate script (e.g. geocode_he5.bash) that runs extract → geocode → save; no changes to geocode.py entry point.
