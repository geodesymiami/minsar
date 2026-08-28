# `run_02_dolphin_wrapped` resubmit failures — pixi / SWEETS environment

Summary of failures when **resubmitting** `run_02_dolphin_wrapped` on Stampede3 (TACC) because the job could not find or use **pixi** or the **SWEETS pixi environment**. Projects referenced: `qxHawaiiCSLCDolphin-autoSenD87`, `qPopoCSLCDolphin-autoSenD143`.

---

## Background

`dolphin_wrapped` runs Dolphin inside the **SWEETS pixi environment**:

`$MINSAR_HOME/tools/sweets/.pixi/envs/default`

(not minsar miniforge conda). Early run files used `pixi run` and `${HOME}/.pixi/bin`. After a **TIMEOUT**, `run_isce3_workflow.bash` resubmits the same `.job` file; resubmits often failed immediately on pixi/env resolution before Dolphin started.

---

## Typical resubmit pattern

1. First job runs on `skx-dev` (may run for hours if pixi/env works on that node).
2. Job **TIMEOUT** → workflow calls `update_walltime_queuename.py` and resubmits via `submit_jobs.bash`.
3. Resubmit job fails in **~1 second** with pixi or env errors below (often on a different partition, e.g. `pvc`).

---

## Error 1: `pixi: command not found` (exit 127)

**Symptom**

```text
run_files/run_02_dolphin_wrapped: line 6: pixi: command not found
```

Example: Hawaii job **3444666** on `pvc` — immediate `FAILED`, exit **127**, after timeout resubmit of **3444417**.

**Cause**

Run file used `pixi run --manifest-path "$MINSAR_HOME/tools/sweets/pyproject.toml"`. Resubmit did not provide a working `pixi` on the compute node:

- `${HOME}/.pixi/bin` on `PATH` fails when `HOME` differs on compute (`/home1/...` vs `/home/...`).
- Auto-resubmit to another partition does not fix a missing user `pixi`.

**What we tried**

- Add `${HOME}/.pixi/bin` to `PATH` in generated run files → worked on some `skx-dev` nodes, still failed on `pvc` after resubmit.
- **Fix:** remove `pixi run`; call binaries from `$MINSAR_HOME/tools/sweets/.pixi/envs/default/bin` directly (same pattern as `prepare_compass_runconfigs.py`).

---

## Error 2: `python3: command not found` (after dropping `pixi run`)

**Symptom** (Hawaii, job **3445013**)

```text
run_files/run_02_dolphin_wrapped: line 13: python3: command not found
```

**Cause**

Preamble called bare `python3` for `dolphin_presets.py`. After tightening `PATH` (to avoid minsar conda GDAL), inherited conda `python3` was no longer available; `$SWEETS_ENV/bin` was not used consistently on the resubmit node.

**What we tried**

- Explicit `"$SWEETS_ENV/bin/python3"` for presets, cleanup, and dolphin CLI.
- Append `/usr/bin:/bin` to `PATH`.
- Invoke dolphin as `"$SWEETS_ENV/bin/python3" "$SWEETS_ENV/bin/dolphin" ...` (ignore shebang pointing at work2).

---

## Error 3: `Permission denied` executing work2 `python3`

**Symptom** (Hawaii, job **3445041**)

```text
/work2/.../tools/sweets/.pixi/envs/default/bin/python3: Permission denied
```

**Cause**

On Stampede3 **compute nodes**, `/work2` is often **noexec**: the SWEETS pixi env under `$MINSAR_HOME` on work2 cannot be executed on compute (login node can). Resubmit jobs hit this when still pointing `SWEETS_ENV` at work2.

The `dolphin` script shebang also hardcodes work2 `python3.12`.

**What we tried**

- `rsync` sweets env to scratch inside the batch job → failed on compute (Error 4).

---

## Error 4: `rsync` cannot read `/work2` on compute

**Symptom** (Hawaii, job **3445041**)

```text
Staging SWEETS environment to /scratch/05861/tg851601/minsar_sweets_pixi_default
rsync: [sender] change_dir "/work2/.../default" failed: Permission denied (13)
```

**Cause**

Compute nodes may not **read** `/work2` at all. Staging the pixi env from work2 inside a resubmitted batch job cannot work on those nodes.

**Fix applied**

- **`minsar/scripts/stage_sweets_pixi_env.bash`** — run **once from a login node** (before submit or resubmit):

  ```bash
  source setup/environment.bash
  stage_sweets_pixi_env.bash
  ```

  Copies to `$SCRATCHDIR/minsar_sweets_pixi_default`. Takes several minutes; `--force` to refresh.

- Run files **do not rsync on compute**. They use:
  1. Staged scratch env if `python3` runs there.
  2. Else work2 sweets env if executable on that node.
  3. Else exit with message to run `stage_sweets_pixi_env.bash` on login.

- `run_isce3_workflow.bash` runs `stage_sweets_pixi_env.bash` before submit and before **timeout resubmit**.

---

## SLURM environment vs pixi (brief)

Batch jobs inherit the submitter’s shell environment, but resubmit failures were not fixed by inheritance alone:

- Submitters often use **minsar conda** (`s.bw2`), not sweets pixi (`s.bs`) — `pixi` is usually not on inherited `PATH`.
- Dolphin needs the **SWEETS pixi env** binaries, not user `~/.pixi`.
- `/work2` sweets env may be **noexec or unreadable** on compute nodes used after resubmit.

ISCE3 run files therefore set `SWEETS_ENV` explicitly and rely on **scratch staging** for Stampede3 resubmits.

---

## Recommended workflow before submit / resubmit

1. **Login node** (once per account, or after sweets upgrade):

   ```bash
   source setup/environment.bash
   stage_sweets_pixi_env.bash
   ```

2. Regenerate or use updated `run_02_dolphin_wrapped` (no `pixi run`; uses `$SWEETS_ENV`).

3. Submit or let `run_isce3_workflow.bash` resubmit (staging runs automatically if using that workflow).

4. Direct `sbatch` after manual resubmit: run `stage_sweets_pixi_env.bash` on login if scratch copy is missing or stale.

---

## Code / scripts related to pixi env fixes

| File | Change |
|------|--------|
| `minsar/src/minsar/cli/create_isce3_runfiles.py` | SWEETS env in run files; no `pixi run`; staging selection; dolphin via `python3` |
| `minsar/scripts/stage_sweets_pixi_env.bash` | Login-node copy of pixi env to SCRATCH |
| `minsar/src/minsar/cli/run_isce3_workflow.bash` | Stage before submit and before timeout resubmit |
| `setup/install_isce3.bash` | Stage after `pixi install` |

---

## Operational notes

- **Scratch staging size:** Full sweets pixi env is large; first run is slow; reuse `$SCRATCHDIR/minsar_sweets_pixi_default` across projects.
- **Resubmit without workflow:** If you `sbatch` manually after a timeout, ensure staging was done on login — resubmit jobs will not rsync from work2 on compute.
