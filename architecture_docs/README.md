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

### Key Scripts to Understand

| Priority | Script | Purpose |
|----------|--------|---------|
| 1 | `minsar/bin/minsarApp.bash` | Main entry point, orchestrates everything |
| 2 | `minsar/bin/run_workflow.bash` | Job submission and monitoring loop |
| 3 | `minsar/bin/submit_jobs.bash` | Batch job submission |
| 4 | `minsar/bin/sbatch_conditional.bash` | Resource-checked sbatch wrapper |
| 5 | `minsar/lib/utils.sh` | Core bash utilities |

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

## Quick Lookup Tables

### Processing Steps

| Step | Flag | Script/Job | Description |
|------|------|------------|-------------|
| download | `--dostep download` | download_asf_burst.sh | Download SLC data |
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

### Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `$MINSAR_HOME` | Repository root |
| `$SCRATCHDIR` | Processing directory |
| `$TEMPLATES` / `$TE` | User templates |
| `$SAMPLESDIR` | Sample templates |
| `$QUEUENAME` | Default SLURM queue |

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
