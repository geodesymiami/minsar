#!/usr/bin/env python3
"""Convert Dolphin/sweets or OPERA DISP stack to MintPy HDF-EOS5 (.he5).

Writes the same HDFEOS tree as MintPy/MiaplPy ``save_hdfeos5.py`` so
``view.py`` and ``ingest_insarmaps.bash`` work. Default mask matches OPERA
DISP-S1 recommended_mask (TC 0.6 / similarity 0.4).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    from minsar.utils.dolphin_presets import METHOD_STRING_HELP, OPERA_DISP_METHOD_STRING, normalize_method_string
    from minsar.utils.dolphin_hdfeos5_utils import (
        DOLPHIN2HDFEOS5_EXAMPLES,
        add_mask_arguments,
        apply_mask_suffix,
        build_mask,
        build_metadata,
        collect_timeseries,
        create_hdfeos_output,
        detect_input_kind,
        find_opera_stack_nc,
        he5_output_filename,
        latlon_grids,
        load_opera_stack,
        load_quality_layers,
        mask_filename_suffix,
        read_reference_point,
        resolve_mask_thresholds,
        resolve_required_files,
        resolve_run_paths,
        same_shape,
    )
except ImportError:
    from dolphin_presets import METHOD_STRING_HELP, OPERA_DISP_METHOD_STRING, normalize_method_string
    from dolphin_hdfeos5_utils import (
        DOLPHIN2HDFEOS5_EXAMPLES,
        add_mask_arguments,
        apply_mask_suffix,
        build_mask,
        build_metadata,
        collect_timeseries,
        create_hdfeos_output,
        detect_input_kind,
        find_opera_stack_nc,
        he5_output_filename,
        latlon_grids,
        load_opera_stack,
        load_quality_layers,
        mask_filename_suffix,
        read_reference_point,
        resolve_mask_thresholds,
        resolve_required_files,
        resolve_run_paths,
        same_shape,
    )

DESCRIPTION = (
    "Convert Dolphin GeoTIFF or OPERA DISP *-stack.nc into HDF-EOS5 "
    "(default -m recommended)"
)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=DOLPHIN2HDFEOS5_EXAMPLES,
    )
    parser.add_argument(
        "input_path",
        help="dolphin dir, OPERA run dir, or *-stack.nc",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="outfile",
        default=None,
        help="Output .he5 path (default: dolphin/timeseries/ or OPERA run timeseries/)",
    )
    parser.add_argument(
        "--no-update",
        dest="update",
        action="store_false",
        default=True,
        help="Use real last date in filename (default: DATE2=XXXXXXXX if within 31 days)",
    )
    parser.add_argument(
        "--method-string",
        type=normalize_method_string,
        default=None,
        metavar="LABEL",
        help=METHOD_STRING_HELP,
    )
    add_mask_arguments(parser)
    return parser


def _print_dolphin_files(files: dict):
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
    if files.get("similarity"):
        print(f"Phase similarity:   {files['similarity'][0]}")
    if files.get("avg_spatial"):
        print(f"Avg spatial coh:    {len(files['avg_spatial'])} interferogram files")
    if files.get("reference_point"):
        print(f"Reference point:    {files['reference_point']}")
    else:
        print("Reference point:    (none; using fallback pixel)")


def _pick_ref(shape, mask, quality, ts_dir=None):
    if ts_dir is not None:
        ref = read_reference_point(ts_dir, shape)
        if ref is not None:
            print(f"Reference point from reference_point.txt: row={ref[0]} col={ref[1]}")
            return ref
    temp_coh = quality.get("temporal_coherence")
    if temp_coh is not None:
        valid = np.where(mask & np.isfinite(temp_coh), temp_coh, -np.inf)
        ref_y, ref_x = np.unravel_index(int(np.argmax(valid)), shape)
    else:
        ref_y, ref_x = shape[0] // 2, shape[1] // 2
    print(f"No reference_point.txt; using REF_Y={ref_y} REF_X={ref_x}")
    return ref_y, ref_x


def run_dolphin(inps, vmin, vmin_sim, suffix: str) -> Path:
    dataset_dir, dolphin_dir, ts_dir = resolve_run_paths(Path(inps.input_path))
    print(f"Kind:       dolphin")
    print(f"Dataset:    {dataset_dir}")
    print(f"Dolphin:    {dolphin_dir}")
    print(f"Timeseries: {ts_dir}")

    files = resolve_required_files(dataset_dir, dolphin_dir, ts_dir)
    _print_dolphin_files(files)

    stack, date_list, grid = collect_timeseries(ts_dir)
    shape = (int(grid["LENGTH"]), int(grid["WIDTH"]))
    quality = load_quality_layers(dataset_dir, dolphin_dir, ts_dir, shape, files=files)
    mask = build_mask(shape, stack, quality, source=inps.mask_source, vmin=vmin, vmin_sim=vmin_sim)
    print(f"Mask:       -m {inps.mask_source} --vmin {vmin}" + (f" --vmin-sim {vmin_sim}" if vmin_sim is not None else ""))

    latitude, longitude = latlon_grids(grid)
    ref_y, ref_x = _pick_ref(shape, mask, quality, ts_dir=ts_dir)
    method_name = inps.method_string or "dolphin"
    print(f"HE5 name:   {method_name}")
    metadata = build_metadata(
        dataset_dir,
        dolphin_dir,
        ts_dir,
        date_list,
        latitude,
        longitude,
        ref_y,
        ref_x,
        processor="dolphin",
        post_processing_method=method_name,
    )
    # Write .he5 next to the GeoTIFF timeseries inputs (dolphin/timeseries/).
    return _write_he5(inps, ts_dir, stack, date_list, grid, quality, mask, latitude, longitude, metadata, suffix, bperp=None)


def run_opera(inps, vmin, vmin_sim, suffix: str) -> Path:
    input_path = Path(inps.input_path).expanduser().resolve()
    stack_nc = find_opera_stack_nc(input_path)
    run_dir = stack_nc.parent if stack_nc.parent.is_dir() else input_path
    print(f"Kind:       opera-disp")
    print(f"Run dir:    {run_dir}")
    print(f"Stack NC:   {stack_nc}")

    stack, date_list, grid, quality, bperp = load_opera_stack(stack_nc, run_dir)
    shape = (int(grid["LENGTH"]), int(grid["WIDTH"]))
    print(f"Timeseries: {stack.shape[0]} dates, {shape[0]}x{shape[1]}")
    print(f"Temp coh:   average_temporal_coherence / mean(temporal_coherence)")
    print(f"Similarity: nanmean(phase_similarity)")
    if quality.get("recommended_density") is not None:
        print(f"Rec dens:   from recommended_mask (for -m recommendedDensity)")
    mask = build_mask(shape, stack, quality, source=inps.mask_source, vmin=vmin, vmin_sim=vmin_sim)
    print(f"Mask:       -m {inps.mask_source} --vmin {vmin}" + (f" --vmin-sim {vmin_sim}" if vmin_sim is not None else ""))

    latitude, longitude = latlon_grids(grid)
    ref_y, ref_x = _pick_ref(shape, mask, quality)
    method_name = inps.method_string or OPERA_DISP_METHOD_STRING
    print(f"HE5 name:   {method_name}")
    metadata = build_metadata(
        run_dir,
        run_dir,
        run_dir,
        date_list,
        latitude,
        longitude,
        ref_y,
        ref_x,
        processor="opera-disp",
        post_processing_method=method_name,
        require_orbit=False,
    )
    out_dir = run_dir / "timeseries"
    out_dir.mkdir(parents=True, exist_ok=True)
    return _write_he5(
        inps, out_dir, stack, date_list, grid, quality, mask, latitude, longitude, metadata, suffix, bperp=bperp
    )


def _write_he5(inps, out_dir, stack, date_list, grid, quality, mask, latitude, longitude, metadata, suffix, bperp):
    shape = (int(grid["LENGTH"]), int(grid["WIDTH"]))
    if inps.outfile:
        out_path = Path(inps.outfile).expanduser().resolve()
        if out_path.suffix.lower() != ".he5":
            out_path = out_path.with_suffix(".he5")
        out_path = apply_mask_suffix(out_path, suffix)
    else:
        out_name = he5_output_filename(
            metadata, update_mode=inps.update, subset_mode=True, suffix=suffix
        )
        out_path = Path(out_dir) / out_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    metadata["FILE_PATH"] = str(out_path)

    create_hdfeos_output(
        ts_data=stack,
        mask=mask,
        latitude=latitude,
        longitude=longitude,
        date_list=date_list,
        output_path=str(out_path),
        temporal_coherence=quality.get("temporal_coherence"),
        height=quality.get("height"),
        azimuth=quality.get("azimuth"),
        incidence=quality.get("incidence"),
        shadow_mask=same_shape(quality.get("shadow"), shape),
        avg_spatial_coherence=same_shape(quality.get("avg_spatial_coherence"), shape),
        watermask=same_shape(quality.get("watermask"), shape),
        conncomp=same_shape(quality.get("conncomp"), shape),
        phase_similarity=same_shape(quality.get("phase_similarity"), shape),
        recommended_density=same_shape(quality.get("recommended_density"), shape),
        bperp=bperp,
        metadata=metadata,
    )
    print(f"\nIngest with:\n  ingest_insarmaps.bash \"{out_path}\"")
    return out_path


def run(inps) -> Path:
    vmin, vmin_sim = resolve_mask_thresholds(inps.mask_source, inps.vmin, inps.vmin_sim)
    suffix = mask_filename_suffix(inps.mask_source, vmin, vmin_sim)
    kind = detect_input_kind(Path(inps.input_path))
    if kind == "dolphin":
        return run_dolphin(inps, vmin, vmin_sim, suffix)
    return run_opera(inps, vmin, vmin_sim, suffix)


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
