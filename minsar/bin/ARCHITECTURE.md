# run_workflow.bash Architecture Documentation

---

## 🚦 Current Status & TODO List

**Last Updated:** January 2026  
**Test Suite Status:** ✅ 73/73 tests passing  
**Refactoring Status:** ✅ Complete

### Completed Tasks

| Task | Status | Notes |
|------|--------|-------|
| Document architecture | ✅ Done | This file |
| Create test suite | ✅ Done | `tests/test_run_workflow.bash` (73 tests) |
| Identify issues | ✅ Done | 6 issues documented below |
| Run baseline tests | ✅ Done | All passing |
| Task 1: Fix --jobfile hack | ✅ Done | Made --jobfile first-class, early-exit path |
| Task 2: Remove special job handling | ✅ Done | mintpy/insarmaps now use jobfile mode |
| Task 3: MiaplPy associative array | ✅ Done | Replaced 18-line if-elif with 5-line array |
| Task 4: Extract shared functions | ✅ Done | Created `minsar/lib/workflow_utils.sh` |
| Task 5: Stop adding empty elements | ✅ Done | Guard added to globlist loop |

### Refactoring Tasks - COMPLETED

| # | Priority | Task | Status | Notes |
|---|----------|------|--------|-------|
| 1 | **HIGH** | Fix the "hack" - make `--jobfile` first-class | ✅ Done | Early-exit path before globlist construction |
| 2 | **HIGH** | Remove special smallbaseline/insarmaps handling | ✅ Done | Converted to jobfile mode internally |
| 3 | **MEDIUM** | Use associative array for MiaplPy step mapping | ✅ Done | `MIAPLPY_STEPS` associative array |
| 4 | **MEDIUM** | Extract shared utility functions to library | ✅ Done | `minsar/lib/workflow_utils.sh` |
| 5 | **MEDIUM** | Stop adding empty elements to globlist | ✅ Done | Guard in loop prevents empty adds |
| 6 | **LOW** | Fix hardcoded regex in sbatch_conditional | Deferred | Low priority, not blocking |

### Key Changes Summary

1. **`run_workflow.bash`**: 
   - Removed ~70 lines of utility functions (moved to shared library)
   - Simplified globlist construction (~30 lines removed)
   - Added early-exit path for `--jobfile` mode
   - Replaced if-elif chain with associative array for MiaplPy steps

2. **`submit_jobs.bash`**:
   - Removed duplicate `abbreviate` function
   - Now sources shared library

3. **New file: `minsar/lib/workflow_utils.sh`**:
   - Contains: `abbreviate`, `convert_array_to_comma_separated_string`, `remove_from_list`, `clean_array`

4. **`tests/test_run_workflow.bash`**:
   - Updated to source shared library directly

### Verification

```bash
# Run all tests to verify refactoring
cd /work2/05861/tg851601/stampede2/code/minsar
bash tests/test_run_workflow.bash

# Expected: 73/73 tests passing
```

---

## Overview

`run_workflow.bash` is the main job orchestration script for the minsar InSAR processing pipeline. It manages the submission, monitoring, and error handling of batch jobs on HPC clusters using SLURM. The script coordinates three major processing pipelines:

1. **ISCE/topsStack** - Interferogram generation (jobs `run_01` through `run_11/16`)
2. **MintPy** - Time series analysis (`smallbaseline_wrapper.job`)
3. **InsarMaps** - Visualization/upload (`insarmaps.job`)
4. **MiaplPy** - Alternative PS/DS processing pipeline (optional)

