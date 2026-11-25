#!/usr/bin/env python3
"""Put the template's looks into an existing project, to rerun ISCE with other looks (minsarApp.bash --isce-start).

Sentinel-1 (topsStack): rewrites range_looks / azimuth_looks / rlks / alks in configs/config_*.
  stackSentinel.py cannot be run again on a processed stack, and the run files do not change.
ALOS-2 (alos2Stack): rewrites -nrlks2 / -nalks2, -nrlks R -nalks A and the _<R>rlks_<A>alks file names in run_files/ and run_files/tasks/.
Job files are not touched; they do not contain looks.

Both: removes the MintPy metadata cached with the old looks (data.rsc next to the reference metadata, and for
Sentinel-1 the *.rsc of merged/). prep_isce.py keeps an existing data.rsc, and would load the geometry with the
old size and looks.
"""

import argparse
import re
import sys
from pathlib import Path

from minsar.utils.template_looks import ALOS2_SCANSAR_DEFAULT, _active_value, stack_prefix

# first run file that depends on the looks, by name
FIRST_LOOKS_STEP = {"topsStack": "merge_reference_secondary_slc", "alos2Stack": "diff_look_filt"}
CONFIG_KEYS = {"range_looks": "rangeLooks", "rlks": "rangeLooks", "azimuth_looks": "azimuthLooks", "alks": "azimuthLooks"}
DEFAULTS_CFG = Path(__file__).resolve().parents[1] / "defaults" / "minsar_template_defaults.cfg"

EXAMPLE = """
Examples:
    update_looks_in_runfiles.py $SAMPLESDIR/unittestGalapagosSenD128.template
    update_looks_in_runfiles.py $TE/TamboraAlos2D25.template --isce-start 12
    update_looks_in_runfiles.py $TE/TamboraAlos2D25.template --print-step
"""


