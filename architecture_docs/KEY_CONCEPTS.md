# Key Concepts

This document explains core concepts and terminology used throughout MinSAR.

## Template Files

### What is a Template?

A `.template` file is the primary configuration mechanism for MinSAR. It's a plain text file containing key-value pairs that control all aspects of processing.

**Example** (`unittestGalapagosSenDT128.template`):
```
# Download parameters
ssaraopt.platform               = SENTINEL-1A,SENTINEL-1B
ssaraopt.relativeOrbit          = 128
ssaraopt.startDate              = 20160601
ssaraopt.endDate                = 20160831

# Processing parameters
topsStack.boundingBox           = -1 -0.6 -91.9 -90.7
topsStack.subswath              = 1
topsStack.numConnections        = 3
topsStack.azimuthLooks          = 5
topsStack.rangeLooks            = 15

# MintPy parameters
mintpy.reference.lalo           = auto
mintpy.troposphericDelay.method = no
```

### Template Parameter Categories

| Prefix | Purpose |
|--------|---------|
| `ssaraopt.*` | Data download parameters |
| `topsStack.*` | ISCE topsStack processing |
| `stripmapStack.*` | ISCE stripmapStack processing |
| `mintpy.*` | MintPy time series analysis |
| `miaplpy.*` | MiaplPy PS/DS analysis |
| `minsar.*` | MinSAR-specific options |

### Template Resolution

Templates are read using an associative array in bash:
```bash
source minsar/lib/minsarApp_specifics.sh
create_template_array $template_file
# Access: ${template[mintpy.reference.lalo]}
```

## Processing Pipelines

### ISCE/topsStack Pipeline

Processes Sentinel-1 TOPS data into interferograms.

**Steps** (11-step "geometry" or 16-step "NESD" coregistration):

| Step | Name | Purpose |
|------|------|---------|
| 01 | `unpack_topo_reference` | Unpack reference SLC |
| 02 | `unpack_secondary_slc` | Unpack secondary SLCs |
| 03 | `average_baseline` | Compute baselines |
| 04 | `extract_burst_overlaps` | Extract overlap regions |
| 05 | `overlap_geo2rdr` | Geocode overlaps |
| 06 | `overlap_resample` | Resample overlaps |
| 07 | `pairs_misreg` | Compute misregistration |
| 08 | `timeseries_misreg` | Time series of misreg |
| 09 | `fullBurst_geo2rdr` | Full burst geocoding |
| 10 | `fullBurst_resample` | Full burst resampling |
| 11 | `extract_stack_valid_region` | Extract valid region |
| 12+ | (NESD only) Additional coregistration steps |

**Output**: Unwrapped interferograms in `merged/`

### MintPy Pipeline

Small Baseline Subset (SBAS) time series analysis.

**Key Steps**:
1. Load data from ISCE outputs
2. Modify network (exclude bad dates)
3. Reference point selection
4. Network inversion
5. Tropospheric correction (optional)
6. Topographic residual correction
7. Time series generation

**Output**: `mintpy/*.h5` (HDF5 time series), `mintpy/pic/` (figures)

### MiaplPy Pipeline

Persistent Scatterer (PS) and Distributed Scatterer (DS) analysis.

**Steps**:

| Step | Name | Purpose |
|------|------|---------|
| 1 | `load_data` | Load SLC stack |
| 2 | `phase_linking` | Estimate wrapped phase |
| 3 | `concatenate_patches` | Merge processed patches |
| 4 | `generate_ifgram` | Generate interferograms |
| 5 | `unwrap_ifgram` | Unwrap interferograms |
| 6 | `load_ifgram` | Load into MintPy format |
| 7 | `ifgram_correction` | Correct interferograms |
| 8 | `invert_network` | Network inversion |
| 9 | `timeseries_correction` | Time series corrections |

**Network Types**:
- `single_reference`: All interferograms relative to one reference
- `sequential_N`: Connect each date to N neighbors
- `delaunay`: Delaunay triangulation in space-time

## Job System

### Job Files

A `.job` file is a SLURM batch script:

