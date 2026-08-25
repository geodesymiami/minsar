# ISCE3 Workflow Generator

## Purpose and scope

The ISCE3 workflow tools create and execute transparent processing stages for three Sentinel-1 starting datasets:

- Sentinel-1 SAFE data, which is the default
- OPERA CSLC products
- OPERA DISP-S1 products

The first objective is to process the same area through all three paths so their products can be compared. The generated files are also structured for later integration into `minsarApp.bash --isce3` and eventual operational processing.

The implementation is intentionally separate from the existing ISCE2 workflow. It does not modify the ISCE2 `run_workflow.bash` stage definitions, `job_defaults.cfg`, or submission behavior.

The workflow consists of three command-line programs:

- `create_isce3_runfiles.py` creates run files and SLURM job files.
- `run_isce3_workflow.bash` runs selected steps locally or submits them to SLURM.
- `validate_isce3_outputs.py` checks outputs using repository validation defaults.

## Required environment

Start from the MinSAR environment and source the normal MinSAR setup:

```bash
source "$MINSAR_HOME/setup/environment.bash"
```

The runner does not require the user to enter a SWEETS Pixi shell. Commands that need SWEETS, COMPASS, Dolphin, or the current `opera-utils` DISP dependencies are launched with:

```bash
pixi run --manifest-path "$MINSAR_HOME/tools/sweets/pyproject.toml" ...
```

The SWEETS environment must be installed once:

```bash
pixi install --manifest-path "$MINSAR_HOME/tools/sweets/pyproject.toml"
```

The local and SLURM runners therefore require:

- `$MINSAR_HOME` and the normal MinSAR paths
- `pixi` on `PATH`
- the installed SWEETS default environment
- `sbatch` when the auto-detected or explicitly selected backend is SLURM
- TACC LAUNCHER only for generated `launcher-task-list` SLURM jobs

The Pixi CUDA system-requirements deprecation message on macOS is a warning and does not indicate installation failure.

## Creating a workflow

### Template input

The generator accepts an existing MinSAR template:

```bash
create_isce3_runfiles.py "$TE/HawaiiSenD87.template"
create_isce3_runfiles.py "$TE/HawaiiSenD87.template" --cslc
create_isce3_runfiles.py "$TE/HawaiiSenD87.template" --disp
```

SAFE is selected when no data-type option is given. `--safe`, `--cslc`, and `--disp` are mutually exclusive. The equivalent explicit form is `--data-type safe`, `--data-type cslc`, or `--data-type disp`.

The generator reads the AOI, dates, track, and available DISP frame information from the template. Command-line values such as `--start-date`, `--end-date`, `--track`, and `--frame-id` override the corresponding template-derived values.

### AOI input

The generator also accepts an AOI followed by a project name:

```bash
create_isce3_runfiles.py 19.4:19.54,-155.02:-154.80 HawaiiPuna --flight-dir desc --disp
create_isce3_runfiles.py -23.3:-23.1,-68.4:-68.2 ChileTest --flight-dir asc --safe
```

AOI mode uses `create_template.py` to resolve the standard MinSAR template before generating the workflow. The generated `.template` is always written in the directory where `create_isce3_runfiles.py` was invoked, while processing files are written under `$SCRATCHDIR`. AOI mode supports negative southern latitudes through the shared bounding-box argument handling. `--flight-dir asc` or `--flight-dir desc` is required.

### Output location and regeneration

The workflow directory is always:

```text
$SCRATCHDIR/<project-name>/
```

The generator changes into `$SCRATCHDIR` before creating the project processing directory. An existing template may be read from any path; AOI-generated templates remain in the invocation directory. Run files and job files are always replaced, and stale numbered files from another workflow are removed. There is no `--overwrite` option.

Downloaded source products are retained and reused. Generated configuration and command files are rebuilt, while processing stages replace their derived stack, Dolphin, HDF-EOS5, and local ingest outputs.

`--dry-run` prints the workflow stages without writing files or querying remote services.

## Generated directory structure

A generated project has the following central files:

