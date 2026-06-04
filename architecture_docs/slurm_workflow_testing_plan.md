# Plan: SLURM end-to-end test harness (testing_plan)

## Goals

- Move beyond **`minsarApp.bash … --start dem`** so regression checks exercise **submission and completion of real SLURM steps** (`run_workflow.bash`, jobfiles, etc.) on Stampede-class hosts (and analogous schedulers elsewhere).
- Support **multiple invocations**: template-first and AOI-based `minsarApp.bash`, without manual copy-paste per experiment.
- Serve **three audiences:**
  - **You** exercising refactors (`nested_loop`, logging, …) across **different HPC systems**
  - **New users / fresh installs** (“does my `minsarApp.bash`, env, queues, scratch work?”)
  - Optional **automated/agent-driven** retries (run → inspect failure → patch → rerun the same curated list).

Accept **latency**: tens of minutes to **hours** (queue wait + workflow wall clock).

---

## Where this should live (`SAMPLESDIR` / CircleCI lineage)

Prefer a **tracked** subdirectory of **`samples/`** next to **`samples/circleci/`** — that keeps install-smoke collateral **beside templates** referenced by **`$SAMPLESDIR`**, and parallels the CircleCI-facing template **`samples/circleci/ci_unittestGalapagosSenDT128.template`**.

Suggested layout (**implementation-phase target**):

```text
samples/slurm_e2e_testing_plan/
  README.md                     # Prerequisites: sourcing minsar env, ACCOUNT, queues, SAMPLESDIR→TE,TEMPLATES
  manifest_commands.list       # OPTIONAL: bare minsar commands (see example below)
  run_full_workflow_checks.bash # Driver: sourced env + loop over manifest (+ dry-run flag)
```

- **`run_full_workflow_checks.bash` is not “only minsar lines”**: it wraps **setup** (failure messages if `minsarApp.bash`/Slurm/`SAMPLESDIR` missing), **`--dry-run`**, logging to a **`RUN_ID` directory**, summary exit codes — then runs each **`minsarApp.bash`** line read from **`manifest_commands.list`** (or from a `# BEGIN_MANIFEST`-embedded block).

- **Why not ONLY `tests/`**: New users mentally look under **`samples/`** and **`$SAMPLESDIR`**. Putting smoke tests there documents “this repo ships example templates **and** the command list we expect to pass on Stampede/frontera/&c.” **`tests/`** can still symlink or README-point here if you prefer one canonical pointer.

Existing related artifact:

- **`samples/circleci/ci_unittestGalapagosSenDT128.template`** — CI-oriented copy; manifests can reference **`"$SAMPLESDIR/circleci/ci_unittestGalapagosSenDT128.template"`** for parity with CircleCI naming, **`"$SAMPLESDIR/unittestGalapagosSenD128.template"`** for the **SenD128**Galapagos line you mentioned, **`unittestGalapagosSenDT128.template`** when you want “DT” ascent naming.

Secrets / site-specific (**alloc, queue partitions**): keep in **gitignored** `local_slurm_env.bash` (or `sources.sh`) next to repo or `$HOME`; driver does `[[ -r ... ]] && source ...`.

---

## Example: manifest + driver sketch (unittestGalapagos)

**Not “only minsar commands”**: keep **`minsarApp.bash` lines in `manifest_commands.list`** (easier for you to authorize an agent **only edit/rerun lines in this file**) and **`run_full_workflow_checks.bash` as bootstrap**.

### File: `manifest_commands.list` (example)

Everything after **`#`** is ignored. One logical command **per logical line**. Use **`$SAMPLESDIR`** so clones work on any filesystem.

```bash
# ------------------------------------------------------------------
# Minimal (fast-ish): DEM only — verifies template/workdir/DEM machinery
# Wall clock: depends on DEM path + node; SLURM may still be skipped or light
# Template: descend 128 Galapagos unittest (adjust if your site prefers SenDT variant)
# ------------------------------------------------------------------
minsarApp.bash "$SAMPLESDIR/unittestGalapagosSenD128.template" --start dem

# ------------------------------------------------------------------
# Heavier smoke: crosses jobfile/ifgram-ish boundary (YOU tune --start/--stop)
# Uncomment when DEM-only passes and you accept queue/runtime cost:
# minsarApp.bash "$SAMPLESDIR/unittestGalapagosSenD128.template" --start jobfiles --stop jobfiles

# CircleCI-aligned template name variant (different basename → different scratch project):
# minsarApp.bash "$SAMPLESDIR/circleci/ci_unittestGalapagosSenDT128.template" --start dem

# ------------------------------------------------------------------
# Full workflow (expensive): omit --stop once ready; reserve for nightly / skx-dev
# minsarApp.bash "$SAMPLESDIR/unittestGalapagosSenD128.template" --no-mintpy --miaplpy
```

**AOI-mode examples** belong in another section of the manifest or **`manifest_aoi.list`** so template-first stays simple for newcomers.

---