## High-Level Control Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        run_workflow.bash                             │
├─────────────────────────────────────────────────────────────────────┤
│  1. Parse Arguments (--start, --stop, --dostep, --miaplpy, etc.)   │
│  2. Determine RUNFILES_DIR (run_files/ or miaplpy/.../run_files/)  │
│  3. Build globlist[] of job file patterns to submit                │
│  4. For each pattern in globlist:                                  │
│     ├─ Submit all matching jobs via submit_jobs.bash               │
│     ├─ Monitor job states (COMPLETED, RUNNING, PENDING, etc.)      │
│     ├─ Handle TIMEOUT/NODE_FAIL by resubmitting                    │
│     ├─ Exit on FAILED/CANCELLED                                    │
│     └─ Run check_job_outputs.py to validate results                │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       submit_jobs.bash                              │
├─────────────────────────────────────────────────────────────────────┤
│  For each job file matching pattern:                               │
│     └─ Call sbatch_conditional.bash with resource checks           │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    sbatch_conditional.bash                          │
├─────────────────────────────────────────────────────────────────────┤
│  1. Check custom resource limits (jobs, tasks per step, total)     │
│  2. Run sbatch --test-only for SLURM validation                    │
│  3. Submit job if all checks pass                                  │
└─────────────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. Argument Parsing (Lines 76-237)

| Argument | Description |
|----------|-------------|
| `--start STEP` | Start processing at step (number or name like `mintpy`, `insarmaps`) |
| `--stop STEP` | Stop processing at step |
| `--dostep STEP` | Run only a single step |
| `--miaplpy` | Use MiaplPy pipeline instead of topsStack |
| `--dir DIR` | Specify MiaplPy subdirectory |
| `--jobfile FILE` | Run a single specific job file |
| `--random` | Submit jobs in random order |
| `--rapid` | Use shorter wait times (10s vs 30s) |
| `--append` | Append to existing log file |
| `--no-check-job-outputs` | Skip post-completion validation |

### 2. Run Files Directory Discovery (Lines 355-395)

For standard topsStack:
```bash
RUNFILES_DIR=$WORKDIR/run_files
```

For MiaplPy, the directory is computed from template parameters:
```bash
RUNFILES_DIR=$WORKDIR/${dir_miaplpy}/network_${network_type}/run_files
```

Where `network_type` is derived from:
- `miaplpy.interferograms.networkType` (default: `single_reference`)
- `miaplpy.interferograms.connNum` (for sequential networks)
- `miaplpy.interferograms.delaunayBaselineRatio` (for delaunay networks)

### 3. Job List Construction (Lines 397-452)

The script builds a `globlist[]` array of job file patterns:

```bash
# For numbered steps (1 to last_jobfile_number):
globlist+=("$RUNFILES_DIR/run_${stepnum}_*.job")

# For mintpy step (last_jobfile_number + 1):
globlist+=("$WORKDIR/smallbaseline_wrapper.job")

# For insarmaps step (last_jobfile_number + 2):
globlist+=("$WORKDIR/insarmaps.job")
```

### 4. Job Submission Loop (Lines 487-524)

For each glob pattern:
1. Expand glob to list of actual job files
2. Optionally shuffle for random order
3. Call `submit_jobs.bash` with the file pattern
4. Collect returned job numbers

### 5. Job Monitoring Loop (Lines 533-610)

Polls job states using `sacct` until all jobs complete:

| State | Action |
|-------|--------|
| `COMPLETED` | Increment counter |
| `RUNNING` | Continue monitoring |
| `PENDING` | Continue monitoring |
| `TIMEOUT` | Update walltime, resubmit |
| `NODE_FAIL` | Resubmit immediately |
| `FAILED` | Exit with error |
| `CANCELLED` | Exit with error |

### 6. Output Validation (Lines 612-623)

After all jobs in a step complete, runs:
```bash
check_job_outputs.py ${files[@]}
```

This Python script:
- Removes known benign error messages
- Checks for actual errors in `.e` and `.o` files
- Handles data quality issues by removing bad dates from subsequent run files
- Consolidates error files for review

---

## Known Issues & Areas for Improvement

### Issue 1: The "Hack" (Lines 458-472)

**Current Code:**
```bash
# 5/2024 hack to be able to run one jobfile
if [[ $jobfile_flag == "true" ]]; then
    if [[ -n $jobfile ]]; then
        globlist=("$jobfile")
        # if it's not already a *.job file, append the pattern
        if [[ ${globlist[0]} != *job ]]; then
            globlist[0]="${globlist[0]}*.job"
        fi
        echo "--jobfile hack applies: replaced full list by jobfile $jobfile"
    else
        # explicitly empty array if jobfile is unset/empty
        globlist=()
        echo "--jobfile flag true but no jobfile provided → globlist is empty"
    fi
fi
```

