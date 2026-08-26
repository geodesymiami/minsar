#!/usr/bin/env python3

import argparse
from netCDF4 import Dataset
from pathlib import Path
from glob import glob
import yaml
from rich.console import Console

console = Console()

parser = argparse.ArgumentParser(
    description="Read the OPERA Dolphin config from a NetCDF file and pretty print it."
)
parser.add_argument(
    "--all-parameters", "-ap",
    action="store_true",
    help="Pretty print the full parsed configuration instead of only the important parameters.",
)
args = parser.parse_args()

# -----------------------------
# 1. Find file
# -----------------------------
path = Path.cwd() / "OPERA_L3_DISP-S1*.nc"
nc_file = glob(str(path))[0]

print(f"Reading {nc_file}")

# -----------------------------
# 2. Open NetCDF
# -----------------------------
nc = Dataset(nc_file)

raw = nc["metadata"]["algorithm_parameters_yaml"][:]

# Handle bytes vs string safely
yaml_text = raw.decode() if isinstance(raw, bytes) else raw

# -----------------------------
# 3. Parse YAML
# -----------------------------
config = yaml.safe_load(yaml_text)

# -----------------------------
# 4. Define IMPORTANT parameters only
# -----------------------------
KEYS = {
    "ps_options": [
        "amp_dispersion_threshold",
    ],

    "phase_linking": [
        "ministack_size",
        "max_num_compressed",
        "use_evd",
        "beta",
        "zero_correlation_threshold",
        "shp_method",
        "shp_alpha",
        "mask_input_ps",
    ],

    "interferogram_network": [
        "max_bandwidth",
        "max_temporal_baseline",
        "reference_idx",
    ],

    "unwrap_options": [
        "unwrap_method",
        "run_goldstein",
        "run_interpolation",
    ],

    "snaphu_options": [
        "cost",
        "init_method",
        "ntiles",
        "tile_overlap",
        "single_tile_reoptimize",
    ],

    "preprocess_options": [
        "alpha",
        "interpolation_cor_threshold",
        "interpolation_similarity_threshold",
    ],

    "timeseries_options": [
        "correlation_threshold",
        "method",
        "run_inversion",
    ],

    "spatial_wavelength_cutoff": None,
}

# -----------------------------
# 5. Filter function
# -----------------------------
def extract_important(cfg, keys):
    out = {}

    for section, fields in keys.items():

        # top-level parameter (not nested)
        if fields is None:
            if section in cfg:
                out[section] = cfg[section]
            continue

        # nested section
        if section not in cfg:
            continue

        out[section] = {}
        for f in fields:
            if f in cfg[section]:
                out[section][f] = cfg[section][f]

    return out


filtered = extract_important(config, KEYS)

# -----------------------------
# 6. Pretty print
# -----------------------------
if args.all_parameters:
    console.print("\n[bold cyan]ALL PARAMETERS[/bold cyan]\n")
    console.print(yaml.dump(config, sort_keys=False))
else:
    console.print("\n[bold cyan]IMPORTANT PARAMETERS ONLY[/bold cyan]\n")
    console.print(yaml.dump(filtered, sort_keys=False))