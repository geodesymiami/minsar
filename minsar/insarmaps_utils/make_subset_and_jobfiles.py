#!/usr/bin/env python3
"""
make_subset_and_jobfiles.py

Automate SARvey subsetting + config + sbatch jobfile creation.

Example usage from project(miaplpy) root (which contains ./inputs):

    make_subset_and_jobfiles.py \
        --subset \
        --make-config \
        --make-sbatch \
        --lat 25.787 25.765 \
        --lon -80.146 -80.127 \
        --outdir MiamiBeach1 \
        --num-cores 48 \
        --partition skx-dev (or nvdimm) \
        --time 1:59:00 \
        --mail-user your-email@gmail.com
"""

import argparse
import subprocess
from pathlib import Path
import sys
import re


# ----------------------------------------------------------------------
# Step 1: Subsetting
# ----------------------------------------------------------------------
def run_subset(
    project_root: Path,
    lat: list[float],
    lon: list[float],
    outdir: Path,
    inputs_dirname: str = "inputs",
    slc_name: str = "slcStack.h5",
    geom_name: str = "geometryRadar.h5",
    subset_script: str = "subset.py",
) -> None:
    """
    Run subset.py on slcStack.h5 and geometryRadar.h5 inside ./inputs,
    then move the sub_* outputs into outdir/inputs as slcStack.h5 and
    geometryRadar.h5.

    Parameters
    ----------
    project_root : Path
        Directory where to run the script (contains 'inputs').
    lat : [lat1, lat2]
        Latitude bounds.
    lon : [lon1, lon2]
        Longitude bounds.
    outdir : Path
        Name/path of the new subset directory (relative or absolute).
    inputs_dirname : str
        Name of the inputs directory in project_root.
    slc_name : str
        Filename of original slcStack.
    geom_name : str
        Filename of original geometry file.
    subset_script : str
        Name (or path) of subset.py executable.
    """
    inputs_dir = project_root / inputs_dirname
    if not inputs_dir.is_dir():
        raise FileNotFoundError(f"Inputs directory not found: {inputs_dir}")

    slc_file = inputs_dir / slc_name
    geom_file = inputs_dir / geom_name

    if not slc_file.is_file():
        raise FileNotFoundError(f"Cannot find {slc_file}")
    if not geom_file.is_file():
        raise FileNotFoundError(f"Cannot find {geom_file}")

    # Paths that subset.py will produce inside inputs/
    sub_slc = inputs_dir / "sub_slcStack.h5"
    sub_geom = inputs_dir / "sub_geometryRadar.h5"

    # Build subset.py command
    cmd = [
        subset_script,
        slc_name,
        geom_name,
        "--lookup", geom_name,
        "--lat", str(lat[0]), str(lat[1]),
        "--lon", str(lon[0]), str(lon[1]),
    ]

    print("\n[INFO] Project root:", project_root)
    print("[INFO] Inputs dir   :", inputs_dir)
    print("[INFO] Running subset.py as:")
    print("       " + " ".join(cmd))

    # Run subset.py inside inputs/ so it finds the files by name
    try:
        subprocess.run(cmd, check=True, cwd=inputs_dir)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] subset.py failed with return code {e.returncode}", file=sys.stderr)
        sys.exit(e.returncode)

    # Check outputs
    if not sub_slc.is_file():
        raise FileNotFoundError(f"Expected subset output not found: {sub_slc}")
    if not sub_geom.is_file():
        raise FileNotFoundError(f"Expected subset output not found: {sub_geom}")

    # Check outputs
    if not sub_slc.is_file():
        raise FileNotFoundError(f"Expected subset output not found: {sub_slc}")
    if not sub_geom.is_file():
        raise FileNotFoundError(f"Expected subset output not found: {sub_geom}")

    # Create outdir/inputs
    target_root = outdir.resolve()
    target_inputs = target_root / inputs_dirname
    print("\n[INFO] Creating subset directory:", target_inputs)
    target_inputs.mkdir(parents=True, exist_ok=True)

    # Target filenames
    target_slc = target_inputs / slc_name
    target_geom = target_inputs / geom_name

    # Safety check to avoid overwriting
    for t in (target_slc, target_geom):
        if t.exists():
            raise FileExistsError(
                f"Target file already exists: {t}\n"
                f"Refusing to overwrite. Remove it or choose a different --outdir."
            )

    # Move and rename
    print(f"[INFO] Moving {sub_slc} → {target_slc}")
    sub_slc.rename(target_slc)

    print(f"[INFO] Moving {sub_geom} → {target_geom}")
    sub_geom.rename(target_geom)

    print("\n[INFO] Subset created successfully.")
    print(f"[INFO] New subset project: {target_root}")
    print(f"[INFO] Subset inputs     : {target_inputs}")


