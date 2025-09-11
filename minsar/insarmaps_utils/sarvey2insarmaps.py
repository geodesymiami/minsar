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
from datetime import date
from mintpy.utils import readfile
import minsar.utils.process_utilities as putils
import pandas as pd
import webbrowser
import sys
import shlex
import shutil

sys.path.insert(0, os.getenv("SSARAHOME"))
import password_config as password


def create_parser():
    parser = argparse.ArgumentParser(
        description="End-to-end pipeline for: SARvey shapefiles -> CSV -> JSON -> MBTiles -> Insarmaps -> jetstream",
        epilog="""\
    Examples:

               Masjed dam (sarvey example)
        sarvey2insarmaps.py outputs/p2_coh80_ts.h5
        sarvey2insarmaps.py outputs/p2_coh80_ts.h5 --no-upload
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
        default=os.environ.get("INSARMAPS_HOST", os.getenv("INSARMAPSHOST")),
        help="Insarmaps server host (default: environment variable INSARMAPS_HOST)"
    )
    # parser.add_argument("--upload", dest='upload_flag', action="store_true", help="Upload to jetstream (Default: no)")
    parser.add_argument("--no-upload",dest='upload_flag',action="store_false", help="Do not upload to jetstream (Default: upload)")

    parser.add_argument("--skip-upload", action="store_true", help="Skip upload to Insarmaps")
    parser.add_argument("--make-jobfile", action="store_true", help="Generate jobfile")
    parser.add_argument(
        "--geocorr", dest="do_geocorr", action="store_true",
        help="Enable geolocation correction step (default: off)"
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
    Returns: csv_file_path, geocorr_csv_path, json_dir, mbtiles_path, outdir, base_dir, dataset_name
    (base_dir extension if exist will be appended to dataset_name )
    """
    output_path = Path(output_path).resolve()

    csv_file_path = output_path / f"{base_filename}.csv"
    geocorr_csv_path = output_path / f"{base_filename}_geocorr.csv"

    json_dir = output_path / "JSON"
    json_dir.mkdir(parents=True, exist_ok=True)

    mbtiles_path = json_dir / f"{base_filename}.mbtiles"

    return csv_file_path, geocorr_csv_path, json_dir, mbtiles_path, output_path

def generate_dataset_name_from_csv(csv_file_path, sarvey_inputs_dir_path=None):
    """
    Generate dataset name from CSV (bbox/date) and optional metadata from sarvey_inputs_dir_path.
    """
    df = pd.read_csv(csv_file_path)

    #extract date columns
    time_cols = [col for col in df.columns if re.fullmatch(r"D\d{8}", col)]
    if not time_cols:
        raise ValueError("No valid date columns found in CSV (expected format: DYYYYMMDD).")

    #sort and strip starting 'D'
    time_cols = sorted(col[1:] for col in time_cols)
    start_date = time_cols[0]
    end_date = time_cols[-1]

    #get bounding box
    min_lat, max_lat = df["Y"].min(), df["Y"].max()
    min_lon, max_lon = df["X"].min(), df["X"].max()
    lat1 = f"N{int(min_lat * 10000):05d}"
    lat2 = f"N{int(max_lat * 10000):05d}"
    lon1 = f"W{abs(int(max_lon * 10000)):06d}"
    lon2 = f"W{abs(int(min_lon * 10000)):06d}"

    # Get the four corners of the data. We use a rectangular box and lat/lon min/max until we have figures out coordinates of the subset.
    footprint_corners = [
        (max_lat, min_lon),         # top-left
        (min_lat, min_lon),         # top-right
        (min_lat, max_lon),         # bottom-right
        (max_lat, max_lon),         # bottom-left
        (max_lat, min_lon)          # close the polygon
    ]
    polygon_str = putils.corners_to_wkt_polygon(footprint_corners)
    corners_str = putils.polygon_corners_string(polygon_str)

    mission, rel_orbit = "S1", "000"
    if sarvey_inputs_dir_path:
        attributes, _ = extract_metadata_from_inputs(sarvey_inputs_dir_path)
        platform_raw = (attributes.get("PLATFORM") or attributes.get("mission") or "").upper()
        platform_aliases = {
            "TSX": "TSX", "TERRASAR-X": "TSX", "SENTINEL-1": "S1", "S1": "S1",
            "ERS": "ERS", "ENVISAT": "ENVISAT", "ALOS": "ALOS"
        }
        mission = platform_aliases.get(platform_raw, "S1")

        rel_orbit_raw = attributes.get("relative_orbit", "")
        rel_orbit = f"{int(rel_orbit_raw):03d}" if str(rel_orbit_raw).isdigit() else "000"

    return f"{mission}_{rel_orbit}_{start_date}_{end_date}_{corners_str}"

def build_commands(shp_file_path, csv_file_path, geocorr_csv_path, json_dir, mbtiles_path, input_csv, inps):
    """
    Build the list of shell command sequences for the SARvey-to-Insarmaps pipeline.

    Returns four commands:
        cmd1 - Convert SHP to CSV using ogr2ogr with WGS84 coordinates.
        cmd2 - Apply geolocation correction using correct_geolocation.py (if --geocorr).
        cmd3 - Convert CSV or HDF5 to JSON and MBTiles format using hdfeos5_or_csv_2json_mbtiles.py.
        cmd4 - Upload MBTiles and JSON data to the Insarmaps server using json_mbtiles2insarmaps.py.
    """
    cmd_ogr2ogr = ["ogr2ogr", "-f", "CSV", "-lco", "GEOMETRY=AS_XY", "-t_srs", "EPSG:4326", str(csv_file_path), str(shp_file_path)]
    cmd_correctgeo = ["correct_geolocation.py", str(csv_file_path), "--outfile", str(geocorr_csv_path)]
    cmd_hdfeos5 = ["hdfeos5_or_csv_2json_mbtiles.py", str(input_csv), str(json_dir)]

    host = inps.insarmaps_host.split(",")[0]
    cmd_jsonmbtiles = [
        "json_mbtiles2insarmaps.py",
         "--num-workers", "3",
         "-u", password.docker_insaruser,
         "-p", password.docker_insarpass,
         "--host", host,
         "-P", password.docker_databasepass,
         "-U", password.docker_databaseuser,
         "--json_folder", str(json_dir),
         "--mbtiles_file", str(mbtiles_path),
    ]
    return cmd_ogr2ogr, cmd_correctgeo, cmd_hdfeos5, cmd_jsonmbtiles

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
            ["conda", "run", "-n", "sarvey", "which", "sarvey_export"],
            universal_newlines=True
        )
        return result.strip()
    except Exception as e:
        raise RuntimeError(f"Could not find 'sarvey_export' using conda run: {e}")


