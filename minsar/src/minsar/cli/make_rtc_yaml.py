#!/usr/bin/env python3
# filepath: make_rtc_yaml.py
import os
import re
import sys
import glob
import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple


EXAMPLE = """example:
  make_rtc_yaml.py \
    --safe-dir /scratch/09580/gdisilvestro/ChilesOperaD/SLC \
    --orbit-dir /scratch/09580/gdisilvestro/ChilesOperaD/Orbits \
    --dem-dir /scratch/09580/gdisilvestro/ChilesOperaD/DEM \
    --product-path /scratch/09580/gdisilvestro/Chile \
    --output rtc_s1.yaml
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build RTC-S1 YAML from SAFE/orbit/DEM folders.",
        epilog=EXAMPLE,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--safe-dir", required=True, help="Directory with *.SAFE")
    parser.add_argument("--orbit-dir", required=True, help="Directory with *.EOF")
    parser.add_argument("--dem-dir", help="Directory containing DEM (*.dem)")
    parser.add_argument("--dem-file", help="Explicit DEM file path (overrides --dem-dir)")
    parser.add_argument("--output", default="rtc_s1.yaml", help="Output YAML file")
    parser.add_argument("--product-path", required=True, help="RTC output product_path")
    parser.add_argument("--product-version", default="1.0", help="Product version string")
    parser.add_argument("--processing-type", default="NOMINAL", help="Processing type")
    parser.add_argument("--burst-database-file", default="", help="Optional burst DB sqlite")
    parser.add_argument("--source-data-access", default="", help="Optional source_data_access")
    parser.add_argument("--safe-glob", default="*.SAFE", help="Glob for SAFE names")
    parser.add_argument("--orbit-glob", default="*.EOF", help="Glob for orbit files")
    parser.add_argument("--recursive", action="store_true", help="Recursive folder scan")
    return parser


def parse_safe_time_and_platform(safe_name: str) -> Tuple[str, datetime]:
    # Example: S1A_IW_SLC__1SDV_20150517T232854_20150517T232924_...
    plat_match = re.match(r"^(S1[AB])_", safe_name)
    time_match = re.search(r"_(\d{8}T\d{6})_(\d{8}T\d{6})_", safe_name)
    if not plat_match or not time_match:
        raise ValueError(f"Cannot parse SAFE name: {safe_name}")
    platform = plat_match.group(1)
    t0 = datetime.strptime(time_match.group(1), "%Y%m%dT%H%M%S")
    return platform, t0


def parse_orbit_metadata(eof_name: str) -> Optional[Dict]:
    # Example: S1A_OPER_AUX_POEORB_OPOD_20141001T122918_V20140909T225944_20140911T005944.EOF
    m = re.match(
        r"^(S1[AB])_OPER_AUX_POEORB_OPOD_(\d{8}T\d{6})_V(\d{8}T\d{6})_(\d{8}T\d{6})\.EOF$",
        eof_name,
    )
    if not m:
        return None
    return {
        "platform": m.group(1),
        "created": datetime.strptime(m.group(2), "%Y%m%dT%H%M%S"),
        "valid_start": datetime.strptime(m.group(3), "%Y%m%dT%H%M%S"),
        "valid_stop": datetime.strptime(m.group(4), "%Y%m%dT%H%M%S"),
    }


def find_files(folder: str, pattern: str, recursive: bool) -> List[str]:
    folder = os.path.abspath(folder)
    if recursive:
        return sorted(glob.glob(os.path.join(folder, "**", pattern), recursive=True))
    return sorted(glob.glob(os.path.join(folder, pattern)))


def choose_dem_file(dem_file: Optional[str], dem_dir: Optional[str]) -> str:
    if dem_file:
        dem_path = os.path.abspath(dem_file)
        if not os.path.isfile(dem_path):
            raise FileNotFoundError(f"DEM file not found: {dem_path}")
        return dem_path

    if not dem_dir:
        raise ValueError("Provide --dem-file or --dem-dir")

    candidates = sorted(glob.glob(os.path.join(os.path.abspath(dem_dir), "**", "*.dem"), recursive=True))
    if not candidates:
        raise FileNotFoundError(f"No .dem found in {dem_dir}")
    return candidates[0]


def build_orbit_index(orbit_files: List[str]) -> List[Dict]:
    idx = []
    for fp in orbit_files:
        meta = parse_orbit_metadata(os.path.basename(fp))
        if meta is None:
            continue
        meta["path"] = os.path.abspath(fp)
        idx.append(meta)
    if not idx:
        raise RuntimeError("No parseable EOF files found.")
    return idx


def match_orbit_for_safe(safe_fp: str, orbit_index: List[Dict]) -> str:
    safe_name = os.path.basename(safe_fp)
    platform, safe_t0 = parse_safe_time_and_platform(safe_name)

    candidates = [
        o for o in orbit_index
        if o["platform"] == platform and o["valid_start"] <= safe_t0 <= o["valid_stop"]
    ]
    if not candidates:
        raise RuntimeError(f"No matching orbit for SAFE: {safe_name}")

    # Prefer smallest validity window, then latest creation
    candidates.sort(
        key=lambda o: ((o["valid_stop"] - o["valid_start"]).total_seconds(), -o["created"].timestamp())
    )
    return candidates[0]["path"]


def write_yaml(
    output_file: str,
    safe_files: List[str],
    orbit_files: List[str],
    dem_file: str,
    product_path: str,
    product_version: str,
    processing_type: str,
    burst_database_file: str,
    source_data_access: str,
):
    lines = []
    lines.append("runconfig:")
    lines.append("  name: rtc_s1_workflow_default")
    lines.append("")
    lines.append("  groups:")
    lines.append("    primary_executable:")
    lines.append("      product_type: RTC_S1")
    lines.append("")
    lines.append("    pge_name_group:")
    lines.append("      pge_name: RTC_S1_PGE")
    lines.append("")
    lines.append("    input_file_group:")
    lines.append("      safe_file_path:")
    for s in safe_files:
        lines.append(f"        - {s}")
    lines.append("")
    lines.append(f"      source_data_access: {source_data_access}")
    lines.append("")
    lines.append("      orbit_file_path:")
    for o in orbit_files:
        lines.append(f"        - {o}")
    lines.append("")
    lines.append("      burst_id:")
    lines.append("")
    lines.append("    dynamic_ancillary_file_group:")
    lines.append(f"      dem_file: {dem_file}")
    lines.append("      dem_file_description: envi")
    lines.append("")
    lines.append("    static_ancillary_file_group:")
    lines.append(f"      burst_database_file: {burst_database_file}")
    lines.append("")
    lines.append("    product_group:")
    lines.append(f"      processing_type: {processing_type}")
    lines.append(f"      product_version: \"{product_version}\"")
    lines.append(f"      product_path: {os.path.abspath(product_path)}")
    lines.append("")

    Path(output_file).write_text("\n".join(lines), encoding="utf-8")


def main(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(args=iargs)

    safe_files = find_files(inps.safe_dir, inps.safe_glob, inps.recursive)
    if not safe_files:
        raise RuntimeError(f"No SAFE files found in: {inps.safe_dir}")

    orbit_files_all = find_files(inps.orbit_dir, inps.orbit_glob, inps.recursive)
    orbit_index = build_orbit_index(orbit_files_all)

    dem_file = choose_dem_file(inps.dem_file, inps.dem_dir)

    matched_orbits = []
    for s in safe_files:
        matched_orbits.append(match_orbit_for_safe(s, orbit_index))
    matched_orbits = sorted(set(matched_orbits))

    write_yaml(
        output_file=inps.output,
        safe_files=[os.path.abspath(s) for s in safe_files],
        orbit_files=matched_orbits,
        dem_file=dem_file,
        product_path=inps.product_path,
        product_version=inps.product_version,
        processing_type=inps.processing_type,
        burst_database_file=inps.burst_database_file,
        source_data_access=inps.source_data_access,
    )

    print("-" * 60)
    print(f"SAFE files      : {len(safe_files)}")
    print(f"Matched orbits  : {len(matched_orbits)}")
    print(f"DEM             : {dem_file}")
    print(f"YAML written    : {os.path.abspath(inps.output)}")
    print("-" * 60)


if __name__ == "__main__":
    sys.exit(main())