**Problems:**
1. Called a "hack" in the code itself - indicates it's a workaround, not a proper solution
2. Appends `*.job` glob pattern to non-job files which is fragile
3. The `--jobfile` path was already validated earlier (lines 208-223), making this double-handling confusing
4. It completely replaces the carefully-constructed `globlist`, bypassing all the step logic

**Recommended Fix:**
Handle `--jobfile` mode as a first-class feature by checking it BEFORE building the globlist:

```bash
# Early exit path for single jobfile mode
if [[ $jobfile_flag == "true" ]]; then
    if [[ ! -f "$jobfile" ]]; then
        echo "ERROR: jobfile '$jobfile' not found. Exiting."
        exit 1
    fi
    # Single jobfile mode - skip all globlist construction
    submit_and_monitor_jobs "$jobfile"
    exit $?
fi

# Normal mode: construct globlist from steps...
```

---

### Issue 2: Special Treatment of smallbaseline.job and insarmaps.job (Lines 423-450)

**Current Code:**
```bash
for (( i=$startstep; i<=$stopstep; i++ )) do
    stepnum="$(printf "%02d" ${i})"
    if [[ $i -le $last_jobfile_number ]]; then
        fname="$RUNFILES_DIR/run_${stepnum}_*.job"
    elif [[ $i -eq $((last_jobfile_number+1)) ]]; then
        fname="$WORKDIR/smallbaseline_wrapper.job"  # ← Special case
    else
        fname="$WORKDIR/insarmaps.job"              # ← Special case
    fi
    globlist+=("$fname")
done

# Later, additional cleanup required:
if [[ "${globlist[*]}" == *"run_"* ]]; then
    globlist=("${globlist[@]/$WORKDIR\/smallbaseline_wrapper.job/}")
    globlist=("${globlist[@]/$WORKDIR\/insarmaps.job/}")
fi
```

**Problems:**
1. Creates virtual "step numbers" for non-run_file jobs (last+1, last+2)
2. Requires cleanup logic to remove them when not needed
3. The special step names `mintpy` and `insarmaps` are hardcoded in multiple places
4. Inconsistent with `--jobfile` mode which can already submit these directly

**The Comment on Line 435 Confirms This:**
```bash
# FA 9/2025: The above inserted empty elements which are removed below. 
# I think we can remove all reference to smallbaseline and insarmaps
```

**Recommended Fix:**
Since `--jobfile` already supports running any job directly, the special treatment is unnecessary:

```bash
# Users can already do:
run_workflow.bash --jobfile smallbaseline_wrapper.job
run_workflow.bash --jobfile insarmaps.job

# So we can simplify step handling to ONLY numbered run files:
for (( i=$startstep; i<=$stopstep; i++ )) do
    stepnum="$(printf "%02d" ${i})"
    fname="$RUNFILES_DIR/run_${stepnum}_*.job"
    globlist+=("$fname")
done
```

The `--start mintpy` and `--start insarmaps` shortcuts can be converted to `--jobfile` mode internally.

---

### Issue 3: Duplicated Utility Functions

The `abbreviate` function is defined identically in:
- `run_workflow.bash` (lines 4-10)
- `submit_jobs.bash` (lines 3-9)
- `sbatch_conditional.bash` (referenced in rename_stderr_stdout_file)

**Recommended Fix:**
Move common functions to a shared library:
```bash
# minsar/lib/workflow_utils.sh
source "$MINSAR_HOME/minsar/lib/workflow_utils.sh"
```

---

### Issue 4: Complex Step Name to Number Mapping (Lines 276-305)

MiaplPy step names are converted to numbers via a large if-elif chain:
```bash
if [[ $startstep == "load_data" ]]; then               startstep=1
elif [[ $startstep == "phase_linking" ]]; then         startstep=2
# ... 9 more conditions
```

