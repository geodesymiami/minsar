"""Run MinSAR helpers that need opera_utils under the sweets pixi env.

The minsar conda env typically lacks opera_utils; sweets pixi has it. Login-node
tools (generate_sweets_config, generate_disp-s1_commands) call into pixi when
import fails so create_isce3_runfiles can stay on minsar.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# Set in the pixi child so helpers never recurse if opera_utils is still missing.
_SWEETS_PIXI_NEST = "MINSAR_SWEETS_PIXI_NEST"


def opera_utils_importable() -> bool:
    """True when opera_utils is importable in this interpreter."""
    try:
        import opera_utils  # noqa: F401

        return True
    except ImportError:
        return False


def invoke_via_sweets_pixi(
    *,
    func_name: str,
    kwargs: dict[str, Any],
    module: str | None = None,
    script_relpath: str | None = None,
) -> Any:
    """Run ``module.func_name(**kwargs)`` (or a hyphenated script via runpy) under sweets pixi.

    Pass exactly one of ``module`` (importable dotted name) or ``script_relpath``
    (path under ``$MINSAR_HOME``, e.g. ``minsar/utils/generate_disp-s1_commands.py``).
    """
    if (module is None) == (script_relpath is None):
        raise ValueError("pass exactly one of module= or script_relpath=")
    minsar_home = os.environ.get("MINSAR_HOME")
    if not minsar_home:
        raise ModuleNotFoundError(
            "No module named 'opera_utils' and MINSAR_HOME is unset; "
            "source setup/environment.bash or run under sweets pixi"
        )
    if os.environ.get(_SWEETS_PIXI_NEST):
        raise ModuleNotFoundError(
            "No module named 'opera_utils' inside sweets pixi; "
            "re-run setup/install_isce3.bash so tools/opera-utils is installed"
        )
    manifest = os.path.join(minsar_home, "tools/sweets/pyproject.toml")
    if not os.path.isfile(manifest):
        raise FileNotFoundError(f"sweets pixi manifest not found: {manifest}")
    if script_relpath is not None:
        code = (
            "import json, os, runpy, sys\n"
            "req = json.load(sys.stdin)\n"
            "path = os.path.join(os.environ['MINSAR_HOME'], req['script'])\n"
            "mod = runpy.run_path(path)\n"
            "out = mod[req['func']](**req['kwargs'])\n"
            "json.dump(out, sys.stdout)\n"
        )
        payload_obj: dict[str, Any] = {
            "func": func_name,
            "kwargs": kwargs,
            "script": script_relpath,
        }
    else:
        code = (
            "import importlib, json, sys\n"
            "req = json.load(sys.stdin)\n"
            "mod = importlib.import_module(req['module'])\n"
            "out = getattr(mod, req['func'])(**req['kwargs'])\n"
            "json.dump(out, sys.stdout)\n"
        )
        payload_obj = {"func": func_name, "kwargs": kwargs, "module": module}
    env = os.environ.copy()
    env["MINSAR_HOME"] = minsar_home
    env[_SWEETS_PIXI_NEST] = "1"
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = minsar_home if not existing else f"{minsar_home}{os.pathsep}{existing}"
    pixi_bin = str(Path.home() / ".pixi" / "bin")
    env["PATH"] = f"{pixi_bin}{os.pathsep}{env.get('PATH', '')}"
    cmd = [
        "pixi",
        "run",
        "--as-is",
        "--manifest-path",
        manifest,
        "--",
        "python",
        "-c",
        code,
    ]
    payload = json.dumps(payload_obj)
    label = script_relpath or module
    print(f"  (opera_utils via sweets pixi: {label}.{func_name})", file=sys.stderr)
    proc = subprocess.run(
        cmd,
        input=payload,
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"sweets pixi {func_name} failed with exit {proc.returncode}")
    text = (proc.stdout or "").strip()
    if not text:
        raise RuntimeError(f"sweets pixi {func_name} returned empty stdout")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("[") or line.startswith("{") or line[:1].isdigit():
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        raise RuntimeError(f"sweets pixi {func_name} stdout was not JSON:\n{text}") from None
