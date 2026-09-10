#!/usr/bin/env bash
set -eo pipefail

clone_repo() {
    [[ -e "$2" ]] && echo "skip clone (exists): $2" && return 0
    git clone "$1" "$2"
}

clone_branch() {
    local url="$1" dest="$2" branch="$3"
    if [[ -e "$dest" ]]; then
        echo "skip clone (exists): $dest"
        # Ensure tags exist so setuptools_scm reports a real version for path pins.
        git -C "$dest" fetch --tags --quiet 2>/dev/null || true
        return 0
    fi
    # Full branch history (not --depth 1): shallow clones break setuptools_scm versions
    # (opera-utils becomes 0.0.post1, which conflicts with dolphin's opera-utils>=0.25.7).
    git clone --branch "$branch" --single-branch "$url" "$dest"
    git -C "$dest" fetch --tags --quiet 2>/dev/null || true
}

### Install #########################
clone_repo git@github.com:opera-adt/COMPASS.git tools/COMPASS
clone_repo git@github.com:opera-adt/disp-s1.git tools/disp-s1
clone_repo git@github.com:opera-adt/bowser.git tools/bowser
clone_repo git@github.com:opera-adt/tropo.git tools/tropo
clone_repo git@github.com:opera-adt/disp-nisar.git tools/disp-nisar
clone_repo git@github.com:OPERA-Cal-Val/OPERA_Applications.git tools/OPERA_Applications
clone_repo git@github.com:isce-framework/dolphin.git tools/dolphin
clone_repo https://github.com/isce-framework/sweets.git tools/sweets

# scottstanie forks used by sweets pyproject (path pins avoid git fetches inside pixi/uv).
clone_branch https://github.com/scottstanie/s1-reader.git tools/s1-reader develop-scott
clone_branch https://github.com/scottstanie/COMPASS.git tools/COMPASS_scott develop-scott
clone_branch https://github.com/scottstanie/opera-utils.git tools/opera-utils develop-scott
clone_branch https://github.com/scottstanie/spurt.git tools/spurt develop-scott