**Recommended Fix:**
Use an associative array:
```bash
declare -A MIAPLPY_STEPS=(
    [load_data]=1
    [phase_linking]=2
    [concatenate_patches]=3
    [generate_ifgram]=4
    [unwrap_ifgram]=5
    [load_ifgram]=6
    [ifgram_correction]=7
    [invert_network]=8
    [timeseries_correction]=9
)

if [[ -n "${MIAPLPY_STEPS[$startstep]}" ]]; then
    startstep="${MIAPLPY_STEPS[$startstep]}"
fi
```

---

### Issue 5: Error-Prone Array Cleaning (Lines 436-450)

Multiple attempts to clean empty elements from arrays:
```bash
tmp=()
for g in "${globlist[@]}"; do
    [[ -n $g ]] && tmp+=("$g")
done
globlist=("${tmp[@]}")

# And again later with clean_array function
clean_array globlist
```

**Recommended Fix:**
Don't add empty elements in the first place. Validate before adding to globlist.

---

### Issue 6: Hardcoded Pattern Matching in sbatch_conditional.bash (Line 142)

```bash
step_name=$(echo $job_file | grep -oP "(?<=run_\d{2}_)(.*)(?=_\d{1,}.job)|smallbaseline_wrapper|insarmaps|ingest_insarmaps|horzvert_timeseries|create_miaplpy_jobfiles")
```

This regex must be updated every time a new special job type is added.

**Recommended Fix:**
Derive step name from job file metadata or use a consistent naming convention.

---

## Refactoring Proposal

### Phase 1: Consolidate Job Handling

Create a unified `JobRunner` class/module that handles:
1. Single job mode (`--jobfile`)
2. Step range mode (`--start/--stop`)
3. Named step mode (`--start mintpy`)

```python
# Proposed: minsar/workflow/job_runner.py
class JobRunner:
    def __init__(self, work_dir, template_file=None):
        self.work_dir = work_dir
        self.template_file = template_file
        
    def run_single_job(self, jobfile):
        """Run a single job file and wait for completion"""
        
    def run_step_range(self, start, stop):
        """Run all jobs from step 'start' to 'stop'"""
        
    def run_named_step(self, step_name):
        """Run a named step (mintpy, insarmaps, etc.)"""
```

### Phase 2: Configuration-Driven Steps

Move step definitions to a configuration file:

```yaml
# minsar/defaults/workflow_steps.yml
topsstack:
  steps:
    - name: unpack_topo_reference
      pattern: run_01_*.job
    - name: unpack_secondary_slc
      pattern: run_02_*.job
    # ...
  special_jobs:
    mintpy:
      file: smallbaseline_wrapper.job
      after: last_numbered_step
    insarmaps:
      file: insarmaps.job
      after: mintpy

miaplpy:
  steps:
    - name: load_data
      pattern: run_01_*.job
    # ...
```

### Phase 3: Improve Testability

Extract pure functions that can be unit tested:
- `build_job_list(start, stop, runfiles_dir) -> list[str]`
- `parse_step_name(name, pipeline) -> int`
- `monitor_job_state(job_id) -> JobState`

---

## Testing

### Running the Test Suite

A comprehensive test suite is available in `tests/test_run_workflow.bash`. To run all tests:

```bash
# From the minsar repository root:
cd /path/to/minsar
bash tests/test_run_workflow.bash
```

Or with explicit path:

```bash
bash /path/to/minsar/tests/test_run_workflow.bash
```

### Test Results Summary

The test suite includes **73 tests** covering:

| Category | Tests | Description |
|----------|-------|-------------|
| Help & Usage | 6 | Verify help flag and documentation |
| Utility Functions | 7 | `abbreviate`, `remove_from_list`, `clean_array`, etc. |
| Globlist Construction | 10 | Job file pattern generation for various scenarios |
| MiaplPy | 12 | Step mapping and directory structure |
| Single Job Mode | 2 | `--jobfile` functionality |
| Special Jobs | 4 | `smallbaseline_wrapper.job`, `insarmaps.job` handling |
| Step Detection | 4 | Last job number, step shortcuts |
| Argument Parsing | 9 | Various CLI argument combinations |
| Regression Tests | 15 | Format preservation for refactoring |
| Integration | 4 | End-to-end workspace validation |

**Expected Output:**

