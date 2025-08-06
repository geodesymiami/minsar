#!/usr/bin/env python3

import argparse
from pathlib import Path
import pandas as pd
from tqdm import tqdm
import os
import re
import subprocess
import json
import shutil
import platform
from datetime import date

import sys
sys.path.insert(0, os.getenv("SSARAHOME"))
import password_config as password


REQUIRED_COLS = {"X", "Y"}

def parse_args():
    parser = argparse.ArgumentParser(description="Concatenate multiple CSV files and ingest into Insarmaps.")
    parser.add_argument("--input-dir", type=str, required=True, help="Directory containing CSVs to concatenate.")
    parser.add_argument("--output-dir", type=str, default="outputs/", help="Directory to write outputs.")
    parser.add_argument("--drop-duplicates", action="store_true", help="Drop duplicates based on (X, Y).")
    parser.add_argument("--suffix", type=str, default=None, help="Suffix for final CSV filename (default: input folder name).")
    parser.add_argument("--insarmaps-host", type=str, default=os.environ.get("INSARMAPS_HOST", "insarmaps.miami.edu"), help="Insarmaps host")
    parser.add_argument("--skip-upload", action="store_true", help="Skip Insarmaps upload step")
    return parser.parse_args()

def load_csvs(csv_files):
    #dataframes=dfs
    dfs = []
    for f in tqdm(csv_files, desc="Reading CSVs"):
        df = pd.read_csv(f)
        if not REQUIRED_COLS.issubset(df.columns):
            raise ValueError(f"Missing required columns in {f.name}")
        dfs.append(df)
    return dfs

def get_shared_date_columns(dfs):
    common_cols = set(dfs[0].columns)
    for df in dfs[1:]:
        common_cols &= set(df.columns)
    return sorted([col for col in common_cols if re.match(r"^D20\d{6}$", col)])

def clean_and_concatenate(dfs, date_cols, drop_duplicates):
    core_cols = ["X", "Y"] + [c for c in dfs[0].columns if not c.startswith("D20") and c not in ["X", "Y"]]
    dfs = [df[core_cols + date_cols] for df in dfs]
    df = pd.concat(dfs, ignore_index=True)

    if drop_duplicates:
        before = len(df)
        df.drop_duplicates(subset=["X", "Y"], inplace=True)
        print(f"[INFO] Dropped {before - len(df)} duplicate points based on (X, Y).")

    valid_obs = df[date_cols].notna().sum(axis=1)
    df = df[valid_obs >= 2].copy()
    print(f"[INFO] Kept {len(df)} rows with ≥2 valid observations.")

    valid_obs = df[date_cols].notna().sum(axis=1)
    df = df[valid_obs >= 5].copy()
    print(f"[INFO] Kept {len(df)} rows with ≥5 time series entries.")

    flat_std = df[date_cols].std(axis=1)
    df = df[~(flat_std.isna() | (flat_std == 0))].copy()
    print(f"[INFO] Removed rows with flat or constant time series.")

    return df

def extract_platform_orbit_from_filenames(csv_files):
    """
    Extract the platform and orbit from a list of filenames.
    Assuming filenames follow the convention: <platform>_<orbit>_YYYYMMDD_...
    """
    platforms = set()
    orbits = set()

    for csv_file in csv_files:
        match = re.match(r"([A-Z]+)_(\d{3})_", Path(csv_file).name)
        if match:
            platform, orbit = match.groups()
            platforms.add(platform)
            orbits.add(orbit)
        else:
            raise ValueError(f"Filename format not recognized: {csv_file}")

    if len(platforms) > 1 or len(orbits) > 1:
        raise ValueError(f"Inconsistent platform or orbit across files:\n  Platforms: {platforms}\n  Orbits: {orbits}")

    return platforms.pop(), orbits.pop()

def generate_filename_from_csv(df, date_cols, csv_files, suffix="data"):
    time_cols = sorted([col[1:] for col in date_cols])
    start_date = time_cols[0]
    end_date = time_cols[-1]

    min_lat, max_lat = df["Y"].min(), df["Y"].max()
    min_lon, max_lon = df["X"].min(), df["X"].max()

    lat1 = f"N{int(min_lat * 10000):05d}"
    lat2 = f"N{int(max_lat * 10000):05d}"
    lon1 = f"W{abs(int(max_lon * 10000)):06d}"
    lon2 = f"W{abs(int(min_lon * 10000)):06d}"

    platform, orbit = extract_platform_orbit_from_filenames(csv_files)
    return f"{platform}_{orbit}_{start_date}_{end_date}_{lat1}_{lat2}_{lon1}_{lon2}_{suffix}.csv"

def run_command(cmd, cwd=None):
    print("[Running]", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, cwd=cwd)

def ingest_to_insarmaps(csv_path, output_dir, insarmaps_host, skip_upload):
    json_dir = Path(output_dir) / "JSON"
    json_dir.mkdir(parents=True, exist_ok=True)
    mbtiles_path = json_dir / csv_path.with_suffix(".mbtiles").name

    run_command(["hdfeos5_or_csv_2json_mbtiles.py", str(csv_path), str(json_dir)])

    if not skip_upload:
        run_command([
            "json_mbtiles2insarmaps.py",
            "--num-workers", "3",
            "-u", password.docker_insaruser,
            "-p", password.docker_insarpass,
            "--host", insarmaps_host,
            "-P", password.docker_databasepass,
            "-U", password.docker_databaseuser,
            "--json_folder", str(json_dir),
            "--mbtiles_file", str(mbtiles_path)
        ])

    #print Insarmaps URL
    df = pd.read_csv(csv_path)
    lat = df["Y"].mean()
    lon = df["X"].mean()
    dataset_name = csv_path.stem
    print(f"[INFO] View in Insarmaps: http://{insarmaps_host}/start/{lat:.4f}/{lon:.4f}/11.0?startDataset={dataset_name}")


def main():
    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(input_dir.glob("*.csv"))
    if not csv_files:
        print("[WARN] No CSV files found.")
        return

    dfs = load_csvs(csv_files)
    date_cols = get_shared_date_columns(dfs)
    print(f"[INFO] Using {len(date_cols)} shared time series columns.")

    df = clean_and_concatenate(dfs, date_cols, args.drop_duplicates)

    suffix = args.suffix or input_dir.name
    output_filename = generate_filename_from_csv(df, date_cols, csv_files, suffix)
    final_path = output_dir / output_filename

    df.to_csv(final_path, index=False)
    print(f"[INFO] Final CSV saved to: {final_path}")

    ingest_to_insarmaps(final_path, output_dir, args.insarmaps_host, args.skip_upload)

if __name__ == "__main__":
    main()

