#!/usr/bin/env python3
"""EGMS L2a CSV/XML metadata helpers for Insarmaps ingest."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional


EGMS_FILENAME_RE = re.compile(
    r"EGMS_L2a_(?P<track>\d+)_(?P<burst>\d+)_IW(?P<subswath>\d)_",
    re.IGNORECASE,
)
# S1* product id: ..._YYYYMMDDTHHMMSS_...
S1_SENSING_RE = re.compile(r"_(\d{8})T(\d{6})_")


def parse_egms_filename(path: str | Path) -> dict[str, Any]:
    """Parse EGMS_L2a_<track>_<burst>_IW<swath>_... stem fields."""
    stem = Path(path).stem
    m = EGMS_FILENAME_RE.search(stem)
    if not m:
        return {}
    return {
        "relative_orbit": int(m.group("track")),
        "egms_burst_id": m.group("burst"),
        "beam_swath": int(m.group("subswath")),
        "beam_mode": "IW",
    }


def center_line_utc_from_hhmmss(hhmmss: str) -> int:
    """Convert HHMMSS string to seconds of day."""
    hh = int(hhmmss[0:2])
    mm = int(hhmmss[2:4])
    ss = int(hhmmss[4:6])
    return hh * 3600 + mm * 60 + ss


def center_line_utc_from_product_id(product_id: str) -> Optional[int]:
    """Extract sensing start time from a Sentinel-1 SLC product_id."""
    m = S1_SENSING_RE.search(product_id)
    if not m:
        return None
    return center_line_utc_from_hhmmss(m.group(2))


def flight_direction_from_track_angle(track_angle: float) -> str:
    """
    Map mean track angle (deg) to Insarmaps short flight_direction A|D.

    Ascending tracks are typically near north (~0° or ~350°); descending near south (~180°).
    """
    ang = float(track_angle) % 360.0
    if ang >= 270.0 or ang < 90.0:
        return "A"
    return "D"


def parse_egms_xml(xml_path: str | Path) -> dict[str, Any]:
    """
    Parse companion EGMS L2a XML (<BURST>).

    Returns keys among: relative_orbit, egms_burst_id, beam_swath, beam_mode,
    CENTER_LINE_UTC, product_level (when present).
    """
    xml_path = Path(xml_path)
    tree = ET.parse(xml_path)
    root = tree.getroot()

    out: dict[str, Any] = {}

    track = root.findtext("track")
    if track is not None and str(track).strip().isdigit():
        out["relative_orbit"] = int(str(track).strip())

    burst = root.findtext("burst_id")
    if burst is not None and str(burst).strip():
        out["egms_burst_id"] = str(burst).strip()

    sub = root.findtext("sub_swath")
    if sub is not None and str(sub).strip().isdigit():
        out["beam_swath"] = int(str(sub).strip())
        out["beam_mode"] = "IW"

    level = root.findtext("product_level")
    if level is not None and str(level).strip():
        out["product_level"] = str(level).strip()

    # Prefer a dataset product_id sensing time (skip reference block if possible)
    product_ids = []
    dataset = root.find("dataset")
    if dataset is not None:
        product_ids = [el.text for el in dataset.findall(".//product_id") if el.text]
    if not product_ids:
        product_ids = [el.text for el in root.findall(".//product_id") if el.text]

    for pid in product_ids:
        clu = center_line_utc_from_product_id(pid)
        if clu is not None:
            out["CENTER_LINE_UTC"] = clu
            break

    return out


def build_egms_attributes(
    csv_path: str | Path,
    xml_path: Optional[str | Path] = None,
    *,
    flight_direction: Optional[str] = None,
    relative_orbit: Optional[int] = None,
    center_line_utc: Optional[int] = None,
    project_name: Optional[str] = None,
    post_processing_method: str = "EGMS",
    track_angle: Optional[float] = None,
) -> dict[str, Any]:
    """
    Merge filename, XML, and CLI overrides into Insarmaps attribute dict.

    Precedence (highest last): filename < XML < track_angle inference < CLI overrides.
    """
    csv_path = Path(csv_path)
    attrs: dict[str, Any] = {
        "mission": "S1",
        "PLATFORM": "S1",
        "beam_mode": "IW",
        "look_direction": "R",
        "wavelength": 0.05546576,
        "post_processing_method": post_processing_method,
        "processing_software": "EGMS",
        "collection": "egms",
    }

    attrs.update(parse_egms_filename(csv_path))

    if xml_path is None:
        candidate = csv_path.with_suffix(".xml")
        if candidate.is_file():
            xml_path = candidate
    if xml_path is not None and Path(xml_path).is_file():
        attrs.update(parse_egms_xml(xml_path))

    if track_angle is not None and "flight_direction" not in attrs:
        attrs["flight_direction"] = flight_direction_from_track_angle(track_angle)

    if flight_direction is not None:
        fd = str(flight_direction).strip().upper()
        if fd in ("A", "ASCENDING"):
            attrs["flight_direction"] = "A"
            attrs["ORBIT_DIRECTION"] = "A"
        elif fd in ("D", "DESCENDING"):
            attrs["flight_direction"] = "D"
            attrs["ORBIT_DIRECTION"] = "D"
        else:
            raise ValueError(f"Invalid flight_direction: {flight_direction} (use A|D)")
    elif "flight_direction" in attrs:
        attrs["ORBIT_DIRECTION"] = attrs["flight_direction"]

    if relative_orbit is not None:
        attrs["relative_orbit"] = int(relative_orbit)
    if center_line_utc is not None:
        attrs["CENTER_LINE_UTC"] = int(center_line_utc)

    attrs["PROJECT_NAME"] = project_name or csv_path.stem
    attrs["post_processing_method"] = post_processing_method

    return attrs
