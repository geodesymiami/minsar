# MinSAR Architecture Documentation

**For AI Agents and Developers**

This documentation is designed to help AI agents and developers quickly understand the MinSAR codebase architecture, navigate the repository, and make effective contributions.

## Quick Reference

### What is MinSAR?

MinSAR (Miami INterferometric SAR) is a pipeline for InSAR processing on HPC clusters. It orchestrates:
- **ISCE2** for interferogram generation
- **MintPy** for time series analysis  
- **MiaplPy** for PS/DS analysis
- **InsarMaps** for web visualization

### Main Entry Point

```bash
minsarApp.bash $SAMPLESDIR/template.template [--start STEP] [--stop STEP] [--mintpy] [--miaplpy]
```

**AOI mode** (no `*.template` as first arg): if the first two arguments look like an AOI and a project name, `minsarApp.bash` `exec`s [`minsar/scripts/minsarapp_aoi_entry.py`](../minsar/scripts/minsarapp_aoi_entry.py), which runs `create_template.py` under `$TEMPLATES`/`$TE` and then re-executes `minsarApp.bash` with the generated primary `.template` file and any remaining flags. Before re-exec it sets **`MINSAR_CLI_COMMAND_AOI`** to a `shlex`-quoted copy of the AOI invocation (basename of `minsarApp.bash` plus argv after bbox argv normalization) so the end-of-run footer can show how the run was started; template-first invocations never set it. If `--flight-dir` requests dual-pass output (`asc,desc` default; also `desc,asc` or legacy `both`), the re-exec also passes `--opposite-orbit` so the opposite-orbit run runs after the primary stack (unless the remainder of the line already has `--opposite-orbit` or `--no-opposite-orbit`). All options accepted by `create_template.py` are supported; list them before the first `minsarApp`-only option (e.g. `--start`), because argv is split with `argparse` against the `create_template` parser first.

### Key Scripts to Understand

| Priority | Script | Purpose |
|----------|--------|---------|
| 1 | `minsar/bin/minsarApp.bash` | Main entry point, orchestrates everything |
| — | `minsar/scripts/minsarapp_aoi_entry.py` | AOI + project name → `create_template.py` in `$TEMPLATES`, then `exec` `minsarApp` with the new `.template` and remaining args |
| 2 | `minsar/bin/run_workflow.bash` | Job submission and monitoring loop |
| 3 | `minsar/bin/submit_jobs.bash` | Batch job submission |
| 4 | `minsar/bin/sbatch_conditional.bash` | Resource-checked sbatch wrapper |
| 5 | `minsar/lib/utils.sh` | Core bash utilities |
| 6 | `minsar/scripts/get_sar_coverage.py` | AOI coverage: orbits, counts; `--select` chooses Asc/Desc relative orbit (S1: prefers full-AOI consistency over incidence) |

### Processing Flow

```
minsarApp.bash
    │
    ├─► download     (generate_download_command.py → download script)
    ├─► dem          (generate_makedem_command.py → makedem script)
    ├─► jobfiles     (create_runfiles.py → run_files/*.job)
    ├─► ifgram       (run_workflow.bash --start 1 → ISCE processing)
    ├─► mintpy       (run_workflow.bash --dostep mintpy → smallbaseline_wrapper.job)
    ├─► insarmaps    (run_workflow.bash --jobfile insarmaps.job)
    └─► miaplpy      (run_workflow.bash --miaplpy → MiaplPy processing)
```

## Documentation Index

| Document | Description | When to Read |
|----------|-------------|--------------|
| [OVERVIEW.md](./OVERVIEW.md) | High-level architecture, pipelines, data flow | First read |
| [FILE_STRUCTURE.md](./FILE_STRUCTURE.md) | Repository layout, key directories | Finding files |
| [WORKFLOW_ARCHITECTURE.md](./WORKFLOW_ARCHITECTURE.md) | Job submission system details | Modifying job handling |
| [KEY_CONCEPTS.md](./KEY_CONCEPTS.md) | Terminology, template files, data structures | Understanding terminology |
| [DEVELOPMENT_GUIDE.md](./DEVELOPMENT_GUIDE.md) | Coding conventions, testing, debugging | Contributing code |
| [burst_testing.md](./burst_testing.md) | Annual template generation, run_templates.sh, testing bursts | Testing burst processing across years |
| [nasa_earthdata_status_check.md](./nasa_earthdata_status_check.md) | NASA Earthdata status check before ASF downloads (check_nasa_earthdata_status.py/.bash, env vars, minsarApp.bash integration) | Understanding or modifying download pre-checks |
| [BURST_DOWNLOAD.md](./BURST_DOWNLOAD.md) | burst_download.bash: per-date burst2stack, SLURM restart (check_SAFE_completeness, filter by complete SAFEs) | ASF burst download and burst2stack flow |
| [GEocode_HE5.md](./GEocode_HE5.md) | Geocode S1*.he5 (HDFEOS5) via thin wrapper over MintPy | Geocoding radar .he5 to geographic |
| [tools/sarvey/docs/ARCHITECTURE.md](../tools/sarvey/docs/ARCHITECTURE.md) | SARvey: MTI time series tool (tools/sarvey), CLI, workflow, inputs | Using or integrating SARvey; displacement from SLC stack |

## Quick Lookup Tables

### Processing Steps

