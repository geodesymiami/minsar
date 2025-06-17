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
import webbrowser
import sys

sys.path.insert(0, os.getenv("SSARAHOME"))
import password_config as password


def create_parser():
    parser = argparse.ArgumentParser(
        description="End-to-end pipeline for: SARvey shapefiles -> CSV -> JSON -> MBTiles -> Insarmaps",
        epilog="""\
    Examples:

               Masjed dam (sarvey example)
        sarvey2insarmaps.py outputs/p2_coh80_ts.h5
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

    # FA: There are packages to read json format
    if config_json_path and config_json_path.exists():
        print(f"Using config file: {config_json_path}")
        with open(config_json_path) as f:
            config_text = f.read()
            config_text = re.sub(r"(?<![\w\"])(\w+) *:", r'"\1":', config_text)
            config_text = re.sub(r",\s*([\]}])", r"\1", config_text)
            config_data = json.loads(config_text)

        try:
            inputs_path = Path(config_data["general"]["input_path"]).resolve()
            print(f"Inputs path set from config.json: {inputs_path}")
        except (KeyError, TypeError):
            inputs_path = Path("inputs").resolve()
            print("'input_path' not found in config.json. Defaulting to ./inputs/")
    elif inps.input_file:
        inputs_path = Path(inps.input_file).resolve().parents[1] / "inputs"
        print(f"Using inferred inputs path: {inputs_path}")
    else:
        raise ValueError("Must provide either --input_file or a valid config.json.")

    return inputs_path


def set_output_paths(shp_path, dataset_name, do_geocorr):
    """
    Create output directories and return key paths.
    Returns: csv_path, geocorr_csv, json_dir, mbtiles_path, outdir, base_dir
    """
    base_dir = shp_path.parent.parent.resolve()
    outputs_dir = base_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    dir_suffix = base_dir.name.split("_")[-1] if "_" in base_dir.name else ""
    if dir_suffix:
       dataset_name = dataset_name + f"_{dir_suffix}"

    #FA: Why to create a new directory? My preference would be to have everything in outputs
    outdir = outputs_dir / "output_csv"
    outdir.mkdir(parents=True, exist_ok=True)
    csv_path = outdir / f"{dataset_name}.csv"
    geocorr_csv = outdir / f"{dataset_name}_geocorr.csv"

    json_dir = outputs_dir / "JSON"
    json_dir.mkdir(parents=True, exist_ok=True)
    mbtiles_name = f"{dataset_name}_geocorr.mbtiles" if do_geocorr else f"{dataset_name}.mbtiles"
    mbtiles_path = json_dir / mbtiles_name

    return csv_path, geocorr_csv, json_dir, mbtiles_path, outdir, base_dir

def build_commands(shp_path, csv_path, geocorr_csv, json_dir, mbtiles_path, input_csv, inps):
    """
    Build the list of shell command sequences for the SARvey-to-Insarmaps pipeline.

    Returns four commands:
        cmd1 - Convert SHP to CSV using ogr2ogr with WGS84 coordinates.
        cmd2 - Apply geolocation correction using correct_geolocation.py (if --geocorr).
        cmd3 - Convert CSV or HDF5 to JSON and MBTiles format using hdfeos5_or_csv_2json_mbtiles.py.
        cmd4 - Upload MBTiles and JSON data to the Insarmaps server using json_mbtiles2insarmaps.py.
    """
    cmd_ogr2ogr = ["ogr2ogr", "-f", "CSV", "-lco", "GEOMETRY=AS_XY", "-t_srs", "EPSG:4326", str(csv_path), str(shp_path)]
    cmd_correctgeo = ["correct_geolocation.py", str(csv_path), "--outfile", str(geocorr_csv)]
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


def extract_metadata_from_inputs(inputs_path):
    """
    Extract essential metadata from slcStack.h5 and geometryRadar.h5 to generate a dataset name.
    Returns a dict of metadata and a created dataset name string based on platform, dates, and bbox.
    """
    attributes = {}
    dataset_name = None

    slc_path = inputs_path / "slcStack.h5"
    geom_path = inputs_path / "geometryRadar.h5"

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
    print(f"[INFO] dataset name: {dataset_name}")

    return attributes, dataset_name

def update_and_save_final_metadata(json_dir, outdir, dataset_name, metadata):
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

    final_meta_path = outdir / f"{dataset_name}_final_metadata.json"
    with open(final_meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"[INFO] Final metadata written to: {final_meta_path}")

    return metadata

def get_data_footprint(metadata):
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
    lat, lon = get_data_footprint(metadata)
    protocol = "https" if host.startswith("insarmaps.miami.edu") else "http"
    suffix = "_geocorr" if geocorr else ""
    return f"{protocol}://{host}/start/{lat:.4f}/{lon:.4f}/11.0?flyToDatasetCenter=true&startDataset={dataset_name}{suffix}"

def run_command(command, shell=False, conda_env=None, cwd=None):
    """
    Execute a shell command and print the command string.
    """
    # FA: is command always a list? If not this function may need modification

    prefix = []
    if conda_env:
        prefix = ["conda", "run", "-n", conda_env, "--no-capture-output"]

    full_cmd = prefix + command

    # replace abosolute by relative paths for display
    cmd_for_display = convert_to_relative_path(full_cmd, cwd=cwd or os.getcwd())
    cmd_str_for_display = ' '.join(cmd_for_display) if isinstance(cmd_for_display, list) else cmd_for_display
    print(f"##########################\nRunning (displaying relative paths)....\n{cmd_str_for_display}\n")

    try:
        subprocess.run(full_cmd, check=True, shell=shell, cwd=str(cwd) if cwd else None)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Command failed with return code {e.returncode}: {cmd_str}")
        raise

    # assemble the full command
    if shell:
        # with shell=True we pass a single string
        full_cmd = prefix + [command]
    else:
        # if it's a string, split it, otherwise assume it's already a list
        parts = shlex.split(command) if isinstance(command, str) else list(command)
        full_cmd = prefix + parts

    print("Running:", full_cmd)
    subprocess.run(full_cmd, check=True, shell=shell, cwd=cwd)


def convert_to_relative_path(cmd_list, cwd=None):
    """
    Return a list where any element that lives under cwd is replaced by its relative path.
    """
    # make sure cwd is a string
    cwd = str(cwd or os.getcwd())
    rel = []
    for token in cmd_list:
        # only rewrite absolute paths under cwd
        if os.path.isabs(token) and token.startswith(cwd + os.sep):
            rel.append(os.path.relpath(token, cwd))
        else:
            rel.append(token)
    return rel


def create_jobfile(inps, input_path, cmds, json_dir, base_dir, mbtiles_path, dataset_name, metadata):
    """
    Generate a SLURM-compatible jobfile with all processing steps and Insarmaps URL.
    """
    # FA these command names are not useful. Use cmd_sarvey_export and similar
    cmd0, cmd1, cmd2, cmd3, cmd4 = cmds
    # FA: confusing that a jobfile_path ends with *.log ???
    jobfile_path = base_dir / "sarvey2insarmaps.log"
    slurm_commands = []

    if input_path.suffix == ".h5":
        slurm_commands.append(" ".join(cmd0))

    slurm_commands.append(" ".join(cmd1))

    if inps.do_geocorr:
        slurm_commands.append(" ".join(cmd2))

    host = inps.insarmaps_host.split(",")[0]
    slurm_commands.extend([
        f"rm -rf {json_dir}",
        " ".join(cmd3),
        " ".join(cmd4).replace(inps.insarmaps_host, "insarmaps.miami.edu") + " &",
        " ".join(cmd4).replace(inps.insarmaps_host, host) + " &"
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

        f.write(f"cat >> insarmaps.log<<EOF\n{url_1}\nEOF\n\n")
        f.write(f"cat >> insarmaps.log<<EOF\n{url_2}\nEOF\n\n")

    print(f"\nJobfile created: {jobfile_path}")

def main():
    parser = create_parser()
    inps = parser.parse_args()
    print(f"Geolocation correction enabled: {inps.do_geocorr}")

    inputs_path = load_config_and_input_path(inps)

    #ensure required files exist
    required_files = ["slcStack.h5", "geometryRadar.h5"]
    for fname in required_files:
        fpath = inputs_path / fname
        if not fpath.exists():
            raise FileNotFoundError(f"Required file not found: {fpath}")

    metadata, dataset_name = extract_metadata_from_inputs(inputs_path)

    if not metadata:
        print("[WARN] No metadata found in slcStack.h5 or geometryRadar.h5.")

    #use $RSMASINSAR_HOME as the root for now (temporarily)
    # FA if you really need an environment variable use variable name RSMASINSAR_HOME
    rsmasinsar_env = os.environ.get("RSMASINSAR_HOME")
    if not rsmasinsar_env:
        raise EnvironmentError("Environment variable RSMASINSAR_HOME is not set.")

    #input/output paths
    # FA: That this is not in build_commands is confusing. If you can't put it there create your own functions
    # FA: input_path is not a good name as it maye contain the string output. Use data_path or similar
    input_path = Path(inps.input_file).resolve()
    if input_path.suffix == ".h5":
        h5_path = input_path
        shp_path = h5_path.parent / "shp" / f"{h5_path.stem}.shp"
        print(f"[INFO] Input is HDF5. Inferred shapefile path: {shp_path}")
        #step0: always run sarvey_export if input is HDF5
        # FA: This is a complicated function. You are dealing with environments, so we need "env" in the function name.
        # FA: You can use CONDA_PREFIX to determine in which environemnt we are.
        sarvey_export_path = get_sarvey_export_path()
        cmd_sarvey_export = [sarvey_export_path, str(h5_path), "-o", str(shp_path)]
        if inps.sarvey_geocorr:
            print("[INFO] Applying SARvey geolocation correction")
            cmd_sarvey_export.append("--correct_geo")
    else:
        shp_path = input_path
        h5_path = shp_path.with_suffix(".h5")
        print(f"[INFO] Input is SHP. Inferred HDF5 path: {h5_path}")

    # FA this section is important while the above is just dealing with filenames/options. This should be optically emphasized with comment signs and text
    # FA: unclear what geocorr_csv is. A file path? then sat it as you do for the others. Same for input_csv below. So it would be csv_file_path, shp_file_path ?
    csv_path, geocorr_csv, json_dir, mbtiles_path, outdir, base_dir = set_output_paths(shp_path, dataset_name, inps.do_geocorr)

    input_csv = geocorr_csv if inps.do_geocorr else csv_path
    cmd_ogr2ogr, cmd_correctgeo, cmd_hdfeos5, cmd_jsonmbtiles = build_commands(
        shp_path, csv_path, geocorr_csv, json_dir, mbtiles_path, input_csv, inps
    )

    # assign python environment for insarmaps_scripts
    if platform.system() == "Darwin":
       insarmaps_script_env = "insarmaps_scripts"
    else:
       insarmaps_script_env = None

    # FA an if ...: else ....: is better than return
    if inps.make_jobfile:
            print("[INFO] Creating jobfile only, skipping execution.")
            create_jobfile(inps, input_path, (cmd0, cmd_ogr2ogr, cmd_correctgeo, cmd_hdfeos5, cmd_jsonmbtiles), json_dir, base_dir, mbtiles_path, dataset_name, metadata)
            return

    #FA the h5_path.parent.parent looks weired. Do you need parent twice? Maybe it is correct. I don't know.
    # FA: why checking for *.h5? What are otehr options? If not *.h5 does next step still work?

    # Step 1: run sarvey_export to  create *.shp file
    if input_path.suffix == ".h5":
        run_command(cmd_sarvey_export, cwd=h5_path.parent.parent, conda_env="sarvey")

    # Step 2: run ogr2ogr to create csv file (FA: is this correct?)
    run_command(cmd_ogr2ogr, conda_env=None)

    # Step 3: geolocation correction
    if inps.do_geocorr:
        run_command(cmd_correctgeo, conda_env = None)


    # Step 4: run hdfeos5_2_mbtiles.pt to convert csv-file into mbptile.
    run_command(cmd_hdfeos5, conda_env=insarmaps_script_env)
    metadata = update_and_save_final_metadata(json_dir, outdir, dataset_name, metadata)

    # Step 5: run json_mbtiles2insarmaps to ingest data into website
    if not inps.skip_upload:
        run_command(cmd_jsonmbtiles, conda_env="insarmaps_scripts" if platform.system() == "Darwin" else None)

    # FA: may want to create an insarmaps.log to be consistent with MintPy and miaplpy
    host = inps.insarmaps_host.split(",")[0]
    url = generate_insarmaps_url(host, dataset_name, metadata, geocorr=inps.do_geocorr)

    with open('insarmaps.log', 'a') as f:
        f.write(url + "\n")

    if os.path.isdir(f"outdir/pic"):
       open(f"{outdir}/pic/insarmaps.log", 'a').write(url + "\n")

    print(f"\nView on Insarmaps:\n{url}")
    if platform.system() == "Darwin":
       webbrowser.open(url)

    print("\nAll done!")

if __name__ == "__main__":
    main()