Each test displays clearly with:
- `TEST START:` header with test name and description
- `[Action]`, `[Check]`, `[Scenario]`, `[Expected]` tags explaining what's happening
- `✓ PASS` or `✗ FAIL` for each assertion
- `TEST END:` footer

```
╔════════════════════════════════════════════════════════════════════╗
║ TEST START: Help Flag
╠════════════════════════════════════════════════════════════════════╣
║ Verifies that 'run_workflow.bash --help' shows usage info and exits cleanly.
╚════════════════════════════════════════════════════════════════════╝
  [Action] Running: run_workflow.bash --help
  [Check] Verifying help output contains expected sections...
  ✓ PASS: Help exits with code 0 (success)
  ✓ PASS: Help contains 'Job submission script'
  ...
└── TEST END: Help Flag
```

**Final Summary:**
```
╔══════════════════════════════════════════════════════════════════════════╗
║                          TEST RESULTS SUMMARY                            ║
╠══════════════════════════════════════════════════════════════════════════╣
║  Total tests run:               73                                       ║
║  Passed:                        73                                       ║
║  Failed:                        0                                        ║
╚══════════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════════╗
║                        ✅ ALL TESTS PASSED ✅                            ║
╚══════════════════════════════════════════════════════════════════════════╝
```

### Test Categories Explained

#### 1. Utility Function Tests

Tests for the shared bash functions extracted from `run_workflow.bash`:

```bash
test_abbreviate_function()              # String truncation with ellipsis
test_remove_from_list_function()        # Array element removal
test_convert_array_to_comma_separated() # Array to string conversion
test_clean_array_function()             # Empty element removal
```

#### 2. Globlist Construction Tests

Verifies correct job file patterns are generated:

```bash
test_globlist_construction_basic()      # 11-step topsStack workflow
test_globlist_with_start_stop()         # --start 5 --stop 8 range
test_last_jobfile_number_detection()    # Detects 11 vs 16 step workflows
```

#### 3. MiaplPy Tests

Tests specific to the MiaplPy pipeline:

```bash
test_miaplpy_step_mapping()             # Step names → numbers (load_data→1, etc.)
test_miaplpy_directory_structure()      # network_single_reference/run_files/
```

#### 4. Regression Tests (Critical for Refactoring)

These tests capture current behavior that MUST be preserved:

```bash
test_regression_globlist_output()       # Glob pattern format must not change
test_regression_miaplpy_directory_naming() # Directory naming conventions
test_regression_special_job_handling()  # --jobfile support for special jobs
```

### Adding New Tests

To add tests, edit `tests/test_run_workflow.bash`:

```bash
test_my_new_feature() {
    echo -e "\n${YELLOW}Test: My new feature${NC}"
    
    setup_test_workspace
    # ... setup mock environment
    
    # Run assertions
    assert_equals "expected" "$actual" "Description"
    assert_contains "$output" "substring" "Description"
    assert_file_exists "$path" "Description"
    
    teardown_test_workspace
}

# Add to run_all_tests():
run_all_tests() {
    # ... existing tests ...
    test_my_new_feature
}
```

### Test Framework Functions

| Function | Description |
|----------|-------------|
| `setup_test_workspace` | Creates temp directory for test |
| `teardown_test_workspace` | Cleans up temp directory |
| `create_mock_run_files DIR [N]` | Creates N-step mock job files |
| `create_mock_miaplpy_run_files DIR TYPE` | Creates MiaplPy structure |
| `assert_equals EXPECTED ACTUAL MSG` | Exact match assertion |
| `assert_contains HAYSTACK NEEDLE MSG` | Substring assertion |
| `assert_not_contains HAYSTACK NEEDLE MSG` | Negative substring assertion |
| `assert_file_exists PATH MSG` | File existence assertion |
| `assert_exit_code EXPECTED ACTUAL MSG` | Exit code assertion |

### Before/After Refactoring Workflow

1. **Before refactoring:** Run all tests to establish baseline
   ```bash
   bash tests/test_run_workflow.bash > baseline_results.txt
   ```

2. **During refactoring:** Run tests frequently to catch regressions
   ```bash
   bash tests/test_run_workflow.bash
   ```

