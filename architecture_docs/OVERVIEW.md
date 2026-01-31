# MinSAR Architecture Overview

## Purpose

MinSAR (Miami INterferometric SAR) is an open-source Python/Bash pipeline for Interferometric Synthetic Aperture Radar (InSAR) processing and time series analysis. It orchestrates multiple external tools (ISCE2, MintPy, MiaplPy) on HPC clusters using SLURM.

## Core Design Philosophy

1. **Template-Driven Processing**: All processing is controlled via `.template` files that specify parameters
2. **HPC-First**: Designed for SLURM-based HPC clusters (Stampede2/3, Frontera, etc.)
3. **Modular Pipelines**: Supports three major processing pipelines that can be combined
4. **Fault Tolerance**: Automatic job resubmission on TIMEOUT/NODE_FAIL

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            USER INTERFACE LAYER                               │
├──────────────────────────────────────────────────────────────────────────────┤
│  minsarApp.bash                 - Main entry point                            │
│  *.template files               - Processing configuration                    │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         WORKFLOW ORCHESTRATION LAYER                          │
├──────────────────────────────────────────────────────────────────────────────┤
│  run_workflow.bash              - Job orchestration & monitoring              │
│  submit_jobs.bash               - Batch job submission                        │
│  sbatch_conditional.bash        - Resource-checked sbatch wrapper             │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                           PROCESSING ENGINES                                  │
├──────────────────────────────────────────────────────────────────────────────┤
│  ISCE2/topsStack               - Interferogram generation (run_01 - run_16)   │
│  MintPy                        - Small baseline time series analysis          │
│  MiaplPy                       - PS/DS time series analysis                   │
│  InsarMaps                     - Visualization/upload to web portal           │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                             HPC INFRASTRUCTURE                                │
├──────────────────────────────────────────────────────────────────────────────┤
│  SLURM Scheduler               - Job scheduling & resource management         │
│  Shared Filesystems            - $SCRATCH, $WORK for data storage             │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Processing Steps

The main processing pipeline executed by `minsarApp.bash`:

| Step | Name | Description |
|------|------|-------------|
| 1 | `download` | Download SLC data (ASF burst, ASF SLC, or SSARA) |
| 2 | `dem` | Download DEM from USGS |
| 3 | `jobfiles` | Create SLURM job files using ISCE2 stackSentinel.py |
| 4 | `ifgram` | Process interferograms (run_01 through run_11/16) |
| 5 | `mintpy` | Time series analysis using MintPy |
| 6 | `insarmaps` | Upload to InsarMaps web portal |
| 7 | `miaplpy` | Alternative PS/DS time series analysis |
| 8 | `upload` | Upload products to Jetstream server |

## Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `$MINSAR_HOME` / `$RSMASINSAR_HOME` | Root directory of MinSAR installation |
| `$SCRATCHDIR` | Working directory for processing |
| `$TEMPLATES` / `$TE` | Directory containing template files |
| `$SAMPLESDIR` | Directory containing sample templates |
| `$QUEUENAME` | Default SLURM queue name |
| `$PLATFORM_NAME` | HPC platform identifier (stampede2, stampede3, etc.) |

## Data Flow

```
SLC Download → DEM → Create JobFiles → Run ISCE Jobs (run_01-16) 
                                              ↓
                              ┌───────────────┴───────────────┐
                              ↓                               ↓
                          MintPy                          MiaplPy
                              ↓                               ↓
                        InsarMaps ←─────────────────────InsarMaps
                              ↓                               ↓
                          Upload ←──────────────────────── Upload
```

## External Dependencies

- **ISCE2**: InSAR Scientific Computing Environment (interferogram processing)
- **MintPy**: Miami InSAR Time series software in Python (time series)
- **MiaplPy**: Miami InSAR Persistent/Distributed scatterer analysis
- **PyAPS**: Python-based Atmospheric Phase Screen estimation
- **GDAL**: Geospatial data processing

## Related Documentation

- [Workflow Architecture](./WORKFLOW_ARCHITECTURE.md) - Detailed job submission system
- [Development Guide](./DEVELOPMENT_GUIDE.md) - Developer guidelines
- [File Structure](./FILE_STRUCTURE.md) - Repository structure
- [Key Concepts](./KEY_CONCEPTS.md) - Core concepts and terminology
