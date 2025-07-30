#!/usr/bin/env python3

import argparse
from pathlib import Path
import pandas as pd
from tqdm import tqdm

REQUIRED_COLS = {"X", "Y"}

def parse_args():
    parser = argparse.ArgumentParser(description="Concatenate multiple CSV files with optional deduplication.")
    parser.add_argument("--input-dir", type=str, required=True, help="Path to the folder containing input CSVs.")
    parser.add_argument("--output", type=str, required=True, help="Output CSV filename.")
    parser.add_argument("--filename-pattern", type=str, default="*.csv", help="Glob pattern to match input files.")
    parser.add_argument("--drop-duplicates", action="store_true", help="Drop duplicates based on (X, Y) coordinates.")
    return parser.parse_args()

def load_csvs(csv_files):
    dataframes = []
    for file in tqdm(csv_files, desc="Reading CSVs"):
        df = pd.read_csv(file)
        if not REQUIRED_COLS.issubset(df.columns):
            raise ValueError(f"Missing required columns {REQUIRED_COLS - set(df.columns)} in {file.name}")
        dataframes.append(df)
    return dataframes

def get_shared_date_columns(dfs):
    common_cols = set(dfs[0].columns)
    for df in dfs[1:]:
        common_cols &= set(df.columns)
    return sorted([col for col in common_cols if col.startswith("D20")])

def clean_and_concatenate(dfs, date_cols, drop_duplicates):
    core_cols = ["X", "Y"] + [c for c in dfs[0].columns if not c.startswith("D20") and c not in ["X", "Y"]]
    dfs = [df[core_cols + date_cols] for df in dfs]
    df = pd.concat(dfs, ignore_index=True)

    if drop_duplicates:
        before = len(df)
        df.drop_duplicates(subset=["X", "Y"], inplace=True)
        print(f"[INFO] Dropped {before - len(df)} duplicate points based on (X, Y).")

    valid_obs = df[date_cols].notna().sum(axis=1)
    before = len(df)
    df = df[valid_obs >= 2].copy()
    print(f"[INFO] Removed {before - len(df)} rows with fewer than 2 valid observations.")

    before = len(df)
    df = df[valid_obs >= 5].copy()
    print(f"[INFO Removed {before - len(df)} rows with fewer than 5 valid time series entries.")

    flat_std = df[date_cols].std(axis=1)
    flat = flat_std.isna() | (flat_std == 0)
    num_flat = flat.sum()
    df = df[~flat]
    print(f"[INFO] Removed {num_flat} rows with constant or flat time series.")

    return df

def save_csv(df, output_path):
    df.to_csv(output_path, index=False)
    print(f"[INFO] Final CSV saved to: {output_path}")
    print(f"[INFO] Total points: {len(df)}")

def main():
    args = parse_args()
    input_dir = Path(args.input_dir)
    csv_files = sorted(input_dir.glob(args.filename_pattern))
    if not csv_files:
        print("[WARN] No CSV files found.")
        return

    dfs = load_csvs(csv_files)
    date_cols = get_shared_date_columns(dfs)
    print(f"[INFO] Using {len(date_cols)} shared time series columns.")
    df = clean_and_concatenate(dfs, date_cols, args.drop_duplicates)
    save_csv(df, input_dir / args.output)

if __name__ == "__main__":
    main()