```bash
#!/bin/bash
#SBATCH -J run_01_unpack_topo_reference_0
#SBATCH -N 1
#SBATCH -n 8
#SBATCH -o run_01_unpack_topo_reference_0.o
#SBATCH -e run_01_unpack_topo_reference_0.e
#SBATCH -p skx
#SBATCH -t 00:15:00
#SBATCH -A allocation_name

# Commands to execute
cd /path/to/workdir
command1
command2
```

### Run Files

A run file (no extension) is a list of commands to execute:

```
# run_02_unpack_secondary_slc_0
unpackFrame_TOPS.py -i /path/to/data/20160601 ...
unpackFrame_TOPS.py -i /path/to/data/20160615 ...
```

The `.job` file typically sources or executes the corresponding run file.

### Launcher Pattern

Many jobs use a "launcher" pattern where:
1. Run file contains N commands (one per line)
2. Job file uses TACC launcher or similar to parallelize

```bash
# In .job file
export LAUNCHER_JOB_FILE=run_02_unpack_secondary_slc_0
$LAUNCHER_DIR/paramrun
```

## Resource Management

### Custom Resource Limits

MinSAR enforces limits beyond SLURM's defaults:

| Limit | Purpose |
|-------|---------|
| `SJOBS_MAX_JOBS_PER_QUEUE` | Max jobs per user in queue |
| `SJOBS_STEP_MAX_TASKS` | Max tasks for current step |
| `SJOBS_TOTAL_MAX_TASKS` | Max tasks across all steps |

### Walltime Calculation

```
walltime = c_walltime + (num_memory_units * s_walltime) * num_data * seconds_factor
```

Where:
- `c_walltime`: Constant base time
- `s_walltime`: Slope (time per data unit)
- `seconds_factor`: Multiplier
- `num_data`: Data count (images, bursts, etc.)

### IO Load

The `io_load` parameter in `job_defaults.cfg` reduces allowed tasks for IO-intensive steps:
```
SJOBS_STEP_MAX_TASKS = SJOBS_STEP_MAX_TASKS / io_load
```

## Data Structures

### SLC Directory

Downloaded/unpacked Single Look Complex data:
```
SLC/
├── 20160601/
│   ├── s1a-iw1-slc-vv-20160601...
│   └── ...
├── 20160615/
└── ...
```

### Merged Directory

ISCE output after interferogram generation:
```
merged/
├── interferograms/
│   ├── 20160601_20160615/
│   │   ├── filt_fine.int
│   │   ├── filt_fine.unw
│   │   └── ...
│   └── ...
├── SLC/
│   ├── 20160601/
│   └── ...
└── geom_reference/
    ├── hgt.rdr
    └── ...
```

### MintPy Directory

Time series analysis outputs:
```
mintpy/
├── inputs/
│   ├── ifgramStack.h5
│   └── geometryRadar.h5
├── timeseries.h5
├── velocity.h5
├── temporalCoherence.h5
├── pic/
│   ├── network.pdf
│   └── ...
└── S1_*.he5  # HDF-EOS5 for InsarMaps
```

## Important Terminology

| Term | Definition |
|------|------------|
| **Reference** | The master SLC all others are coregistered to |
| **Secondary** | SLCs coregistered to the reference |
| **Burst** | A Sentinel-1 TOPS mode image segment |
| **Subswath** | IW1, IW2, or IW3 imaging swath |
| **Coherence** | Measure of phase quality (0-1) |
| **Unwrapping** | Converting wrapped phase to absolute phase |
| **Network** | Set of interferometric pairs |
| **SBAS** | Small Baseline Subset method |
| **PS** | Persistent Scatterer (stable point over time) |
| **DS** | Distributed Scatterer (stable area over time) |

## Platform-Specific Notes

### Stampede2/3

- Queue: `skx` (Skylake), `icx` (Ice Lake)
- Scratch: `$SCRATCH`
- Work: `$WORK`

### Frontera

- Queue: `normal`, `development`
- Different node configurations

### Environment Modules

Common modules needed:
```bash
module load python3
module load gcc
module load gdal
```

Modules are typically loaded via `setup/environment.bash`.
