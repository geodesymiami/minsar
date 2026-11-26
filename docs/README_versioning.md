# MinSAR versioning

## Commands

```bash
minsarApp.bash --version
minsar_version.bash --short
tag_version.bash minor "support of WHIRLWIND for ISCE2"
tag_version.bash --dry-run patch "MintPy updated"
git tag -n1 --sort=-v:refname
```

## 1. The version comes from git tags

There is no version file. The version is computed from `git describe` each time it is asked for:

| State of the checkout | Version shown |
|---|---|
| exactly on tag `v0.5.0` | `0.5.0` |
| 14 commits after the tag | `0.5.0+14.g3b9984c7` |
| same, with uncommitted changes to tracked files | `0.5.0+14.g3b9984c7.dirty` |
| no tag reachable | `0.0.0+g3b9984c7` |
| not a git checkout | `unknown` |

Every commit therefore has its own version (commit count and hash), and nobody edits a number per commit. The number changes only when a tag is created.

## 2. Numbering: `vMAJOR.MINOR.PATCH`

The first tag is `v0.5.0`. While the version is `0.x`:

| Bump | When | Examples |
|---|---|---|
| MINOR (`0.5` → `0.6`) | New capability, a dependency change, or a user must change something to keep working | WHIRLWIND support, processing.template; `conda-lock.yml` regenerated; `additions/` rebased on a newer MintPy/MiaplPy/ISCE2; template option or CLI option renamed or removed; work-directory layout changed |
| PATCH (`0.5.0` → `0.5.1`) | A fix worth pointing people to | a bug that produced wrong results or broke a workflow step |
| MAJOR (`1.0.0`) | Declared once, by decision, when the template options and command line are considered stable | from then on, anything that forces a user to change something bumps MAJOR |

Ordinary commits (job defaults, template tweaks, small fixes) get no tag.

### Renames, refactors, removed scripts

The rule is whether anyone outside the code can notice.

| Change | Version effect |
|---|---|
| Internal function, variable or file rename; comment or message cleanup; extracting a function | none: no tag. The commit count and hash already identify it |
| Removing a script that no workflow or user calls (sandbox, unused helpers) | none |
| Rename or removal of something a user types or reads: CLI option, template key, script on `PATH`, output file or directory name, environment variable | MINOR while `0.x`, MAJOR from `1.0.0` |
| A large internal refactor with no intended behavior change | no bump for the refactor; tag the commit before it as a PATCH (known-good state) |

## 3. When to create a tag

Tag when one of these happens, and only after the test suite passes and one end-to-end run of the unittest template completed on that commit:

1. A new capability is complete (MINOR).
2. `conda-lock.yml` changed, or MintPy/MiaplPy/ISCE2 was updated, or an `additions/` overlay was rebased on a new upstream (PATCH if nothing changes for the user, otherwise MINOR).
3. Just before a risky refactor, to mark the last known-good state (PATCH).
4. Data are uploaded for a paper or handed to someone else, so the product can cite a clean version (PATCH if nothing else applies).
5. A fix for wrong results is in (PATCH).

Annotated tags replace the `MAJOR CHANGE:` commit prefix: the tag message says what changed, and `git tag -n1 --sort=-v:refname` is the changelog.

## 4. Creating a tag

`tag_version.bash {major|minor|patch|X.Y.Z} "message"`

1. Refuses unless on `main`, tracked files are clean, and HEAD equals `origin/main`.
2. Computes the next number from the latest `v*` tag (or takes `X.Y.Z` as given).
3. Writes the installed dependency versions to `setup/tested_versions.cfg` and commits it if it changed.
4. Creates the annotated tag on that commit.
5. Prints the push command. It does not push.

Create tags on one server; the others get them with `git pull`.

## 5. Dependencies and `additions/`

Dependency versions are not part of the MinSAR number. They are reported next to it:

| Component | Source |
|---|---|
| MintPy, MiaplPy, sardem, sarvey, insarmaps_scripts, dolphin, sweets, disp-s1, opera-utils | `git describe --tags --always` in `tools/<name>` |
| isce2, gdal, python | version and build string from `conda-meta` of the `minsar` env |
| burst2safe, asf_search | `dist-info` in site-packages |
| snaphu | `tools/snaphu-v*` directory name |

`git describe` gives the exact commit: `v1.6.4-5-gcc441486` is 5 commits past MintPy tag 1.6.4. A `git pull` in `tools/MintPy` changes the string even when MintPy has no new tag.

`setup/tested_versions.cfg` holds the versions the last tag was tested with. It is written only by `tag_version.bash`. `minsarApp.bash --version` marks every component that differs from it:

```text
minsar             0.5.0+14.g3b9984c7
isce2              2.6.5-py312hb5ba3d1_0
MintPy             v1.6.4-9-gabc1234            * tested with v1.6.4-5-gcc441486
MiaplPy            V0.2.1-22-g0d5f4b0
```

After updating a dependency, the `*` stays until a test run passes and a new tag records the new versions.

`additions/` files are part of this repository, so the MinSAR version covers them. The upstream they overlay is what the `*` reports; `check_mintpy_overlay_drift.py` guards the MintPy `_orig` files at install time.

## 6. Where the version is recorded

- `minsarApp.bash --version` (must be the first argument): full report.
- `$WORK_DIR/log`: one line at each `minsarApp.bash` start, e.g. `# minsar 0.5.0+14.g3b9984c7 (isce2 2.6.5-py312hb5ba3d1_0, MintPy v1.6.4-5-gcc441486, MiaplPy V0.2.1-22-g0d5f4b0)`.
