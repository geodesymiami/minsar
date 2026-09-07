#!/usr/bin/env python3
"""Launch OPERA DISP-S1 local produce (tools/disp-s1/scripts/disp_s1_process.py).

Examples:
  disp_s1_process.py --cslc-dir data --work-dir disp_s1_produce --frame-id 23211 --extent "-154.91,19.459 : -154.887,19.486"
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def _minsar_home() -> Path:
    raw = os.environ.get("MINSAR_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def _ensure_disp_s1_importable(src: Path) -> None:
    """Allow importing disp_s1 from tools/disp-s1/src without a pip install."""
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    version_mod = "disp_s1._version"
    if version_mod not in sys.modules:
        import types

        stub = types.ModuleType(version_mod)
        stub.version = "0.0.0+minsar"
        sys.modules[version_mod] = stub


def main() -> int:
    home = _minsar_home()
    script = home / "tools/disp-s1/scripts/disp_s1_process.py"
    src = home / "tools/disp-s1/src"
    if not script.is_file():
        raise FileNotFoundError(f"disp_s1_process script not found: {script}")
    _ensure_disp_s1_importable(src)
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
