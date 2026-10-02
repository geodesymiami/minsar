#!/usr/bin/env python3
"""
Compare MinSAR MintPy pin files (*_orig.py under additions/mintpy/) to vanilla MintPy at
tools/MintPy git HEAD. Used by setup/install_additions.bash and minsar/utils/update_symlinks.py.

Exit 0 when every pin matches upstream at HEAD, or when --ignore-mintpy-drift is set (drift
prints a warning but still exits 0). Exit 1 on drift, missing pin, or unreadable MintPy repo.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# (pin file under MINSAR_HOME, path inside MintPy repo at HEAD)
MINTPY_OVERLAY_PINS: list[tuple[str, str]] = [
    ("additions/mintpy/view_orig.py", "src/mintpy/view.py"),
    ("additions/mintpy/cli/view_orig.py", "src/mintpy/cli/view.py"),
    ("additions/mintpy/cli/geocode_orig.py", "src/mintpy/cli/geocode.py"),
    ("additions/mintpy/save_qgis_orig.py", "src/mintpy/save_qgis.py"),
    ("additions/mintpy/cli/save_qgis_orig.py", "src/mintpy/cli/save_qgis.py"),
    ("additions/mintpy/save_explorer_orig.py", "src/mintpy/save_explorer.py"),
    ("additions/mintpy/cli/save_explorer_orig.py", "src/mintpy/cli/save_explorer.py"),
    ("additions/mintpy/save_hdfeos5_orig.py", "src/mintpy/save_hdfeos5.py"),
    ("additions/mintpy/cli/save_hdfeos5_orig.py", "src/mintpy/cli/save_hdfeos5.py"),
    ("additions/mintpy/plot_network_orig.py", "src/mintpy/plot_network.py"),
]


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def mintpy_head_rev(mintpy_repo: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(mintpy_repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def mintpy_file_at_head(mintpy_repo: Path, relpath: str) -> bytes | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(mintpy_repo), "show", f"HEAD:{relpath}"],
            check=True,
            capture_output=True,
        )
        return out.stdout
    except (OSError, subprocess.CalledProcessError):
        return None


def check_mintpy_overlay_drift(
    minsar_home: Path,
    *,
    ignore_drift: bool = False,
) -> int:
    """
    Return 0 if OK (or ignored drift), 1 on failure.
    Prints messages to stderr/stdout.
    """
    mintpy_repo = minsar_home / "tools" / "MintPy"
    if not (mintpy_repo / ".git").is_dir() and not (mintpy_repo / ".git").is_file():
        print(
            "WARN: tools/MintPy is not a git checkout; skipping MintPy overlay drift check.",
            file=sys.stderr,
        )
        return 0

    head = mintpy_head_rev(mintpy_repo)
    if not head:
        print("WARN: cannot read MintPy HEAD; skipping MintPy overlay drift check.", file=sys.stderr)
        return 0

    missing: list[str] = []
    drifted: list[tuple[str, str]] = []

    for pin_rel, upstream_rel in MINTPY_OVERLAY_PINS:
        pin_path = minsar_home / pin_rel
        if not pin_path.is_file():
            missing.append(pin_rel)
            continue
        upstream = mintpy_file_at_head(mintpy_repo, upstream_rel)
        if upstream is None:
            print(
                f"ERROR: MintPy HEAD has no file {upstream_rel!r} (tools/MintPy at {head[:12]}).",
                file=sys.stderr,
            )
            return 1
        pin_bytes = pin_path.read_bytes()
        if pin_bytes != upstream:
            drifted.append((pin_rel, upstream_rel))

    if missing:
        print("ERROR: MintPy overlay pin file(s) missing:", file=sys.stderr)
        for m in missing:
            print(f"  {m}", file=sys.stderr)
        print(
            "Create each *_orig.py from vanilla MintPy at the commit you support, then commit.",
            file=sys.stderr,
        )
        return 1

    if not drifted:
        return 0

    print(f"MintPy overlay drift: tools/MintPy HEAD is {head[:12]}", file=sys.stderr)
    print("Pin file(s) differ from upstream (merge MinSAR patches, then update *_orig.py):", file=sys.stderr)
    for pin_rel, upstream_rel in drifted:
        print(f"  {pin_rel}  !=  HEAD:{upstream_rel}", file=sys.stderr)
    print(
        "To install additions symlinks anyway: re-run with --ignore-mintpy-drift",
        file=sys.stderr,
    )

    if ignore_drift:
        print("WARNING: --ignore-mintpy-drift set; continuing despite drift.", file=sys.stderr)
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check additions/mintpy/*_orig.py against tools/MintPy git HEAD.",
    )
    parser.add_argument(
        "--ignore-mintpy-drift",
        action="store_true",
        help="Warn on drift but exit 0 (install MinSAR MintPy symlinks anyway).",
    )
    parser.add_argument(
        "--minsar-home",
        type=Path,
        default=None,
        help="Repository root (default: parent of minsar/ package).",
    )
    args = parser.parse_args(argv)
    home = (args.minsar_home or repo_root_from_script()).resolve()
    return check_mintpy_overlay_drift(home, ignore_drift=args.ignore_mintpy_drift)


if __name__ == "__main__":
    sys.exit(main())
