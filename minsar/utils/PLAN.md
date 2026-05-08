# Plan: `modify_insarmapslog.py`

## Summary
New utility `minsar/utils/modify_insarmapslog.py` that:

1. Backs up `insarmaps.log` → `orig_insarmaps.log` (only if backup does not yet exist).
2. Rewrites every line of `insarmaps.log` so the `/start/<lat>/<lon>/<zoom>` portion of each URL uses the lat/lon/zoom from a reference URL (CLI arg 1), rounded to:
   - lat: 3 decimals
   - lon: 3 decimals
   - zoom: 1 decimal
3. Prints a single new "overlay" URL of the form
   `http://149.165.154.65/data/HDF5EOS/<project_path>/overlay.html#/start/<lat>/<lon>/<zoom>?...`
   re-using selected query params from the reference URL: `minScale`, `maxScale`, `background=satellite`, and `pixelSize` when present. Do not include `startDataset`.

## Inputs
```
modify_insarmapslog.py <reference_url> <insarmaps_log_path>
```

Two reference-URL flavors must be accepted:

A. `http://149.165.154.65/data/HDF5EOS/Kerinci/miaplpy/overlay.html#/start/-1.6959/101.2711/13.9520?startDataset=...&minScale=-0.75&maxScale=0.75&background=satellite&...`
   (host serves `overlay.html` or `index.html`; `/start/...` lives in the URL fragment after `#`)

B. `http://149.165.153.50/start/-8.2733/123.5110/14.8136?flyToDatasetCenter=false&startDataset=...&minScale=-1.5&maxScale=1.5&background=satellite&pixelSize=5.6&opacity=73`
   (no `overlay.html` / `index.html`; `/start/...` is in the path)

## Project-path resolution for the printed URL
- If reference URL contains `/data/HDF5EOS/<...>/overlay.html` (or `index.html`), use `<...>` as `<project_path>`.
- Otherwise derive `<project_path>` from the second arg (the log file path):
  - `Kerinci/miaplpy/insarmaps.log` → `Kerinci/miaplpy`
  - `insarmaps.log` (no dir) → use the parent directory context; if that path contains `/data/HDF5EOS/`, take the relative project path after it, otherwise fall back to the last two parent directory components.
- The printed URL always contains `REMOTE_DIR = "/data/HDF5EOS/"`.
- The printed URL always uses `REMOTEHOST_VOLCDEF = "http://149.165.154.65"`.
- Page name is `overlay.html` unless ref URL clearly used `index.html`.

## Parsing rules
- Extract lat/lon/zoom by regex on the reference URL: `/start/(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)`. Works for both flavors above (URL fragment or path).
- Extract query params from whichever side actually carries them (after `?`, regardless of whether the `?` is in the path or in the fragment). Use Python's `urllib.parse` with a small fallback for the `#.../start/.../?...` flavor.
- Replace `/start/<lat>/<lon>/<zoom>` in every existing line of `insarmaps.log` with the new (rounded) values. Other parts of each line are untouched.

## File writes
- Read `insarmaps.log`.
- If `orig_insarmaps.log` does not exist in the same directory, copy `insarmaps.log` → `orig_insarmaps.log` first.
- Overwrite `insarmaps.log` with the modified lines (preserve order; preserve trailing newline).
- Print the freshly built overlay URL to stdout.

## CLI
- `argparse` with positional `url` and `logfile`.
- `--help` / Examples block: only command lines, no prose between them (per project rules).

## Action Items
- [x] Implement script `minsar/utils/modify_insarmapslog.py`.
- [x] `chmod +x` it.
- [x] Add unit tests under `minsar/utils/tests/test_modify_insarmapslog.py` for: lat/lon/zoom rounding, line rewrite, project-path resolution from URL, project-path resolution from log file path, backup-once behavior, overlay-URL assembly with/without `pixelSize`.
- [x] Run `python -m unittest minsar.utils.tests.test_modify_insarmapslog`.
- [ ] Run `./run_all_tests.bash --python-only` after installing required test dependencies (`numpy` is missing in the current environment).

## Confirmed Decisions
- Use filename `modify_insarmapslog.py`.
- Use `REMOTE_DIR = "/data/HDF5EOS/"`.
- Use `REMOTEHOST_VOLCDEF = "http://149.165.154.65"`.
- Do not include `startDataset` in the printed overlay URL.
- `insarmaps.log` contains only URL lines.