```text
PROJECT/
├── run_files/
│   ├── run_01_<stage>
│   ├── run_01_<stage>.job
│   ├── run_02_<stage>
│   ├── run_02_<stage>.job
│   └── ...
├── sweets_config.yaml
├── sweets_config_command.bash
└── processing outputs created by later stages
```

The exact stage names depend on the starting dataset.

### Validation definitions

`minsar/defaults/isce3_validation.json` is part of the repository and contains the expected output patterns for every step in each workflow. No validation configuration is copied into project directories.

The validator runs from the processing directory, discovers its ordered steps from `run_files/run_NN_*.job`, and infers SAFE, CSLC, or DISP-S1 from those step names. `--data-type` can select the workflow explicitly.

### Run files

`run_files/run_NN_<stage>` is either an executable shell script or a task list:

- A script stage changes to the workflow directory and runs its commands in order.
- A task-list stage contains one independent command per line.

The files are deliberately readable so an operator can inspect or run an individual command without reconstructing it from Python state.

### Job files

`run_files/run_NN_<stage>.job` wraps the corresponding run file for SLURM. On a configured MinSAR SLURM system, the generator reuses the existing `JOB_SUBMIT` header rendering through a localized adapter. A generic SLURM header is used when that environment is unavailable.

Task-list jobs export LAUNCHER settings and execute `$LAUNCHER_DIR/paramrun`. Script and single-multicore jobs execute their run file directly. Every job validates its step after processing; a validation failure makes the job fail and prevents dependent `afterok` jobs from starting.

The numbered `.job` files are the runner's source of truth. Their filenames define step order and names, their SLURM directives define resources, and `LAUNCHER_JOB_FILE` identifies task-list jobs. Generated run files contain the concrete processing parameters needed by their commands.

## Workflow stages

### SAFE workflow

The SAFE path contains five stages:

1. `download_safe`
   - Creates `sweets_config.yaml`.
   - Downloads DEM, water mask, burst database, and SAFE data.
   - Runs `check-safe --delete`, downloads again, and runs a final strict `check-safe`.
   - Deletes structurally incomplete or unreadable SAFEs and fails if expected acquisitions remain missing after the retry.
   - Downloads required orbits after the SAFE set passes validation.
   - Creates COMPASS runconfigs after the acquisition list is known.
   - Materializes the commands for stage 2.
2. `create_cslc`
   - Runs one `s1_cslc.py` command for each CSLC runconfig.
   - Runs one `s1_static_layers.py` command per burst.
   - Uses a LAUNCHER task list on SLURM.
3. `run_dolphin`
   - Stitches the static-layer geometry.
   - Runs SWEETS starting at its Dolphin stage.
4. `create_hdfeos5`
   - Converts the Dolphin directory into an HDF-EOS5 product.
5. `ingest_insarmaps`
   - Runs the MinSAR InsarMaps ingest on the generated `.he5` product.

Stage 2 cannot be fully generated before stage 1 because the number of COMPASS runconfigs depends on the downloaded acquisition and burst list. `run_01_download_safe` therefore rewrites `run_02_create_cslc` with concrete commands. This is expected behavior, not modification of an already-running job.

### CSLC workflow

The OPERA CSLC path contains four stages:

1. `download_cslc`
   - Creates a SWEETS configuration with the OPERA CSLC source.
   - Downloads CSLC and CSLC-STATIC products.
   - Runs `check-cslc --delete`, downloads again, and runs a final strict `check-cslc`.
   - Compares local filenames with ASF search results and verifies the HDF5 datasets needed by Dolphin and geometry stitching.
   - Creates the stitched geometry needed by Dolphin.
2. `run_dolphin`
   - Runs SWEETS starting at Dolphin and reuses the downloaded geocoded inputs.
3. `create_hdfeos5`
   - Converts the Dolphin output into HDF-EOS5.
4. `ingest_insarmaps`
   - Converts and uploads the HDF-EOS5 result.

SWEETS is used instead of constructing a separate direct Dolphin configuration because it already resolves the CSLC layout, geometry, masking, and Dolphin configuration consistently with the SAFE path.

### DISP-S1 workflow

The OPERA DISP-S1 path contains four stages:

1. `download_disp`
   - Resolves the DISP frame when it is not supplied.
   - Downloads products into `subsets/`.
   - Runs `check-disp --delete`, downloads again, and runs a final strict `check-disp`.
   - Deletes unreadable products and fails if expected CMR products remain missing after the retry.
2. `reformat_disp`
   - Reformats the downloaded products into `<project>-stack.nc`.
3. `create_hdfeos5`
   - Converts the stack directly into HDF-EOS5.
4. `ingest_insarmaps`
   - Converts and uploads the HDF-EOS5 result.

The resolved commands are saved in `disp-s1_commands.bash` for inspection. DISP command construction and execution run explicitly in the SWEETS Pixi environment because current `opera-utils[disp]` requires Python and Zarr versions newer than the MinSAR Python 3.10 environment. The operator should not install those dependencies into the MinSAR environment or upgrade that environment in place.

All three download steps use the same retry contract: tolerate an initial downloader error long enough to run the delete-capable checker, remove corrupt products, retry the downloader once, and let the final strict checker determine the step exit status. Search or authentication failures in a checker remain fatal because the expected product set cannot be established.

## Execution modes

The ISCE3 defaults support three execution modes:

- `sequential`: a shell script containing commands that must run in order
- `single-multicore`: one program that controls its own threads or worker processes
- `launcher-task-list`: independent commands suitable for TACC LAUNCHER

Every genuine task list uses LAUNCHER on SLURM, matching the existing ISCE2 policy and reducing scheduler overhead. A short script remains a script even when it could technically be represented as a one-line task list.

Locally, task lists are sequential by default. `--max-parallel N` runs up to `N` task-list commands concurrently without requiring GNU Parallel.

## Running locally

Change to the generated processing directory and run all steps:

```bash
cd "$SCRATCHDIR/HawaiiSenD87"
run_isce3_workflow.bash
```

The default backend is `auto`. The runner uses the shared MinSAR `minsar_are_we_on_slurm_system` function, backed by `are_we_on_slurm_system()` in `system_utils.py`, to select the backend:

- a SLURM login node outside an allocation selects `slurm`
- a SLURM compute node or active allocation selects `local`
- macOS and regular Linux systems select `local`

The selected backend is printed before execution. `$JOBSCHEDULER` is not used for this decision because platform defaults may define it even on systems without active SLURM commands.

Use an explicit override when testing or when local execution is desired on a SLURM login node:

```bash
run_isce3_workflow.bash --backend local
run_isce3_workflow.bash --backend slurm
```

Run an inclusive step range:

```bash
run_isce3_workflow.bash --start download_disp --end reformat_disp
run_isce3_workflow.bash --start 2 --end 4
```

Run exactly one step:

```bash
run_isce3_workflow.bash --dostep download_disp
run_isce3_workflow.bash --dostep 3
```

A `STEP` can be:

- the step number, such as `3`
- the step name, such as `reformat_disp`
- the run-file basename, such as `run_03_reformat_disp`

`--start` and `--end` are inclusive. `--dostep` cannot be combined with either range option. An unknown step or a start step after the end step is rejected before execution.

Use a dry run to inspect the selected files and commands:

```bash
run_isce3_workflow.bash --start 2 --end 4 --dry-run
```

For a local SAFE task list:

```bash
run_isce3_workflow.bash --dostep create_cslc --max-parallel 4
```

The output from a successfully completed preceding stage remains on disk. A failed restart-safe stage can therefore be rerun with `--dostep` or used as the first stage of a range.

## Running with SLURM

On a SLURM login node, submit all stages with the default auto backend:

```bash
run_isce3_workflow.bash
```

Submit a selected range, with an explicit backend shown for clarity:

```bash
run_isce3_workflow.bash --backend slurm --start create_cslc --end create_hdfeos5
```

The first selected job is submitted normally. Each later job is submitted with `afterok:<previous-job-id>`, so it becomes eligible only after the preceding stage succeeds. The Bash runner submits the chain and returns; it does not monitor jobs to completion or automatically resubmit failures.

SLURM dry-run mode prints the commands and synthetic dependency IDs without calling `sbatch`:

```bash
run_isce3_workflow.bash --backend slurm --start 2 --end 4 --dry-run
```

## Resources and restart policy