(
cd tools/sweets

# Prefer local clones over sweets' scottstanie git pins (HPC: uv git-fetch hits nproc limits).
python3 - <<'PY'
from pathlib import Path
import re

path = Path("pyproject.toml")
text = path.read_text()
replacements = [
    (
        r'^s1reader = \{ git = "https://github.com/scottstanie/s1-reader\.git".*$',
        's1reader = { path = "../s1-reader", editable = false }',
        r'^s1reader = \{ path = "\.\./s1-reader".*$',
    ),
    (
        r'^compass = \{ git = "https://github.com/scottstanie/COMPASS\.git".*$',
        'compass = { path = "../COMPASS_scott", editable = false }',
        r'^compass = \{ path = "\.\./COMPASS_scott".*$',
    ),
    (
        r'^dolphin = \{ git = "https://github.com/scottstanie/dolphin\.git".*$',
        'dolphin = { path = "../dolphin", editable = false }',
        r'^dolphin = \{ path = "\.\./dolphin".*$',
    ),
    (
        r'^spurt = \{ git = "https://github.com/scottstanie/spurt\.git".*$',
        'spurt = { path = "../spurt", editable = false }',
        r'^spurt = \{ path = "\.\./spurt".*$',
    ),
]
for git_pat, path_line, path_pat in replacements:
    text2, n = re.subn(git_pat, path_line, text, count=1, flags=re.M)
    if n == 0:
        text2, n = re.subn(path_pat, path_line, text, count=1, flags=re.M)
    if n == 0:
        raise SystemExit(f"Error: could not pin sweets dependency to path: {path_line}")
    text = text2
    print(f"Pinned {path_line}")

# opera-utils may be multi-line (extras list).
opera_path = '''opera-utils = { path = "../opera-utils", editable = false, extras = [
  "asf",
  "disp",
  "nisar",
  "tropo",
] }'''
opera_pat = re.compile(
    r'^opera-utils = \{ git = "https://github.com/scottstanie/opera-utils\.git".*?\n\] \}',
    re.M | re.S,
)
text2, n = opera_pat.subn(opera_path, text, count=1)
if n == 0:
    opera_pat2 = re.compile(
        r'^opera-utils = \{ path = "\.\./opera-utils".*?\n\] \}',
        re.M | re.S,
    )
    text2, n = opera_pat2.subn(opera_path, text, count=1)
if n == 0:
    raise SystemExit("Error: could not pin sweets opera-utils to ../opera-utils")
text = text2
print("Pinned opera-utils to ../opera-utils (non-editable)")
path.write_text(text)
PY

# MinSAR generate_sweets_config passes --burst-ids for opera-cslc; upstream ConfigCli
# hides search and does not expose that flat flag. Re-apply the local CLI wire-up.
python3 - <<'PY'
from pathlib import Path

path = Path("src/sweets/cli.py")
text = path.read_text()
if "burst_ids: Optional[list[str]]" in text and 'search["burst_ids"]' in text:
    print("sweets ConfigCli already has --burst-ids")
else:
    needle = '''    swaths: Optional[list[str]] = Field(
        default=None,
        description=(
            "Restrict to specific subswaths (e.g. ['IW2']). Only"
            " honored by --source safe."
        ),
        exclude=True,
    )
    out_dir: Path = Field('''
    insert = '''    swaths: Optional[list[str]] = Field(
        default=None,
        description=(
            "Restrict to specific subswaths (e.g. ['IW2']). Only"
            " honored by --source safe."
        ),
        exclude=True,
    )
    burst_ids: Optional[list[str]] = Field(
        default=None,
        description=(
            "Restrict to specific OPERA burst IDs (e.g. t078_165573_iw2)."
            " Only honored by --source opera-cslc."
        ),
        exclude=True,
    )
    out_dir: Path = Field('''
    if needle not in text:
        raise SystemExit("Error: could not insert sweets ConfigCli burst_ids field")
    text = text.replace(needle, insert, 1)
    needle2 = '''            elif src == "opera-cslc":
                if data.get("track") is not None:
                    search["track"] = data["track"]
            elif src == "nisar-gslc":'''
    insert2 = '''            elif src == "opera-cslc":
                if data.get("track") is not None:
                    search["track"] = data["track"]
                if data.get("burst_ids") is not None:
                    search["burst_ids"] = data["burst_ids"]
            elif src == "nisar-gslc":'''
    if needle2 not in text:
        raise SystemExit("Error: could not wire sweets ConfigCli burst_ids into search")
    text = text.replace(needle2, insert2, 1)
    path.write_text(text)
    print("Patched sweets ConfigCli for --burst-ids (opera-cslc)")
PY

# Patch YamlModel for sweets oneOf/$ref schemas if needed.
if [[ -f ../dolphin/src/dolphin/workflows/config/_yaml_model.py ]]; then
    python3 - <<'PY'
from pathlib import Path
path = Path("../dolphin/src/dolphin/workflows/config/_yaml_model.py")
text = path.read_text()
old = '''        if "anyOf" in val:
            #   'anyOf': [{'type': 'string'}, {'type': 'null'}],
            # Join the options with a pipe, like Python types
            type_str = " | ".join(d["type"] for d in val["anyOf"])
            type_str.replace("null", "None")
        elif "const" in val:
            type_str = val["const"]
        else:
            type_str = val["type"]'''
new = '''        if "anyOf" in val or "oneOf" in val:
            #   'anyOf': [{'type': 'string'}, {'type': 'null'}],
            # or for a Union of submodels (plain or discriminated):
            #   'anyOf': [{'$ref': '#/$defs/A'}, {'$ref': '#/$defs/B'}]
            #   'oneOf': [{'$ref': '#/$defs/A'}, {'$ref': '#/$defs/B'}]
            # `oneOf` shows up when the field uses
            # `Annotated[Union[...], Field(discriminator=...)]`. Join the
            # options with a pipe, like Python types; fall back to the
            # sub-model name for `$ref` entries that have no primitive
            # `type` key.
            def _union_label(d: dict) -> str:
                if "type" in d:
                    return d["type"]
                if "$ref" in d:
                    return d["$ref"].rsplit("/", 1)[-1]
                return "object"

            entries = val.get("anyOf") or val.get("oneOf") or []
            type_str = " | ".join(_union_label(d) for d in entries)
            type_str.replace("null", "None")
        elif "const" in val:
            type_str = val["const"]
        else:
            type_str = val.get("type", "object")'''
if old in text:
    path.write_text(text.replace(old, new, 1))
    print("Patched dolphin YamlModel for sweets oneOf/$ref schemas")
elif 'val.get("type", "object")' in text:
    print("dolphin YamlModel already patched")
else:
    raise SystemExit("Error: unexpected dolphin _yaml_model.py; cannot patch for sweets")
PY
fi

# Pixi solves the lockfile for every workspace platform. On Linux that means it
# also tries to fetch/solve osx-arm64 PyPI/conda packages (and vice versa). That
# cross-platform solve often fails on HPC and leaves a half-installed env.
# Restrict platforms to the host before install; sweets already lists both.
case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) host_pixi_platform="linux-64" ;;
    Darwin-arm64) host_pixi_platform="osx-arm64" ;;
    Darwin-x86_64) host_pixi_platform="osx-64" ;;
    *)
        echo "Error: unsupported host for sweets pixi: $(uname -s) $(uname -m)" >&2
        exit 1
        ;;
