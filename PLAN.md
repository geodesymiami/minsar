# Plan: Use bare `horzvert_timeseries.bash` in horzvert jobfile creator

## Summary
Adjust `create_horzvert_timeseries_jobfile.py` so the generated jobfile invokes `horzvert_timeseries.bash` by bare name (relying on `PATH`), instead of resolving it to an absolute repo-relative path.

## Key Components Affected
- `minsar/scripts/create_horzvert_timeseries_jobfile.py`
  - Replace `_resolve_horzvert_timeseries_bash()` usage with fixed command `horzvert_timeseries.bash`
  - Optionally remove now-unused resolver helper and imports (`Path`, `shutil`) to keep lint clean.

## Action Items
- [ ] Update `create_horzvert_timeseries_jobfile.py` to set `hv_bash = "horzvert_timeseries.bash"`
- [ ] Remove `_resolve_horzvert_timeseries_bash()` helper and related unused imports if no longer needed
- [ ] Run `python3 -m py_compile` on the modified script

## Execution Plan (Detailed Change Instructions)
1. Edit `/work2/05861/tg851601/stampede2/code/minsar/minsar/scripts/create_horzvert_timeseries_jobfile.py`:
   1. Remove (or stop using) `_resolve_horzvert_timeseries_bash()`.
   2. In `main()`, set:
      - `hv_bash = "horzvert_timeseries.bash"`
      - `command_parts = [hv_bash, inps.file1, inps.file2]`
2. If the resolver helper is removed, also remove related imports (`shutil`, `Path`) to avoid dead code / lint warnings.
3. Validate syntax with:
   - `python3 -m py_compile minsar/scripts/create_horzvert_timeseries_jobfile.py`

## Key Commands & Flows
- Flow remains the same: Python script builds the final job command line; job submission uses `JOB_SUBMIT.submit_script(...)`.
- Only the `horzvert_timeseries.bash` invocation token changes.

## TODO List
- [ ] Write/adjust tests (if existing ones cover this generator)
- [ ] Implement the edit after approval
- [ ] Run full test suite if feasible in this environment

# Plan: Split ASF burst output into download_asf_burst.sh and pack_bursts.sh

## Summary

`generate_download_command.py` currently writes a single `download_asf_burst.sh` that does both (1) ASF burst download and (2) burst2safe jobfile creation, run_workflow, check, and rerun. We will split this into two scripts for asf-burst: **download_asf_burst.sh** (download only) and **pack_bursts.sh** (burst2safe/pack steps), and add a trailing comment in pack_bursts.sh pointing to the future scripts/pack_bursts.bash.

## Key Components Affected

- `minsar/scripts/generate_download_command.py` – ASF burst block: trim download_asf_burst.sh content and add pack_bursts.sh generation.
- `minsar/bin/minsarApp.bash` – already runs `./download_asf_burst.sh` for download and `pack_bursts.bash SLC` for preprocessing; no change needed if we keep download_asf_burst.sh runnable and document that pack_bursts.sh is the generated script that will be replaced by scripts/pack_bursts.bash.
- `docs/README_burst_download.md` – optional: mention the two generated scripts (download_asf_burst.sh, pack_bursts.sh).

## Action Items

- [ ] In `generate_download_command.py`: make `download_asf_burst.sh` contain only shebang, mkdir, set -e, and the three asf_download.sh lines (--print, --download x2).
- [ ] In `generate_download_command.py`: create `pack_bursts.sh` with: bursts_to_burst2safe_jobfile.py SLC; run_workflow.bash --jobfile $work_dir/SLC/run_01_burst2safe --no-check-job-outputs; check_burst2safe_job_outputs.py SLC; if-block for rerun_burst2safe.sh; final comment "Need to convert to scripts/pack_bursts.bash SLC".
- [ ] chmod +x pack_bursts.sh in the script.
- [ ] Update docs/README_burst_download.md to mention the two scripts (brief).

## Execution Plan

1. **download_asf_burst.sh**  
   In `generate_download_command.py`, replace the current single-file block (lines ~105–128) so that the file written to `download_asf_burst.sh` contains only:
   - `#!/usr/bin/env bash`
   - `mkdir -p SLC`
   - `set -e`
   - asf_download.sh ... --print >SLC/asf_burst_listing.txt
   - asf_download.sh ... --download 2>asf_burst_download1.e
   - asf_download.sh ... --download 2>asf_burst_download2.e  
   Remove from this file: bursts_to_burst2safe_jobfile.py, run_workflow.bash, check_burst2safe_job_outputs.py, the if/rerun block, and the commented lines.

2. **pack_bursts.sh**  
   After writing `download_asf_burst.sh`, write `pack_bursts.sh` with:
   - Shebang and set -e if desired (user did not specify; we can use same style as download script).
   - `bursts_to_burst2safe_jobfile.py SLC`
   - `run_workflow.bash --jobfile {inps.work_dir}/SLC/run_01_burst2safe --no-check-job-outputs`
   - `check_burst2safe_job_outputs.py SLC`
   - `if [[ -s SLC/run_01_burst2safe_timeout_0 ]]; then` / `rerun_burst2safe.sh SLC/run_01_burst2safe_timeout_0.job` / `fi`
   - Final line: comment `# Need to convert to scripts/pack_bursts.bash SLC`
   - os.chmod('pack_bursts.sh', 0o755)

3. **Docs**  
   In docs/README_burst_download.md, add a short note that generate_download_command.py produces download_asf_burst.sh (download only) and pack_bursts.sh (burst2safe + run_workflow + check + rerun), and that the latter is intended to be replaced by scripts/pack_bursts.bash.

## Key Commands & Flows

- `generate_download_command.py $template --delta-lat 0.0 --delta-lon 0.0` → creates download_asf_burst.sh and pack_bursts.sh in work_dir.
- minsarApp.bash: download step runs ./download_asf_burst.sh; preprocessing step runs pack_bursts.bash SLC (existing script in bin or scripts). The generated pack_bursts.sh is the inline equivalent until scripts/pack_bursts.bash exists.

## TODO List

- [ ] Implement changes in generate_download_command.py
- [ ] Update docs/README_burst_download.md
- [ ] Run tests if any cover generate_download_command or download step
