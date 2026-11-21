#!/usr/bin/env python3
import os
import argparse
import subprocess
import json
import re
import platform
import pickle
import h5py
from pathlib import Path
from datetime import date, datetime
from mintpy.utils import readfile
import minsar.utils.process_utilities as putils
import pandas as pd
import webbrowser
import sys
import shlex
import shutil

# step 2 is shared with the other uploaders; this file's folder goes on the path also when a jobfile loads it by path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from insarmaps_step2 import (  # noqa: E402
    _append_command_log,
    _append_ingest_command_log,
    _reset_ingest_command_log,
    convert_to_relative_path,
    ingest_remote_paths_for_scratch,
    ingest_step2_rsh,
    ingest_step2_rsync_and_remote_ingest,
    insarmaps_host_list,
)

def _load_get_output_filename():
    """Prefer MinSAR additions/mintpy save_hdfeos5 over upstream MintPy."""
    import importlib.util

    minsar_home = os.environ.get("MINSAR_HOME", "")
    if minsar_home:
        he5_path = Path(minsar_home) / "additions" / "mintpy" / "save_hdfeos5.py"
        if he5_path.is_file():
            spec = importlib.util.spec_from_file_location("minsar_save_hdfeos5", he5_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.get_output_filename

    from mintpy.save_hdfeos5 import get_output_filename
    return get_output_filename

_get_output_filename_fn = None

def _get_he5_get_output_filename():
    global _get_output_filename_fn
    if _get_output_filename_fn is None:
        _get_output_filename_fn = _load_get_output_filename()
    return _get_output_filename_fn

try:
    from mintpy.objects import sensor as mintpy_sensor
except ImportError:
    mintpy_sensor = None

def he5_dataset_filename(metadata, suffix=None, subset_mode=True):
    """Call get_output_filename across MinSAR and upstream MintPy signatures."""
    import inspect

    get_output_filename = _get_he5_get_output_filename()
    kwargs = {"suffix": suffix, "update_mode": False, "subset_mode": subset_mode}
    if "template" in inspect.signature(get_output_filename).parameters:
        return get_output_filename(metadata, {}, **kwargs)
    return get_output_filename(metadata, **kwargs)

def merge_into_metadata_pickle(json_dir, attrs):
    """Ensure Insarmaps' JSON/metadata.pickle has every direction key/value the title might read."""

    p = Path(json_dir) / "metadata.pickle"
    if not p.exists():
        print("[WARN] metadata.pickle not found; cannot set orbit_direction/mission")
        return

    with open(p, "rb") as f:
        meta = pickle.load(f)

    a = meta.get("attributes", {})

    # Normalize mission for title (e.g., "S1")
    mission_raw = (attrs.get("PLATFORM") or attrs.get("mission") or a.get("mission") or "").upper()
    aliases = {"SENTINEL-1": "S1", "SEN": "S1", "S1": "S1",
               "TERRASAR-X": "TSX", "TSX": "TSX"}
    a["mission"] = aliases.get(mission_raw, mission_raw or "S1")

    # Derive orbit/flight direction in both long and short forms
    raw_dir = (
        attrs.get("ORBIT_DIRECTION")
        or attrs.get("flight_direction")
        or a.get("orbit_direction")
        or a.get("flight_direction")
        or ""
    )
    raw_dir = str(raw_dir).strip().upper()

    if raw_dir in ("A", "ASCENDING"):
        long_dir, short_dir = "ASCENDING", "A"
    elif raw_dir in ("D", "DESCENDING"):
        long_dir, short_dir = "DESCENDING", "D"
    else:
        # Fallback: try to infer from SAR track if available (no-op here); otherwise bail.
        long_dir, short_dir = None, None

    if long_dir:
        # Make every likely-read key the short letter so the title shows A/D
        a["orbit_direction"]  = short_dir   # "A"/"D"
        a["flight_direction"] = short_dir   # force letter
        a["direction"]        = short_dir   # force letter
        a["ORBIT_DIRECTION"]  = short_dir   # force letter


    # Pass through other handy fields if missing
    for k in ("relative_orbit", "beam_mode", "look_direction", "first_frame", "last_frame"):
        if k in attrs and k not in a:
            a[k] = attrs[k]

    meta["attributes"] = a
    with open(p, "wb") as f:
        pickle.dump(meta, f)

    # Debug: show which keys ended up in the pickle
    print("[INFO] metadata.pickle keys:", sorted(a.keys()))
    if long_dir:
        print(f"[INFO] Set direction keys -> long='{long_dir}', short='{short_dir}'")
    else:
        print("[WARN] Could not determine orbit/flight direction to set")


def create_parser():
    parser = argparse.ArgumentParser(
        description="End-to-end pipeline for: SARvey shapefiles -> CSV -> JSON -> Insarmaps -> jetstream\n"
                    "Insarmaps upload rsyncs JSON/ to the host (under /data/scratch) and runs json_mbtiles2insarmaps.py there over ssh,\n"
                    "which loads the dataset and builds the recolor store the map draws it from. On the Insarmaps host itself\n"
                    "(localhost, its own name, or a host in INSARMAPS_LOCAL_HOSTS) it runs json_mbtiles2insarmaps.py on JSON/ where it is.",
        epilog="""\
    Examples:

               Masjed dam (sarvey example)
        sarvey2insarmaps.py outputs/p2_coh80_ts.h5
        sarvey2insarmaps.py outputs/p2_coh80_ts.h5 --upload
        sarvey2insarmaps.py outputs/p2_coh80_ts.h5 --suffix thermal
        sarvey2insarmaps.py outputs/p2_coh80_ts.h5 --sarvey-geocorr

        sarvey2insarmaps.py outputs/shp/p2_coh70_ts.shp
        sarvey2insarmaps.py outputs/shp/p2_coh70_ts.shp --geocorr
        sarvey2insarmaps.py outputs/shp/p2_coh70_ts.shp --make-jobfile
        sarvey2insarmaps.py outputs/shp/p2_coh70_ts.shp --skip-upload

    """,
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("input_file", nargs="?", help="Optional input .h5 or .shp file (uses config.json if omitted)")
    parser.add_argument("--config-json", help="Path to config.json (overrides default detection)")
    parser.add_argument("--insarmaps-host",
        default=os.environ.get("INSARMAPSHOST_OLDDATA", "insarmaps.miami.edu"),
        help="Insarmaps host, or comma-separated hosts (default: INSARMAPSHOST_OLDDATA or insarmaps.miami.edu)"
    )
    parser.add_argument("--upload", dest="upload_flag", action="store_true", help="Upload to jetstream (default: no upload)")
    parser.add_argument("--suffix", metavar="TAG", default=None, help="Tag appended to Insarmaps dataset filename before the extension (e.g. thermal → ..._thermal.csv)")

    parser.add_argument("--skip-upload", action="store_true", help="Skip upload to Insarmaps")
    parser.add_argument("--make-jobfile", action="store_true", help="Generate jobfile")
    parser.add_argument(
        "--geocorr", dest="do_geocorr", action="store_true",
        help="Accepted for existing command lines. CSV geolocation correction always runs."
    )

    parser.set_defaults(do_geocorr=False)
    parser.add_argument("--sarvey-geocorr", action="store_true", help="Apply geolocation correction for sarvey_export (--correct_geo)")

    return parser

def load_config_and_input_path(inps):
    """
    Load input path from config.json or infer it from the input file location.
    """
    config_json_path = Path(inps.config_json).resolve() if inps.config_json else None
    sarvey_inputs_dir_path, output_path = None, None

    # FA: There are packages to read json format
    if config_json_path and config_json_path.exists():
        print(f"Using config file: {config_json_path}")
        with open(config_json_path) as f:
            config_text = f.read()
            config_text = re.sub(r"(?<![\w\"])(\w+) *:", r'"\1":', config_text)
            config_text = re.sub(r",\s*([\]}])", r"\1", config_text)
            config_data = json.loads(config_text)

        try:
            sarvey_inputs_dir_path = Path(config_data["general"]["input_path"]).resolve()
            print(f"Inputs path set from config.json: {sarvey_inputs_dir_path}")
        except (KeyError, TypeError):
            sarvey_inputs_dir_path = Path("inputs").resolve()
            print("'input_path' not found in config.json. Defaulting to ./inputs/")

        try:
            output_path = Path(config_data["general"]["output_path"]).resolve()
            print(f"Output path set from config.json: {output_path}")
        except (KeyError, TypeError):
            raise ValueError("`output_path` must be specified in config.json under general.")

    elif inps.input_file:
        input_file_path = Path(inps.input_file).resolve()
        sarvey_inputs_dir_path = input_file_path.parents[1] / "inputs"
        output_path = input_file_path.parent.resolve()
        print(f"Inferred paths — inputs: {sarvey_inputs_dir_path}, output: {output_path}")
    else:
        raise ValueError("Must provide either --input_file or a valid config.json.")

    return sarvey_inputs_dir_path, output_path


def set_output_paths(output_path, base_filename, do_geocorr):
    """
    Create output directories and return key paths.
    Returns: csv_file_path, geocorr_csv_path, json_dir, output_path
    (base_dir extension if exist will be appended to dataset_name )
    """
    output_path = Path(output_path).resolve()

    csv_file_path = output_path / f"{base_filename}.csv"
    geocorr_csv_path = output_path / f"{base_filename}_geocorr.csv"

    json_dir = output_path / "JSON"
    json_dir.mkdir(parents=True, exist_ok=True)

    return csv_file_path, geocorr_csv_path, json_dir, output_path

def _parse_int_orbit(value):
    """Parse orbit/track numbers stored as int, float, or numeric string."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None

def resolve_relative_orbit(slc_attr, geom_attr=None):
    """Return relative orbit from stack/geometry attributes (HE5-compatible lookup)."""
    geom_attr = geom_attr or {}
    for src in (slc_attr, geom_attr):
        for key in ("relative_orbit", "unavco.relative_orbit", "track_number"):
            orbit = _parse_int_orbit(src.get(key))
            if orbit is not None:
                return orbit
    return None

def csv_bbox_to_footprint_wkt(df):
    """Build a closed WKT POLYGON from CSV X/Y min/max bounds."""
    min_lat, max_lat = df["Y"].min(), df["Y"].max()
    min_lon, max_lon = df["X"].min(), df["X"].max()
    footprint_corners = [
        (max_lat, min_lon),
        (min_lat, min_lon),
        (min_lat, max_lon),
        (max_lat, max_lon),
        (max_lat, min_lon),
    ]
    return putils.corners_to_wkt_polygon(footprint_corners)

def build_he5_metadata_for_naming(attributes, start_date, end_date, data_footprint_wkt):
    """Build metadata dict for get_output_filename() using CSV dates and stack attributes."""
    meta = dict(attributes)
    meta["first_date"] = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    meta["last_date"] = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
    meta["data_footprint"] = data_footprint_wkt

    if mintpy_sensor is not None:
        try:
            meta["mission"] = mintpy_sensor.get_unavco_mission_name(meta)
        except ValueError:
            pass
    if "mission" not in meta:
        platform_raw = (meta.get("PLATFORM") or meta.get("mission") or "S1").upper()
        platform_aliases = {
            "TSX": "TSX", "TERRASAR-X": "TSX", "SENTINEL-1": "S1", "S1": "S1", "SEN": "S1",
            "ERS": "ERS", "ENVISAT": "ENVISAT", "ALOS": "ALOS",
        }
        meta["mission"] = platform_aliases.get(platform_raw, platform_raw or "S1")

    meta.setdefault("beam_mode", "IW")
    beam_swath = meta.get("beam_swath", meta.get("beamSwath", 0))
    try:
        meta["beam_swath"] = int(beam_swath or 0)
    except (TypeError, ValueError):
        meta["beam_swath"] = 0

    rel_orbit = _parse_int_orbit(meta.get("relative_orbit"))
    if rel_orbit is None:
        rel_orbit = resolve_relative_orbit(meta, {})
    if rel_orbit is None:
        raise ValueError(
            "relative_orbit not found in slcStack.h5 or geometryRadar.h5; "
            "run add_missing_attributes.py"
        )
    meta["relative_orbit"] = rel_orbit
    meta["post_processing_method"] = "sarvey"
    if "ORBIT_DIRECTION" not in meta:
        for key in ("flight_direction", "orbit_direction"):
            val = str(meta.get(key, "")).strip().upper()
            if val in ("A", "ASCENDING"):
                meta["ORBIT_DIRECTION"] = "ASCENDING"
                break
            if val in ("D", "DESCENDING"):
                meta["ORBIT_DIRECTION"] = "DESCENDING"
                break
    return meta

def generate_dataset_name_from_csv(csv_file_path, sarvey_inputs_dir_path=None):
    """
    Generate Insarmaps dataset stem using HE5 naming (see architecture_docs/HE5_NAMING.md).
    Corners always come from the CSV bounding box.
    """
    df = pd.read_csv(csv_file_path)

    time_cols = [col for col in df.columns if re.fullmatch(r"D\d{8}", col)]
    if not time_cols:
        raise ValueError("No valid date columns found in CSV (expected format: DYYYYMMDD).")

    time_cols = sorted(col[1:] for col in time_cols)
    start_date = time_cols[0]
    end_date = time_cols[-1]
    data_footprint_wkt = csv_bbox_to_footprint_wkt(df)

    if not sarvey_inputs_dir_path:
        raise ValueError("sarvey_inputs_dir_path is required to build HE5-compatible dataset names.")

    attributes, _ = extract_metadata_from_inputs(sarvey_inputs_dir_path)
    he5_meta = build_he5_metadata_for_naming(
        attributes, start_date, end_date, data_footprint_wkt
    )
    he5_name = he5_dataset_filename(he5_meta, suffix=None, subset_mode=True)
    return Path(he5_name).stem

def normalize_user_suffix(user_suffix):
    """Return a cleaned --suffix tag or None; reject empty or path-like values."""
    if user_suffix is None:
        return None
    tag = str(user_suffix).strip().strip("_")
    if not tag:
        raise ValueError("--suffix must be a non-empty tag")
    if re.search(r"[/\\]", tag):
        raise ValueError("--suffix must not contain path separators")
    return tag

def build_ingest_basename(dataset_name, output_suffix="", user_suffix=None):
    """Build Insarmaps dataset stem from auto name, output-dir tag, and optional --suffix."""
    parts = [dataset_name]
    if output_suffix:
        parts.append(str(output_suffix).strip("_"))
    tag = normalize_user_suffix(user_suffix)
    if tag:
        parts.append(tag)
    return "_".join(part for part in parts if part).rstrip("_")

def build_ingest_csv_filename(dataset_name, output_suffix="", user_suffix=None, geocorr=False):
    """Return final CSV filename for Insarmaps ingest."""
    stem = build_ingest_basename(dataset_name, output_suffix, user_suffix)
    return f"{stem}_geocorr.csv" if geocorr else f"{stem}.csv"

def sarvey_points_h5(data_path):
    """Return the SARvey points HDF5 that holds coord_xy and point_id."""
    data_path = Path(data_path)
    if data_path.suffix == ".h5":
        return data_path
    if data_path.parent.name == "shp":
        return data_path.parent.parent / f"{data_path.stem}.h5"
    return data_path.with_suffix(".h5")


def build_commands(shp_file_path, csv_file_path, geocorr_csv_path, json_dir, input_csv, geometry_h5=None, points_h5=None):
    """
    Build the list of shell command sequences for the SARvey-to-Insarmaps pipeline.

    Returns three commands:
        cmd1 - Convert SHP to CSV using ogr2ogr with WGS84 coordinates.
        cmd2 - Sample incidenceAngle/azimuthAngle and write longitude_corrected/latitude_corrected.
        cmd3 - Convert CSV or HDF5 to JSON chunks using hdfeos5_or_csv_2json_mbtiles.py.
    Insarmaps upload is ingest_step2_rsync_and_remote_ingest(), not a local json_mbtiles2insarmaps.py call.
    """
    cmd_ogr2ogr = ["ogr2ogr", "-f", "CSV", "-lco", "GEOMETRY=AS_XY", "-t_srs", "EPSG:4326", str(csv_file_path), str(shp_file_path)]
    correct_csv = geocorr_csv_path if geocorr_csv_path else csv_file_path
    # The bare command name is MiaplPy's correct_geolocation.py, which does not take a CSV.
    geocorr_script = Path(os.environ.get("MINSAR_HOME") or Path(__file__).resolve().parents[2]) / "minsar" / "insarmaps_utils" / "correct_geolocation.py"
    cmd_correctgeo = [sys.executable, str(geocorr_script), str(correct_csv), "--outfile", str(correct_csv)]
    if geometry_h5 is not None and points_h5 is not None:
        cmd_correctgeo.extend(["--geometry", str(geometry_h5), "--points", str(points_h5)])
    cmd_hdfeos5 = ["hdfeos5_or_csv_2json_mbtiles.py", str(input_csv), str(json_dir)]
    return cmd_ogr2ogr, cmd_correctgeo, cmd_hdfeos5

def get_sarvey_export_path():
    """
    Find the path to the 'sarvey_export' executable in the 'sarvey' conda environment.
    """

    #try guessing from the current python executable path
    try:
        # FA: there is a CONDA_PREFIX environment variable which may do this
        conda_root = Path(sys.executable).resolve().parents[2]
        expected_path = conda_root / "envs" / "sarvey" / "bin" / "sarvey_export"
        if expected_path.exists():
            return str(expected_path)
    except Exception as e:
        print(f"[WARN] Could not locate 'sarvey_export' by guessing: {e}")

    #fallback: use conda run
    try:
        result = subprocess.check_output(
            ["conda", "run", "-n", "minsar", "which", "sarvey_export"],
            universal_newlines=True
        )
        return result.strip()
    except Exception as e:
        raise RuntimeError(f"Could not find 'sarvey_export' using conda run: {e}")


def extract_metadata_from_inputs(sarvey_inputs_dir_path):
    """
    Extract stack metadata from slcStack.h5 and geometryRadar.h5 for Insarmaps ingest.
    Returns attributes dict (dataset stem is built later from CSV via generate_dataset_name_from_csv).
    """
    attributes = {}

    slc_path = sarvey_inputs_dir_path / "slcStack.h5"
    geom_path = sarvey_inputs_dir_path / "geometryRadar.h5"

    #load slcStack.h5 attributes
    if slc_path.exists():
        slc_attr = readfile.read_attribute(str(slc_path))

        keys_to_extract = [
            "mission", "PLATFORM", "beam_mode", "beam_swath", "flight_direction", "relative_orbit",
            "processing_method", "post_processing_method", "REF_LAT", "REF_LON", "areaName", "DATE",
            "LAT_REF1", "LAT_REF2", "LAT_REF3", "LAT_REF4",
            "LON_REF1", "LON_REF2", "LON_REF3", "LON_REF4",
            "ORBIT_DIRECTION", "HEADING",
        ]
        for key in keys_to_extract:
            if key in slc_attr:
                attributes[key] = slc_attr[key]

        # Normalize orbit direction expected by Insarmaps title: A/D
        dir_src = (
            attributes.get("ORBIT_DIRECTION") or
            attributes.get("flight_direction") or
            ""
        )
        dir_src = str(dir_src).strip().upper()
        if dir_src in ("ASCENDING", "A"):
            attributes["orbit_direction"] = "A"
        elif dir_src in ("DESCENDING", "D"):
            attributes["orbit_direction"] = "D"

    geom_attr = {}
    #load geometryRadar.h5 attributes
    if geom_path.exists():
        geom_attr = readfile.read_attribute(str(geom_path))
        if "beamSwath" in geom_attr:
            attributes["beamSwath"] = geom_attr["beamSwath"]
        for key in (
            "unavco.relative_orbit", "relative_orbit", "track_number",
            "HEADING", "ORBIT_DIRECTION", "beam_swath", "beamSwath",
        ):
            if key not in attributes and key in geom_attr:
                attributes[key] = geom_attr[key]

    rel_orbit = resolve_relative_orbit(attributes, geom_attr)
    if rel_orbit is not None:
        attributes["relative_orbit"] = rel_orbit

    #set default/fallback attributes
    attributes.setdefault("data_type", "LOS_TIMESERIES")
    attributes.setdefault("look_direction", "R" if attributes.get("mission", "").upper() != "NISAR" else "L")
    attributes.setdefault("start_date", "TO_INFER")
    attributes.setdefault("end_date", "TO_INFER")
    attributes.setdefault("history", str(date.today()))
    attributes.setdefault("data_footprint", "")

    print(f"[INFO] slcStack.h5: mission={attributes.get('mission') or attributes.get('PLATFORM')}, "
          f"platform={attributes.get('PLATFORM')}, beam_mode={attributes.get('beam_mode')}, "
          f"orbit={attributes.get('relative_orbit')}")
    bbox = (
        f"({attributes.get('LAT_REF3')}, {attributes.get('LON_REF4')}) to "
        f"({attributes.get('LAT_REF2')}, {attributes.get('LON_REF1')})"
    )
    print(f"[INFO] bounding box: {bbox}")
    print("[INFO] slcStack.h5 metadata loaded. Final dataset name will be computed from the CSV.")

    return attributes, None

def update_and_save_final_metadata(json_dir, outdir, ingest_stem, metadata):
    """
    Update metadata dictionary using metadata.pickle if available,
    and save the final metadata as a JSON file.

    Returns: updated metadata
    """
    final_metadata_path = json_dir / "metadata.pickle"
    if final_metadata_path.exists():
        try:
            with open(final_metadata_path, "rb") as f:
                meta = pickle.load(f)
            final_metadata = meta.get("attributes", {})
            for key in ["first_date", "last_date", "data_footprint"]:
                if key in final_metadata:
                    metadata[key.replace("first_", "start_").replace("last_", "end_")] = final_metadata[key]
            for ref_key in ["REF_LAT", "REF_LON"]:
                if ref_key in final_metadata:
                    metadata[ref_key] = float(final_metadata[ref_key])
        except Exception as e:
            print(f"[WARN] Failed to read final metadata from pickle: {e}")

    final_meta_path = outdir / f"{ingest_stem}_final_metadata.json"
    with open(final_meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"[INFO] Final metadata written to: {final_meta_path}")

    return metadata

def get_data_footprint_center(metadata):
    """
    Compute center of WKT-style POLYGON string in 'data_footprint'.
    Falls back to REF_LAT and REF_LON if needed.
    """
    from shapely.wkt import loads as load_wkt

    wkt = metadata.get("data_footprint", "")
    if not isinstance(wkt, str) or not wkt.strip().upper().startswith("POLYGON"):
        print("[WARN] No valid data_footprint available — using REF_LAT/REF_LON instead")
        return metadata.get("REF_LAT", 26.1), metadata.get("REF_LON", -80.1)

    try:
        polygon = load_wkt(wkt)
        centroid = polygon.centroid
        return centroid.y, centroid.x  # lat, lon
    except Exception as e:
        print(f"[WARN] Failed to parse data_footprint WKT: {e}")
        return metadata.get("REF_LAT", 26.1), metadata.get("REF_LON", -80.1)


def generate_insarmaps_url(host, dataset_name, metadata, geocorr=False):
    """
    Generate an Insarmaps viewer URL using center of data footprint if available.
    """
    lat, lon = get_data_footprint_center(metadata)
    protocol = "https" if host.startswith("insarmaps.miami.edu") else "http"
    suffix = "_geocorr" if geocorr else ""
    return f"{protocol}://{host}/start/{lat:.4f}/{lon:.4f}/11.0?flyToDatasetCenter=true&startDataset={dataset_name}{suffix}"

def run_command(command, shell=False, conda_env=None, cwd=None):
    """
    Execute a shell command and print it once.
    - `command`: list of args or a single string
    - `shell`: whether to run in shell mode (requires string command)
    - `conda_env`: name of conda env to prefix with `conda run -n …`
    - `cwd`: working directory
    """
    #build prefix for conda
    prefix = ["conda", "run", "-n", conda_env, "--no-capture-output"] if conda_env else []

    #normalize command into list
    if shell:
        if not isinstance(command, str):
            raise ValueError("shell=True requires command to be a string")
        full_cmd_list = prefix + [command]
        display_cmd = full_cmd_list
    else:
        #if string, split; if list, copy
        cmd_parts = shlex.split(command) if isinstance(command, str) else list(command)
        full_cmd_list = prefix + cmd_parts
        display_cmd = full_cmd_list

    #convert to relative paths for display
    cmd_for_display = convert_to_relative_path(display_cmd, cwd=cwd or os.getcwd())
    command_line = " ".join(cmd_for_display)
    _append_ingest_command_log(command_line)
    print(
        "##########################\n"
        "Running (displaying relative paths)....\n"
        f"{command_line}\n"
        "##########################\n"
    )

    #execute once
    subprocess.run(
        full_cmd_list,
        check=True,
        shell=shell,
        cwd=str(cwd) if cwd else None
    )


def remote_ingest_job_command(host, json_dir, data_dir):
    """One jobfile line that runs ingest_step2_rsync_and_remote_ingest from this script."""
    script = str(Path(__file__).resolve())
    code = (
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('sarvey2insarmaps', {script!r})\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "mod.ingest_step2_rsync_and_remote_ingest("
        f"{host!r}, {str(json_dir)!r}, data_dir={str(data_dir)!r})\n"
    )
    return "python3 -c " + shlex.quote(code)


CSV_COLUMN_RENAMES = {
    "coherence": "temporalCoherence",
    "temporal_coherence": "temporalCoherence",
    "dem": "height",
    "dem_error": "demError",
    "X": "longitude",
    "Y": "latitude",
}


def rename_csv_columns_for_hdfeos5(csv_path):
    """Rename sarvey CSV columns to the HDFEOS5 names.

    Shapefile fields stay short (10-character DBF limit). This runs on the CSV after ogr2ogr
    and before geolocation correction.
    """
    csv_path = Path(csv_path)
    df = pd.read_csv(csv_path)
    present = {}
    for src, dst in CSV_COLUMN_RENAMES.items():
        if src in df.columns and dst not in df.columns and dst not in present.values():
            present[src] = dst
    if not present:
        print(f"[WARN] no sarvey columns to rename in {csv_path.name}; left unchanged")
        return
    rel = convert_to_relative_path([str(csv_path.resolve())])[0]
    rename_literal = ", ".join(f"{src!r}: {dst!r}" for src, dst in present.items())
    command_line = (
        "python3 -c \"import pandas as pd; "
        f"p={rel!r}; df=pd.read_csv(p); "
        f"df.rename(columns={{{rename_literal}}}).to_csv(p, index=False)\""
    )
    print(
        "##########################\n"
        "Running (displaying relative paths)....\n"
        f"{command_line}\n"
        "##########################\n"
    )
    _append_ingest_command_log(command_line)
    df = df.rename(columns=present)
    df.to_csv(csv_path, index=False)


def convert_displacement_mm_to_m(csv_path):
    """Convert sarvey millimeter columns to meters or m/year.

    DYYYYMMDD and st_consist are millimeters. velocity is mm/year. HDFEOS5 displacement
    and MintPy/MiaplPy velocity are meters and m/year. omega is a phase residual and is left unchanged.
    """
    csv_path = Path(csv_path)
    df = pd.read_csv(csv_path)
    date_cols = [col for col in df.columns if re.fullmatch(r"D\d{8}", str(col))]
    scale_cols = date_cols + [col for col in ("velocity", "st_consist") if col in df.columns]
    if not scale_cols:
        print(f"[WARN] no displacement or velocity columns in {csv_path.name}; left unchanged")
        return
    rel = convert_to_relative_path([str(csv_path.resolve())])[0]
    command_line = (
        "python3 -c \"import pandas as pd; "
        f"p={rel!r}; df=pd.read_csv(p); "
        "cols=[c for c in df.columns if (len(c)==9 and c[0]=='D' and c[1:].isdigit()) or c in ('velocity','st_consist')]; "
        "df[cols]=df[cols]/1000.0; df.to_csv(p, index=False)\""
    )
    print(
        "##########################\n"
        "Running (displaying relative paths)....\n"
        f"{command_line}\n"
        "##########################\n"
    )
    _append_ingest_command_log(command_line)
    df[scale_cols] = df[scale_cols] / 1000.0
    df.to_csv(csv_path, index=False)


def create_jobfile(inps, data_path, cmds, json_dir, output_path, dataset_name, metadata):
    """
    Generate a SLURM-compatible jobfile with all processing steps and Insarmaps URL.
    """

    cmd_sarvey_export, cmd_ogr2ogr, cmd_geocorr, cmd_hdfeos5 = cmds

    jobfile_path = Path(output_path) / "sarvey2insarmaps.job"
    slurm_commands = []

    # Step 1: HDF5 to shp if input is HDF5
    if data_path.suffix == ".h5":
        slurm_commands.append(" ".join(cmd_sarvey_export))

    # Step 2: shp to csv
    slurm_commands.append(" ".join(cmd_ogr2ogr))

    # Step 3: geolocation correction (always)
    slurm_commands.append(" ".join(cmd_geocorr))

    slurm_commands.extend([
        f"rm -rf {json_dir}",
        # Step 4: hdfeos5_or_csv_2json_mbtiles.py
        " ".join(cmd_hdfeos5),
    ])
    # Step 5: rsync JSON/ to each host and ingest there (same as ingest_insarmaps.bash step 2)
    for host in insarmaps_host_list(inps.insarmaps_host):
        slurm_commands.append(remote_ingest_job_command(host, json_dir, output_path))

    with open(jobfile_path, 'w') as f:
        f.write("#!/bin/bash\n\n")
        f.write("# Generated by sarvey2insarmaps.py\n")
        f.write(f"# Dataset: {dataset_name}\n")
        f.write(f"# Generated on: {date.today()}\n\n")

        for cmd in slurm_commands:
            f.write(cmd + "\n")
            if any(key in cmd for key in ("rm -rf", "geolocation", "hdfeos5")):
                f.write("\n")

        f.write("wait\n\n")

        f.write("\n# Insarmaps URLs:\n")
        for host in insarmaps_host_list(inps.insarmaps_host):
            url = generate_insarmaps_url(host, dataset_name, metadata, geocorr=False)
            f.write(f"cat >> insarmaps.log<<EOF\n{url}\nEOF\n\n")

    print(f"\nJobfile created: {jobfile_path}")

def main():
    parser = create_parser()
    inps = parser.parse_args()
    print("Geolocation correction: always (longitude_corrected, latitude_corrected)")

    # FA inputs_path is a confusing name. You expect that it is the path to an input file. Maybe sarvey_inputs_dir_path. And beloe you have input_path
    sarvey_inputs_dir_path, output_path = load_config_and_input_path(inps)

    #ensure required files exist
    required_files = ["slcStack.h5", "geometryRadar.h5"]
    for fname in required_files:
        fpath = sarvey_inputs_dir_path / fname
        if not fpath.exists():
            raise FileNotFoundError(f"Required file not found: {fpath}")

    #metadata, _ = extract_metadata_from_inputs(sarvey_inputs_dir_path)
    #if not metadata:
    #    print("[WARN] No metadata found in slcStack.h5 or geometryRadar.h5.")

    #use $RSMASINSAR_HOME as the root for now (temporarily)
    # FA if you really need an environment variable use variable name RSMASINSAR_HOME
    rsmasinsar_home = os.environ.get("MINSAR_HOME")
    if not rsmasinsar_home:
        raise EnvironmentError("Environment variable MINSAR_HOME is not set.")

    #input/output paths
    # FA: That this is not in build_commands is confusing. If you can't put it there create your own functions
    # FA: input_path is not a good name as it maye contain the string output. Use data_path or similar
    data_path = Path(inps.input_file).resolve()
    if data_path.suffix == ".h5":
        h5_path = data_path
        shp_file_path = h5_path.parent / "shp" / f"{h5_path.stem}.shp"
        print(f"[INFO] Input is HDF5. Inferred shapefile path: {shp_file_path}")
        # Step 0: always run sarvey_export if input is HDF5
        # FA: This is a complicated function. You are dealing with environments, so we need "env" in the function name.
        # FA: You can use CONDA_PREFIX to determine in which environemnt we are.
        sarvey_export_path = get_sarvey_export_path()
        cmd_sarvey_export = [sarvey_export_path, str(h5_path), "-o", str(shp_file_path)]
        if inps.sarvey_geocorr:
            print("[INFO] Applying SARvey geolocation correction")
            cmd_sarvey_export.append("--correct_geo")
    else:
        shp_file_path = data_path
        h5_path = shp_file_path.with_suffix(".h5")
        print(f"[INFO] Input is SHP. Inferred HDF5 path: {h5_path}")

    geometry_h5 = sarvey_inputs_dir_path / "geometryRadar.h5"
    points_h5 = sarvey_points_h5(data_path)
    if not points_h5.is_file():
        raise FileNotFoundError(f"Required file not found: {points_h5}")
    if inps.sarvey_geocorr:
        print("[WARN] --sarvey-geocorr moves the shapefile coordinates, and the CSV step shifts them again")

    # FA this section is important while the above is just dealing with filenames/options. This should be optically emphasized with comment signs and text
    # FA: unclear what geocorr_csv is. A file path? then sat it as you do for the others. Same for input_csv below. So it would be csv_file_path, shp_file_path ?
    data_path = Path(inps.input_file).resolve()
    base_filename = data_path.stem
    csv_file_path, geocorr_csv_path, json_dir, output_path = set_output_paths(
        output_path, base_filename, inps.do_geocorr
    )
    input_csv = csv_file_path


    cmd_ogr2ogr, cmd_correctgeo, cmd_hdfeos5 = build_commands(
        shp_file_path, csv_file_path, csv_file_path, json_dir, input_csv, geometry_h5, points_h5
    )

    #assign python environment for insarmaps_scripts
    if platform.system() == "Darwin":
       insarmaps_script_env = None
    else:
       insarmaps_script_env = None


    if inps.make_jobfile:
            print("[INFO] Creating jobfile only, skipping execution.")
            create_jobfile(inps, data_path, (cmd_sarvey_export, cmd_ogr2ogr, cmd_correctgeo, cmd_hdfeos5), json_dir, output_path, dataset_name, metadata)

    else:
        _reset_ingest_command_log()
        # Step 1: run sarvey_export to  create *.shp file
        if data_path.suffix == ".h5":
            run_command(cmd_sarvey_export, cwd=h5_path.parent.parent, conda_env=None)

        # Step 2: run ogr2ogr to create csv file (FA: is this correct?)
        run_command(cmd_ogr2ogr, conda_env=None)

        #update dataset_name from csv bbox and dates while X,Y are still the column names
        dataset_name = generate_dataset_name_from_csv(csv_file_path, sarvey_inputs_dir_path)

        output_suffix = Path(output_path).name.partition("outputs_")[2]
        ingest_stem = build_ingest_basename(dataset_name, output_suffix, inps.suffix)

        #rename csv to match desired output format
        final_csv_name = build_ingest_csv_filename(
            dataset_name, output_suffix, inps.suffix, geocorr=False
        )
        final_csv_path = output_path / final_csv_name

        #to final format
        shutil.move(csv_file_path, final_csv_path)
        input_csv = final_csv_path
        rename_csv_columns_for_hdfeos5(input_csv)
        convert_displacement_mm_to_m(input_csv)

        # Step 3: sample incidenceAngle/azimuthAngle and write corrected coordinates
        _, cmd_correctgeo, cmd_hdfeos5 = build_commands(
            shp_file_path, csv_file_path, input_csv, json_dir, input_csv, geometry_h5, points_h5
        )
        run_command(cmd_correctgeo, conda_env=None)

        # Step 4: convert the CSV into JSON chunks and metadata.pickle
        run_command(cmd_hdfeos5, conda_env=None)
        metadata, _ = extract_metadata_from_inputs(sarvey_inputs_dir_path)
        merge_into_metadata_pickle(json_dir, metadata)
        metadata = update_and_save_final_metadata(json_dir, output_path, ingest_stem, metadata)

        # Step 5: rsync JSON/ to each Insarmaps host and ingest there (on the Insarmaps host itself, in place)
        if not inps.skip_upload:
            for host in insarmaps_host_list(inps.insarmaps_host):
                ingest_step2_rsync_and_remote_ingest(host, json_dir, data_dir=output_path)

        # Step 6: create insarmaps.log with URL
        urls = [
            generate_insarmaps_url(host, ingest_stem, metadata, geocorr=False)
            for host in insarmaps_host_list(inps.insarmaps_host)
        ]

        with open("insarmaps.log", "a", encoding="utf-8") as handle:
            for url in urls:
                handle.write(url + "\n")
        if os.path.isdir(f"{output_path}/pic"):
            with open(f"{output_path}/pic/insarmaps.log", "a", encoding="utf-8") as handle:
                for url in urls:
                    handle.write(url + "\n")

        # Step 7: create pic/index.html
        run_command(["create_html.py", f"{output_path}/pic"])

        # Step 8: upload to jetstream
        if inps.upload_flag:
            print("\nUploading to Jetstream...")
            run_command(["upload_data_products.py",f"{os.path.dirname(inps.input_file)}"])

        #print the Insarmaps URL and open it in a web browser
        print("\nView on Insarmaps:")
        for url in urls:
            print(url)
        if platform.system() == "Darwin":
           webbrowser.open(f"{output_path}/pic/index.html")
        #  webbrowser.open(url)

    print("\nAll done!")

if __name__ == "__main__":
    main()
