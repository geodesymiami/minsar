#!/usr/bin/env python3
"""Stage tutorial notebooks into $SCRATCHDIR/notebooks and point their output at $SCRATCHDIR/nb_runs.

Sources are listed in tools/notebooks/notebooks.list (paths relative to $MINSAR_HOME/tools/notebooks).
Annotated FA_*.ipynb from $MINSAR_HOME/tools/notebooks/ are copied alongside them. Staged copies are
disposable; $MINSAR_HOME/tools/notebooks/ is never modified.
"""

import argparse
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

EXAMPLE = """Examples:
  stage_notebooks.py
  stage_notebooks.py opera-disp-01-explore.ipynb
  stage_notebooks.py --force opera-disp-01-explore.ipynb
  stage_notebooks.py --dry-run
"""

VAR = r"(?P<indent>[ \t]*)(?P<var>WORK_DIR|work_dir)\s*=\s*"
TRAIL = r"\s*(?:#.*)?$"

# Work-dir assignments rewritten to NB_WORK; add a rule when a notebook uses another form.
PATCH_RULES = [
    # WORK_DIR = Path("./example_opera_cslc").resolve()  /  work_dir = Path(f'~/data/Hawaii_{ymd}').expanduser()
    (
        re.compile(VAR + r"Path\(\s*[rf]?(?P<quote>['\"])[^'\"]*(?P=quote)\s*\)"
                   r"(?:\s*\.\s*(?:resolve|expanduser)\(\s*\))?" + TRAIL),
        "{indent}{var} = NB_WORK",
    ),
    # work_dir = Path.home() / "data" / "SanFranSenDT42" / "mintpy"
    (
        re.compile(VAR + r"Path\.home\(\)\s*/\s*['\"]data['\"]"
                   r"(?P<rest>(?:\s*/\s*[rf]?['\"][^'\"]*['\"])*)" + TRAIL),
        "{indent}{var} = NB_WORK{rest}",
    ),
    # work_dir = os.path.join(os.getenv("HOME"), "work")
    (
        re.compile(VAR + r"os\.path\.join\(\s*os\.(?:getenv\(\s*['\"]HOME['\"]\s*\)|environ\[['\"]HOME['\"]\])"
                   r"(?:\s*,\s*[rf]?['\"][^'\"]*['\"])*\s*\)" + TRAIL),
        "{indent}{var} = str(NB_WORK)",
    ),
    # home_dir = os.path.join(os.getenv("HOME"), "testing"|"work")
    (
        re.compile(r"(?P<indent>[ \t]*)home_dir\s*=\s*os\.path\.join\(\s*os\.getenv\(\s*['\"]HOME['\"]\s*\)"
                   r"\s*,\s*[rf]?['\"][^'\"]*['\"]\s*\)" + TRAIL),
        "{indent}home_dir = str(NB_WORK)",
    ),
    # RUNS_DIR = Path(".")  (example_compare_sources reads sibling sweets runs)
    (
        re.compile(r"(?P<indent>[ \t]*)RUNS_DIR\s*=\s*Path\(\s*['\"]\.['\"]\s*\)" + TRAIL),
        '{indent}RUNS_DIR = Path(os.environ["SCRATCHDIR"]) / "nb_runs"',
    ),
    # tutorial_home_dir = os.getcwd()
    (
        re.compile(r"(?P<indent>[ \t]*)tutorial_home_dir\s*=\s*os\.getcwd\(\s*\)" + TRAIL),
        "{indent}tutorial_home_dir = str(NB_WORK)",
    ),
    # HERE = Path.cwd()  /  NOTEBOOK_DIR = Path.cwd()
    (
        re.compile(r"(?P<indent>[ \t]*)(?P<var>HERE|NOTEBOOK_DIR)\s*=\s*Path\.cwd\(\s*\)" + TRAIL),
        "{indent}{var} = NB_WORK",
    ),
    # path = f"{os.getcwd()}/data"
    (
        re.compile(r"(?P<indent>[ \t]*)path\s*=\s*f['\"]\{os\.getcwd\(\)\}/data['\"]" + TRAIL),
        '{indent}path = str(NB_WORK / "data")',
    ),
]

NB_WORK_DEF_RE = re.compile(r"^\s*NB_WORK\s*=")

