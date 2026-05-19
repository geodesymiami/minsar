# ISCE2 upgrade notes (2.6.3 → 2.6.4)

## Current status: Phase 1 (interim orbit download)

Conda still installs **isce2 2.6.3** (SciHub GNSS `fetchOrbit.py`). MinSAR symlinks the **Copernicus Data Space** script from the `tools/isce2` git clone.

### Prerequisites

```bash
cd "$MINSAR_HOME/tools/isce2"
git fetch --tags
git checkout v2.6.4
```

Confirm the script uses CDSE (not SciHub):

```bash
grep -E 'dataspace.copernicus|scihub.copernicus' "$MINSAR_HOME/tools/isce2/contrib/stack/topsStack/fetchOrbit.py"
```

You should see `dataspace.copernicus`, not `scihub.copernicus.eu/gnss`.

### One-time fix on an existing env (without full reinstall)

After `source setup/environment.bash`:

```bash
ln -sf "$MINSAR_HOME/tools/isce2/contrib/stack/topsStack/fetchOrbit.py" \
    "$ISCE_STACK/topsStack/fetchOrbit.py"
```

Fresh installs: [`setup/install_minsar.bash`](../setup/install_minsar.bash) creates the same symlink when `tools/isce2/.../fetchOrbit.py` exists.

### Copernicus Data Space credentials (download step only)

Orbit **catalog search** does not need your account. **Download** needs CDSE credentials (not ASF/Earthdata).

Add to `~/.netrc` (mode `600`):

```text
machine dataspace.copernicus.eu
login YOUR_CDSE_USERNAME
password YOUR_CDSE_PASSWORD
```

Or pass `-u` / `-p` to `fetchOrbit.py`.

### Verify

```bash
fetchOrbit.py -i /path/to/S1A_*.SAFE -o /path/to/orbits/YYYYMMDD
```

Expect catalog activity and a downloaded `*.EOF` under `-o`. Failure `Failed to find S1A orbits` with no connection error usually means no matching product; connection errors on `scihub` mean the symlink is missing or wrong.

---

## Phase 2 (later): conda `isce2=2.6.4`

When you bump the lockfile, **remove the temporary symlink** — the conda package includes CDSE `fetchOrbit.py`.

### Required when upgrading to 2.6.4

1. In [`setup/install_minsar.bash`](../setup/install_minsar.bash), **delete** the block between:
   - `# TEMPORARY (isce2<2.6.4): Copernicus Data Space fetchOrbit`
   - and the next `#FA 1/2026:` comment (the `_fetch_orbit_*` variables and `ln -sf`).

2. Pin and regenerate lock (do **not** hand-edit [`conda-lock.yml`](../conda-lock.yml)):

   ```bash
   # minsar_env.yml:  - isce2=2.6.4   # [linux]   (keep python=3.10)
   conda-lock lock -f minsar_env.yml --lockfile conda-lock.yml --update isce2
   mamba create --prefix tools/miniforge3/envs/minsar --file conda-lock.yml --yes
   ```

3. Re-run non-conda steps from `install_minsar.bash` (pip `-e` MintPy/MiaplPy, other `additions/isce2` symlinks).

4. Verify:

   ```bash
   conda list isce2    # 2.6.4 py310
   head -5 "$ISCE_STACK/topsStack/fetchOrbit.py"   # dataspace.copernicus, not scihub
   ls -l "$ISCE_STACK/topsStack/fetchOrbit.py"     # regular file from conda, not symlink to tools/isce2
   ```

### Conda builds (linux-64)

| Python | Available for isce2 2.6.4 |
|--------|---------------------------|
| 3.10   | Yes (matches MinSAR `minsar_env.yml`) |
| 3.12   | Yes (not required for this upgrade) |

### Benefits of full 2.6.4 (beyond orbit fetch)

- Copernicus Data Space in `fetchOrbit.py` and `dloadOrbits.py`
- Sentinel-1C in TOPS sensor
- topsStack ionosphere and related fixes (if used)
- GPU topo/geo2rdr and compiler compatibility fixes (situational)

After upgrade, review other `additions/isce2` symlinks in `install_minsar.bash` — some may override fixes already in 2.6.4 (especially `Sentinel1.py` for S1C).
