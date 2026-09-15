#!/usr/bin/env python3
"""Testing helpers for ISCE3 project data/ layout."""

from __future__ import annotations

from pathlib import Path

# Reusable inputs from download_cslc / stitch_sweets_geometry.
_PROJECT_ROOT_LINKS = (
    "data",
    "geometry",
    "watermask.tif",
    "sweets_config.yaml",
)

# Static Dolphin layers for he5 (do not link the full dolphin/ work tree).
_DOLPHIN_SUBDIR_LINKS = ("geometry",)


def _resolve_link_source(root: Path, source: str) -> Path:
    """Resolve --link-project-dir to an existing project directory."""
    src = Path(source).expanduser()
    if not src.is_absolute():
        src = (root / src).resolve()
    if not src.is_dir():
        raise ValueError(f"--link-project-dir source not found or not a directory: {src}")
    if src.name == "data":
        return src.parent
    return src


def _replace_with_symlink(dest: Path, source: Path) -> None:
    """Replace ``dest`` with a symlink to ``source`` when source exists."""
    if not source.exists() and not source.is_symlink():
        return
    if dest.exists() or dest.is_symlink():
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        else:
            raise ValueError(f"refusing --link-project-dir: {dest} exists and is not a symlink")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.symlink_to(source.resolve(), target_is_directory=source.is_dir())


def link_project_dir(
    work_dir: Path,
    source: str,
    dolphin_dir: str = "dolphin",
) -> list[Path]:
    """Symlink reusable inputs from an existing ISCE3 project into ``work_dir``.

    Testing helper (--link-project-dir). Links ``data/``, root ``geometry/``,
    ``watermask.tif``, ``sweets_config.yaml``, and ``{dolphin_dir}/geometry/`` when
    present in the source project. Refuses when a destination path exists as a real
    directory or file (non-symlink).
    """
    root = Path(work_dir).resolve()
    src_project = _resolve_link_source(root, source)
    linked: list[Path] = []

    for name in _PROJECT_ROOT_LINKS:
        src = src_project / name
        if src.exists() or src.is_symlink():
            dest = root / name
            _replace_with_symlink(dest, src)
            linked.append(dest)

    for sub in _DOLPHIN_SUBDIR_LINKS:
        src = src_project / dolphin_dir / sub
        if src.exists() or src.is_symlink():
            dest = root / dolphin_dir / sub
            _replace_with_symlink(dest, src)
            linked.append(dest)

    if not linked:
        raise ValueError(
            f"--link-project-dir: no linkable paths found under {src_project} "
            f"(expected data/, geometry/, watermask.tif, or {dolphin_dir}/geometry/)"
        )
    return linked