3. **After refactoring:** Compare with baseline
   ```bash
   bash tests/test_run_workflow.bash > refactored_results.txt
   diff baseline_results.txt refactored_results.txt
   ```

### Future Test Improvements

| Priority | Test Type | Description |
|----------|-----------|-------------|
| High | Mock SLURM | Test job submission without actual cluster |
| High | Error Handling | Test TIMEOUT, FAILED, CANCELLED states |
| Medium | check_job_outputs.py | Python unit tests for output validation |
| Medium | End-to-end | Test with real sample data (CI/CD) |
| Low | Property-based | Fuzz testing for argument parsing |

---

## Files Involved

| File | Purpose |
|------|---------|
| `minsar/bin/run_workflow.bash` | Main orchestration script |
| `minsar/bin/submit_jobs.bash` | Batch job submission with retries |
| `minsar/bin/sbatch_conditional.bash` | Resource-checked sbatch wrapper |
| `minsar/scripts/check_job_outputs.py` | Output validation |
| `minsar/defaults/job_defaults.cfg` | Walltime/memory defaults |
| `minsar/defaults/queues.cfg` | Queue resource limits |
| `tests/test_run_workflow.bash` | Test suite for run_workflow.bash |

---

## Summary of Recommended Changes

| Priority | Change | Impact | Status |
|----------|--------|--------|--------|
| **High** | Remove special smallbaseline/insarmaps handling | Simplifies code, removes fragile cleanup | Pending |
| **High** | Refactor `--jobfile` to be first-class mode | Eliminates the "hack" | Pending |
| **Medium** | Extract shared utility functions | Reduces duplication | Pending |
| **Medium** | Use associative arrays for step mapping | More maintainable | Pending |
| **Medium** | Add configuration-driven step definitions | Easier to extend | Pending |
| **Low** | Convert core logic to Python | Better testability | Pending |
| ~~Low~~ | ~~Add comprehensive test suite~~ | ~~Prevents regressions~~ | ✅ Done |

### Completed: Test Suite

A comprehensive test suite (`tests/test_run_workflow.bash`) has been implemented with 73 tests covering:
- Utility functions
- Argument parsing
- Globlist construction
- MiaplPy step mapping
- Regression tests for before/after refactoring

Run with: `bash tests/test_run_workflow.bash`

---

## 📋 Detailed Refactoring Instructions

### Task 1: Fix the "Hack" (HIGH PRIORITY)

**Goal:** Make `--jobfile` a first-class feature instead of a late-stage override.

**Current Location:** `run_workflow.bash` lines 458-472

**Current Problem:**
```bash
# 5/2024 hack to be able to run one jobfile
if [[ $jobfile_flag == "true" ]]; then
    globlist=("$jobfile")  # ← Completely replaces carefully-built globlist
    ...
```

**Suggested Fix:**
1. Move `--jobfile` handling to BEFORE the globlist construction (around line 395)
2. Create early-exit path that skips globlist building entirely
3. The job file path is already validated at lines 208-223, so reuse that

**Implementation Sketch:**
```bash
# Add around line 395, BEFORE "RUNFILES_DIR=$WORKDIR..."
if [[ $jobfile_flag == "true" ]]; then
    echo "Single job file mode: $jobfile"
    globlist=("$jobfile")
    # Skip directly to the submission loop (line 487)
    # OR extract submission into a function and call it here
fi
```

**Test to verify:** `test_jobfile_single_file_mode`, `test_regression_special_job_handling`

---

### Task 2: Remove Special smallbaseline/insarmaps Handling (HIGH PRIORITY)

**Goal:** Remove the virtual "step numbers" for mintpy and insarmaps.

**Current Location:** `run_workflow.bash` lines 406-420, 423-450

**Current Problem:**
- `mintpy` is treated as step `last_jobfile_number + 1`
- `insarmaps` is treated as step `last_jobfile_number + 2`
- This creates empty elements that need cleanup (lines 436-450)
- The code author already noted on line 435: "I think we can remove all reference to smallbaseline and insarmaps"