# Notebooks that share one run directory (they read each other's CWD-relative files).
SHARED_RUNS = {
    "opera-disp-01-explore.ipynb": "opera-disp",
    "opera-disp-01-explore-executed.ipynb": "opera-disp",
    "opera-disp-02-mintpy.ipynb": "opera-disp",
    "opera-disp-02-mintpy-executed.ipynb": "opera-disp",
    "phase-linked-ifg-comparison.ipynb": "phase-linking",
    "theory-phase-linking.ipynb": "phase-linking",
    "NISAR_GUNW_Tutorial.ipynb": "nisar-standard-products",
    "NISAR_RSLC_Tutorial.ipynb": "nisar-standard-products",
    "download_data.ipynb": "nisar-standard-products",
    "NISAR_GSLC_Tutorial.ipynb": "nisar-standard-products",
}

# Files/dirs next to the source notebook, copied into the run directory.
SIDECARS = {
    "S1_GSLC_burst.ipynb": ["utils.py"],
    "S1_GSLC_burst_stack.ipynb": ["utils.py"],
    "opera-disp-01-explore.ipynb": ["utils.py"],
    "opera-disp-01-explore-executed.ipynb": ["utils.py"],
    "opera-disp-02-mintpy.ipynb": ["utils.py"],
    "opera-disp-02-mintpy-executed.ipynb": ["utils.py"],
    "smallbaselineApp_aria.ipynb": ["utils.py"],
    "smallbaselineApp_nisar.ipynb": ["utils.py"],
    "theory-phase-linking.ipynb": ["synth_config.json", "dolphin_config.yaml"],
    "phase-linked-ifg-comparison.ipynb": ["synth_config.json", "dolphin_config.yaml"],
    "dolphin-isce2.ipynb": ["dolphin_config.yaml"],
    "dolphin-three-sisters-cslcs.ipynb": ["staging", "dolphin_config.yaml"],
    "dolphin-nisar-mexico-city.ipynb": ["staging"],
}

# Exact string replacements applied to the whole notebook after regex rules.
NOTEBOOK_REPLACEMENTS = {
    "stripmapApp-Baja_Env.ipynb": [
        ("cmd_reference_config = '''", "cmd_reference_config = f'''"),
        ("cmd_secondary_config = '''", "cmd_secondary_config = f'''"),
        ("/home/jovyan/work/data/Baja", "{DATA_DIR}"),
        ("/home/jovyan/testing/Baja", "{PROCESS_DIR}"),
    ],
    "ui.ipynb": [
        ('input_work_dir = widgets.Text(placeholder=".")',
         "input_work_dir = widgets.Text(value=str(NB_WORK), placeholder=str(NB_WORK))"),
        ('kwargs["work_dir"] = input_data_dir.value',
         'kwargs["work_dir"] = input_work_dir.value'),
    ],
}


def create_parser():
    parser = argparse.ArgumentParser(
        description="Copy notebooks to $SCRATCHDIR/notebooks (redirect output to $SCRATCHDIR/nb_runs/<name>). Missing notebooks will be replaced.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EXAMPLE,
    )
    parser.add_argument("notebook", nargs="?", metavar="NOTEBOOK", help="optional .ipynb to stage (basename, path under tools/notebooks/, or absolute path)")
    parser.add_argument("--list", dest="list_file", metavar="FILE", help="notebook list (default: $MINSAR_HOME/tools/notebooks/notebooks.list)")
    parser.add_argument("--dest", metavar="DIR", help="staging directory (default: $SCRATCHDIR/notebooks)")
    parser.add_argument("--runs", metavar="DIR", help="run-data directory (default: $SCRATCHDIR/nb_runs)")
    parser.add_argument("--force", action="store_true", help="overwrite existing staged copies (FA_*.ipynb are always kept)")
    parser.add_argument("--dry-run", action="store_true", help="show what would be copied")
    return parser


def minsar_home():
    home = os.environ.get("MINSAR_HOME")
    if home:
        return Path(home)
    return Path(__file__).resolve().parents[2]


def read_list(list_file):
    """Return notebook paths relative to tools/notebooks/, ignoring blank lines and comments."""
    entries = []
    for line in list_file.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            entries.append(line)
    return entries