# ----------------------------------------------------------------------
# Step 2: Config generation / modification
# ----------------------------------------------------------------------
def make_config_from_template(
    template_path: Path,
    subset_root: Path,
    config_name: str = "config.json",
    num_cores: int | None = None,
    num_patches: int | None = None,
) -> Path:
    """
    Copy a SARvey config template into the subset directory and optionally
    modify num_cores and num_patches.

    The template is assumed to be SARvey's "JSON-like" format
    (keys without quotes, trailing commas, etc.), so we do simple
    text substitutions rather than strict JSON parsing.
    """
    if not template_path.is_file():
        raise FileNotFoundError(f"Config template not found: {template_path}")

    subset_root.mkdir(parents=True, exist_ok=True)
    target_cfg = subset_root / config_name

    text = template_path.read_text()

    if num_cores is not None:
        # Replace the first occurrence of num_cores: <int>
        text, n = re.subn(
            r"(num_cores:\s*)(\d+)",
            rf"\g<1>{num_cores}",
            text,
            count=1,
        )
        if n == 0:
            print("[WARN] num_cores field not found in template; no change applied.")

    if num_patches is not None:
        text, n = re.subn(
            r"(num_patches:\s*)(\d+)",
            rf"\g<1>{num_patches}",
            text,
            count=1,
        )
        if n == 0:
            print("[WARN] num_patches field not found in template; no change applied.")

    target_cfg.write_text(text)
    print(f"[INFO] Wrote config to {target_cfg}")

    return target_cfg


# ----------------------------------------------------------------------
# Step 3: SBATCH job file
# ----------------------------------------------------------------------
def make_sbatch_job(
    subset_root: Path,
    sbatch_name: str = "sarvey.job",
    job_name: str | None = None,
    account: str = "TG-EAR200012",
    mail_user: str | None = None,
    mail_type: str = "fail",
    nodes: int = 1,
    ntasks: int = 48,
    partition: str = "skx-dev",
    time: str = "1:59:00",
    conda_env: str = "minsar",
    config_name: str = "config.json",
) -> Path:
    """
    Write a SLURM sbatch jobfile to run SARvey on this subset.
    """
    subset_root = subset_root.resolve()
    subset_root.mkdir(parents=True, exist_ok=True)
    job_path = subset_root / sbatch_name

    if job_name is None:
        job_name = f"sarvey_{subset_root.name}"

    out_log = subset_root / "sarvey_%J.o"
    err_log = subset_root / "sarvey_%J.e"

    lines = [
        "#! /bin/bash",
        f"#SBATCH -J {job_name}",
        f"#SBATCH -A {account}",
    ]

    if mail_user:
        lines.append(f"#SBATCH --mail-user={mail_user}")
        lines.append(f"#SBATCH --mail-type={mail_type}")

    lines.extend(
        [
            f"#SBATCH -N {nodes}",
            f"#SBATCH -n {ntasks}",
            f"#SBATCH -o {out_log}",
            f"#SBATCH -e {err_log}",
            f"#SBATCH -p {partition}",
            f"#SBATCH -t {time}",
            "",
            "echo \"[INFO] Hostname: $(hostname)\"",
            "echo \"[INFO] Starting SARvey job at: $(date)\"",
            "",
            "# Load environment if needed and activate conda env",
            "source ~/.bashrc  # adjust if your conda init is elsewhere",
            f"conda activate {conda_env}",
            "",
            f"cd {subset_root}",
            f"echo \"[INFO] Working directory: $(pwd)\"",
            "",
            f"sarvey -f {config_name} 0 2",
            "echo \"[INFO] SARvey finished at: $(date)\"",
            "",
        ]
    )

    job_path.write_text("\n".join(lines))
    print(f"[INFO] Wrote sbatch jobfile to {job_path}")

    return job_path


