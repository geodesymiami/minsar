# Plan: Single-shell multi-orbit processing (nested_loop)

## Summary

`minsarApp.bash` in **AOI mode** currently delegates to `minsarapp_aoi_entry.py`, which creates templates (possibly primary + opposite) then **re-execs** `minsarApp.bash` once with `--opposite-orbit` appended so that, after MiaplPy, a **nested** invocation runs the complementary stack from a **separate bash process**.

That works but has **structural downsides**:

- Two long-lived shells, duplicated environment setup, and harder reasoning about globals (`cli_command_*`, `MINSAR_*` env bridges, footer/summary duplication).
- The “second job” feels like an exception path rather than a normal control-flow extension of template mode.

**Recommendation:** Yes — it would generally be better to normalize **multiple stacks** into a single **template-mode loop** (ordered list of template paths + shared reduced CLI args): one persistent `minsarApp.bash` process runs *N* stacks sequentially. That aligns with AOIs such as `--flight-dir asc,desc`: “run these templates in order with the same options,” rather than “finish one tree then spawn another copy of oneself.”

**Caveats:** SLURM / `run_command` semantics, `WORK_DIR`/`PROJECT_NAME`, and cross-stack flags (`--horzvert`, uploads) must be defined once and remain correct per iteration. Nested env passing becomes unnecessary if loops live entirely in one shell after AOI setup.

---

## Key components affected

| Area | Role |
|------|------|
| `minsar/bin/minsarApp.bash` | Today: AOI `exec` to Python → re-exec; template path consumes `--flight-dir`. Target: optionally drive a **queue** of `template_file` values inside one bash run after AOI bridge. |
| `minsar/scripts/minsarapp_aoi_entry.py` | Today: builds `margs`, sets `MINSAR_FIRST_ORBIT_TEMPLATE_FILE`, `MINSAR_OPPOSITE_ORBIT_TEMPLATE`, `MINSAR_CLI_COMMAND_AOI`, single re-exec. Target: compute **ordered list** of template paths (+ optional explicit “modes”); pass into bash **once** instead of nesting. |
| `minsar/scripts/create_template.py` | Unchanged externally: still returns `(primary_path, opposite_path_or_None)` consistent with `--flight-dir` / `--opposite-orbit` expansion semantics. Callers accumulate paths. |
| `minsar/lib/minsarApp_specifics.sh` | `get_modified_command_line_for_opposite_orbit` may shrink or disappear for the nested case; helpers for “args per iteration without `--opposite-orbit` duplication” instead. |

---

## Design sketch (implementable target)

### 1. Contract after AOI bootstrap

Define a stable convention (environment or positional) that bash reads **exactly once** at entry to template-first mode:

- `MINSAR_RUN_STACKS_JSON` — JSON array of objects, e.g. `[{"template":"/path/fooSenA.template","label":"primary_asc"},{"template":"/path/fooSenD.template","label":"opposite_desc"}]`, **or**
- `MINSAR_RUN_STACK_ORDER` — `template1:template2` (paths separated by safe delimiter only if escaping is airtight; JSON is preferable).

Unset or single-element array → current single-stack behavior (no loop).

### 2. Loop placement

- Prefer the loop **outside** duplicate step logic: one pass that sets `export template_file=...`, `PROJECT_NAME`, `WORK_DIR`, re-runs `create_template_array`, recomputes step flags **or** refactor into `run_one_stack` function sourced from specifics.
- Minimal first implementation: iterate templates **sequentially**, same as today’s nesting order (primary then opposite).

### 3. Opposite-orbit flag

- **`--opposite-orbit`** on the invocation that previously triggered nested re-run becomes a **logical “append second stack from create_template”**, not “run subprocess at end.”
- After refactor, omit appending `--opposite-orbit` to tail args for the recursive call; AOI Python sets stack list directly.

### 4. Footer / summaries

- For each iteration, append or tag **per-stack** summary (template path, PROJECT_DIR).
- Preserve AOI-level `cli_command_aoi` once at top of transcript if desired.

### 5. Horzvert and cross-stack assumptions

- Document and test: horizontal–vertical coupling still expects **paired** MintPy dirs; verify once both stacks ran in-loop before `horzvert` (if still post-stack).

---

## Action items

- [ ] Document current data flow (AOI → env → bash → nested bash) with a short sequence diagram; list every `MINSAR_*` variable relied on today.
- [ ] Choose serialization format (`MINSAR_RUN_STACKS_JSON` vs newline-delimited paths + metadata); validate quoting and portability (no `jq` dependency unless acceptable).
- [ ] Change `minsarapp_aoi_entry.py`: build ordered template list from `main()` output; exec bash **once** with list in env (`execv` unchanged except payload).
- [ ] Refactor `minsarApp.bash` top segment: parse stack list → `for`/indexed loop → set `template_file`/WORK_DIR/`args` invariant per iteration; remove post-MiaplPy `run_command` self-call for opposition when list length > 1.
- [ ] Remove or shrink `get_modified_command_line_for_opposite_orbit` for nested self-invocation paths; retain filtering for duplicated flags only if generic “next iteration argv” helper needs it.
- [ ] Add integration tests or workflow tests that run AOI with dual flight-dir without nested process (e.g. assert single parent PID vs two bashes, or grep log markers).
- [ ] Update `architecture_docs/WORKFLOW_ARCHITECTURE.md` and AOI sections in `KEY_CONCEPTS.md` / `FILE_STRUCTURE.md` after implementation.

---

## Execution plan (step-by-step)

1. Implement read of `MINSAR_RUN_STACKS_JSON` at start of template-first branch; default one-element array from `$1` if unset → **backward compatible**.
2. In Python AOI entry, after successful `create_template`, set env to `[primary]` or `[primary, opposite]` matching present `--flight-dir` / `--opposite-orbit` rules; unset old `MINSAR_OPPOSITE_ORBIT_TEMPLATE` from being required by bash (deprecate after transition).
3. Replace inline body of processing (download → … → MiaplPy) with either:
   - **Option A:** `for stack in ...; do ( body ); done` duplicated minimal wrapper, **or**
   - **Option B:** extract inner block to `_minsarApp_run_single_stack()` in `minsarApp_specifics.sh` for testability — prefer B if refactor scope is acceptable.
4. Delete nested `minsarApp.bash ... $opposite_orbit_template_file` block guarded by `--opposite-orbit`; ensure reduced args apply identically each iteration unless spec says otherwise.
5. Regression-test: AOI asc only, asc,desc, desc,asc, `both`; template-first still works single-file; `-geocode / horzvert` workflows if used.
6. Performance / failure behavior: failure in stack 2 should not corrupt stack 1; exit code nonzero; optionally document resume.

---

## Key commands & flows

- **Before:** AOI → templates → bash stack1 → `--opposite-orbit` tail → bash stack2.
- **After:** AOI → templates → bash **loops** `{stack1 → stack2}` with shared argv tail and per-iteration `WORK_DIR`/template.

---

## TODO list

- [ ] Freeze stack-list schema (version field in JSON for future compat).
- [ ] Implement bash loop + Python env writer.
- [ ] Bash tests (`tests/`): mock JSON with two fake template paths dry-run subset if feasible.
- [ ] Documentation pass.
- [ ] Roll out behind env flag for one release if rollback needed (`MINSAR_AOI_LEGACY_NESTED=1` optional).
