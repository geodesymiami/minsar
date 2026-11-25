---
paths:
  - "**/*.py"
---

# Python scripts

- `argparse` for the CLI, with examples in the epilog. `pathlib.Path` for paths. Docstrings for modules and functions.
- Each `parser.add_argument(...)` on a single line. If the line, indentation included, would exceed 170 characters, shorten `help` first, then split the call. `create_parser()` in `minsar/scripts/create_template.py` is the model.

## AOI arguments

When a script accepts a geographic area of interest:

- Write **AOI** in capitals in everything users see (help, `metavar="AOI"`, examples, errors, docs). The argparse `dest` may stay lowercase.
- Before `parse_args`, call `fix_argv_for_negative_bbox_sn_we` from `minsar.utils.bbox_cli_argv` so negative latitudes parse. Pass a kwargs dict of the script's options (`consume_one`, `consume_two`, `flags`); `CONVERT_BBOX_ARGV_KW` and `CREATE_TEMPLATE_ARGV_KW` in that module are the patterns. With two or more leading positionals (e.g. AOI then project name), set `multiple_initial_positionals=True`.
- Accept the same forms as `minsar/utils/convert_bbox.py`: bounds `lat_min:lat_max,lon_min:lon_max` (S:N,W:E), WKT `POLYGON((lon lat, ...))`, and whatever else `_input_to_bounds` handles.
- Reuse `minsar.utils.convert_bbox._input_to_bounds` instead of writing new parsing. For subprocess calls to tools that take the same AOI string (e.g. `get_sar_coverage.py`), pass the raw AOI after the argv fix.
