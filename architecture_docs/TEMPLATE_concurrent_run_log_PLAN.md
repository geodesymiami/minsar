# Plan: TEMPLATES / project run ledger (TEMPLATE_log)

## Summary

You run several `minsarApp.bash …` invocations **in AOI mode in parallel**. Each flow eventually enters **template mode** under `$WORK_DIR`/project name derived from template basename. It is difficult to tell which runs have **started**, which are **still running**, and which **completed successfully**.

This plan adds a **lightweight ledger** appended to **`$TEMPLATES/log`** at **run start** and **successful completion**, and mirrored notes under **`PROJECT_DIR`/log** (or a dedicated **`run_ledger`** file in the project workspace) while keeping behavior compatible with the future **`nested_loop` refactor** ([`architecture_docs/nested_loop_PLAN.md`](nested_loop_PLAN.md)): one parent shell may process multiple stacks sequentially; ledger entries must distinguish **overall AOI invocation**, **each stack iteration**, or both as you prefer.

Design goals:

- Visible in **one place** (`$TEMPLATES/log`) without opening each scratch dir.
- Durable correlation: PID, hostname, `$SCRATCHDIR` project folder, optional job id (`SLURM_JOB_ID`), and a **completion line** guaranteed on success paths.
- Address the gap: entries that belong to “submitted vs finished” workflows now missing from `TEMPLATES/log` until someone manually checks scratch.

Assume **`nested_loop` is implemented:** a single bash process runs N stacks—ledger should optionally emit **per-stack begin/end** markers under the **same AOI correlation id**.

---

## Key components affected

| Area | Responsibility |
|------|----------------|
| `minsar/scripts/minsarapp_aoi_entry.py` | Already appends AOI argv to `$TEMPLATES/log` early; extend with structured **BEGIN** markers and a unique **CORRELATION_ID** passed into env for template mode (`export MINSAR_RUN_ID=…`). |
| `minsar/bin/minsarApp.bash` | After `cd $WORK_DIR` and parsing args, emit **TEMPLATE_MODE_BEGIN** before long work; on successful termination path (explicit trap + normal exit zero), emit **COMPLETE** lines to `$TEMPLATES/log` **and** project log. Consider `EXIT` trap for FAILURE without duplicating SUCCESS. |
| `minsar/lib/minsarApp_specifics.sh` or minimal `minsar/lib/run_ledger.sh` | Encapsulate `append_ledger(direction, phase, payload)` → centralize path, flock, timestamp ISO8601, JSON line or prefixed text. |
| Optional: `architecture_docs/` | Workflow doc + naming of ledger fields. |

---

## Log format recommendation

Use **one append-only UTF-8 file** `$TEMPLATES/log` plus append to **`$WORK_DIR/log`** (already tee’d extensively) OR a **`$WORK_DIR/run_ledger.txt`** sidecar so completion lines survive log noise.

Suggested line prefix (easy to grep, no jq):

```text
MINSAR_RUN <utcISO> CORR=<uuid> PHASE=BEGIN SCOPE=aoi_argv USER=$USER HOST=$HOSTNAME SCRIPT=minsarApp.bash ARGS=...
MINSAR_RUN <utcISO> CORR=<uuid> PHASE=BEGIN SCOPE=template_stack TEMPLATE=<path> WORK_DIR=<path> IDX=1/N STACK_LABEL=...
MINSAR_RUN <utcISO> CORR=<uuid> PHASE=END STATUS=SUCCESS SCOPE=template_stack WORK_DIR=<path> IDX=1/N EXIT=0
MINSAR_RUN <utcISO> CORR=<uuid> PHASE=END STATUS=SUCCESS SCOPE=overall EXIT=0
```

**Correlation id:** generate in Python AOI entry (`uuid.uuid4()`), export `MINSAR_RUN_CORR`; bash propagates unchanged across loop iterations. For pure template-first (no AOI), synthesize corr in bash or skip AOI-only BEGIN.

**Concurrency:** parallel runs must append safely → `flock` on `$TEMPLATES/log` optional but recommended under NFS if multiple hosts share `TEMPLATES` (might not—but cheap insurance).

---

## Root cause hypothesis: completion missing after “submission”

If “completed job does not appear” after workloads that primarily **submit** SLURM steps and exit early:

- `minsarApp.bash` may **exit successfully** immediately after spawning chunk jobs (`--chunks`), or SLURM steps complete later while bash already exited with **SUCCESS** ledger missing because completion write only runs at final line.
- Conversely, some paths `exit 1` from `run_command` without flushing TEMPLATES ledger.

Mitigations in implementation phase:

1. Decide **truth** for SUCCESS: bash exit 0 **after workflow steps you consider “hands-off complete”**, vs **after all children complete** — document clearly; for chunk mode, ledger should likely say **`PHASE=BATCH_SUBMITTED`** vs **`PHASE=WORKFLOW_COMPLETE`**.

2. Add **trap EXIT** handlers: normalize `EXIT` code; write `STATUS=FAILED`/`STATUS=SUCCESS` appropriately; dedupe SUCCESS (don't write SUCCESS twice).

3. If async SLURM is expected, optionally add **`run_workflow.bash`** or job-end hooks into project dir only (narrower scope) unless you unify “job done” externally.

---

## Action items

- [ ] Define scope: AOI-only ledger vs template-first single-file entry as well (`CORR` still useful).
- [ ] Add **`MINSAR_RUN_CORR`** (and optionally `STACK_IDX`/`STACK_TOTAL` when `nested_loop` runs).
- [ ] Implement `minsar_append_run_ledger` shell function using `mkdir -p` on `dirname TEMPLATES` (already assumed), tee-friendly messages.
- [ ] Python: augment existing `$TEMPLATES/log` append with **BEGIN AOI** record including correlation id exported to environ before `exec` bash.
- [ ] Bash: after `WORK_DIR` known → **BEGIN template-mode** mirroring corr + template path + abbreviated argv.
- [ ] Bash: single success exit path (**end of script** after summaries) writes **COMPLETE** into both targets; **`trap EXIT`** for non-zero exits writes **FAILED** unless already written.
- [ ] **`nested_loop` integration:** Inside loop wrapper, bracket each stack with **`BEGIN/END STACK`** lines sharing same corr.
- [ ] Tests: unit test shell function parsing; optionally dry-run minsarApp with `MINSAR_DRY_LEDGER=1` echo-only mode for CI.
- [ ] Docs: **`DEVELOPMENT_GUIDE.md`** subsection “Reading `TEMPLATES/log` concurrency ledger.”

---

## Execution plan (step-by-step)

1. Specify exact file paths (**`$TEMPLATES/log`**, **`$WORK_DIR/run_ledger.txt`** or **`$WORK_DIR/log` tail convention**).

2. Add Python-side **BEGIN AOI** (+ export corr) in `minsarapp_aoi_entry.py` **before** `exec` bash (keep correlation stable across stacks).

3. Source small ledger helper early in `minsarApp.bash` after libs.

4. Insert **TEMPLATE_MODE_BEGIN** after `cd "$WORK_DIR"` and `PROJECT_NAME` known; include `TEMPLATE_FILE`, `TEMPLATE_PRINT_NAME`, abbreviated flags.

5. Register **`trap`** on `EXIT` (and optionally `TERM`/`INT` for humane cancel) invoking ledger write with exit code `$?`.

6. At nominal successful bottom (after summaries), call **`finalize_run_ledger SUCCESS`**.

7. With **`nested_loop`:** wrap each iteration BEGIN/END; overall BEGIN once at entering loop, END once after last stack success.

8. Verify parallel runs: spawn two mocks writing simultaneously with `flock` test harness.

---

## Risks / open questions

- **Shared NFS `TEMPLATES/log` contention:** flock vs simple append acceptable?
- **`set -e` interactions with traps:** must use careful pattern (`trap '_code=$?; …' EXIT`).
- **Chunk / submit-only workflows:** wording of SUCCESS vs SUBMITTED to avoid false reassurance.
- **Very long ARGV:** cap or hash ARGS for log line length.

---

## TODO list

- [ ] Decide SUCCESS semantics for chunked / detached SLURM runs.
- [ ] Implement corr id + traps + flock.
- [ ] Wire into AOI Python + bash + future loop.
- [ ] Document grep snippets for operators (`CORR=` / `STATUS=FAILED`).
- [ ] Optional: Grafana/Loki ingestion later—not in scope here.