`minsar/defaults/job_defaults_isce3.cfg` is independent of the ISCE2 defaults. It starts with the same columns and header names as `job_defaults.cfg`:

```text
jobname c_walltime s_walltime seconds_factor c_memory s_memory num_threads io_load rerun_walltime_factor switch_queue rerun_walltime_factor_switch
```

ISCE3 appends only `execution_mode` and `queue_class`. `queue_class` selects the generator's short or long queue option. All current jobs use one node; node count is not stored in the defaults.

For a LAUNCHER task list, `num_threads` is the number of threads used by one task. `LAUNCHER_PPN` is calculated from the selected queue's CPU and memory capacity using the existing JOB_SUBMIT limits: the smaller of tasks allowed by CPU and tasks allowed by memory. It is not copied directly from `num_threads` and is not stored as a separate defaults column.

Current default policies are:

- `download_safe`: sequential, 2 hours, restart-safe
- `create_cslc`: LAUNCHER task list, 2 hours, restart-safe
- `download_cslc`: sequential, 2 hours, restart-safe
- `run_dolphin`: single-multicore, 2 hours, restart-safe
- `download_disp`: sequential, 2 hours, restart-safe
- `reformat_disp`: sequential, 2 hours, restart-safe
- `create_hdfeos5`: single-multicore, 8 hours, restart behavior unknown
- `ingest_insarmaps`: sequential, 12 hours, restart-unsafe

Restart-safe stages use `--queue skx-dev` by default. Unknown or unsafe stages use `--long-queue skx`. Both queues can be changed when generating the workflow.

Download stages are restart-safe because existing complete products are reused and missing products can be downloaded again. COMPASS and Dolphin are currently classified as restart-safe because their existing-output checks allow them to resume. HDF-EOS5 remains conservative until partial-file behavior has been verified. InsarMaps ingest remains unsafe because a timeout may leave partially updated external state.

These classifications describe retry policy, not output validation. Operators should inspect or validate outputs before skipping prerequisite stages.

## Output validation

Each local step is validated by the runner after its run file completes. Each SLURM job performs the same validation at the end of the job. Validation failure produces a nonzero status, so dependent jobs are not started.

Validation can also be run manually from the processing directory:

```bash
validate_isce3_outputs.py
validate_isce3_outputs.py --step run_dolphin
validate_isce3_outputs.py --data-type disp --step 2
validate_isce3_outputs.py --json validation_report.json
```

The validator loads `minsar/defaults/isce3_validation.json`, expands each selected step's output patterns under the current processing directory, reports match counts, and fails if a required pattern has no matches. `--allow-empty` is intended for diagnostics.

## Failure recovery

Useful recovery patterns include:

```bash
run_isce3_workflow.bash --dostep download_disp
run_isce3_workflow.bash --start reformat_disp
validate_isce3_outputs.py --step reformat_disp
```

When a stage fails:

1. Read the stage output and the concrete run file.
2. Confirm that prerequisite outputs exist.
3. For restart-safe stages, rerun the stage with `--dostep`.
4. Validate the result.
5. Resume with `--start` at the next stage.

For SLURM, downstream `afterok` jobs remain blocked or are cancelled when an earlier job fails. Submit a new range after correcting the failed stage.

## NISAR status

`--platform NISAR` and `--platform NI` are recognized aliases. Workflow generation fails explicitly because RSLC/GSLC download and processing commands have not yet been defined. This prevents a Sentinel-1 command from being generated accidentally for a NISAR request.

NISAR support should add explicit source acquisition, product discovery, Dolphin input, expected-output, resource, and restart definitions before enabling the platform.

## Integration boundary

The ISCE2 workflow remains the production path for `minsarApp.bash --isce2`. The ISCE3 tools currently operate as standalone entry points. Future `minsarApp.bash --isce3` integration should invoke the generator and runner without duplicating stage definitions.

The generated-file boundary is:

- the generator owns step construction and job creation
- the Bash runner discovers `.job` files and owns step selection and execution/submission
- the validator reads `minsar/defaults/isce3_validation.json` and owns expected-output checks

Keeping those responsibilities separate avoids extending the current ISCE2 orchestration with ISCE3-specific conditionals before the new workflows are operationally mature.
