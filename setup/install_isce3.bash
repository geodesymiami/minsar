#!/usr/bin/env bash
set -eo pipefail

### Install #########################
git clone git@github.com:opera-adt/COMPASS.git tools/COMPASS
git clone git@github.com:opera-adt/disp-s1.git tools/disp-s1
git clone git@github.com:opera-adt/bowser.git  tools/bowser
git clone git@github.com:opera-adt/tropo.git  tools/tropo
git clone git@github.com:opera-adt/disp-nisar.git  tools/disp-nisar.git
git clone git@github.com:OPERA-Cal-Val/OPERA_Applications.git tools/OPERA_Applications

# chttps://github.com/scottstanie/opera-utils.git@develop-scott"
git clone https://github.com/isce-framework/sweets.git tools/sweets && cd tools/sweets

# MinSAR ISCE3 split stages need dolphin.workflows._block_split from tools/dolphin.
# Upstream sweets pins scottstanie/dolphin@develop-scott, which can lag that API.
# Prefer isce-framework/dolphin (cloned as tools/dolphin); do not switch to Scott's fork.
if [[ -d "${MINSAR_HOME}/tools/dolphin" ]]; then
    python3 - <<'PY'
from pathlib import Path
import re

path = Path("pyproject.toml")
text = path.read_text()
replacement = 'dolphin = { path = "../dolphin", editable = false }'
text2, n = re.subn(
    r'^dolphin = \{ git = "https://github.com/scottstanie/dolphin\.git".*$',
    replacement,
    text,
    count=1,
    flags=re.M,
)
if n == 0:
    text2, n = re.subn(
        r'^dolphin = \{ path = "\.\./dolphin".*$',
        replacement,
        text,
        count=1,
        flags=re.M,
    )
if n == 0:
    raise SystemExit("Error: could not pin sweets dolphin to ../dolphin in pyproject.toml")
path.write_text(text2)
print("Pinned sweets dolphin to ../dolphin (non-editable)")
PY
fi

# isce-framework YamlModel KeyErrors on sweets Workflow unions ($ref / oneOf).
# Apply the scottstanie/develop-scott comment-schema fix before installing into sweets.
if [[ -f "${MINSAR_HOME}/tools/dolphin/src/dolphin/workflows/config/_yaml_model.py" ]]; then
    python3 - <<'PY'
import os
from pathlib import Path

path = Path(os.environ["MINSAR_HOME"]) / "tools/dolphin/src/dolphin/workflows/config/_yaml_model.py"
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

if pixi install; then
    pixi upgrade asf_search || true
else
    echo "Warning: pixi install failed (lock/solve); continuing with pip dolphin fallback" >&2
fi
# Ensure dolphin with _block_split is in the env even if pixi lock/solve fails under HPC limits.
if [[ -d "${MINSAR_HOME}/tools/dolphin" && -x .pixi/envs/default/bin/python ]]; then
    .pixi/envs/default/bin/python -m pip install "${MINSAR_HOME}/tools/dolphin" --no-deps --force-reinstall
fi
###pixi shell

echo "sweets installation DONE"

if [[ -f "${MINSAR_HOME}/minsar/scripts/stage_sweets_pixi_env.bash" ]]; then
    "${MINSAR_HOME}/minsar/scripts/stage_sweets_pixi_env.bash" --force
fi