def extract_metadata_from_inputs(sarvey_inputs_dir_path):
    """
    Extract essential metadata from slcStack.h5 and geometryRadar.h5 to generate a dataset name.
    Returns a dict of metadata and a created dataset name string based on platform, dates, and bbox.
    """
    attributes = {}
    dataset_name = None

    slc_path = sarvey_inputs_dir_path / "slcStack.h5"
    geom_path = sarvey_inputs_dir_path / "geometryRadar.h5"

    #load slcStack.h5 attributes
    if slc_path.exists():
        slc_attr = readfile.read_attribute(str(slc_path))

        keys_to_extract = [
            "mission", "PLATFORM", "beam_mode", "flight_direction", "relative_orbit",
            "processing_method", "REF_LAT", "REF_LON", "areaName", "DATE",
            "LAT_REF1", "LAT_REF2", "LAT_REF3", "LAT_REF4",
            "LON_REF1", "LON_REF2", "LON_REF3", "LON_REF4"
        ]
        for key in keys_to_extract:
            if key in slc_attr:
                attributes[key] = slc_attr[key]

    #load geometryRadar.h5 attributes
    if geom_path.exists():
        geom_attr = readfile.read_attribute(str(geom_path))
        if "beamSwath" in geom_attr:
            attributes["beamSwath"] = geom_attr["beamSwath"]

    #set default/fallback attributes
    attributes.setdefault("data_type", "LOS_TIMESERIES")
    attributes.setdefault("look_direction", "R" if attributes.get("mission", "").upper() != "NISAR" else "L")
    attributes.setdefault("start_date", "TO_INFER")
    attributes.setdefault("end_date", "TO_INFER")
    attributes.setdefault("history", str(date.today()))
    attributes.setdefault("data_footprint", "")

    #generate dataset name
    try:
        #normalize platform name
        platform_raw = (attributes.get("PLATFORM") or attributes.get("mission") or "").upper()
        platform_aliases = {
            "TSX": "TSX", "TERRASAR-X": "TSX", "SENTINEL-1": "S1", "S1": "S1",
            "ERS": "ERS", "ENVISAT": "ENVISAT", "ALOS": "ALOS"
        }
        mission = platform_aliases.get(platform_raw, platform_raw or "S1")

        #orbit
        rel_orbit_raw = attributes.get("relative_orbit", "")
        rel_orbit = f"{int(rel_orbit_raw):03d}" if str(rel_orbit_raw).isdigit() else "000"

        #default date values
        start_date, end_date = "YYYYMMDD", "YYYYMMDD"

        #try to get actual start/end dates from dataset
        if slc_path.exists():
            try:
                with h5py.File(slc_path, "r") as f:
                    if "date" in f:
                        date_list = [d.decode() if isinstance(d, bytes) else str(d) for d in f["date"][:]]
                        if date_list:
                            start_date, end_date = date_list[0], date_list[-1]
            except Exception as e:
                print(f"[WARN] Could not read 'date' dataset from slcStack.h5: {e}")

        #use bounding box to generate geographic part of the name
        lat_vals = [float(attributes[k]) for k in ["LAT_REF1", "LAT_REF2", "LAT_REF3", "LAT_REF4"] if k in attributes]
        lon_vals = [float(attributes[k]) for k in ["LON_REF1", "LON_REF2", "LON_REF3", "LON_REF4"] if k in attributes]

        if lat_vals and lon_vals:
            lat1 = f"N{int(min(lat_vals) * 10000):05d}"
            lat2 = f"N{int(max(lat_vals) * 10000):05d}"
            lon1 = f"W{abs(int(max(lon_vals) * 10000)):06d}"
            lon2 = f"W{abs(int(min(lon_vals) * 10000)):06d}"
            dataset_name = f"{mission}_{rel_orbit}_{start_date}_{end_date}_{lat1}_{lat2}_{lon1}_{lon2}"
        else:
            dataset_name = f"{mission}_{rel_orbit}_{start_date}_{end_date}"

    except Exception as e:
        print(f"[WARN] Could not generate dataset_name: {e}")

    #info summary
    mission = attributes.get('mission') or attributes.get('PLATFORM')
    platform = attributes.get('PLATFORM')
    beam = attributes.get('beam_mode')
    orbit = attributes.get('relative_orbit')

    bbox = f"({attributes.get('LAT_REF3')}, {attributes.get('LON_REF4')}) to ({attributes.get('LAT_REF2')}, {attributes.get('LON_REF1')})"

    print(f"[INFO] slcStack.h5: mission={mission}, platform={platform}, beam_mode={beam}, orbit={orbit}")
    print(f"[INFO] bounding box: {bbox}")
    print("[INFO] slcStack.h5 metadata loaded. Final dataset name will be computed from the CSV.")

    return attributes, dataset_name