esac
python3 - <<PY
from pathlib import Path
import re
path = Path("pyproject.toml")
text = path.read_text()
text2, n = re.subn(
    r"^platforms = \[.*?\]$",
    'platforms = ["${host_pixi_platform}"]',
    text,
    count=1,
    flags=re.M,
)
if n != 1:
    raise SystemExit("Error: could not set tool.pixi platforms to host-only in pyproject.toml")
text = text2

# Keep sweets HDF5 on 1.14.x so *-stack.nc VDS is readable by minsar conda
# dolphin2hdfeos5 (HDF5 1.14.6). Unpinned solves now pull HDF5 2.x (VDS heap v1).
hdf5_line = 'hdf5 = ">=1.14,<2"'
text2, n = re.subn(r'^hdf5 = .*$', hdf5_line, text, count=1, flags=re.M)
if n == 0:
    text2, n = re.subn(r'^(h5py = .*)$', rf'\1\n{hdf5_line}', text, count=1, flags=re.M)
if n != 1:
    raise SystemExit("Error: could not pin hdf5 >=1.14,<2 in sweets pyproject.toml")
path.write_text(text2)
print(f"Restricted sweets pixi platforms to ${host_pixi_platform} for this install")
print(f"Pinned sweets pixi {hdf5_line} (minsar dolphin2hdfeos5 compatibility)")
PY

# Prefer local disk for rattler/pixi cache when HOME cache is on Lustre/NFS.
if [[ -z "${PIXI_CACHE_DIR:-}" ]]; then
    export PIXI_CACHE_DIR="${TMPDIR:-/tmp}/pixi-cache-${USER}"
    mkdir -p "$PIXI_CACHE_DIR"
    echo "Using PIXI_CACHE_DIR=$PIXI_CACHE_DIR"
fi

# A sourced minsar env (s.bw2) puts MintPy/sarvey/etc on PYTHONPATH; pip then
# reports unrelated "dependency conflicts" and can install into the wrong context.
unset PYTHONPATH PYTHONHOME || true

# Login/interactive nodes often hit process/thread ulimits during uv/rayon PyPI solves.
# Prefer a dedicated sbatch/idev shell (not Cursor) if install fails with WouldBlock.
export RAYON_NUM_THREADS="${RAYON_NUM_THREADS:-1}"
export TOKIO_WORKER_THREADS="${TOKIO_WORKER_THREADS:-2}"
export UV_CONCURRENCY="${UV_CONCURRENCY:-1}"
export PIXI_NO_PROGRESS=true
# Fallback when path clones still lack reachable tags for setuptools_scm.
export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OPERA_UTILS="${SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OPERA_UTILS:-0.25.8}"
pixi install --no-progress --concurrent-solves "${PIXI_CONCURRENT_SOLVES:-1}" --concurrent-downloads "${PIXI_CONCURRENT_DOWNLOADS:-4}"
pixi upgrade asf_search || true

sweets_python=".pixi/envs/default/bin/python"
[[ -x "$sweets_python" ]] || {
    echo "Error: sweets pixi python missing after install: $sweets_python" >&2
    exit 1
}
# Path deps are already in pyproject; --no-deps avoids pip wheels (e.g. h5py)
# overwriting conda-forge packages and breaking the hdf5 1.14.x pin.
if [[ -d ../dolphin ]]; then
    "$sweets_python" -m pip install ../dolphin --no-deps --force-reinstall
fi
if [[ -d ../opera-utils ]]; then
    SETUPTOOLS_SCM_PRETEND_VERSION=0.25.8 "$sweets_python" -m pip install ../opera-utils --no-deps --force-reinstall
fi
# disp_s1_process (ISCE3 opera mode) needs cmap; not always pulled by sweets alone.
"$sweets_python" -m pip install 'cmap' --quiet
"$sweets_python" -c "import opera_utils, shapely, cmap; print('Verified opera_utils + shapely + cmap in sweets env')"
"$sweets_python" -c "import h5py; v=h5py.version.hdf5_version; assert v.startswith('1.'), f'expected HDF5 1.x, got {v}'; print(f'Verified sweets HDF5 {v} (h5py {h5py.__version__})')"
)

echo "sweets installation DONE"

echo "Running of install_isce3.bash DONE"
