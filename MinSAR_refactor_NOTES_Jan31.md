# MinSAR Refactor Notes - January 31, 2026

Supporting notes and current state analysis for the satellite registry refactoring.

---

## Current Satellite Logic Locations

### minsarApp.bash (minsar/bin/minsarApp.bash)

| Line | Code | Purpose |
|------|------|---------|
| 123 | `download_method="asf-burst"` | Default download method |
| 127-130 | `isce_stopstep=11` / `16` for NESD | ISCE steps depend on coregistration |
| 414-420 | `grep platform` / fallback TERRASAR-X | Detect satellite from template |
| 422-428 | `platform_str =~ COSMO-SKYMED\|TERRASAR-X\|ENVISAT` | Non-Sentinel satellites |
| 423 | `download_dir="$WORK_DIR/SLC_ORIG"` | Download dir for non-Sentinel |
| 424 | `download_method="ssara-bash"` | Force ssara-bash for non-Sentinel |
| 427 | `download_dir="$WORK_DIR/SLC"` | Download dir for Sentinel |
| 480-482 | `platform_str != *"Sentinel-1"*` | Unpack only for non-Sentinel |
| 553 | `template_file == *"Sen"*` | Orbit download only for Sentinel |
| 562 | `template_file =~ (Tsx\|Csk\|Env)` | BUFFOPT for stripmap satellites |
| 570-574 | `template_file =~ (Tsx\|Csk\|Env)` | Use stripmapStack PATH |

### unpack_sensors.py (minsar/objects/unpack_sensors.py)

| Line | Code | Purpose |
|------|------|---------|
| 54-65 | Glob patterns per sensor | File pattern detection |
| 66-67 | `sensor_str_list` / `sensor_list` | Mapping patterns to sensor names |
| 76 | `Sensors = dict(zip(...))` | Pattern to sensor lookup |

**Current sensor patterns:**
```python
ENV_str = 'ASA*'            # Envisat
ERS_CEOS_str = 'ER*CEOS*'   # ERS in CEOS format
ERS_ENV_str = 'ER*ESA*'     # ERS in Envisat format
ALOS1_str = 'ALPSRP*'       # ALOS-1 Palsar
ALOS2_str = '00*ALOS2*'     # ALOS-2
CSK_str = 'EL*'             # CSK, zip files
CSK_str2 = 'CSK*'           # CSK, zip files
TSX_TDX_DLR_str = 'dims_op*' # TSX zip files
TSX_TDX_str = 'T*X1*'       # TSX/TDX zip files
RSAT2_str = 'RS2*SLC*'      # RSAT2 zip files
```

### auto_defaults.py (minsar/objects/auto_defaults.py)

| Line | Code | Purpose |
|------|------|---------|
| 38-41 | `required_template_options()` | Different required keys for tops vs stripmap |
| 134-152 | `correct_for_isce_naming_convention()` | Different key mappings per stack |
| 152 | `stackprefix = 'topsStack'` | Stack prefix based on acquisition_mode |
| 135 | `stackprefix = 'stripmapStack'` | Stripmap prefix |

### create_insar_template.py (minsar/src/minsar/cli/create_insar_template.py)

| Line | Code | Purpose |
|------|------|---------|
| 200-208 | `get_satellite_name()` | Short name to ssara platform string |

```python
def get_satellite_name(satellite):
    if satellite == 'Sen':
        return 'SENTINEL-1A,SENTINEL-1B'
    elif satellite == 'Radarsat':
        return 'RADARSAT2'
    elif satellite == 'TerraSAR':
        return 'TerraSAR-X'
```

### job_submission.py (minsar/job_submission.py)

| Line | Code | Purpose |
|------|------|---------|
| 115-120 | `if inps.prefix == 'stripmap'` | Stack path selection |
| 299-302 | PATH modification | stripmapStack vs topsStack |
| 814-817 | Source command in job files | Platform-specific PATH |

---

## Download Methods

Current download methods in minsarApp.bash (lines 441-463):

| Method | Script/Command | Used By |
|--------|----------------|---------|
| `asf-burst` | `./download_asf_burst.sh` | Sentinel-1 (default) |
| `asf-slc` | `./download_asf.sh` | Sentinel-1 |
| `ssara-python` | `download_ssara_python.cmd` | All satellites |
| `ssara-bash` | `download_ssara_bash.cmd` | TSX, CSK, Envisat (default) |
| `remote_data_dir` | `rsync` | Any (manual data) |

---

## ISCE Stack Differences

### topsStack (Sentinel-1)
- Steps: 11 (geometry) or 16 (NESD coregistration)
- PATH: `$ISCE_STACK/topsStack`
- Workflow options: `interferogram`, `slc`
- Orbits required: Yes (ASF download)

### stripmapStack (TSX, CSK, Envisat, ALOS, ERS)
- Steps: ~9 (default)
- PATH: `$ISCE_STACK/stripmapStack`
- Requires unpack step
- Orbits: Not required (embedded in data)

---

## Sample Template Files

### Sentinel-1: `samples/GalapagosSenDT128.template`
```
ssaraopt.platform               = SENTINEL-1A,SENTINEL-1B
ssaraopt.relativeOrbit          = 128
```

### Envisat: `samples/GalapagostestEnvD140.template`
```
acquisition_mode        = stripmap
ssaraopt.platform       = ENVISAT
ssaraopt.relativeOrbit  = 140
```

### COSMO-SkyMed: `samples/MaunaLoatestCskAT10.template`
```
acquisition_mode        = stripmap
ssaraopt.platform       = COSMO-SKYMED-1,COSMO-SKYMED-2,COSMO-SKYMED-3,COSMO-SKYMED-4
ssaraopt.relativeOrbit  = 10
```

---

## Unpack Scripts Location

```
additions/isce2/contrib/stack/stripmapStack/
├── unpackFrame_ENV.py       # Envisat
├── unpackFrame_ENV_raw.py   # Envisat raw
└── unpackFrame_TSX.py       # TerraSAR-X
```

---

## Key Questions for Implementation

1. **ALOS-1 vs ALOS-2**: Are these handled differently? Current patterns suggest yes.

2. **ERS**: Two formats (CEOS and Envisat) - need separate handlers?

3. **RADARSAT-2**: Pattern exists but unclear if fully supported.

4. **TanDEM-X**: Same as TSX or different?

5. **Download method flexibility**: Should users be able to override per-template? (Plan says yes via `minsar.downloadMethod`)

6. **Unpack method flexibility**: Some sensors may have multiple unpack options (raw vs SLC).

---

## Files to Watch During Refactoring

Critical files that touch satellite logic:
- `minsar/bin/minsarApp.bash` - main orchestration
- `minsar/objects/unpack_sensors.py` - sensor detection
- `minsar/objects/auto_defaults.py` - stack configuration
- `minsar/job_submission.py` - job file generation
- `minsar/utils/process_utilities.py` - utility functions
- `minsar/src/minsar/cli/create_runfiles.py` - runfile creation
