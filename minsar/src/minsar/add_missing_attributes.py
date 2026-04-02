#!/usr/bin/env python3
"""
Add missing orbit_direction (ORBIT_DIRECTION) and relative_orbit attributes to
slcStack.h5 and/or geometryRadar.h5.

Uses MintPy readfile to read attributes; computes ORBIT_DIRECTION from HEADING
and relative_orbit from orbit number and platform when missing.
"""

import os
import re
import sys

from mintpy.utils import readfile, utils as ut


def get_orbit_direction(heading_angle):
    """
    Determine orbit direction from ISCE heading angle.

    Parameters
    ----------
    heading_angle : float
        Satellite heading in degrees (clockwise from north).
        ISCE headings are often negative.

    Returns
    -------
    str
        "ASCENDING" or "DESCENDING"
    """
    heading = heading_angle % 360
    if heading < 90 or heading > 270:
        return "ASCENDING"
    return "DESCENDING"


def get_relative_orbit(orbit_number, platform):
    """
    Return relative orbit number for common SAR platforms.

    Parameters
    ----------
    orbit_number : int
        Absolute orbit number.
    platform : str
        Platform name (case-insensitive; accepts common aliases).

    Returns
    -------
    int
        Relative orbit number (1-based within repeat cycle).

    Raises
    ------
    ValueError
        If platform is not in the known orbit_cycles mapping.
    """
    platform = platform.lower().strip()

    orbit_cycles = {
        "sentinel-1": 175,
        "sentinel1": 175,
        "s1": 175,
        "terrasarx": 167,
        "terrasar-x": 167,
        "tsx": 167,
        "tandemx": 167,
        "tdx": 167,
        "cosmo-skymed": 237,
        "csk": 237,
        "nisar": 173,
    }

    if platform not in orbit_cycles:
        raise ValueError(f"Unknown platform: {platform}")

    n_orbits = orbit_cycles[platform]
    return ((orbit_number - 1) % n_orbits) + 1


