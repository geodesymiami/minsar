# MinSAR

InSAR processing pipeline. `$MINSAR_HOME` is the repository root (contains `minsar/`, `setup/`, `additions/`).

## Read first

- `architecture_docs/README.md` - quick reference and lookup tables
- `architecture_docs/OVERVIEW.md` - high-level architecture
- `architecture_docs/FILE_STRUCTURE.md` - repository layout
- `architecture_docs/WORKFLOW_ARCHITECTURE.md` - job submission system
- `architecture_docs/KEY_CONCEPTS.md` - terminology
- `architecture_docs/DEVELOPMENT_GUIDE.md` - coding conventions and testing
- `minsar/bin/ARCHITECTURE.md` - `run_workflow.bash` internals

| Entry point | Purpose |
|---|---|
| `minsar/bin/minsarApp.bash` | Main entry point |
| `minsar/bin/run_workflow.bash` | Job orchestration |
| `minsar/bin/submit_jobs.bash` | Batch submission |
| `minsar/bin/sbatch_conditional.bash` | Resource-checked sbatch |

Configuration: `minsar/defaults/job_defaults.cfg` (walltime, memory per job), `minsar/defaults/queues.cfg` (queue limits), `samples/*.template` (example templates).

File-type rules (Bash, Python CLIs and AOI arguments, tests, overlay debug table, sweets config) are in `.claude/rules/` and load when matching files are touched.

## Working rules

- **Implement without asking.** Outside plan mode, do the requested work; do not ask whether to implement or wait for plan approval. In plan mode, present a short plan (summary, files affected, steps, risks) and wait.
- **`scripts/…` and `utils/…` mean `minsar/scripts/…` and `minsar/utils/…`.** Do not create a top-level `scripts/` or `utils/` unless explicitly asked.
- **Do not create or update `PLAN.md`** or other git-tracked plan files. They cause merge conflicts across servers. Plan in chat only.
- **Do not create or extend tests** unless explicitly asked in this request: no new `test_*.py` / `test_*.bash`, no new cases or fixtures in existing files, no registering suites in `run_all_tests.bash` or `tests/run_bash_tests.bash`. A shell smoke check (`--help`, `--dry-run`) is fine, and so is running an existing suite that already covers the change.
- **Do not routinely edit `architecture_docs/`** (especially `FILE_STRUCTURE.md`); it causes merge conflicts across servers. Update only when asked, or for a substantial architecture change where docs were approved as part of the plan.
- **Exception:** when changing `minsar/scripts/check_burst2safe_job_outputs.py` (error strings, output files, behavior), read and update `docs/README_burst_download.md`.
- **Ask before deleting any file.**
- **Ask before adding backward compatibility.** No dual-format parsing, legacy fallbacks, or "also accepts X" without approval.
- **Never modify legacy copies** unless the exact file path is named: everything under `minsar/unused/`, scripts whose basename starts with `old` (e.g. `oldminsarApp.bash`), and legacy copies named `q` + a real script's basename (e.g. `qrun_workflow`). Do not sync or "fix" them for consistency.
- **Refactoring** is OK when localized: extracting functions, not rewriting architecture or changing widely used interfaces.
- **New `.py`, `.bash`, `.sh` scripts must be executable:** `chmod +x` right after creating, copying or moving one.

## Git

Commit after each code change, in the same turn, without being asked. Skip for question-only or read-only turns, when told not to commit, or when there is nothing to commit.

- One short message (about one line), in the tone of recent `git log`. Say why, not a file list.
- `git add` explicit paths. No `git add -A` unless every change belongs in the commit.
- Pass the message with a heredoc. Do not skip hooks. Do not push unless asked.
- Never change git config. No force-push. No amend unless asked.

## Chat output

- End every summary of changes with `Files modified: path/to/a.bash, path/to/b.py`.
- For edits to `minsar/bin/minsarApp.bash`, show a short before/after in chat (old lines, then new lines) for each substantive edit.
- Put shell commands and copy-paste snippets on **one line** each. No `\` continuations, no flags on following lines.
- Plans read as a first draft: state only the current design. No "previously", "changed from", "instead of X", change logs or "updated:" markers. When a plan is revised, rewrite the affected sections in place.
- "This notebook" / "the notebook" without a path means the currently open notebook in the editor. Do not guess from chat history or recently modified files; if none is open, ask.

## Running and debugging

- **`cd` to the right directory before rerunning a script.** Several launchers use `WORKDIR=$(pwd)` to decide where logs and jobfiles go.
- **When a change to a bash function or sourced helper (`minsar/lib/*.sh`, `environment.bash`) seems not to work, first ask whether the user re-sourced** (e.g. `source $MINSAR_HOME/setup/environment.bash`). Behavior matching the old code usually means a stale shell. Only then look for logic bugs.
- **Environments:** Stampede3 uses SLURM (`sbatch`/`srun`; check `#SBATCH --mem`, `sacct`, `scontrol show job` for OOM or limits). Jetstream is a plain Linux server with no SLURM; jobs run directly on the node (`free -h`; `dmesg` may be restricted). For "Killed" or resource problems, consider which one the job ran on.
- **Workflow nuances:**
  - MiaplPy needs the template file: `run_workflow.bash $TE/file.template --miaplpy`
  - `--jobfile` is a special path that bypasses the step logic
  - NESD has 16 steps, geometry 11, depending on `topsStack.coregistration`
  - The MiaplPy run directory varies: `miaplpy/network_<type>/run_files/`
- **Tests:** run the relevant existing suite when it covers the area you changed.

```bash
./run_all_tests.bash
./run_all_tests.bash --python-only
./run_all_tests.bash --bash-only
bash tests/run_bash_tests.bash test_run_workflow.bash
```

## Code style

- Keep comments and output messages short. Comments explain why, not what; drop obvious ones. No progress chatter (`"Cleaning up..."`, `"Removed"`) and no advice in messages:
  - Bad: `echo "Skipping conversion - use a different output name or delete existing file"`
  - Good: `echo "Output file already exists: $OUTPUT_FILE_ABS"`
- Prefer self-documenting names over comments.
- Temporary directories go in the working directory, not `/tmp`, with an absolute path: `TEMP_DIR="$(cd "$WORK_DIR" && pwd)/tmp_<purpose>_$$_${RANDOM}"`.
- Every Python and Bash script supports `--help`, very concise, in this order: usage synopsis, description and options, examples. Under a single `Examples:` heading put command lines only: no labels, notes, comments, prose or blank lines between them.

```text
usage: script.py [-h] [--opt VALUE] FILE

Does one thing. Concise.

options:
  -h, --help     show this help
  --opt VALUE    ...

Examples:
  script.py --opt 1 file.txt
  script.py file.txt
```
