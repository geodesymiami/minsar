#!/usr/bin/env bash
set -eo pipefail

clone_repo() {
    [[ -e "$2" ]] && echo "skip clone (exists): $2" && return 0
    git clone "$1" "$2"
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

(
cd tools/sweets

# Prefer tools/dolphin over sweets' scottstanie/dolphin pin (needs _block_split).
if [[ -d ../dolphin ]]; then
    python3 - <<'PY'
from pathlib import Path
import re
path = Path("pyproject.toml")
text = path.read_text()
replacement = 'dolphin = { path = "../dolphin", editable = false }'
text2, n = re.subn(r'^dolphin = \{ git = "https://github.com/scottstanie/dolphin\.git".*$', replacement, text, count=1, flags=re.M)
if n == 0:
    text2, n = re.subn(r'^dolphin = \{ path = "\.\./dolphin".*$', replacement, text, count=1, flags=re.M)
if n == 0:
    raise SystemExit("Error: could not pin sweets dolphin to ../dolphin in pyproject.toml")
path.write_text(text2)
print("Pinned sweets dolphin to ../dolphin (non-editable)")
PY
fi

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

# sweets pins scottstanie/opera-utils@develop-scott; shipped pixi.lock + dolphin
# egg-info can still advertise opera-utils>=0.25.7 against an old 0.25.5.dev0
# lock entry. Relax metadata for the solve, drop the lock, install default only.
dolphin_req="../dolphin/requirements.txt"
dolphin_req_bak=""
if [[ -f "$dolphin_req" ]] && grep -q 'opera-utils>=0\.25\.7' "$dolphin_req"; then
    dolphin_req_bak="${dolphin_req}.minsar.bak"
    cp "$dolphin_req" "$dolphin_req_bak"
    python3 - <<'PY'
from pathlib import Path
p = Path("../dolphin/requirements.txt")
text = p.read_text()
text2 = text.replace("opera-utils>=0.25.7", "opera-utils>=0.25.5", 1)
if text2 == text:
    raise SystemExit("Error: could not relax dolphin opera-utils pin")
p.write_text(text2)
egg = Path("../dolphin/src/dolphin.egg-info")
for name in ("requires.txt", "PKG-INFO"):
    meta = egg / name
    if meta.is_file():
        meta.write_text(meta.read_text().replace("opera-utils>=0.25.7", "opera-utils>=0.25.5"))
print("Relaxed dolphin opera-utils pin for sweets develop-scott solve")
PY
fi

restore_dolphin_req() {
    if [[ -n "$dolphin_req_bak" && -f "$dolphin_req_bak" ]]; then
        mv "$dolphin_req_bak" "$dolphin_req"
    fi
}

# Path-pinning dolphin invalidates sweets' lock (was scottstanie/dolphin git).
rm -f pixi.lock

# default env is what MinSAR stages/runs; full `pixi install` also solves gpu
# (including osx-arm64 / linux-cuda) and is unnecessary here.
if ! pixi install -e default; then
    restore_dolphin_req
    echo "Error: pixi install failed (lock/solve)" >&2
    exit 1
fi
pixi upgrade asf_search || true

if [[ ! -x .pixi/envs/default/bin/python ]]; then
    restore_dolphin_req
    echo "Error: SWEETS pixi default env missing after pixi install: $(pwd)/.pixi/envs/default" >&2
    exit 1
fi
if [[ -d ../dolphin ]]; then
    .pixi/envs/default/bin/python -m pip install ../dolphin --no-deps --force-reinstall
fi
restore_dolphin_req
)

echo "sweets installation DONE"

# Scratch staging is for SLURM compute nodes (often noexec on $MINSAR_HOME).
if [[ "$(uname)" == "Linux" && -f minsar/scripts/stage_sweets_pixi_env.bash ]]; then
    minsar/scripts/stage_sweets_pixi_env.bash --force
fi

echo "Running of install_isce3.bash DONE"
