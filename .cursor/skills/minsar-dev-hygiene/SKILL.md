---
name: minsar-dev-hygiene
description: >-
  MinSAR development hygiene: do not create PLAN.md; do not add a test for every
  new script; do not always edit architecture_docs (merge conflicts). Use when
  planning, implementing, or testing MinSAR changes, especially new utils/scripts,
  PLAN.md, test_*.bash, or architecture_docs updates.
---

# MinSAR development hygiene

## Do not create `PLAN.md`

- **Never** create or update a repo-root (or working-dir) `PLAN.md`.
- It causes merge conflicts when the same repo is edited on different servers.
- Plan in the Cursor plan UI and/or chat only. Keep plans out of git-tracked scratch files unless the user explicitly asks for a named plan doc.

## Do not create a test for every script

- **Do not** add `tests/test_<script>.bash` (or similar) for every new utility script by default.
- Only add tests when the user asks, or when changing core workflow/job orchestration where regressions are costly (`run_workflow`, `minsarApp`, submit/sbatch paths, etc.).
- Prefer manual smoke checks (`--help`, a quick dry-run) over new test files for one-off admin/utils tools (e.g. `clean_dir.bash`).

## Do not always modify `architecture_docs/`

- **Do not** update `architecture_docs/` (e.g. `FILE_STRUCTURE.md`) on every new script, rename, or option tweak.
- Shared docs edited on multiple servers cause the same class of merge conflicts as `PLAN.md`.
- Update architecture docs **only** when the user asks, or when a substantial workflow/architecture change includes docs in an approved plan.
- Exception: targeted non-architecture docs the user or rules call out (e.g. `docs/README_burst_download.md` when changing burst-download error handling).

## Related

Project always-apply rule: `.cursor/rules/minsar-project.mdc`.