def resolve_notebook(notebook_arg, notebooks_dir, list_entries):
    """Resolve NOTEBOOK to (src Path, is_fa bool). Exit on error."""
    raw = Path(notebook_arg).expanduser()
    if raw.suffix != ".ipynb":
        sys.exit(f"ERROR: NOTEBOOK must be a .ipynb file: {notebook_arg}")

    # Absolute / explicit path
    if raw.is_file():
        return raw.resolve(), raw.name.startswith("FA_")

    # Basename match in notebooks.list
    matches = [e for e in list_entries if Path(e).name == raw.name]
    if len(matches) == 1:
        src = notebooks_dir / matches[0]
        if not src.is_file():
            sys.exit(f"ERROR: listed notebook not found: {src}")
        return src.resolve(), False
    if len(matches) > 1:
        sys.exit(f"ERROR: ambiguous notebook name {raw.name}: {', '.join(matches)}")

    # Path relative to tools/notebooks/
    under_notebooks = notebooks_dir / notebook_arg
    if under_notebooks.is_file():
        return under_notebooks.resolve(), False

    # FA_ under $MINSAR_HOME/tools/notebooks/
    fa = notebooks_dir / raw.name
    if raw.name.startswith("FA_") and fa.is_file():
        return fa.resolve(), True

    sys.exit(f"ERROR: notebook not found: {notebook_arg}")


def cell_lines(cell):
    source = cell.get("source", [])
    if isinstance(source, str):
        return source.splitlines(keepends=True)
    return list(source)


def set_cell_source(cell, lines):
    cell["source"] = lines


def run_dir_for(nb_name, runs_dir):
    """Return $SCRATCHDIR/nb_runs/<stem>, or a shared family directory."""
    return runs_dir / SHARED_RUNS.get(nb_name, Path(nb_name).stem)