def _relative_orbit_from_project_name(project_name):
    """
    Extract relative orbit from PROJECT_NAME for TSX/TDX-style names.

    Examples: MiamiTsxSMA135 -> 135, MiamiTsxSMD36 -> 36, MiamiTsxSMDT36 -> 36.
    Looks for a number at the end preceded by A, AT, D, or DT.
    """
    if not project_name:
        return None
    s = str(project_name).strip()
    # Match A, AT, D, or DT followed by digits at end of string (case-insensitive)
    m = re.search(r"(?:A|AT|D|DT)(\d+)$", s, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            return None
    return None


def _normalize_platform(raw):
    """Return a key suitable for get_relative_orbit (lowercase, no spaces)."""
    if not raw:
        return ""
    s = str(raw).lower().strip().replace(" ", "-").replace("_", "-")
    if s in ("s1", "sen", "sentinel1", "sentinel-1"):
        return "s1"
    if s in ("tsx", "terrasar-x", "terrasarx"):
        return "tsx"
    if s in ("tdx", "tandemx", "tandem-x"):
        return "tdx"
    if s in ("csk", "cosmo-skymed", "cosmoskymed"):
        return "csk"
    return s


def _is_geometry_file(path):
    """Heuristic: file has geometry-style datasets."""
    try:
        ds_list = readfile.get_dataset_list(path)
    except Exception:
        ds_list = []
    return any(d in (ds_list or []) for d in ["height", "latitude", "bperp"])


def process_file(path, dry_run=False, orbit_number_cli=None, platform_cli=None):
    """
    Read H5 attributes; add ORBIT_DIRECTION and/or relative_orbit if missing.

    Returns
    -------
    bool
        True if any attribute was added (or would be in dry-run).
    """
    try:
        atr = readfile.read_attribute(path)
    except Exception as e:
        print(f"{path}: failed to read attributes: {e}", file=sys.stderr)
        return False

    to_add = {}
    is_geometry = _is_geometry_file(path)

    # ORBIT_DIRECTION
    existing_dir = (atr.get("ORBIT_DIRECTION") or "").strip().upper()
    if existing_dir not in ("ASCENDING", "DESCENDING"):
        heading_raw = atr.get("HEADING")
        if heading_raw is not None:
            try:
                heading = float(heading_raw)
                to_add["ORBIT_DIRECTION"] = get_orbit_direction(heading)
            except (TypeError, ValueError) as e:
                print(
                    f"{path}: cannot compute ORBIT_DIRECTION from HEADING={heading_raw!r}: {e}",
                    file=sys.stderr,
                )
        else:
            print(
                f"{path}: cannot compute ORBIT_DIRECTION (no HEADING attribute)",
                file=sys.stderr,
            )

    # relative_orbit
    has_rel = False
    rel_val = atr.get("relative_orbit")
    if rel_val is not None and str(rel_val).strip() != "":
        try:
            int(rel_val)
            has_rel = True
        except (TypeError, ValueError):
            pass
    if not has_rel and is_geometry:
        unavco = atr.get("unavco.relative_orbit")
        if unavco is not None and str(unavco).strip() != "":
            try:
                int(unavco)
                has_rel = True
            except (TypeError, ValueError):
                pass

    if not has_rel:
        orbit_num = None
        platform = None
        if orbit_number_cli is not None and platform_cli:
            orbit_num = int(orbit_number_cli)
            platform = _normalize_platform(platform_cli)
        else:
            for key in ("ORBIT_NUMBER", "orbit_number", "orbitNumber"):
                v = atr.get(key)
                if v is not None:
                    try:
                        orbit_num = int(float(v))
                        break
                    except (TypeError, ValueError):
                        continue
            for key in ("PLATFORM", "mission", "Mission"):
                v = atr.get(key)
                if v:
                    platform = _normalize_platform(v)
                    break
        rel = None
        # For TSX/TDX, prefer relative orbit from PROJECT_NAME (e.g. MiamiTsxSMA135 -> 135)
        if platform in ("tsx", "tdx"):
            proj = atr.get("PROJECT_NAME")
            rel = _relative_orbit_from_project_name(proj)
        if rel is None and orbit_num is not None and platform:
            try:
                rel = get_relative_orbit(orbit_num, platform)
            except ValueError as e:
                print(f"{path}: {e}", file=sys.stderr)
        if rel is not None:
            to_add["relative_orbit"] = rel
            if is_geometry:
                to_add["unavco.relative_orbit"] = str(rel)
        elif orbit_num is None or not platform:
            if not (orbit_number_cli is not None and platform_cli):
                print(
                    f"{path}: cannot compute relative_orbit (missing orbit number/platform; use --orbit-number and --platform)",
                    file=sys.stderr,
                )

    if not to_add:
        return False

    if dry_run:
        print(f"{path}: would add {to_add}")
        return True

    try:
        ut.add_attribute(path, atr_new=to_add)
        print(f"{path}: added {list(to_add.keys())}")
        return True
    except Exception as e:
        print(f"{path}: failed to write attributes: {e}", file=sys.stderr)
        return False


def add_missing_attributes_for_upload(work_dir, data_dirs):
    """
    If miaplpy/inputs is in data_dirs and slcStack.h5 exists there, run
    add_missing_attributes on that slcStack.h5 and geometryRadar.h5.

    Option A: only when the upload includes miaplpy/inputs and the file exists.
    """
    normalized = [d.rstrip("/") for d in data_dirs]
    if "miaplpy/inputs" not in normalized:
        return
    inputs_dir = os.path.join(work_dir, "miaplpy", "inputs")
    slc_path = os.path.join(inputs_dir, "slcStack.h5")
    if not os.path.isfile(slc_path):
        return
    geom_path = os.path.join(inputs_dir, "geometryRadar.h5")
    paths = [slc_path]
    if os.path.isfile(geom_path):
        paths.append(geom_path)
    for p in paths:
        process_file(p, dry_run=False)