**Suggested Fix:**
1. When user specifies `--start mintpy`, convert to `--jobfile smallbaseline_wrapper.job`
2. When user specifies `--start insarmaps`, convert to `--jobfile insarmaps.job`
3. Remove lines 427-431 (the elif branches for special jobs)
4. Remove lines 443-450 (the cleanup logic)

**Implementation Sketch:**
```bash
# Around line 406-420, replace the mintpy/insarmaps step number logic with:
if [[ $startstep == "mintpy" ]]; then
    jobfile_flag=true
    jobfile="$WORKDIR/smallbaseline_wrapper.job"
    # Will be handled by Task 1's early-exit path
elif [[ $startstep == "insarmaps" ]]; then
    jobfile_flag=true
    jobfile="$WORKDIR/insarmaps.job"
fi
```

**Test to verify:** `test_step_name_shortcuts`, `test_regression_special_job_handling`

---

### Task 3: Use Associative Array for MiaplPy Steps (MEDIUM PRIORITY)

**Goal:** Replace 18-line if-elif chain with 10-line associative array.

**Current Location:** `run_workflow.bash` lines 276-305

**Suggested Fix:**
```bash
# Replace lines 276-305 with:
declare -A MIAPLPY_STEPS=(
    [load_data]=1 [phase_linking]=2 [concatenate_patches]=3
    [generate_ifgram]=4 [unwrap_ifgram]=5 [load_ifgram]=6
    [ifgram_correction]=7 [invert_network]=8 [timeseries_correction]=9
)

if [[ $miaplpy_flag == "true" ]]; then
    [[ -n "${MIAPLPY_STEPS[$startstep]}" ]] && startstep="${MIAPLPY_STEPS[$startstep]}"
    [[ -n "${MIAPLPY_STEPS[$stopstep]}" ]] && stopstep="${MIAPLPY_STEPS[$stopstep]}"
fi
```

**Test to verify:** `test_miaplpy_step_mapping`

---

### Task 4: Extract Shared Utility Functions (MEDIUM PRIORITY)

**Goal:** Move duplicated functions to shared library.

**Affected Files:**
- `run_workflow.bash` lines 4-73 (utility functions)
- `submit_jobs.bash` lines 3-9 (`abbreviate` function)

**Suggested Fix:**
1. Create `minsar/lib/workflow_utils.sh`
2. Move `abbreviate`, `remove_from_list`, `convert_array_to_comma_separated_string`, `clean_array` there
3. Add `source "$MINSAR_HOME/minsar/lib/workflow_utils.sh"` to both scripts

**Test to verify:** `test_abbreviate_function`, `test_remove_from_list_function`, etc.

---

### Task 5: Stop Adding Empty Elements to globlist (MEDIUM PRIORITY)

**Goal:** Validate before adding instead of cleaning after.

**Current Location:** `run_workflow.bash` lines 423-450

**Current Problem:** Loop adds elements, then multiple cleanup passes remove empties.

**Suggested Fix:** Check if file pattern matches anything before adding:
```bash
for (( i=$startstep; i<=$stopstep; i++ )) do
    stepnum="$(printf "%02d" ${i})"
    fname="$RUNFILES_DIR/run_${stepnum}_*.job"
    # Only add if pattern matches files
    if compgen -G "$fname" > /dev/null; then
        globlist+=("$fname")
    fi
done
```

**Test to verify:** `test_clean_array_function`, `test_regression_globlist_output`

---

## 🔧 Refactoring Workflow Summary

```
┌─────────────────────────────────────────────────────────────────┐
│  BEFORE EACH CHANGE:  bash tests/test_run_workflow.bash        │
│  AFTER EACH CHANGE:   bash tests/test_run_workflow.bash        │
│  IF TESTS FAIL:       git checkout -- <file>  (revert)         │
└─────────────────────────────────────────────────────────────────┘

Recommended order:
  1. Task 1 (--jobfile first-class) ← Enables Task 2
  2. Task 2 (remove special jobs)   ← Biggest simplification  
  3. Task 3 (associative arrays)    ← Quick win
  4. Task 4 (shared library)        ← Can do anytime
  5. Task 5 (no empty elements)     ← May be automatic after Task 2
```