| Step | Flag | Script/Job | Description |
|------|------|------------|-------------|
| download | `--dostep download` | download_slc.sh / download_burst2safe.sh / download_burst2stack.sh | Download SLC data (method-dependent) |
| dem | `--dostep dem` | makedem_sardem.sh | Download DEM |
| jobfiles | `--dostep jobfiles` | create_runfiles.py | Create SLURM jobs |
| ifgram | `--dostep ifgram` | run_01 - run_11/16 | ISCE processing |
| mintpy | `--dostep mintpy` | smallbaseline_wrapper.job | Time series |
| insarmaps | `--dostep insarmaps` | insarmaps.job | Web upload |
| miaplpy | `--start miaplpy` | miaplpy/run_files/*.job | PS/DS analysis |

### Key Directories

| Path | Purpose |
|------|---------|
| `minsar/bin/` | Entry point scripts |
| `minsar/lib/` | Shared bash libraries |
| `minsar/scripts/` | Python helper scripts |
| `minsar/defaults/` | Configuration files |
| `samples/` | Template examples |
| `tests/` | Test suite |
| `tools/sarvey/` | SARvey MTI time series package (standalone) |

### Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `$MINSAR_HOME` | Repository root |
| `$SCRATCHDIR` | Processing directory |
| `$TEMPLATES` / `$TE` | User templates (includes opposite-orbit templates from `create_opposite_orbit_template.bash`; AOI mode runs `create_template.py` under this directory via `minsarapp_aoi_entry.py`). |
| `$SAMPLESDIR` | Sample templates |
| `$QUEUENAME` | Default SLURM queue |

For the `--opposite-orbit` rerun, `minsarApp.bash` preloads **`opposite_orbit_template_file`** soon after **`cd`** into **`$WORK_DIR`**, then **`${TE}/opposite_orbit.txt`** if present. If no valid pointer/template path is known at the rerun step it runs `create_opposite_orbit_template.bash` once to populate **`${WORK_DIR}/opposite_orbit.txt`** (the AOI entry path **`exec`**s Python and never assigns in that branch).

### Configuration Files

| File | Purpose |
|------|---------|
| `minsar/defaults/job_defaults.cfg` | Walltime, memory per job type |
| `minsar/defaults/queues.cfg` | Queue resource limits |
| `minsar/defaults/minsar_template_defaults.cfg` | Default template values |

## Common Tasks for AI Agents

### Modifying Job Resources

1. Edit `minsar/defaults/job_defaults.cfg`
2. Find the job name row
3. Modify `c_walltime`, `c_memory`, etc.

### Adding a New Processing Step

1. Create job file generator in `minsar/scripts/`
2. Add execution block to `minsarApp.bash`
3. Add to `job_defaults.cfg`

### Debugging a Failed Job

1. Check `$WORKDIR/run_files/*.e` for errors
2. Check `$WORKDIR/log` for command history
3. Check `sacct -j <jobid>` for job state

### Running Tests

```bash
bash tests/test_run_workflow.bash  # 73 tests
bash tests/run_all_tests.bash      # All tests
```

## Nuances and Gotchas

### Template File Requirement

MiaplPy mode **requires** a template file argument:
```bash
# Wrong - will fail
run_workflow.bash --miaplpy --start 1

# Correct
run_workflow.bash $TE/template.template --miaplpy --start 1
```

### Job File Mode

`--jobfile` mode bypasses normal step logic:
```bash
# Runs just this one job, doesn't build globlist
run_workflow.bash --jobfile smallbaseline_wrapper.job
```

### MiaplPy Directory Structure

The run_files directory depends on network type:
- `miaplpy/network_single_reference/run_files/`
- `miaplpy/network_sequential_3/run_files/`
- `miaplpy/network_delaunay_4/run_files/`

### Step Numbers vs Names

Both work for `--start`/`--stop`:
```bash
run_workflow.bash --start 5 --stop 8    # By number
run_workflow.bash --start mintpy        # By name
```

### Coregistration Modes

- `geometry` coregistration: 11 steps (run_01 - run_11)
- `NESD` coregistration: 16 steps (run_01 - run_16)

Check `topsStack.coregistration` in template.

## Open Issues: matrix.html Time Controls

### Problem (as reported)

When using Time Controls in `minsar/html/matrix.html`:
- **Periods 2 and 3 do not display** — they remain blank
- **Loading does not happen in the background** — unlike `overlay.html`, where period 1 is shown and other periods load in the background, matrix.html does not load other periods while displaying the current one
- Periods 2 and 3 appear to be handled differently somewhere in the code

### Attempts made (unsuccessful)

1. **Ignore postMessage from period iframes** — Period iframes send `insarmaps-url-update` when they load; processing these caused the active grid to reload. Added `isFromPeriodIframe()` check to ignore period-iframe messages. Did not fix blank periods 2 and 3.

2. **Show period 0 earlier** — Reduced initial wait from ~28s to 5s so period 0 appears sooner; other periods still loaded via stagger. Did not fix the issue.

3. **Match overlay.html behavior** — Removed stagger; create all period grids at once (like overlay.html). Use `visibility: visible` and `z-index: -1` for inactive grids so iframes load in background. Show period 0 immediately with no delay. Still did not solve the problem.

### Current state

`minsar/html/matrix.html` has been reverted to the last committed version. The Time Controls issue remains open.

### Reference

`overlay.html` successfully loads periods in the background — it creates all period panels in one loop, uses `visibility: visible` + `z-index: -1` for inactive panels, and shows period 0 immediately.

## Related Files

- Existing detailed docs: `minsar/bin/ARCHITECTURE.md` (run_workflow.bash specific)
- User docs: `docs/README.md`
- Installation: `docs/installation.md`
