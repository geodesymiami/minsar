# Plan: Make plot_data.py user-friendly and compatible with MintPy / MinSAR conventions

## Summary

`plot_data.py` works but diverges from MintPy/MinSAR conventions in output
locations, filenames, option names, option organization, and caching. It also
lacks the HTML index + upload step that other MinSAR tools have.

The work is split into four independent parts so they can be implemented
one-by-one:

1. **Suggested improvements and clarifications** (option cleanup, period parsing, caching/`--force`)
2. **MintPy compatibility** (option names, output folder)
3. **MinSAR compatibility** (naming, HTML index, consistency with `plot_fault_transect.py`)
4. **Upload-to-Jetstream functionality**

**Decisions made:**
- Output folder: flat **`images/`** (no per-period subfolders)
- Font size option: **`--fontsize`** (MintPy spelling)

## Key Components Affected

- `tools/PlotData/src/plotdata/cli/plot_data.py` (parser, period parsing, save paths, html/upload hooks)
- `tools/PlotData/src/plotdata/utils/argument_parsers.py` (option names, groups, removals)
- `tools/PlotData/src/plotdata/objects/process_data.py` (caching / `--force`)
- `tools/PlotData/src/plotdata/fault_transect/html_index.py` + `cache.py` (reuse)
- `minsar/scripts/upload_data_products.py` (no change; we follow its conventions)

---

# Part 1: Suggested improvements and clarifications

## 1.1 `--period` with commas

`--period 20141001:20181222,20181228:20201225` currently silently uses only the
**first** period: the parser splits on `,` and `:` with the same regex
(`re.split('[,:\-\s]', p)`) and keeps only `dates[0]`, `dates[1]`.

**Change:** support both forms, same as `plot_fault_transect.py`:

- `--period A:B C:D` (space separated — works today)
- `--period A:B,C:D` (comma separated — currently broken)

Port `parse_periods()` from `plot_fault_transect.py` (splits on commas first,
then `:` within each chunk, validates 8-digit dates). Error clearly on
malformed input instead of silently mis-reading.

## 1.2 Caching and `--force` (currently: NO caching at all)

**Current state.** `objects/process_data.py` contains cache checks that are all
**disabled** with `or True` placeholders marked `# TODO Overwrite option`:

| Product | Code location | Check |
|---|---|---|
| velocity h5 (`timeseries2velocity`) | `_convert_timeseries_to_velocity` | `if not os.path.exists(output_file) or True:` |
| masked velocity (`*_msk.h5`) | `_apply_mask` | `if not os.path.exists(out_mskd_file) or True:` |
| geocoded files (`geo_*`) | `_geocode_velocity_file` | `if not os.path.exists(outdir) or True:` |
| horizontal/vertical (`hz_*.h5`, `up_*.h5`) | `_process_vectors`, `_convert_to_horz_vert` | `... or True:` |
| mask file | `_extract_file_names` | `if True: mask_file = None` (always regenerated) |

So **every intermediate product is recomputed on every run** — the most
expensive steps (ts2v, geocode, asc_desc2horz_vert) included. There is no
`--force` because the current behavior is effectively "always force".

**Contrast with `plot_fault_transect.py`,** which has a full caching model:
- `cache_is_fresh(product, *input_paths)`: product is fresh when newer than all inputs
- data (txt) caching with bracket metadata (parameters embedded in the txt header,
  so a parameter change invalidates the cache)
- figure style keys (`*.style` sidecar files) so figures rebuild when only styling changed
- `--force` to recompute everything, `--plots-only` to rebuild figures from txt

**Suggested change (consistency with plot_fault_transect):**
1. Replace each `or True` with a real freshness check:
   `cache_is_fresh(product, eos_file)` (mtime-based; reuse
   `plotdata/fault_transect/cache.py:cache_is_fresh`, which is generic).
2. Add `--force` to recompute intermediate products even when fresh.
3. Since processing parameters affect the products (`--mask-thresh`, period,
   `--ref-lalo`), either embed them in filenames (already partly done:
   `hz_{start}_{end}.h5`) or store a small sidecar (like the figure style
   keys). Minimal version: mask threshold and ref-lalo go into a sidecar;
   dates are already in the names.
4. Print `Using cached: <path>` / `Skipping (up to date): <path>` messages like
   plot_fault_transect, so users see what is reused.

## 1.3 Option cleanup (`--help` clarity)