def nb_work_cell(nbformat_minor, run_dir):
    """Code cell defining NB_WORK, chdir, and import path for sidecars."""
    source = [
        "# staged by stage_notebooks.py: all output of this notebook goes to NB_WORK\n",
        "import os\n",
        "import sys\n",
        "from pathlib import Path\n",
        f'NB_WORK = Path(os.environ["SCRATCHDIR"]) / "{run_dir.parent.name}" / "{run_dir.name}"\n',
        "NB_WORK.mkdir(parents=True, exist_ok=True)\n",
        "os.chdir(NB_WORK)\n",
        "sys.path.insert(0, str(NB_WORK))\n",
        "print('NB_WORK:', NB_WORK)",
    ]
    cell = {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": source}
    if nbformat_minor >= 5:
        cell["id"] = f"nbwork-{uuid.uuid4().hex[:8]}"
    return cell


def apply_line_rules(lines):
    """Rewrite known work-dir assignment lines. Return (new_lines, n_replaced)."""
    n_replaced = 0
    out = []
    for line in lines:
        replaced = False
        for regex, template in PATCH_RULES:
            match = regex.match(line.rstrip("\n"))
            if match:
                newline = "\n" if line.endswith("\n") else ""
                out.append(template.format(**match.groupdict(default="")) + newline)
                n_replaced += 1
                replaced = True
                break
        if not replaced:
            out.append(line)
    return out, n_replaced


def apply_notebook_replacements(text, nb_name):
    """Apply exact string replacements for a specific notebook."""
    n = 0
    for old, new in NOTEBOOK_REPLACEMENTS.get(nb_name, []):
        if old in text:
            text = text.replace(old, new)
            n += 1
    return text, n


def patch_notebook(src, dest, run_dir):
    """Copy src to dest with NB_WORK, chdir, and notebook-specific path rewrites."""
    notebook = json.loads(src.read_text())
    cells = notebook.get("cells", [])
    code_indices = [i for i, c in enumerate(cells) if c.get("cell_type") == "code"]
    if not code_indices:
        shutil.copyfile(src, dest)
        return 0

    already_defined = any(NB_WORK_DEF_RE.match(line) for i in code_indices for line in cell_lines(cells[i]))

    n_replaced = 0
    for cell in (cells[i] for i in code_indices):
        lines, n = apply_line_rules(cell_lines(cell))
        text = "".join(lines)
        text, n2 = apply_notebook_replacements(text, src.name)
        set_cell_source(cell, text.splitlines(keepends=True) or [text])
        n_replaced += n + n2

    if not already_defined:
        cells.insert(code_indices[0], nb_work_cell(notebook.get("nbformat_minor", 0), run_dir))

    dest.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n")
    return n_replaced


def copy_sidecars(src_nb, run_dir, force=False, dry_run=False):
    """Copy helper files from the source notebook directory into the run directory."""
    n = 0
    for name in SIDECARS.get(src_nb.name, []):
        src = src_nb.parent / name
        dest = run_dir / name
        if not src.exists():
            print(f"    note: sidecar missing {src}")
            continue
        if dest.exists() and not force:
            continue
        print(f"    sidecar {src} -> {dest}")
        n += 1
        if dry_run:
            continue
        run_dir.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest, dirs_exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    return n


def main(argv=None):
    inps = create_parser().parse_args(argv)

    scratch = os.environ.get("SCRATCHDIR")
    if not scratch:
        sys.exit("ERROR: SCRATCHDIR is not set")

    home = minsar_home()
    notebooks_dir = home / "tools" / "notebooks"
    list_file = Path(inps.list_file).expanduser() if inps.list_file else notebooks_dir / "notebooks.list"
    dest_dir = Path(inps.dest).expanduser() if inps.dest else Path(scratch) / "notebooks"
    runs_dir = Path(inps.runs).expanduser() if inps.runs else Path(scratch) / "nb_runs"

    if not list_file.is_file():
        sys.exit(f"ERROR: notebook list not found: {list_file}")

    entries = read_list(list_file)

    by_name = {}
    for entry in entries:
        by_name.setdefault(Path(entry).name, []).append(entry)
    clashes = {name: paths for name, paths in by_name.items() if len(paths) > 1}
    if clashes:
        for name, paths in sorted(clashes.items()):
            print(f"ERROR: duplicate notebook name {name}: {', '.join(paths)}", file=sys.stderr)
        sys.exit("ERROR: notebook names must be unique (staging is flat)")

    if not inps.dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    # Stage a single NOTEBOOK
    if inps.notebook:
        src, is_fa = resolve_notebook(inps.notebook, notebooks_dir, entries)
        dest = dest_dir / src.name
        run_dir = run_dir_for(src.name, runs_dir)
        if dest.exists() and not inps.force:
            print(f"skipped existing {dest} (use --force to refresh)")
            return 0
        print(f"{src} -> {dest}  [run {run_dir}]")
        if inps.dry_run:
            if not is_fa:
                copy_sidecars(src, run_dir, force=True, dry_run=True)
            return 0
        if is_fa:
            shutil.copyfile(src, dest)
        else:
            patch_notebook(src, dest, run_dir)
            copy_sidecars(src, run_dir, force=inps.force, dry_run=False)
        print(f"\nstaged 1 notebook in {dest_dir}")
        print(f"run data goes to {runs_dir}/<name>; remove with: rm -rf {runs_dir}")
        return 0

    missing = [entry for entry in entries if not (notebooks_dir / entry).is_file()]
    present = [entry for entry in entries if (notebooks_dir / entry).is_file()]
    if missing:
        for entry in missing:
            print(f"WARNING: missing source (skipped): {notebooks_dir / entry}", file=sys.stderr)
        print(f"WARNING: skipped {len(missing)} of {len(entries)} notebooks not found under {notebooks_dir}", file=sys.stderr)
    if not present:
        sys.exit(f"ERROR: none of {len(entries)} listed notebooks found under {notebooks_dir}")

    n_copied = n_skipped = n_sidecars = 0
    for entry in present:
        src = notebooks_dir / entry
        dest = dest_dir / src.name
        run_dir = run_dir_for(src.name, runs_dir)
        if dest.exists() and not inps.force:
            n_skipped += 1
            n_sidecars += copy_sidecars(src, run_dir, force=False, dry_run=inps.dry_run)
            continue
        print(f"{src} -> {dest}  [run {run_dir}]")
        if inps.dry_run:
            n_copied += 1
            n_sidecars += copy_sidecars(src, run_dir, force=True, dry_run=True)
            continue
        patch_notebook(src, dest, run_dir)
        n_sidecars += copy_sidecars(src, run_dir, force=inps.force, dry_run=False)
        n_copied += 1

    n_fa = 0
    for src in sorted(notebooks_dir.glob("FA_*.ipynb")):
        dest = dest_dir / src.name
        if dest.exists():
            n_skipped += 1
            continue
        print(f"{src} -> {dest}")
        if not inps.dry_run:
            shutil.copyfile(src, dest)
        n_fa += 1

    print(f"\nstaged {n_copied} notebooks and {n_fa} FA notebooks in {dest_dir}")
    if missing:
        print(f"skipped {len(missing)} missing sources")
    if n_sidecars:
        print(f"copied {n_sidecars} sidecars into {runs_dir}")
    if n_skipped:
        print(f"skipped {n_skipped} existing (use --force to refresh; FA_*.ipynb must be deleted by hand)")
    print(f"run data goes to {runs_dir}/<name>; remove with: rm -rf {runs_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