# ----------------------------------------------------------------------
# Argument parsing and main
# ----------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create SARvey subsets and related jobfiles."
    )

    # --- subsetting ---
    parser.add_argument(
        "--subset",
        action="store_true",
        help="Run subsetting step to create a new subset project.",
    )

    parser.add_argument(
        "--lat",
        nargs=2,
        type=float,
        metavar=("LAT1", "LAT2"),
        help="Latitude bounds passed to subset.py (two numbers).",
    )

    parser.add_argument(
        "--lon",
        nargs=2,
        type=float,
        metavar=("LON1", "LON2"),
        help="Longitude bounds passed to subset.py (two numbers).",
    )

    parser.add_argument(
        "--outdir",
        type=str,
        help="Name/path of new subset directory (e.g., MiamiBeach1).",
    )

    parser.add_argument(
        "--inputs-dirname",
        type=str,
        default="inputs",
        help="Name of inputs directory (default: inputs).",
    )
    parser.add_argument(
        "--subset-script",
        type=str,
        default="subset.py",
        help="Name/path of subset.py executable (default: subset.py).",
    )

    # --- config.json generation ---
    parser.add_argument(
        "--make-config",
        action="store_true",
        help="Create config.json in subset directory from template.",
    )
    parser.add_argument(
        "--config-template",
        type=str,
        default="config.json",
        help="Path to template config (default: config.json in project root).",
    )
    parser.add_argument(
        "--config-name",
        type=str,
        default="config.json",
        help="Filename of config in subset directory (default: config.json).",
    )
    parser.add_argument(
        "--num-cores",
        type=int,
        default=None,
        help="Override num_cores in config and SBATCH -n (optional).",
    )
    parser.add_argument(
        "--num-patches",
        type=int,
        default=None,
        help="Override num_patches in config (optional).",
    )

    # --- sbatch jobfile generation ---
    parser.add_argument(
        "--make-sbatch",
        action="store_true",
        help="Create sarvey.job (SBATCH) in subset directory.",
    )
    parser.add_argument(
        "--sbatch-name",
        type=str,
        default="sarvey.job",
        help="Name of SBATCH script (default: sarvey.job).",
    )
    parser.add_argument(
        "--job-name",
        type=str,
        default=None,
        help="SLURM job name (default: sarvey_<outdir>).",
    )
    parser.add_argument(
        "--account",
        type=str,
        default="TG-EAR200012",
        help="SLURM project/account for -A (default: TG-EAR200012).",
    )
    parser.add_argument(
        "--mail-user",
        type=str,
        default=None,
        help="Email for job notifications (optional).",
    )
    parser.add_argument(
        "--mail-type",
        type=str,
        default="fail",
        help="Mail type for SLURM (default: fail).",
    )
    parser.add_argument(
        "--nodes",
        type=int,
        default=1,
        help="Number of nodes for SBATCH -N (default: 1).",
    )
    parser.add_argument(
        "--ntasks",
        type=int,
        default=None,
        help="Number of tasks for SBATCH -n "
             "(default: num_cores if given, otherwise 48).",
    )
    parser.add_argument(
        "--partition",
        type=str,
        default="nvdimm",
        help="SLURM partition (default: nvdimm).",
    )
    parser.add_argument(
        "--time",
        type=str,
        default="1:59:00",
        help="Walltime for SBATCH -t (default: 1:59:00).",
    )
    parser.add_argument(
        "--conda-env",
        type=str,
        default="minsar",
        help="Conda environment name (default: minsar).",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path.cwd()

    # outdir is needed for subset and for config/sbatch creation
    subset_root = Path(args.outdir).resolve() if args.outdir else None

    # --- subset creation ---
    if args.subset:
        if args.lat is None or args.lon is None or subset_root is None:
            print(
                "[ERROR] --subset requires --lat LAT1 LAT2, "
                "--lon LON1 LON2 and --outdir OUTDIR.",
                file=sys.stderr,
            )
            sys.exit(1)

        run_subset(
            project_root=project_root,
            lat=args.lat,
            lon=args.lon,
            outdir=subset_root,
            inputs_dirname=args.inputs_dirname,
            subset_script=args.subset_script,
        )

    # --- config.json generation ---
    if args.make_config:
        if subset_root is None:
            print(
                "[ERROR] --make-config requires --outdir OUTDIR.",
                file=sys.stderr,
            )
            sys.exit(1)

        template_path = (project_root / args.config_template).resolve()
        make_config_from_template(
            template_path=template_path,
            subset_root=subset_root,
            config_name=args.config_name,
            num_cores=args.num_cores,
            num_patches=args.num_patches,
        )

    # --- sbatch jobfile generation ---
    if args.make_sbatch:
        if subset_root is None:
            print(
                "[ERROR] --make-sbatch requires --outdir OUTDIR.",
                file=sys.stderr,
            )
            sys.exit(1)

        # Decide ntasks: prefer explicit, else num_cores, else 48
        if args.ntasks is not None:
            ntasks = args.ntasks
        elif args.num_cores is not None:
            ntasks = args.num_cores
        else:
            ntasks = 48

        make_sbatch_job(
            subset_root=subset_root,
            sbatch_name=args.sbatch_name,
            job_name=args.job_name,
            account=args.account,
            mail_user=args.mail_user,
            mail_type=args.mail_type,
            nodes=args.nodes,
            ntasks=ntasks,
            partition=args.partition,
            time=args.time,
            conda_env=args.conda_env,
            config_name=args.config_name,
        )

    # If user didn’t request anything:
    if not (args.subset or args.make_config or args.make_sbatch):
        print(
            "[INFO] No action selected.\n"
            "       Use --subset, --make-config and/or --make-sbatch."
        )


if __name__ == "__main__":
    main()

