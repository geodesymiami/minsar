#!/usr/bin/env python3
"""
Recreate MinSAR overlay symlinks listed in setup/install_minsar.bash (additions → tools / env).

Interprets the same lines the installer would run:

- **Skipped (not executed in bash):** blank lines and **full-line** comments (first non-whitespace
  character is ``#``), e.g. ``#ln -sf ...`` or ``# patches...``.
- **Trailing comments** on a command line (``ln ... # note``) are ignored, like bash.
- **Linux-only ISCE/miniforge symlinks:** in ``install_minsar.bash`` these are the ``ln -sf``
  lines whose destination path contains ``tools/miniforge3/envs/minsar``. That matches the block
  under ``if [[ "$(uname)" == "Linux" ]]; then`` (without relying on fragile nested ``if``/``fi``
  parsing). On non-Linux hosts those lines are skipped unless ``--force-linux-isce`` is set.

When a symlink already exists and points at the correct additions file, the script does nothing
and prints nothing for that entry (including in ``--dry-run``). Output is only for creates,
replacements, skips (missing parent dir), warnings, or errors.

``--dry-run`` ends with a block: ``cd <MINSAR_HOME>``, then ``Will run:`` and one ``ln -s <rel> <rel>``
line per needed symlink (paths relative to MINSAR_HOME; the installer uses ``ln -sf``).

Usage (from repository root):
    python3 minsar/utils/update_symlinks.py
    python3 minsar/utils/update_symlinks.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import sys
from pathlib import Path

# ln -sf $MINSAR_HOME/<src> $MINSAR_HOME/<dst>   optional trailing # comment on same line
_LN_SF = re.compile(
    r"^\s*ln\s+-sf\s+(\$MINSAR_HOME/\S+)\s+(\$MINSAR_HOME/\S+)\s*(?:#.*)?$"
)

# Destinations under this path appear only in the Linux-guarded ISCE section of install_minsar.bash
_LINUX_ONLY_DST_MARK = "miniforge3/envs/minsar"


def repo_root_from_script() -> Path:
    """minsar/utils/update_symlinks.py → repository root (MINSAR_HOME)."""
    return Path(__file__).resolve().parent.parent.parent


def posix_rel_to_minsar_home(path: Path, minsar_home: Path) -> str:
    """Path relative to MINSAR_HOME for display (forward slashes)."""
    resolved = path.resolve()
    home = minsar_home.resolve()
    try:
        return resolved.relative_to(home).as_posix()
    except ValueError:
        return resolved.as_posix()


def substitute_minsar_home(token: str, minsar_home: Path) -> Path:
    if not token.startswith("$MINSAR_HOME/"):
        raise ValueError(f"Expected path under $MINSAR_HOME, got: {token!r}")
    rel = token[len("$MINSAR_HOME/") :]
    return minsar_home / rel


def _executable_ln_line(physical_line: str) -> str:
    """Drop trailing bash comment from a line; install script paths contain no ``#``."""
    return physical_line.split("#", 1)[0].strip()


def _is_linux_only_install_line(dst_token: str) -> bool:
    """True if this ln matches the ISCE→miniforge block (run only on Linux in the installer)."""
    return _LINUX_ONLY_DST_MARK in dst_token.replace("\\", "/")


def parse_executable_ln_sf_lines(
    install_bash: Path, *, on_linux: bool | None = None
) -> list[tuple[str, str]]:
    """
    Return (src_token, dst_token) for each ``ln -sf`` that would run in install_minsar.bash.

    Omits lines that bash would not execute (full-line comments). Omits Linux-only miniforge
    ISCE symlinks when ``on_linux`` is False.
    """
    if on_linux is None:
        on_linux = platform.system() == "Linux"

    pairs: list[tuple[str, str]] = []
    text = install_bash.read_text(encoding="utf-8", errors="replace")

    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        line = _executable_ln_line(raw)
        if not line:
            continue
        m = _LN_SF.match(line)
        if not m:
            continue
        src_t, dst_t = m.group(1), m.group(2)
        if "/additions/" not in src_t.replace("\\", "/"):
            continue
        if _is_linux_only_install_line(dst_t) and not on_linux:
            continue
        pairs.append((src_t, dst_t))

    return pairs


