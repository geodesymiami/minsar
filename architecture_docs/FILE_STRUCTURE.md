# MinSAR Repository Structure

High-level layout for navigation. The main workflow entry points live under `minsar/bin/`; Python helpers under `minsar/scripts/` and `minsar/utils/`.

## Top-level

| Path | Purpose |
|------|---------|
| `minsar/bin/` | `minsarApp.bash`, `run_workflow.bash`, job wrappers |
| `minsar/lib/` | Shared bash libraries |
| `minsar/scripts/` | Python CLIs (download, ingest, helpers) |
| `minsar/scripts/egms_search.py` | Search EGMS products (CLMS archive API; `--print`, `--write-curl`) |
| `minsar/scripts/egms_search_unstable.py` | EGMS search with `--relativeOrbit` + `--swath` client-side filter (API workaround) |
| `minsar/scripts/clms_get_access_token.py` | Refresh CLMS OAuth Bearer token from JWT service key JSON |
| `minsar/utils/clms_auth.py` | Shared CLMS jwt-bearer auth helpers |
| `minsar/utils/` | Reusable Python modules and colocated `tests/` |
| `minsar/defaults/` | Job and queue defaults |
| `samples/` | Example `.template` files |
| `tests/` | Integration and bash tests |
| `architecture_docs/` | Architecture notes (this tree) |
| `tools/sarvey/` | SARvey package (standalone) |
| `tools/thermal_models/` | Thermal / building deformation tools |
| `tools/thermal_models/simulator_falk/` | Building settlement / shrinkage 3D GUI |

## Building settlement simulator (`tools/thermal_models/simulator_falk`)

| Path | Purpose |
|------|---------|
| `tools/thermal_models/simulator_falk/building_model.py` | Prism geometry, settlement/tilt/shrinkage kinematics |
| `tools/thermal_models/simulator_falk/gui_app.py` | PySide6 + PyVista 3D before/after viewer |
| `tools/thermal_models/simulator_falk/requirements.txt` | Optional deps (PyVista, PySide6) |
| `tools/thermal_models/simulator_falk/tests/test_building_model.py` | Unit tests |
| `tools/thermal_models/simulator_falk/fit_thermal_models.py` | Fit deformation models to InSAR point time series |

## Thermal expansion (displacement CSV post-processing)

| Path | Purpose |
|------|---------|
| `tools/emirhan_insarmaps_utils/helper_thermal.py` | Library: displacement/temperature parsing, regression, correction; Open-Meteo/CDS download helpers |
| `tools/emirhan_insarmaps_utils/download_temperature.py` | CLI for daily temperature text file; default output `temp.txt` if `--out` omitted |
| `tools/emirhan_insarmaps_utils/fit_thermal_expansion.py` | CLI: fit + write `*_thermal_fit.csv` |
| `tools/emirhan_insarmaps_utils/remove_thermal_expansion.py` | CLI: optional temperature download + fit + `*_corrected.csv` |
| `tools/emirhan_insarmaps_utils/plot_temperature.py` | CLI: plot daily temperature text file (default input `temp.txt`) |
| `tools/emirhan_insarmaps_utils/tests/test_thermal_expansion.py` | Unit tests |

Run from the repo root, e.g. `python tools/emirhan_insarmaps_utils/download_temperature.py --help` (scripts add their directory to `sys.path` for imports).

## Other documentation

| Document | Description |
|----------|-------------|
| [OVERVIEW.md](./OVERVIEW.md) | Pipelines and design |
| [README.md](./README.md) | Index and quick reference |
| [DEVELOPMENT_GUIDE.md](./DEVELOPMENT_GUIDE.md) | Conventions and testing |
