#!/usr/bin/env python3
"""
Ingest EGMS L2a CSV (+ optional companion XML) into Insarmaps.

Pipeline:
  EGMS CSV → hdfeos5_or_csv_2json_mbtiles.py → patch metadata.pickle → json_mbtiles2insarmaps.py
"""

from __future__ import annotations

import argparse
import csv
import os
import pickle
import subprocess
import sys
from pathlib import Path

from egms_metadata import build_egms_attributes
from insarmaps_csv_geo import csv_mean_lat_lon

sys.path.insert(0, os.getenv("SSARAHOME") or "")
try:
    import password_config as password
except ImportError:
    password = None


def create_parser():
    parser = argparse.ArgumentParser(
        description="Ingest an EGMS L2a CSV into Insarmaps (JSON/MBTiles + optional upload).",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""\
Examples:
  egms2insarmaps.py /data/HDF5EOS/egmsEtnaSenA44/egms/EGMS_L2a_044_0221_IW2_VV_2020_2024_1.csv
  egms2insarmaps.py EGMS_L2a_044_0221_IW2_VV_2020_2024_1.csv --step 1 --num-workers 1
  egms2insarmaps.py EGMS_L2a_044_0221_IW2_VV_2020_2024_1.csv --step 2
  egms2insarmaps.py EGMS_L2a_044_0221_IW2_VV_2020_2024_1.csv --skip-upload
  egms2insarmaps.py EGMS_L2a_044_0221_IW2_VV_2020_2024_1.csv --flight-direction A --relative-orbit 44 --num-workers 1
""",
    )
    parser.add_argument("csv_file", help="Path to EGMS L2a CSV")
    parser.add_argument(
        "--xml",
        dest="xml_file",
        default=None,
        help="Companion EGMS XML (default: same stem as CSV with .xml)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for JSON chunks and MBTiles (default: <csv_dir>/JSON)",
    )
    parser.add_argument(
        "--num-workers",
        type=int,
        default=1,
        help="Workers for hdfeos5_or_csv_2json_mbtiles.py (default: 1; prefer low for large CSVs)",
    )
    parser.add_argument(
        "--insarmaps-host",
        default=os.environ.get("INSARMAPSHOST") or os.environ.get("INSARMAPS_HOST", "insarmaps.miami.edu"),
        help="Insarmaps host (default: INSARMAPSHOST / INSARMAPS_HOST / insarmaps.miami.edu)",
    )
    parser.add_argument(
        "--step",
        type=int,
        choices=(1, 2),
        default=None,
        help="1 = CSV→JSON/MBTiles + metadata patch only; 2 = upload only (requires prior step 1). Default: both.",
    )
    parser.add_argument(
        "--hdfeos5_2json_mbtiles",
        action="store_true",
        help="Same as --step 1 (CSV→JSON/MBTiles + metadata patch; no upload)",
    )
    parser.add_argument(
        "--json_mbtiles2insarmaps",
        action="store_true",
        help="Same as --step 2 (upload only; assumes step 1 succeeded)",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Same as --step 1 (kept for convenience)",
    )
    parser.add_argument(
        "--flight-direction",
        choices=("A", "D", "ASCENDING", "DESCENDING"),
        default=None,
        help="Orbit sense override (default: from track_angle sample or leave unset)",
    )
    parser.add_argument("--relative-orbit", type=int, default=None, help="Relative orbit override")
    parser.add_argument(
        "--center-line-utc",
        type=int,
        default=None,
        dest="center_line_utc",
        help="CENTER_LINE_UTC override (seconds of day)",
    )
    parser.add_argument("--project-name", default=None, help="PROJECT_NAME (default: CSV stem)")
    parser.add_argument(
        "--post-processing-method",
        default="EGMS",
        help="post_processing_method attribute (default: EGMS)",
    )
    return parser


def resolve_ingest_step(args) -> str:
    """
    Return 'all' | 'step1' | 'step2' from --step / long flags / --skip-upload.

    Matches ingest_insarmaps.bash: step 1 = convert, step 2 = upload, default = both.
    """
    flags = []
    if args.step == 1 or args.hdfeos5_2json_mbtiles or args.skip_upload:
        flags.append("step1")
    if args.step == 2 or args.json_mbtiles2insarmaps:
        flags.append("step2")
    if args.step is not None and args.step not in (1, 2):
        raise ValueError(f"--step must be 1 or 2 (got {args.step})")
    if "step1" in flags and "step2" in flags:
        raise ValueError(
            "Cannot combine step 1 (--step 1, --hdfeos5_2json_mbtiles, --skip-upload) "
            "with step 2 (--step 2, --json_mbtiles2insarmaps)"
        )
    if "step1" in flags:
        return "step1"
    if "step2" in flags:
        return "step2"
    return "all"


def find_mbtiles(output_dir: Path, csv_stem: str) -> Path:
    mbtiles_path = output_dir / f"{csv_stem}.mbtiles"
    if mbtiles_path.is_file():
        return mbtiles_path
    candidates = sorted(output_dir.glob("*.mbtiles"))
    if candidates:
        print(f"[INFO] Using mbtiles: {candidates[0].name}")
        return candidates[0]
    raise FileNotFoundError(
        f"No .mbtiles found under {output_dir} (run --step 1 / --hdfeos5_2json_mbtiles first)"
    )


def run_command(cmd, cwd=None):
    print("[Running]", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, cwd=cwd)


def sample_track_angle(csv_path: Path, max_rows: int = 200) -> float | None:
    """Read a few rows to get a representative track_angle (degrees), if present."""
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "track_angle" not in reader.fieldnames:
            return None
        values = []
        for i, row in enumerate(reader):
            if i >= max_rows:
                break
            raw = row.get("track_angle")
            if raw is None or not str(raw).strip():
                continue
            try:
                values.append(float(raw))
            except ValueError:
                continue
    if not values:
        return None
    return sum(values) / len(values)


def patch_metadata_pickle(json_dir: Path, attrs: dict) -> None:
    """Overwrite/merge EGMS attributes into metadata.pickle (attributes + upload key lists)."""
    pickle_path = json_dir / "metadata.pickle"
    if not pickle_path.exists():
        print(f"[WARN] {pickle_path} not found; skip metadata patch")
        return

    with open(pickle_path, "rb") as f:
        meta = pickle.load(f)

    a = meta.get("attributes", {})
    for k, v in attrs.items():
        a[k] = v

    # Normalize direction keys for Insarmaps title
    raw = str(a.get("flight_direction") or a.get("ORBIT_DIRECTION") or "").strip().upper()
    if raw in ("A", "ASCENDING"):
        short = "A"
    elif raw in ("D", "DESCENDING"):
        short = "D"
    else:
        short = None
    if short:
        a["flight_direction"] = short
        a["orbit_direction"] = short
        a["direction"] = short
        a["ORBIT_DIRECTION"] = short

    keys = list(meta.get("attribute_keys", []))
    vals = list(meta.get("attribute_values", []))
    idx = {k: i for i, k in enumerate(keys)}

    # Prefer updating fields that Insarmaps title / popup care about
    prefer = (
        "relative_orbit",
        "flight_direction",
        "beam_mode",
        "beam_swath",
        "CENTER_LINE_UTC",
        "post_processing_method",
        "mission",
        "wavelength",
        "look_direction",
    )
    for k in prefer:
        if k not in a:
            continue
        v = a[k]
        if k in idx:
            vals[idx[k]] = v
        else:
            keys.append(k)
            vals.append(v)
            idx[k] = len(keys) - 1

    meta["attributes"] = a
    meta["attribute_keys"] = keys
    meta["attribute_values"] = vals
    if attrs.get("PROJECT_NAME"):
        meta["project_name"] = attrs["PROJECT_NAME"]

    with open(pickle_path, "wb") as f:
        pickle.dump(meta, f)
    print(f"[INFO] Patched metadata.pickle with EGMS attributes: {sorted(prefer)}")


def main(argv=None):
    parser = create_parser()
    args = parser.parse_args(argv)
    try:
        ingest_step = resolve_ingest_step(args)
    except ValueError as e:
        parser.error(str(e))

    csv_path = Path(args.csv_file).resolve()
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    xml_path = Path(args.xml_file).resolve() if args.xml_file else csv_path.with_suffix(".xml")
    if not xml_path.is_file():
        print(f"[WARN] Companion XML not found at {xml_path}; using filename/CLI only")
        xml_path = None

    output_dir = Path(args.output_dir).resolve() if args.output_dir else csv_path.parent / "JSON"
    if ingest_step in ("all", "step1"):
        output_dir.mkdir(parents=True, exist_ok=True)
    elif not output_dir.is_dir():
        raise FileNotFoundError(
            f"JSON directory missing (run --step 1 first): {output_dir}"
        )

    print(f"[INFO] Ingest mode: {ingest_step}")

    egms_attrs = None
    if ingest_step in ("all", "step1") or (
        ingest_step == "step2"
        and any(
            v is not None
            for v in (
                args.flight_direction,
                args.relative_orbit,
                args.center_line_utc,
                args.project_name,
            )
        )
    ):
        track_angle = sample_track_angle(csv_path) if ingest_step != "step2" else None
        if track_angle is not None:
            print(f"[INFO] Sampled mean track_angle ≈ {track_angle:.2f}°")

        egms_attrs = build_egms_attributes(
            csv_path,
            xml_path,
            flight_direction=args.flight_direction,
            relative_orbit=args.relative_orbit,
            center_line_utc=args.center_line_utc,
            project_name=args.project_name,
            post_processing_method=args.post_processing_method,
            track_angle=track_angle,
        )
        if "flight_direction" not in egms_attrs and args.flight_direction is None:
            egms_attrs["flight_direction"] = "A"
            egms_attrs["ORBIT_DIRECTION"] = "A"
            print("[INFO] flight_direction defaulted to A (override with --flight-direction)")
        print("[INFO] EGMS attributes:", {k: egms_attrs[k] for k in sorted(egms_attrs)})

    if ingest_step in ("all", "step1"):
        run_command(
            [
                "hdfeos5_or_csv_2json_mbtiles.py",
                str(csv_path),
                str(output_dir),
                "--num-workers",
                str(args.num_workers),
            ]
        )
        patch_metadata_pickle(output_dir, egms_attrs)

    mbtiles_path = find_mbtiles(output_dir, csv_path.stem)
    if not (output_dir / "metadata.pickle").is_file() and ingest_step == "step2":
        raise FileNotFoundError(
            f"metadata.pickle missing (run --step 1 first): {output_dir / 'metadata.pickle'}"
        )

    if egms_attrs is not None and ingest_step == "step2":
        patch_metadata_pickle(output_dir, egms_attrs)

    if ingest_step in ("all", "step2"):
        if password is None:
            raise RuntimeError("password_config not available (SSARAHOME); cannot upload")
        host = args.insarmaps_host.split(",")[0]
        run_command(
            [
                "json_mbtiles2insarmaps.py",
                "--num-workers",
                "3",
                "-u",
                password.docker_insaruser,
                "-p",
                password.docker_insarpass,
                "--host",
                host,
                "-P",
                password.docker_databasepass,
                "-U",
                password.docker_databaseuser,
                "--json_folder",
                str(output_dir),
                "--mbtiles_file",
                str(mbtiles_path),
            ]
        )
    else:
        print("[INFO] Skipping upload (step 1 only)")

    try:
        lat, lon = csv_mean_lat_lon(csv_path)
    except Exception as e:
        print(f"[WARN] Could not compute map center from CSV: {e}")
        lat, lon = 0.0, 0.0
    dataset_name = csv_path.stem
    host = args.insarmaps_host.split(",")[0]
    protocol = "https" if host.startswith("insarmaps.miami.edu") else "http"
    url = (
        f"{protocol}://{host}/start/{lat:.4f}/{lon:.4f}/11.0"
        f"?flyToDatasetCenter=true&startDataset={dataset_name}"
    )
    print(f"\nView on Insarmaps:\n{url}")
    log_path = csv_path.parent / "insarmaps.log"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(url + "\n")
    print(f"[INFO] Appended URL to {log_path}")


if __name__ == "__main__":
    main()