def resolve_link_paths(
    src_t: str, dst_t: str, minsar_home: Path
) -> tuple[Path, Path]:
    """
    Return (absolute source path, absolute symlink path).

    If dst exists and is a directory, symlink is dst / src.name (GNU ln behavior).
    """
    src = substitute_minsar_home(src_t, minsar_home)
    dst = substitute_minsar_home(dst_t, minsar_home)
    if dst.exists() and dst.is_dir():
        link_path = dst / src.name
    else:
        link_path = dst
    return src.resolve(), link_path


def symlink_already_correct(link_path: Path, src: Path) -> bool:
    """True if link_path is a symlink whose target resolves to the same path as src."""
    if not link_path.is_symlink():
        return False
    try:
        return link_path.resolve() == src.resolve()
    except OSError:
        return False


def ensure_symlink(src: Path, link_path: Path, dry_run: bool) -> str:
    """
    Create or replace symlink link_path -> src (absolute targets, like install_minsar.bash).

    Returns:
        noop — already correct symlink (caller prints nothing)
        skipped_no_parent — target parent directory missing
        would_create / would_replace — dry-run only
        created / replaced — symlink written
    """
    if symlink_already_correct(link_path, src):
        return "noop"

    if not link_path.parent.is_dir():
        return "skipped_no_parent"

    had_existing = link_path.exists() or link_path.is_symlink()

    if had_existing:
        if dry_run:
            return "would_replace"
        link_path.unlink(missing_ok=True)
    elif dry_run:
        return "would_create"

    link_path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(str(src), str(link_path), target_is_directory=False)
    return "replaced" if had_existing else "created"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create symlinks from setup/install_minsar.bash (additions overlays). "
            "Only prints lines when a symlink must be created or updated, or for warnings/errors."
        )
    )
    parser.add_argument(
        "--install-bash",
        type=Path,
        default=None,
        help="Path to install_minsar.bash (default: <MINSAR_HOME>/setup/install_minsar.bash)",
    )
    parser.add_argument(
        "--minsar-home",
        type=Path,
        default=None,
        help="Repository root MINSAR_HOME (default: inferred from this file location)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print only symlinks that would be created or replaced (no changes on disk)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with error if any source under additions/ is missing",
    )
    parser.add_argument(
        "--force-linux-isce",
        action="store_true",
        help=(
            "Apply Linux-only ISCE→miniforge symlinks even when not on Linux "
            "(default: same as install_minsar.bash uname check)"
        ),
    )
    args = parser.parse_args(argv)

    minsar_home = (args.minsar_home or repo_root_from_script()).resolve()
    install_bash = args.install_bash or (minsar_home / "setup" / "install_minsar.bash")

    if not install_bash.is_file():
        print(f"Error: install script not found: {install_bash}", file=sys.stderr)
        return 1

    if args.force_linux_isce:
        pairs = parse_executable_ln_sf_lines(install_bash, on_linux=True)
    else:
        pairs = parse_executable_ln_sf_lines(install_bash)

    if not pairs:
        print(f"No executable ln -sf ... additions/ ... lines parsed from {install_bash}", file=sys.stderr)
        return 1

    errors = 0
    dry_run_commands: list[tuple[str, str]] = []

    for src_t, dst_t in pairs:
        try:
            src, link_path = resolve_link_paths(src_t, dst_t, minsar_home)
        except ValueError as e:
            print(f"SKIP parse: {e}", file=sys.stderr)
            errors += 1
            continue

        if not src.is_file():
            msg = f"WARN source missing: {src}"
            if args.strict:
                print(f"Error: {msg}", file=sys.stderr)
                errors += 1
            else:
                print(msg, file=sys.stderr)

        status = ensure_symlink(src, link_path, args.dry_run)

        if status == "noop":
            continue
        if status == "skipped_no_parent":
            print(f"SKIP (parent dir missing): {link_path.parent}", file=sys.stderr)
            continue
        if args.dry_run:
            if status in ("would_create", "would_replace"):
                dry_run_commands.append(
                    (
                        posix_rel_to_minsar_home(src, minsar_home),
                        posix_rel_to_minsar_home(link_path, minsar_home),
                    )
                )
            continue
        print(f"{status}: {link_path} -> {src}")

    if args.dry_run and dry_run_commands:
        print(f"cd {minsar_home.as_posix()}")
        print("Will run:")
        for src_rel, dst_rel in dry_run_commands:
            print(f"ln -s {src_rel} {dst_rel}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