### File: `run_full_workflow_checks.bash` (example skeleton)

Shows **wrapper around** reads from manifest — not just raw inline minsar-only content.

```bash
#!/usr/bin/env bash
# samples/slurm_e2e_testing_plan/run_full_workflow_checks.bash
set -eo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"   # …/samples/slurm_e2e_testing_plan/../.. → repo root
LIST="${SCRIPT_DIR}/manifest_commands.list"
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1 && shift || true

# Optional: HOME-stored allocation + queue overrides
[[ -z "${LOCAL_SLURM_ENV:-}" ]] || source "${LOCAL_SLURM_ENV}"
: "${SAMPLESDIR:=${ROOT}/samples}"
[[ -z "${minsarApp:-}${MINSAR_HOME:-}${WORKDIR:-}}" ]] &&
  echo "USER ERROR: source your minsar environment so minsarApp.bash and SCRATCH/TEMPLATES are set." >&2 && exit 1
command -v minsarApp.bash >/dev/null 2>&1 || {
  export PATH="$ROOT/minsar/bin:$PATH"; }

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)_$$"
RUN_DIR="${SCRATCHDIR:-/tmp}/${USER}_slurm_e2e_${RUN_ID}"
mkdir -p "$RUN_DIR"

echo "### slurm_workflow_testing_plan RUN_ID=${RUN_ID} DRY_RUN=${DRY}" | tee "${RUN_DIR}/session.log"

n=0
while IFS= read -r raw || [[ -n "$raw" ]]; do
  line="${raw%%#*}"           # strip trailing comment
  line="$(echo "$line" | sed 's/[[:space:]]*$//' | sed 's/^[[:space:]]*//')"
  [[ -z "$line" ]] && continue
  n=$(( n + 1 ))
  printf '\n===== CASE %s (%s lines in manifest) =====\n' "$n" "$#" | tee -a "${RUN_DIR}/session.log"
  echo "CMD> $line" | tee -a "${RUN_DIR}/session.log"

  if [[ "$DRY" == 1 ]]; then
    echo "[dry-run] skip execute" | tee -a "${RUN_DIR}/session.log"
    continue
  fi

  bash -lc "$line" 2>&1 | tee "${RUN_DIR}/case_${n}.log"
  rc=${PIPESTATUS[0]}
  echo "EXIT_${n}=${rc}" | tee -a "${RUN_DIR}/session.log"
  [[ "$rc" -eq 0 ]] || exit "$rc"

done < "$LIST"

echo "### ALL_CASES_COMPLETE RUN_ID=${RUN_ID}" | tee -a "${RUN_DIR}/session.log"
```

The reference **`basename unittestGalapagosSenD128`** matches **`samples/unittestGalapagosSenD128.template`** shipped in-repo; **`ci_unittest…`** illustrates CircleCI-relative path.

Tune **`bash -lc` vs direct eval** depending on login-module requirements.

---

## Can the Cursor agent submit jobs?

### Remote SSH Cursor (recommended mental model)

If you **open the workspace over SSH** (Cursor connected to Stampede/frontera login or **shared fs + dev node**):

- Commands the agent invokes via **the integrated terminal** usually run **as your logged-in user** on **that remote host**.
- If **you already completed MFA** for that SSH session **and Slurm/account policies allow **`sbatch`/`minsarApp.bash`** for that UID**, **the agent can submit workloads** exactly like you would in bash — unless your site or Cursor restricts **automated terminals** separately (check local policy).

**No extra OS “permission ticket”**: the limiting factors are **`sbatch`/queue availability**, **`set -eo pipefail`** failures, **`WORK_DIR` quotas**, **network** (ASF downloads).

### Sandbox / cloud agent without SSH

Agents that execute in an **ephemeral Cursor cloud VM** attached to repo **typically do not see your scratch or Slurm** — there, **cannot** realistically run **`minsarApp.bash`** E2E. **Remote SSH solves that.**

### Approving automation

You can constrain scope: **`manifest_commands.list` is explicitly “what the assistant may propose run”**. Policy: edits only paths under **`samples/`** + driver; never arbitrary shell.

---

## Fix loop: “Agent runs → fails → patches → rerun”

**Feasible** on **remote SSH**:

1. **`run_full_workflow_checks.bash`** logs **`RUN_DIR/case_N.log`** and stops on first nonzero exit (`set -eo` variant) or **`--continue-on-fail`** (future enhancement).
2. Agent reads **`$WORK_DIR/log`**, **`slurm *.e|.o`, `sacct`**, diagnoses, patches codebase, **`git pull`/`commit`/`push`**, then **reruns** same driver or offending line via **`bash samples/.../run_full_workflow_checks.bash`** or **`manifest` subset**.

**Friction:** iterative **hours-long** retries burn queue hours — keep manifest **tiered**.

---

## The “30 minute timeout” misconception

What **normally** hurts agents is **not** “workflow must finish in &lt; 30 min universally”:

1. **Shell tooling / synchronous waits:** each `run_terminal_cmd`-style invocation has a configurable wait budget (**often tens of seconds to a few minutes** by default—see **Cursor multitask vs single-task** modes). **`block_until_ms`** can be raised so **`minsarApp.bash`** running foreground for **many minutes** still returns cleanly to the agent when the workflow finishes inside that ceiling.

   Alternatively, run **`minsarApp.bash` in the background** and **poll logs / `AwaitShell` / `sacct`** afterward so the agent turn does not block indefinitely.

2. A **rough ~30 minute turnaround budget** (varies by product) sometimes caps **individual agent-turn** responsiveness — that is **still not** the workflow wall clock: you can **`sbatch` + exit** immediately and poll **`sacct`** later.

**So:**

- **`&lt;30 minute end-to-end` + low queue latency** ⇒ **might** squeak past as **foreground** synchronous run **if Cursor wait budget suffices** for that invocation (environment-dependent).

- **`>few minutes`** foreground ⇒ **much safer**:

  - **`sbatch run_full_workflow_checks.bash`** (driver itself becomes Slurm allocation), **or**

  - **`tmux` / screen** wrapping **`minsar …`**, agent reconnects and uses **`tail -f`** / **`grep EXIT`**.

- **Overnight **`skx-dev`** / low contention windows** ⇒ **recommended**: launch **detach** **`before sleep`**, next morning **`sacct`/logs** ⇒ agent **reviews**, not necessarily **blocked** babysitting (`skx-dev` partitioning name may change site-by-site).

Document **recommended Slurm wrappers** explicitly in **`README.md`**.

---

## Queue strategy (e.g. Stampede **`skx-dev`**)

Note in **`samples/slurm_e2e_testing_plan/README.md`:**

- Prefer an **interactive / dev partition** with **bounded wall clocks** whenever developing the driver itself.
- For **confidence similar production**, **`normal`**/`skx`/project partition per policy.
- **Local night/low wait** ⇒ user kicks **`sbatch`**, sleeps, agent analyzes **later** ⇒ acceptable async loop.

---

## Should commands live in a file?

**Still yes**: **`manifest_commands.list`** (**minsar lines only**) + **`run_full_workflow_checks.bash`** (**bootstrap/logging/dry-run**). Authorize agent **manifest-only** tweaks if paranoid.

---

## Test matrix (suggested tiers)

| Tier | Typical command example | Audience |
|------|--------------------------|----------|
| **Smoke** | `…unittestGalapagosSenD128.template --start dem` | install / queue sanity |
| **Mid** | `--start jobfiles --stop jobfiles` (adjust) | real Slurm jobfiles/submit |
| **Full** | no `--stop` / production flags | nightly / **`skx-dev` low contention** |

---

## Post-run check (human or AI)

Same table as earlier: **`sacct`**, **`WORK_DIR/log`**, **`run_files/*.{e,o}`**. **`README.md`** should print standard **`journalctl`/paths** excerpt template for **`paste`** into chat.

---

## Risks / policy

- **`samples/` ballooning logs** ⇒ gitignore artifacts; **`RUN_DIR`** on `$SCRATCHDIR`.
- **CircleCI divergence** ⇒ periodically sync **`unittestGalapagos*.template`** fields with **`samples/circleci/ci_*.template`** or document drift.

---

## Action items

- [ ] **`mkdir samples/slurm_e2e_testing_plan/`**, add **`README.md`**, **`manifest_commands.list` skeleton**, **`run_full_workflow_checks.bash`** (executable).
- [ ] **`README`** links **`samples/circleci/ci_unittestGalapagosSenDT128.template`** and **`unittestGalapagosSen{D,DT}128.template`**.
- [ ] Document **`sbatch`/`tmux`/overnight`** patterns + **Cursor SSH agent** expectations vs **timeouts**.
- [ ] Optional **`LOCAL_SLURM_ENV`** snippet **gitignored**.
- [ ] Cross-link **`nested_loop_PLAN`** + **`TEMPLATE_concurrent_run_log_PLAN`** when logs land **`TEMPLATES/log`**.

---

## Summary

| Question | Recommendation |
|---------|----------------|
| **`run_full_workflow_checks.bash` content** | **Driver + sourcing + logging**; **`minsarApp.bash`** lines **`manifest`** |
| **`unittestGalapagos` example** | **`"$SAMPLESDIR/unittestGalapagosSenD128.template"`** `--start dem` first; **`circleci/ci_*.template`** optional parity |
| **Location** | **`samples/slurm_e2e_testing_plan/`** (beside **`samples/circleci/`**) |
| **Agent submits?** | **Yes on Remote SSH** after your login+MFA (**same user** shell); **`sbatch`/`background`** defeats short default waits |
| **30 min myth** | **Tool wait budget≠workflow length** — long runs **detach**/`sbatch`; **≤~30 min total** foreground **might** work **if Cursor allows that wait** |

This document path includes **`testing_plan`**.