| Problem | Options | Change |
|---|---|---|
| Unused in plot_data flow | `--latitude`, `--longitude` (never read; only Stre.py builds its own values from `--lalo`) | Remove from plot_data parser |
| Confusing near-duplicates | `--latitude/--longitude` vs `--lat/--lon` vs `--lalo` | Keep `--lalo` (MintPy tsview name) + `--lat/--lon` convenience |
| Belong to horzvert_timeseries only | `--window-size`, `--lat-step` | Remove from shared `add_location_arguments`; define locally in `horzvert_timeseries.py` (it already re-defines `--window-size`) |
| Model-specific options in main help | `--model`, `--no-sources`, `--fullres`, `--norm`, `--denoise` | Move into a new `Modeling options` argument group |
| Two colormap options, different defaults | `--colormap` (jet) and `--colorbar` (viridis) | Keep `--colormap`; remove `--colorbar` |
| Misplaced group members | `--vector-legend`, `--vertical-exaggeration` added to bare `parser` inside `add_plot_parameters_arguments` (with stray trailing comma) | Put in a `Section / vectors` group with `--section`, `--num-vectors`, `--vector-scale` |
| Stale help text | `--save` says "default path: $SCRATCHDIR/Volcano_dir" | Update to actual behavior |
| Inverted help strings | `--no-dem` says "Add relief to the map"; `--no-shade` says "Shade the dem" | Fix wording |

---

# Part 2: MintPy compatibility

## 2.1 Output folder: `images/` flat, dates only in filename

Current output has the dates twice:

```
$SCRATCHDIR/EtnaSenA44/images/20201225_20260701/Etna_default_20201225_20260701.png
```

**Change** (decision made): drop the per-period subfolder; keep dates in the
filename only:

```
$SCRATCHDIR/EtnaSenA44/images/Etna_default_20201225_20260701.png
$SCRATCHDIR/EtnaSenA44/images/Etna_default_20141001_20181222.png
$SCRATCHDIR/EtnaSenA44/images/index.html
```

This mirrors MintPy's flat `pic/` folder (all output images in one place, no
nesting). Dates in the filename survive copying/uploading; multi-period runs
land side by side in one folder, which also makes the HTML index trivial.

Touch points in `plot_data.py` `main()`: the vectors txt path, the PDF save
loop, and the PNG save loop (all currently build `images/{start}_{end}/`).

## 2.2 Option names aligned with MintPy

| plot_data.py today | MintPy | Change |
|---|---|---|
| `--font-size` | `--fontsize` (view.py) | **Rename to `--fontsize`** (decision made) |
| `--colormap` (dest `cmap`) | `-c/--colormap` | add `-c` short form |
| `--vlim VMIN VMAX` | `-v/--vlim` | add `-v` short form |
| `--no-display` | `--nodisplay` | accept both spellings |
| `--ref-lalo` | `--ref-lalo` | already aligned |
| `--mask-thresh` | (plot_fault_transect uses the same name) | keep |

Note: `plot_fault_transect.py` currently uses `--font-size`; for consistency it
should eventually accept `--fontsize` too (small follow-on, listed in Part 3).

---

# Part 3: MinSAR compatibility

## 3.1 HTML index (like plot_fault_transect)

After saving, write `index.html` into `images/` listing all PNGs, grouped by
project/period. Reuse `plotdata/fault_transect/html_index.py`
(`build_index_html` / `write_index_html`) — it already produces the
left-aligned gallery with txt links used by `plot_fault_transect.py`.

## 3.2 Caching / `--force` / messages consistent with plot_fault_transect

Covered in Part 1.2 — the *implementation* reuses
`plotdata/fault_transect/cache.py`, making the two tools behave the same:
skip-when-fresh by default, `--force` to recompute, explicit "Using cached"
messages.

## 3.3 Naming and logging conventions

- Output basenames already use `build_plot_output_basename(project, tag,
  label, start, end)` — same `{project}_{tag}_{label}_{start}_{end}` pattern as
  plot_fault_transect. Keep.
- Command logging: `plot_data.py` already appends to the project command log
  (`_log_plot_data_command`). Keep; ensure the log lands in the project dir
  when `--outdir` is used.
- Follow-on: let `plot_fault_transect.py` accept `--fontsize` as alias so both
  tools take the same spelling.

---

# Part 4: Upload-to-Jetstream functionality

## 4.1 `--upload` flag

Add `--upload`: after saving and writing `index.html`, upload the `images/`
folder to Jetstream following `minsar/scripts/upload_data_products.py`
conventions:

- Preferred implementation: shell out to
  `upload_data_products.py $PROJECT/images` (one upload implementation to
  maintain). When given a subdirectory path that is not a `network_*` dir, it
  uploads the full directory contents — so `images/` works without modifying
  the upload script. We provide our own `index.html` (its automatic
  `create_html_if_needed` only fires for `pic/` dirs).
