"""Run MinSAR helpers that need opera_utils under the sweets pixi env.

The minsar conda env typically lacks opera_utils; sweets pixi has it. Login-node
tools (generate_sweets_config, generate_disp-s1_commands) call the sweets env
python when import fails so create_isce3_runfiles can stay on minsar.

Prefer the installed env binaries under tools/sweets/.pixi (or $SWEETS_ENV)
instead of ``pixi run``, which is slow on HPC (rattler/repodata checks).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# Set in the sweets child so helpers never recurse if opera_utils is still missing.
_SWEETS_PIXI_NEST = "MINSAR_SWEETS_PIXI_NEST"

# Bash: sweets bin + GDAL/PROJ so inherited minsar conda plugins are not used.
SWEETS_PATH_EXPORT = """_s="${SWEETS_ENV:-$MINSAR_HOME/tools/sweets/.pixi/envs/default}"
export PATH="$_s/bin:$PATH"
export GDAL_DRIVER_PATH="$_s/lib/gdalplugins"
export GDAL_DATA="$_s/share/gdal"
export PROJ_LIB="$_s/share/proj"
export PROJ_DATA="$_s/share/proj\""""


def opera_utils_importable() -> bool:
    """True when opera_utils is importable in this interpreter."""
    try:
        import opera_utils  # noqa: F401

        return True
    except ImportError:
        return False


def sweets_env_prefix() -> Path:
    """Return sweets pixi env prefix ($SWEETS_ENV or $MINSAR_HOME/tools/sweets/.pixi/...)."""
    sweets_env = os.environ.get("SWEETS_ENV")
    if sweets_env:
        return Path(sweets_env).expanduser()
    minsar_home = os.environ.get("MINSAR_HOME")
    if not minsar_home:
        raise ModuleNotFoundError(
            "MINSAR_HOME is unset; source setup/environment.bash or set SWEETS_ENV"
        )
    return Path(minsar_home) / "tools" / "sweets" / ".pixi" / "envs" / "default"


def sweets_env_bin_dir() -> Path:
    """Return ``bin`` under the sweets pixi env prefix."""
    return sweets_env_prefix() / "bin"


def sweets_env_python() -> Path:
    """Return sweets env python; raise if the env looks incomplete."""
    bin_dir = sweets_env_bin_dir()
    for name in ("python", "python3"):
        candidate = bin_dir / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise FileNotFoundError(
        f"SWEETS pixi python not found under {bin_dir}; "
        "re-run setup/install_sweets_env.bash"
    )


def sweets_env_environ(base: dict[str, str] | None = None) -> dict[str, str]:
    """Copy env with sweets bin prepended and MINSAR_HOME / PYTHONPATH set."""
    env = dict(base if base is not None else os.environ)
    minsar_home = env.get("MINSAR_HOME") or os.environ.get("MINSAR_HOME")
    if not minsar_home:
        raise ModuleNotFoundError(
            "MINSAR_HOME is unset; source setup/environment.bash or set SWEETS_ENV"
        )
    env["MINSAR_HOME"] = minsar_home
    bin_dir = str(sweets_env_bin_dir())
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = minsar_home if not existing else f"{minsar_home}{os.pathsep}{existing}"
    prefix = sweets_env_prefix()
    proj = prefix / "share" / "proj"
    gdal = prefix / "share" / "gdal"
    if proj.is_dir():
        env["PROJ_LIB"] = str(proj)
        env["PROJ_DATA"] = str(proj)
    if gdal.is_dir():
        env["GDAL_DATA"] = str(gdal)
    plugins = prefix / "lib" / "gdalplugins"
    if plugins.is_dir():
        env["GDAL_DRIVER_PATH"] = str(plugins)
    return env


def invoke_via_sweets_pixi(
    *,
    func_name: str,
    kwargs: dict[str, Any],
    module: str | None = None,
    script_relpath: str | None = None,
) -> Any:
    """Run ``module.func_name(**kwargs)`` (or a hyphenated script via runpy) under sweets python.

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
            "re-run setup/install_sweets_env.bash so tools/opera-utils is installed"
        )
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
    env = sweets_env_environ()
    env[_SWEETS_PIXI_NEST] = "1"
    python = sweets_env_python()
    cmd = [str(python), "-c", code]
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