def update_and_save_final_metadata(json_dir, outdir, dataset_name, metadata, output_suffix):
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

    final_meta_path = outdir / f"{dataset_name}_{output_suffix}"
    final_meta_path = Path(str(final_meta_path).rstrip('_'))
    final_meta_path = final_meta_path.with_name(f"{final_meta_path.name}_final_metadata.json")
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
    print(
        "##########################\n"
        "Running (displaying relative paths)....\n"
        f"{' '.join(cmd_for_display)}\n"
        "##########################\n"
    )

    #execute once
    subprocess.run(
        full_cmd_list,
        check=True,
        shell=shell,
        cwd=str(cwd) if cwd else None
    )


def convert_to_relative_path(cmd_list, cwd=None):
    """
    Return a list where any element that lives under cwd is replaced by its relative path.
    """
    #make sure cwd is a string
    cwd = str(cwd or os.getcwd())
    rel = []
    for token in cmd_list:
        #only rewrite absolute paths under cwd
        if os.path.isabs(token) and token.startswith(cwd + os.sep):
            rel.append(os.path.relpath(token, cwd))
        else:
            rel.append(token)
    return rel


def create_jobfile(inps, data_path, cmds, json_dir, output_path, mbtiles_path, dataset_name, metadata):
    """
    Generate a SLURM-compatible jobfile with all processing steps and Insarmaps URL.
    """

    cmd_sarvey_export, cmd_ogr2ogr, cmd_geocorr, cmd_hdfeos5, cmd_json_mbtiles = cmds

    jobfile_path = Path(output_path) / "sarvey2insarmaps.job"
    slurm_commands = []

    # Step 1: HDF5 to shp if input is HDF5
    if data_path.suffix == ".h5":
        slurm_commands.append(" ".join(cmd_sarvey_export))

    # Step 2: shp to csv
    slurm_commands.append(" ".join(cmd_ogr2ogr))

    # Step 3: geolocation correction if enabled
    if inps.do_geocorr:
        slurm_commands.append(" ".join(cmd_geocorr))

    host = inps.insarmaps_host.split(",")[0]
    slurm_commands.extend([
        f"rm -rf {json_dir}",
        # Step 4: hdfeos5_or_csv_2json_mbtiles.py
        " ".join(cmd_hdfeos5),
         # Step 5: json_mbtiles2insarmaps.py
        " ".join(cmd_json_mbtiles).replace(inps.insarmaps_host, "insarmaps.miami.edu") + " &",
        " ".join(cmd_json_mbtiles).replace(inps.insarmaps_host, host) + " &"
    ])

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

        #use generate_insarmaps_url to compute accurate footprint center URLs
        url_1 = generate_insarmaps_url("insarmaps.miami.edu", dataset_name, metadata, geocorr=inps.do_geocorr)
        url_2 = generate_insarmaps_url(inps.insarmaps_host.split(",")[0], dataset_name, metadata, geocorr=inps.do_geocorr)

        f.write("\n# Insarmaps URLs:\n")
        f.write(f"cat >> insarmaps.log<<EOF\n{url_1}\nEOF\n\n")
        f.write(f"cat >> insarmaps.log<<EOF\n{url_2}\nEOF\n\n")

    print(f"\nJobfile created: {jobfile_path}")

