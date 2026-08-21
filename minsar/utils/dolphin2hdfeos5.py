#!/usr/bin/env python3
"""Convert a Dolphin/sweets displacement directory to MintPy HDF-EOS5 (.he5).

Writes the same HDFEOS tree as MintPy/MiaplPy ``save_hdfeos5.py`` so
``view.py`` and ``ingest_insarmaps.bash`` work. Filename uses the MinSAR
MintPy convention with ``post_processing_method=dolphin``.

Dataset directories follow MinSAR naming, e.g. HawaiiPunaSweetsSenA124:
project HawaiiPunaSweets, satellite Sen, ascending, relative orbit 124.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    from minsar.utils.dolphin_hdfeos5_utils import (
        build_mask,
        build_metadata,
        collect_timeseries,
        create_hdfeos_output,
        he5_output_filename,
        latlon_grids,
        load_quality_layers,
        read_reference_point,
        resolve_required_files,
        resolve_run_paths,
        same_shape,
    )
except ImportError:
    from dolphin_hdfeos5_utils import (
        build_mask,
        build_metadata,
        collect_timeseries,
        create_hdfeos_output,
        he5_output_filename,
        latlon_grids,
        load_quality_layers,
        read_reference_point,
        resolve_required_files,
        resolve_run_paths,
        same_shape,
    )

DESCRIPTION = "Convert Dolphin timeseries into hdfeos5 file (needs timeseries/, geometry/, interferograms/)"

EXAMPLE = """Examples:
  dolphin2hdfeos5.py dolphin
  dolphin2hdfeos5.py /scratch/05861/tg851601/HawaiiPunaSweetsSenA124/dolphin
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EXAMPLE,
    )
    parser.add_argument(
        "input_path",
        help="dolphin directory (e.g. dolphin or .../HawaiiPunaSweetsSenA124/dolphin)",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="outfile",
        default=None,
        help="Output .he5 path (default: timeseries/<MintPy-style name>.he5)",
    )
    parser.add_argument(
        "--no-update",
        dest="update",
        action="store_false",
        default=True,
        help="Use real last date in filename (default: DATE2=XXXXXXXX if within 31 days)",
    )
    parser.add_argument(
        "--mask-temp-coh",
        type=float,
        default=0.65,
        help="Keep pixels with temporal coherence above this (default: 0.65)",
    )
    return parser


def _print_loaded_files(files: dict):
    temp_paths = files["temporal_coherence"]
    temp_label = str(temp_paths[0]) if len(temp_paths) == 1 else f"{len(temp_paths)} interferogram files"
    print(f"Timeseries:         {len(files['timeseries'])} GeoTIFFs")
    print(f"Temporal coherence: {temp_label}")
    print(f"Watermask:          {files['watermask']}")
    print(f"Conncomp:           {files['conncomp']}")
    print(f"Height:             {files['height']}")
    print(f"Incidence:          {files['incidence']}")
    print(f"LOS east/north:     {files['los_east']}")
    print(f"                    {files['los_north']}")
    if files.get("shadow"):
        print(f"Shadow mask:        {files['shadow']}")
    if files.get("avg_spatial"):
        print(f"Avg spatial coh:    {len(files['avg_spatial'])} interferogram files")
    if files.get("reference_point"):
        print(f"Reference point:    {files['reference_point']}")
    else:
        print("Reference point:    (none; using fallback pixel)")


def run(inps) -> Path:
    dataset_dir, dolphin_dir, ts_dir = resolve_run_paths(Path(inps.input_path))
    print(f"Dataset:    {dataset_dir}")
    print(f"Dolphin:    {dolphin_dir}")
    print(f"Timeseries: {ts_dir}")

    files = resolve_required_files(dataset_dir, dolphin_dir, ts_dir)
    _print_loaded_files(files)

    stack, date_list, grid = collect_timeseries(ts_dir)
    shape = (int(grid["LENGTH"]), int(grid["WIDTH"]))
    quality = load_quality_layers(dataset_dir, dolphin_dir, ts_dir, shape, files=files)
    mask = build_mask(shape, stack, quality, temp_coh_thresh=inps.mask_temp_coh)

    latitude, longitude = latlon_grids(grid)
    ref = read_reference_point(ts_dir, shape)
    if ref is None:
        temp_coh = quality.get("temporal_coherence")
        valid = np.where(mask & np.isfinite(temp_coh), temp_coh, -np.inf)
        ref_y, ref_x = np.unravel_index(int(np.argmax(valid)), shape)
        print(f"No reference_point.txt; using REF_Y={ref_y} REF_X={ref_x}")
    else:
        ref_y, ref_x = ref
        print(f"Reference point from reference_point.txt: row={ref_y} col={ref_x}")

    metadata = build_metadata(
        dataset_dir,
        dolphin_dir,
        ts_dir,
        date_list,
        latitude,
        longitude,
        ref_y,
        ref_x,
    )

    if inps.outfile:
        out_path = Path(inps.outfile).expanduser().resolve()
        if out_path.suffix.lower() != ".he5":
            out_path = out_path.with_suffix(".he5")
    else:
        out_name = he5_output_filename(
            metadata, update_mode=inps.update, subset_mode=True
        )
        out_path = ts_dir / out_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    metadata["FILE_PATH"] = str(out_path)

    create_hdfeos_output(
        ts_data=stack,
        mask=mask,
        latitude=latitude,
        longitude=longitude,
        date_list=date_list,
        output_path=str(out_path),
        temporal_coherence=quality["temporal_coherence"],
        height=quality["height"],
        azimuth=quality["azimuth"],
        incidence=quality["incidence"],
        shadow_mask=same_shape(quality.get("shadow"), shape),
        avg_spatial_coherence=same_shape(quality.get("avg_spatial_coherence"), shape),
        metadata=metadata,
    )
    print(f"\nIngest with:\n  ingest_insarmaps.bash \"{out_path}\"")
    return out_path


def main(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    try:
        run(inps)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