- Write `upload.log` with the remote URL
  (`http://$REMOTEHOST_DATA/$REMOTE_DIR/$PROJECT/images`), both in the project
  dir and inside `images/` — same convention as `upload_data_products.py`.
- `--upload` implies `--save` (no point uploading without saving).

---

## Action Items

**Part 1 (improvements):**
- [ ] Fix `--period` comma parsing (port `parse_periods`)
- [ ] Enable caching (replace `or True` checks with `cache_is_fresh`), add `--force`
- [ ] Reorganize argument groups; remove unused/duplicate options; fix help texts

**Part 2 (MintPy):**
- [ ] Flat `images/` folder; dates only in filename
- [ ] `--fontsize` rename; `-c`, `-v` short forms; accept `--nodisplay`

**Part 3 (MinSAR):**
- [ ] Write `index.html` after saving (reuse `html_index.py`)
- [ ] Verify command-log placement with `--outdir`
- [ ] Follow-on: `--fontsize` alias in plot_fault_transect

**Part 4 (upload):**
- [ ] `--upload` flag (subprocess to `upload_data_products.py`), `upload.log`

**All parts:**
- [ ] Tests before each change (capture current behavior), tests after
- [ ] Run `./run_all_tests.bash`
- [ ] Update `tools/PlotData/README.md` and `architecture_docs/` as needed

## Execution Plan (after approval, per part)

1. **Parser groundwork** (needed by all parts): split `create_parser()` into
   `create_parser()` + `cmd_line_parse(iargs)` (currently parses inside
   creation and ignores `iargs`; untestable as is). Behavior unchanged.
2. **Part 1**: periods → `parse_periods`; caching → wire `cache_is_fresh` into
   the five `or True` sites + `--force`; option cleanup per tables above.
3. **Part 2**: path changes in `main()` (3 sites); option renames/aliases.
4. **Part 3**: html index call after the save loop.
5. **Part 4**: `--upload` subprocess + `upload.log`.

## Key Commands & Flows

```bash
plot_data.py EtnaSenA44/mintpy/ EtnaSenD124/mintpy/ --ref-lalo 37.87090 15.14225 \
    --section 37.70522:15.05101,37.70522:15.19727 --save-axis \
    --period 20141001:20181222,20181228:20201225,20201225:20260701 --upload
# -> $SCRATCHDIR/EtnaSenA44/images/*.png + index.html, uploaded to Jetstream
# second run: reuses cached velocity/geocode/horz-vert products; --force recomputes
```

## TODO List

- [ ] Approval of this plan (and which part to start with)
- [ ] Write tests for existing behavior (period parsing, path building)
- [ ] Implement part by part per execution plan
- [ ] Add tests for new behavior
- [ ] Run full test suite
- [ ] Update architecture docs

---

## Refactoring Notes (FUTURE — not part of this change, per request)

Code issues observed while reviewing; for later:

1. **`create_parser()` parses args** (`inps = parser.parse_args()` inside it)
   and validates; `main(iargs)` ignores `iargs`. (Part of this is fixed as
   groundwork above, but a fuller cleanup of validation belongs here.)
2. **Two `process_data` modules**: `plotdata/process_data.py` and
   `plotdata/objects/process_data.py` — near-duplicates; consolidate.
3. **Dead code / placeholders**: `if False: inps.style = 'ifgram'`;
   commented-out options; `# TODO unused` on `--dem`.
4. **Hardwired Hawaii paths** (GPS dir, `hawaii_lines_new.mat`) — move to
   config or trigger by option.
5. **Regex escape warnings**: `'[,:\-\s]'` raises `SyntaxWarning`; use raw strings.
6. **`populate_dates` surprise**: `initialize_dates_from_files` silently
   appends an extra (min_start, max_end) full-span period.
7. **`os.chdir()` side effects** in `process()` and `_geocode_velocity_file`.
8. **`get_file_names()`** assumes SenA/SenD/CskA/CskD in project names;
   `project_base_dir` unbound otherwise (crash).
9. **Axis-label string matching** (`'ascending' in self.ax.get_label()`) drives
   both plotting and output filenames — fragile; pass explicit metadata.
10. **`ProcessData.__init__` copies all inps attributes** via `dir(inps)` loop —
    hides data flow; pass explicit fields.
11. **No CLI tests** for plot_data.py (fault_transect has ~140).
12. **`--save-gbis`** flows only through the older `plotdata/process_data.py` —
    verify or retire.