def main():
    parser = create_parser()
    inps = parser.parse_args()
    print(f"Geolocation correction enabled: {inps.do_geocorr}")

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
    rsmasinsar_home = os.environ.get("RSMASINSAR_HOME")
    if not rsmasinsar_home:
        raise EnvironmentError("Environment variable RSMASINSAR_HOME is not set.")

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

    # FA this section is important while the above is just dealing with filenames/options. This should be optically emphasized with comment signs and text
    # FA: unclear what geocorr_csv is. A file path? then sat it as you do for the others. Same for input_csv below. So it would be csv_file_path, shp_file_path ?
    #csv_path, geocorr_csv_path, json_dir, mbtiles_path, base_dir, dataset_name = set_output_paths(output_path, dataset_name, inps.do_geocorr)
    data_path = Path(inps.input_file).resolve()
    base_filename = data_path.stem
    csv_file_path, geocorr_csv_path, json_dir, mbtiles_path, output_path = set_output_paths(output_path, base_filename, inps.do_geocorr)
    input_csv = geocorr_csv_path if inps.do_geocorr else csv_file_path

    cmd_ogr2ogr, cmd_correctgeo, cmd_hdfeos5, cmd_jsonmbtiles = build_commands(
        shp_file_path, csv_file_path, geocorr_csv_path, json_dir, mbtiles_path, input_csv, inps
    )

    #assign python environment for insarmaps_scripts
    if platform.system() == "Darwin":
       insarmaps_script_env = "insarmaps_scripts"
    else:
       insarmaps_script_env = None


    if inps.make_jobfile:
            print("[INFO] Creating jobfile only, skipping execution.")
            create_jobfile(inps, data_path, (cmd_sarvey_export, cmd_ogr2ogr, cmd_correctgeo, cmd_hdfeos5, cmd_jsonmbtiles), json_dir, output_path, mbtiles_path, dataset_name, metadata)

    else:
        # Step 1: run sarvey_export to  create *.shp file
        if data_path.suffix == ".h5":
            run_command(cmd_sarvey_export, cwd=h5_path.parent.parent, conda_env="sarvey")

        # Step 2: run ogr2ogr to create csv file (FA: is this correct?)
        run_command(cmd_ogr2ogr, conda_env=None)

        # Step 3: geolocation correction
        if inps.do_geocorr:
            run_command(cmd_correctgeo, conda_env = None)

        #update dataset_name from csv bbox and dates
        dataset_name = generate_dataset_name_from_csv(input_csv, sarvey_inputs_dir_path)

        output_suffix = Path(output_path).name.partition("outputs_")[2]

        #replace mbtiles path to reflect final name
        mbtiles_path = json_dir / f"{dataset_name}_{output_suffix}.mbtiles"

        #rename csv to match desired output format
        final_csv_name = f"{dataset_name}_{output_suffix}"
        final_csv_name = final_csv_name.rstrip('_')                       # remove trailing "_" if there is
        final_csv_name += "_geocorr.csv" if inps.do_geocorr else ".csv"
        final_csv_path = output_path / final_csv_name

        #to final format
        shutil.move(input_csv, final_csv_path)
        input_csv = final_csv_path

        #update paths used by downstream steps
        if inps.do_geocorr:
            geocorr_csv_path = input_csv
        else:
            csv_file_path = input_csv

        #rebuild cmd_hdfeos5 and cmd_jsonmbtiles using updated csv name
        _, _, cmd_hdfeos5, cmd_jsonmbtiles = build_commands(
            shp_file_path, csv_file_path, geocorr_csv_path, json_dir, mbtiles_path, input_csv, inps
        )

        # Step 4: run hdfeos5_2_mbtiles.pt to convert csv-file into mbptile.
        run_command(cmd_hdfeos5, conda_env=insarmaps_script_env)
        metadata, _ = extract_metadata_from_inputs(sarvey_inputs_dir_path)
        metadata = update_and_save_final_metadata(json_dir, output_path, dataset_name, metadata, output_suffix)

        # Step 5: run json_mbtiles2insarmaps to ingest data into insarmaps
        if not inps.skip_upload:
            run_command(cmd_jsonmbtiles, conda_env="insarmaps_scripts" if platform.system() == "Darwin" else None)

        #rename MBTiles to match dataset name
        final_mbtiles_name = f"{dataset_name}_{output_suffix}"
        final_mbtiles_name = final_mbtiles_name.rstrip('_')
        final_mbtiles_name = f"{final_mbtiles_name}.mbtiles"
        final_mbtiles_path = json_dir / final_mbtiles_name

        #update mbtiles_path only if the file exists
        if final_mbtiles_path.exists():
            mbtiles_path = final_mbtiles_path
        else:
            #in case tippecanoe output is still p1_ts.mbtiles — fallback check
            default_mbtiles_path = json_dir / "p1_ts.mbtiles"
            if default_mbtiles_path.exists():
                print(f"[INFO] Renaming fallback p1_ts.mbtiles → {final_mbtiles_path.name}")
                shutil.move(default_mbtiles_path, final_mbtiles_path)
                mbtiles_path = final_mbtiles_path
            else:
                raise FileNotFoundError(f"[ERROR] Neither final nor fallback mbtiles found:\n  {final_mbtiles_path}\n  {default_mbtiles_path}")

        #rebuild cmd_jsonmbtiles with updated mbtiles filename
        _, _, _, cmd_jsonmbtiles = build_commands(
            shp_file_path, csv_file_path, geocorr_csv_path, json_dir, mbtiles_path, input_csv, inps
        )

        # Step 6: create insarmaps.log with URL
        host = inps.insarmaps_host.split(",")[0]
        dataset_name_with_suffix = f"{dataset_name}_{output_suffix}"
        dataset_name_with_suffix = dataset_name_with_suffix.rstrip('_')
        url = generate_insarmaps_url(host, dataset_name_with_suffix, metadata, geocorr=inps.do_geocorr)

        with open('insarmaps.log', 'a') as f:
            f.write(url + "\n")
        if os.path.isdir(f"{output_path}/pic"):
            open(f"{output_path}/pic/insarmaps.log", 'a').write(url + "\n")

        # Step 7: create pic/index.html
        run_command(["create_html.py", f"{output_path}/pic"])

        # Step 8: upload to jetstream
        if inps.upload_flag:
            print("\nUploading to Jetstream...")
            run_command(["upload_data_products.py",f"{os.path.dirname(inps.input_file)}"])

        #print the Insarmaps URL and open it in a web browser
        print(f"\nView on Insarmaps:\n{url}")
        if platform.system() == "Darwin":
           webbrowser.open(f"{output_path}/pic/index.html")
        #  webbrowser.open(url)

    print("\nAll done!")

if __name__ == "__main__":
    main()
