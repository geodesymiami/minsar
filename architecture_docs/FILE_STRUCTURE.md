# File Structure

## Repository Layout

```
minsar/
├── architecture_docs/        # Architecture documentation (this folder)
│   ├── OVERVIEW.md
│   ├── WORKFLOW_ARCHITECTURE.md
│   ├── FILE_STRUCTURE.md
│   ├── DEVELOPMENT_GUIDE.md
│   └── KEY_CONCEPTS.md
│
├── docs/                     # User documentation
│   ├── README.md             # Main documentation entry point
│   ├── installation.md       # Installation instructions
│   └── *.md                  # Various topic-specific docs
│
├── minsar/                   # Main source code
│   ├── bin/                  # Executable scripts (entry points)
│   ├── lib/                  # Shared bash libraries
│   ├── scripts/              # Python helper scripts
│   ├── defaults/             # Configuration defaults
│   ├── objects/              # Python classes and utilities
│   ├── utils/                # Utility scripts (Python & Bash)
│   ├── workflow/             # Workflow-related Python modules
│   └── src/minsar/cli/       # CLI command implementations
│
├── samples/                  # Sample template files
├── setup/                    # Environment setup scripts
├── tests/                    # Test suite
└── additions/                # Patches/additions for external tools
```

## Key Directories

### `minsar/bin/` - Entry Points

These are the main executable scripts users interact with:

| Script | Purpose |
|--------|---------|
| `minsarApp.bash` | **Main entry point** - orchestrates entire processing |
| `run_workflow.bash` | Job orchestration and monitoring |
| `submit_jobs.bash` | Batch job submission |
| `sbatch_conditional.bash` | Resource-checked sbatch wrapper |
| `ingest_insarmaps.bash` | InsarMaps ingestion |
| `download_data.sh` | Data download helper |
| `run_clean_dir.bash` | Directory cleanup |

### `minsar/lib/` - Shared Libraries

Bash libraries sourced by multiple scripts:

| Library | Purpose |
|---------|---------|
| `utils.sh` | Common utility functions (`run_command`, `get_reference_date`, etc.) |
| `workflow_utils.sh` | Workflow-specific utilities (`abbreviate`, `clean_array`, etc.) |
| `minsarApp_specifics.sh` | minsarApp-specific functions |
| `common_helpers.sh` | Generic helper functions |

### `minsar/scripts/` - Python Helpers

Python scripts called by bash entry points:

| Script | Purpose |
|--------|---------|
| `generate_download_command.py` | Generate data download commands |
| `generate_makedem_command.py` | Generate DEM creation commands |
| `check_job_outputs.py` | Validate job outputs after completion |
| `update_walltime_queuename.py` | Update job walltime after TIMEOUT |
| `create_ingest_insarmaps_jobfile.py` | Create InsarMaps ingestion job |
| `create_save_hdfeos5_jobfile.py` | Create HDF-EOS5 save job |
| `upload_data_products.py` | Upload products to Jetstream |

### `minsar/defaults/` - Configuration

Default configuration files:

| File | Purpose |
|------|---------|
| `job_defaults.cfg` | Default walltime, memory per job type |
| `queues.cfg` | Queue-specific resource limits |
| `minsar_template_defaults.cfg` | Default template values |
| `insar_template.template` | Template file template |

### `minsar/objects/` - Python Classes

| Module | Purpose |
|--------|---------|
| `dataset_template.py` | Template file parsing |
| `message_rsmas.py` | Messaging utilities |
| `rsmas_logging.py` | Logging configuration |
| `auto_defaults.py` | Automatic default detection |
| `unpack_sensors.py` | Sensor unpacking utilities |

### `minsar/utils/` - Utility Scripts

Mixed Python and Bash utilities:

| Category | Examples |
|----------|----------|
| Data handling | `uncompress_and_rename_data.py`, `check_download.py` |
| Template management | `generate_template_files.py`, `create_insar_template.py`, `create_annual_template_files.bash` |
| Job utilities | `examine_job_stdout_files.py`, `summarize_job_run_times.py` |
| Geospatial | `convert_boundingbox.py`, `get_boundingBox_from_kml.py` |

`create_annual_template_files.bash` generates year-shifted template copies from a base template and writes `$SCRATCHDIR/run_templates.sh` (overwritten each run; not version-controlled) to batch-run minsarApp.bash on those templates. See [burst_testing.md](burst_testing.md).

### `minsar/src/minsar/cli/` - CLI Commands

Python CLI command implementations:

| Module | Purpose |
|--------|---------|
| `create_runfiles.py` | Create ISCE run files |
| `create_mintpy_jobfile.py` | Create MintPy job file |
| `create_html.py` | Create HTML index pages |
| `get_flight_direction.py` | Determine satellite flight direction |

### `samples/` - Template Examples

Sample `.template` files for testing and reference:

| Template | Purpose |
|----------|---------|
| `unittestGalapagosSenDT128.template` | Main unit test template |
| `GalapagosSenDT128.template` | Full Galapagos example |
| `hvGalapagosSenA106.template` | Horizontal/vertical decomposition |
| `KilaueaCskAT10.template` | COSMO-SkyMed example |

### `setup/` - Environment Setup

| Script | Purpose |
|--------|---------|
| `environment.bash` | Set environment variables |
| `platforms_defaults.bash` | Platform-specific defaults |
| `install_minsar.bash` | Installation script |
| `install_python.bash` | Python environment setup |

### `tests/` - Test Suite

| Test File | Purpose |
|-----------|---------|
| `test_run_workflow.bash` | Main workflow tests (73 tests) |
| `test_sbatch_conditional.bash` | sbatch_conditional tests |
| `test_submit_jobs.bash` | submit_jobs tests |
| `test_helpers.bash` | Test utility functions |
| `run_all_tests.bash` | Run complete test suite |

### `additions/` - External Tool Patches

Patches and additions for external tools:

```
additions/
├── isce/           # ISCE patches
├── isce2/          # ISCE2 patches  
├── miaplpy/        # MiaplPy patches
└── mintpy/         # MintPy patches
```

## Processing Directory Structure

When `minsarApp.bash` runs, it creates this structure in `$SCRATCHDIR`:

```
$SCRATCHDIR/<ProjectName>/
├── SLC/                      # Downloaded SLC data
├── DEM/                      # Downloaded DEM
├── run_files/                # ISCE job files
│   ├── run_01_*.job
│   ├── run_02_*.job
│   └── ...
├── reference/                # Reference SLC data
├── coreg_secondarys/         # Coregistered secondaries
├── geom_reference/           # Reference geometry
├── merged/                   # Merged interferograms
│   ├── interferograms/
│   └── SLC/
├── mintpy/                   # MintPy outputs
│   ├── inputs/
│   ├── pic/
│   └── *.h5
├── miaplpy/                  # MiaplPy outputs
│   └── network_<type>/
│       ├── run_files/
│       └── ...
├── log                       # Main processing log
├── workflow.*.log            # Workflow logs
├── smallbaseline_wrapper.job # MintPy job file
└── insarmaps.job             # InsarMaps job file
```

## Important Paths

| Variable | Typical Value | Purpose |
|----------|---------------|---------|
| `$MINSAR_HOME` | `/path/to/minsar` | Repository root |
| `$SCRATCHDIR` | `/scratch/user/` | HPC scratch space |
| `$TEMPLATES` / `$TE` | `$HOME/Templates` | User templates |
| `$SAMPLESDIR` | `$MINSAR_HOME/samples` | Sample templates |
| `$WORKDIR` | `$SCRATCHDIR/<Project>` | Processing directory |