def create_parser():
    parser = argparse.ArgumentParser(description="Write the template's looks into the existing configs (Sentinel-1) or run files (ALOS-2).",
                                     epilog=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("template", metavar="TEMPLATE", help="template file")
    parser.add_argument("--work-dir", type=Path, default=Path.cwd(), help="project directory (default: current directory)")
    parser.add_argument("--print-step", action="store_true", help="only print the number of the first run file that depends on looks (minsarApp.bash --isce-start looks)")
    parser.add_argument("--isce-start", type=int, default=None, help="planned --isce-start; an error when it is after the first step that depends on looks")
    return parser


def template_looks(text, prefix):
    """Return {'rangeLooks': n, 'azimuthLooks': n}; auto resolves to the default."""
    looks = {}
    for name in ("rangeLooks", "azimuthLooks"):
        value = _active_value(text, f"{prefix}.{name}")
        if value is None or value.lower() in ("auto", "none"):
            value = ALOS2_SCANSAR_DEFAULT[name] if prefix == "alos2Stack" else _active_value(DEFAULTS_CFG.read_text(), f"{prefix}.{name}")
        looks[name] = int(value)
    return looks


def set_looks_in_config_text(text, looks):
    """Replace the looks values in one topsStack config file."""
    for key, name in CONFIG_KEYS.items():
        text = re.sub(rf"(?m)^({key}\s*:\s*)\S+", rf"\g<1>{looks[name]}", text)
    return text


def alos2_current_looks(texts):
    """Return (looks 1, final looks), each (range, azimuth), read from the first command that has looks 1 and 2."""
    for text in texts:
        match = re.search(r"-nrlks1 (\d+) -nalks1 (\d+) -nrlks2 (\d+) -nalks2 (\d+)", text)
        if match:
            range1, azimuth1, range2, azimuth2 = (int(value) for value in match.groups())
            return (range1, azimuth1), (range1 * range2, azimuth1 * azimuth2)
    raise ValueError("no command with -nrlks1 -nalks1 -nrlks2 -nalks2 in the run files")


def set_looks_in_alos2_text(text, looks, looks1, old):
    """Replace the looks in one alosStack run file or task. looks 1 stay; old is the current final (range, azimuth).

    Four forms: -nrlks2 N, -nalks2 N, the pair -nrlks R -nalks A (geocode), and file names _<R>rlks_<A>alks.
    """
    new = (looks["rangeLooks"], looks["azimuthLooks"])
    if new[0] % looks1[0] or new[1] % looks1[1]:
        raise ValueError(f"looks {new[0]} x {new[1]} (range x azimuth) are not multiples of looks 1, {looks1[0]} x {looks1[1]}")
    text = re.sub(r"-nrlks2 \d+", f"-nrlks2 {new[0] // looks1[0]}", text)
    text = re.sub(r"-nalks2 \d+", f"-nalks2 {new[1] // looks1[1]}", text)
    text = re.sub(rf"-nrlks {old[0]} -nalks {old[1]}(?!\d)", f"-nrlks {new[0]} -nalks {new[1]}", text)
    return re.sub(rf"_{old[0]}rlks_{old[1]}alks", f"_{new[0]}rlks_{new[1]}alks", text)


def alos2_looks_files(work_dir, first_step):
    """Run files and task scripts of the steps from first_step on (no job, log or output files)."""
    run_dir = work_dir / "run_files"
    paths = [path for path in sorted(run_dir.glob("run_[0-9][0-9]_*")) if re.fullmatch(r"run_\d\d_[A-Za-z_]+?", path.name)]
    paths += sorted((run_dir / "tasks").glob("run_[0-9][0-9]_*.bash"))
    return [path for path in paths if path.is_file() and int(path.name.split("_")[1]) >= first_step]


def remove_stale_metadata(work_dir, prefix):
    """Remove the *.rsc files that prep_isce.py wrote with the old looks. Returns the number removed."""
    if prefix == "alos2Stack":
        patterns = ["dates_resampled/*/data.rsc"]   # other .rsc names carry the looks, so new ones are written
    else:
        patterns = ["reference/data.rsc", "merged/geom_reference/*.rsc", "merged/interferograms/*/*.rsc"]
    paths = [path for pattern in patterns for path in work_dir.glob(pattern)]
    for path in paths:
        path.unlink()
    return len(paths)


def first_looks_step(work_dir, prefix):
    """Number of the first run file that depends on looks, or None when it is not found."""
    for path in sorted((work_dir / "run_files").glob(f"run_[0-9][0-9]_{FIRST_LOOKS_STEP[prefix]}")):
        return int(path.name.split("_")[1])
    return None


def main(argv=None):
    args = create_parser().parse_args(argv)
    text = Path(args.template).read_text()
    prefix = stack_prefix(text)
    if prefix not in FIRST_LOOKS_STEP:
        print(f"ERROR: changing looks of an existing project is not supported for {prefix}", file=sys.stderr)
        return 1
    work_dir = args.work_dir
    step = first_looks_step(work_dir, prefix)
    if step is None:
        print(f"ERROR: no run_NN_{FIRST_LOOKS_STEP[prefix]} in {work_dir / 'run_files'}; run the jobfiles step first", file=sys.stderr)
        return 1
    if args.print_step:
        print(step)
        return 0
    if args.isce_start is not None and args.isce_start > step:
        print(f"ERROR: new looks need --isce-start {step} or smaller ({FIRST_LOOKS_STEP[prefix]}), got {args.isce_start}", file=sys.stderr)
        return 1
    looks = template_looks(text, prefix)
    print(f"{prefix} looks: azimuth {looks['azimuthLooks']}, range {looks['rangeLooks']}; first step that depends on looks: {step}")

    try:
        if prefix == "alos2Stack":
            paths, kind = alos2_looks_files(work_dir, step), "run files and tasks"
            looks1, old_looks = alos2_current_looks(path.read_text() for path in paths)
            edit = lambda text: set_looks_in_alos2_text(text, looks, looks1, old_looks)  # noqa: E731
        else:
            paths = [path for name in ("configs", "configs_tmp") for path in sorted((work_dir / name).glob("config_*"))]
            kind = "config files"
            edit = lambda text: set_looks_in_config_text(text, looks)  # noqa: E731
        edited = [(path, path.read_text(), edit(path.read_text())) for path in paths]
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    changed = 0
    for path, old, new in edited:
        if new != old:
            path.write_text(new)
            changed += 1
    print(f"updated looks in {changed} {kind}")
    print(f"removed {remove_stale_metadata(work_dir, prefix)} MintPy metadata files (*.rsc) made with the earlier looks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
