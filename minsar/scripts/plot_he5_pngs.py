#!/usr/bin/env python3
"""Generate MintPy-style summary PNGs from an ISCE3/Dolphin HDF-EOS5 (.he5) file."""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
import time
from pathlib import Path

import h5py
from mintpy.utils import readfile, utils as ut

from minsar.objects import message_rsmas
DESCRIPTION = (
    "Generate MintPy-style summary PNGs from an HDF-EOS5 file using view.py "
    "(quality, geometry, velocity). Optional displacement epoch pages with --displacements."
)

EXAMPLES = """Examples:
plot_he5_pngs.py dolphin/timeseries/S1*.he5 -t MyProject.template
plot_he5_pngs.py S1_desc_087_modeOperaDisp_20220114_20220619.he5 --memory 0.2 --dpi 150
plot_he5_pngs.py dolphin/timeseries/S1*.he5 --displacements --nrows 2 --ncols 5
plot_he5_pngs.py ./*.he5 --outdir pic --dry-run
"""

HE5_ROOT = "HDFEOS/GRIDS/timeseries"

QUALITY_JOBS: list[tuple[str, list[str]]] = [
    ("temporalCoherence", ["-c", "gray", "-v", "0", "1"]),
    ("avgSpatialCoherence", ["-c", "gray", "-v", "0", "1"]),
    ("mask", ["-c", "gray", "-v", "0", "1"]),
    ("conncomp", ["-c", "gray", "-v", "0", "1"]),
    ("waterMask", ["-c", "gray", "-v", "0", "1"]),
    ("phaseSimilarity", ["-c", "gray", "-v", "0", "1"]),
    ("recommendedDensity", ["-c", "gray", "-v", "0", "1"]),
    ("persistentScattererDensity", ["-c", "gray", "-v", "0", "1"]),
]

# MintPy/view.py may emit MintPy-style names; map them to HE5 dataset names.
LEGACY_PNG_ALIASES = {
    "geo_maskTempCoh.png": "mask.png",
    "geo_maskConnComp.png": "conncomp.png",
    "geo_velocity.png": "velocity.png",
}

GEOMETRY_DATASETS = (
    "height",
    "latitude",
    "longitude",
    "incidenceAngle",
    "azimuthAngle",
    "slantRangeDistance",
    "shadowMask",
)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLES,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("he5_file", metavar="HE5_FILE", help="HDF-EOS5 file path or glob (newest match)")
    parser.add_argument("-t", "--template", dest="template_file", metavar="FILE", default=None, help="MinSAR/MintPy *.template for plot memory and dpi")
    parser.add_argument("--outdir", dest="out_dir", metavar="DIR", default="pic", help="Output directory (default: pic under dolphin/ or cwd)")
    parser.add_argument("--dpi", dest="dpi", metavar="INT", type=int, default=None, help="Figure DPI (default: mintpy.plot.dpi from template, else 150)")
    parser.add_argument("--memory", dest="max_memory", metavar="GB", type=float, default=None, help="Max memory per view.py call in GB (default: mintpy.plot.maxMemory from template, else 0.2)")
    parser.add_argument("--num-workers", dest="num_workers", metavar="N", type=int, default=None, help="Parallel view.py jobs (default: mintpy.compute.numWorker from template, else 4)")
    parser.add_argument("--nrows", dest="nrows", metavar="N", type=int, default=None, help="view.py subplot rows for geometry/displacement panels")
    parser.add_argument("--ncols", dest="ncols", metavar="N", type=int, default=None, help="view.py subplot columns for geometry/displacement panels")
    parser.add_argument("--displacements", dest="plot_displacements", action="store_true", help="Plot wrapped displacement pages (slow on long stacks)")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Print view.py commands only")
    return parser


def _read_plot_settings(template_file: str | None) -> dict:
    settings = {
        "dpi": 150,
        "max_plot_memory": 0.2,
        "max_memory": 4.0,
        "num_workers": 4,
        "cluster": "local",
    }
    if not template_file or not os.path.isfile(template_file):
        return settings

    template = readfile.read_template(template_file)
    template = ut.check_template_auto_value(template)
    for key, attr in (
        ("mintpy.plot.dpi", "dpi"),
        ("mintpy.plot.maxMemory", "max_plot_memory"),
        ("mintpy.compute.maxMemory", "max_memory"),
        ("mintpy.compute.numWorker", "num_workers"),
    ):
        if key in template and template[key] not in (None, "none", "None", ""):
            val = template[key]
            if key == "mintpy.plot.maxMemory" and str(val).lower() == "auto":
                val = settings["max_plot_memory"]
            settings[attr] = val
    if "mintpy.compute.cluster" in template:
        settings["cluster"] = template["mintpy.compute.cluster"]

    settings["dpi"] = int(abs(float(settings["dpi"])))
    settings["max_plot_memory"] = abs(float(settings["max_plot_memory"]))
    settings["max_memory"] = abs(float(settings["max_memory"]))
    settings["num_workers"] = int(abs(float(settings["num_workers"])))
    return settings


def resolve_he5_path(pattern: str) -> Path:
    path = pattern.strip()
    if "*" in path or "?" in path:
        matches = sorted(glob.glob(path), key=os.path.getmtime, reverse=True)
        if not matches:
            raise FileNotFoundError(f"No HE5 file matched: {pattern}")
        return Path(matches[0]).resolve()
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"HE5 file not found: {resolved}")
    return resolved


def resolve_pic_dir(he5_path: Path, out_dir: str) -> Path:
    out = Path(out_dir)
    if out.is_absolute():
        return out
    if he5_path.parent.name == "timeseries":
        return (he5_path.parent.parent / out).resolve()
    return (Path.cwd() / out).resolve()


def resolve_template(template_arg: str | None) -> str | None:
    if template_arg and os.path.isfile(template_arg):
        return os.path.abspath(template_arg)
    if template_arg and glob.glob(template_arg):
        return os.path.abspath(sorted(glob.glob(template_arg))[0])
    for pattern in ("*.template",):
        hits = sorted(glob.glob(pattern))
        if hits:
            return os.path.abspath(hits[0])
    return None


def he5_has_dataset(he5_path: Path, group: str, name: str) -> bool:
    dset_path = f"{HE5_ROOT}/{group}/{name}"
    try:
        with h5py.File(he5_path, "r") as f:
            return dset_path in f
    except OSError:
        return False


def _view_common(dpi: int, max_plot_memory: float) -> list[str]:
    return [
        "--dpi", str(dpi),
        "--noverbose", "--nodisplay", "--update",
        "--memory", str(max_plot_memory),
    ]


def _out_png(name: str) -> list[str]:
    """Flat output PNG name (required for HE5 datasets; MintPy otherwise uses paths with /)."""
    return ["-o", name]


def _layout_opts(nrows: int | None, ncols: int | None) -> list[str]:
    opts: list[str] = []
    if nrows is not None:
        opts.extend(["--nrows", str(nrows)])
    if ncols is not None:
        opts.extend(["--ncols", str(ncols)])
    return opts


def _build_quality_jobs(
    he5_path: Path,
    dpi: int,
    max_plot_memory: float,
) -> list[tuple[list[str], str | None]]:
    jobs: list[tuple[list[str], str | None]] = []
    common = _view_common(dpi, max_plot_memory)
    he5_str = str(he5_path)
    for dset, extra in QUALITY_JOBS:
        if not he5_has_dataset(he5_path, "quality", dset):
            continue
        out_name = f"{dset}.png"
        jobs.append((common + [he5_str, dset] + extra + _out_png(out_name), out_name))
    return jobs


def _build_geometry_job(
    he5_path: Path,
    dpi: int,
    max_plot_memory: float,
    nrows: int | None,
    ncols: int | None,
) -> tuple[list[str], str | None] | None:
    dsets = [name for name in GEOMETRY_DATASETS if he5_has_dataset(he5_path, "geometry", name)]
    if not dsets:
        return None
    common = _view_common(dpi, max_plot_memory)
    iargs = common + [str(he5_path)] + dsets + _layout_opts(nrows, ncols)
    if nrows is None and ncols is None and len(dsets) > 1:
        ncols_default = min(3, len(dsets))
        nrows_default = (len(dsets) + ncols_default - 1) // ncols_default
        iargs.extend(["--nrows", str(nrows_default), "--ncols", str(ncols_default)])
    iargs.extend(_out_png("geometryRadar.png"))
    return iargs, "geometryRadar.png"


def _build_displacement_job(
    he5_path: Path,
    dpi: int,
    max_plot_memory: float,
    nrows: int | None,
    ncols: int | None,
) -> list[str] | None:
    if not he5_has_dataset(he5_path, "observation", "displacement"):
        return None
    return (
        _view_common(dpi, max_plot_memory)
        + [str(he5_path), "displacement", "--noaxis", "-u", "cm", "--wrap", "--wrap-range", "-5", "5"]
        + _layout_opts(nrows, ncols)
        + _out_png("displacement.png")
    )


def _run_timeseries2velocity(he5_path: Path, work_dir: Path, dry_run: bool) -> Path | None:
    vel_path = work_dir / "geo_velocity.h5"
    iargs = [str(he5_path), "-o", str(vel_path)]
    print("timeseries2velocity.py", " ".join(iargs))
    if dry_run:
        return vel_path
    import mintpy.cli.timeseries2velocity
    mintpy.cli.timeseries2velocity.main(iargs)
    return vel_path if vel_path.is_file() else None


def _run_view_jobs(
    iargs_list: list[list[str]],
    max_memory: float,
    max_plot_memory: float,
    num_workers: int,
    cluster: str,
    dry_run: bool,
) -> None:
    if not iargs_list:
        return
    for iargs in iargs_list:
        print("view.py", " ".join(iargs))
    if dry_run:
        return

    import matplotlib
    matplotlib.use("Agg")
    import mintpy.cli.view

    run_parallel = False
    num_cores = 1
    if cluster and str(cluster).lower() not in ("none", "no", ""):
        try:
            from mintpy.objects import cluster as mintpy_cluster
        except ImportError:
            from mintpy.utils import cluster as mintpy_cluster  # older MintPy
        num_workers_fmt = mintpy_cluster.DaskCluster.format_num_worker(cluster, str(num_workers))
        num_cores, run_parallel, Parallel, delayed = ut.check_parallel(
            len(iargs_list),
            print_msg=False,
            maxParallelNum=num_workers_fmt,
        )
        plot_memory = 1.5 if 2.0 < max_plot_memory <= 4.0 else 1.5 * (max_plot_memory / 4.0)
        num_cores = min(num_cores, max(int(max_memory / plot_memory), 1))

    if run_parallel and num_cores > 1:
        print(f"parallel view.py using {num_cores} workers for {len(iargs_list)} figure(s) ...")
        Parallel(n_jobs=num_cores)(delayed(mintpy.cli.view.main)(iargs) for iargs in iargs_list)
    else:
        for iargs in iargs_list:
            mintpy.cli.view.main(iargs)


def _expected_png_basenames(he5_path: Path, dset: str) -> list[str]:
    stem = he5_path.stem
    return [
        f"{dset}.png",
        f"{stem}_{dset}.png",
        f"geo_{dset}.png",
        f"{stem}_geo_{dset}.png",
    ]


def _collect_pngs(work_dir: Path, out_dir: Path, rename_map: dict[str, str]) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for png in sorted(work_dir.glob("*.png")):
        dest_name = rename_map.get(png.name, png.name)
        dest = out_dir / dest_name
        if png.resolve() == dest.resolve():
            moved.append(str(dest))
            continue
        if dest.exists():
            dest.unlink()
        shutil.move(str(png), dest)
        moved.append(str(dest))
    return moved


def _copy_template_to_pic(template_file: str | None, pic_dir: Path) -> None:
    if not template_file or not os.path.isfile(template_file):
        return
    dest = pic_dir / os.path.basename(template_file)
    shutil.copy2(template_file, dest)
    print(f"Copied template to {dest}")


def _write_reference_date(he5_path: Path, pic_dir: Path) -> None:
    try:
        atr = readfile.read_attribute(str(he5_path))
    except Exception:
        return
    ref = atr.get("REF_DATE") or atr.get("reference_date")
    if not ref:
        return
    ref_path = pic_dir / "reference_date.txt"
    ref_path.write_text(str(ref).strip() + "\n")
    print(f"Wrote {ref_path}")


def _copy_minsar_log(he5_path: Path, pic_dir: Path) -> None:
    candidates = [
        Path.cwd() / "minsar_log",
        he5_path.parent / "minsar_log",
        he5_path.parent.parent / "minsar_log",
    ]
    for src in candidates:
        if src.is_file():
            dest = pic_dir / "minsar_log"
            shutil.copy2(src, dest)
            print(f"Copied {src} to {dest}")
            return


def _copy_insarmaps_log(he5_path: Path, pic_dir: Path) -> None:
    candidates = [
        he5_path.parent / "insarmaps.log",
        he5_path.parent.parent / "insarmaps.log",
        Path.cwd() / "insarmaps.log",
    ]
    for src in candidates:
        if src.is_file():
            dest = pic_dir / "insarmaps.log"
            shutil.copy2(src, dest)
            print(f"Copied {src} to {dest}")
            return


def plot_he5_pngs(
    he5_path: Path,
    pic_dir: Path,
    *,
    template_file: str | None = None,
    dpi: int = 150,
    max_plot_memory: float = 0.2,
    max_memory: float = 4.0,
    num_workers: int = 4,
    cluster: str = "local",
    nrows: int | None = None,
    ncols: int | None = None,
    plot_displacements: bool = False,
    dry_run: bool = False,
) -> int:
    work_dir = he5_path.parent
    rename_map: dict[str, str] = dict(LEGACY_PNG_ALIASES)
    view_jobs: list[list[str]] = []

    for dset, _extra in QUALITY_JOBS:
        if not he5_has_dataset(he5_path, "quality", dset):
            continue
        for base in _expected_png_basenames(he5_path, dset):
            rename_map[base] = f"{dset}.png"

    for iargs, _rename in _build_quality_jobs(he5_path, dpi, max_plot_memory):
        view_jobs.append(iargs)

    geom = _build_geometry_job(he5_path, dpi, max_plot_memory, nrows, ncols)
    if geom is not None:
        iargs, _rename = geom
        view_jobs.append(iargs)
        for base in ("geometryRadar.png", f"{he5_path.stem}_geometryRadar.png", "geo_geometryRadar.png"):
            rename_map[base] = "geometryRadar.png"

    _run_view_jobs(view_jobs, max_memory, max_plot_memory, num_workers, cluster, dry_run)

    vel_h5 = _run_timeseries2velocity(he5_path, work_dir, dry_run)
    if vel_h5 is not None:
        vel_job = _view_common(dpi, max_plot_memory) + [str(vel_h5), "velocity"] + _out_png("velocity.png")
        print("view.py", " ".join(vel_job))
        if not dry_run:
            import mintpy.cli.view
            mintpy.cli.view.main(vel_job)
        for base in ("velocity.png", "geo_velocity.png", f"{vel_h5.stem}_velocity.png"):
            rename_map[base] = "velocity.png"

    if plot_displacements:
        disp_job = _build_displacement_job(he5_path, dpi, max_plot_memory, nrows, ncols)
        if disp_job:
            print("view.py", " ".join(disp_job))
            if not dry_run:
                import mintpy.cli.view
                mintpy.cli.view.main(disp_job)

    if dry_run:
        print(f"Would collect PNGs from {work_dir} into {pic_dir}/")
        return 0

    moved = _collect_pngs(work_dir, pic_dir, rename_map)
    print(f"Moved {len(moved)} PNG file(s) to {pic_dir}/")
    _copy_template_to_pic(template_file, pic_dir)
    _write_reference_date(he5_path, pic_dir)
    _copy_minsar_log(he5_path, pic_dir)
    _copy_insarmaps_log(he5_path, pic_dir)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    message_rsmas.log(
        os.getcwd(),
        os.path.basename(__file__) + " " + " ".join(argv if argv is not None else sys.argv[1:]),
    )

    try:
        he5_path = resolve_he5_path(args.he5_file)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    template_file = resolve_template(args.template_file)
    settings = _read_plot_settings(template_file)
    dpi = args.dpi if args.dpi is not None else settings["dpi"]
    max_plot_memory = args.max_memory if args.max_memory is not None else settings["max_plot_memory"]
    max_memory = settings["max_memory"]
    num_workers = args.num_workers if args.num_workers is not None else settings["num_workers"]
    pic_dir = resolve_pic_dir(he5_path, args.out_dir)

    print(f"HE5:  {he5_path}")
    print(f"pic:  {pic_dir}")
    start = time.time()
    cwd = os.getcwd()
    os.chdir(he5_path.parent)
    try:
        rc = plot_he5_pngs(
            he5_path,
            pic_dir,
            template_file=template_file,
            dpi=dpi,
            max_plot_memory=max_plot_memory,
            max_memory=max_memory,
            num_workers=num_workers,
            cluster=settings["cluster"],
            nrows=args.nrows,
            ncols=args.ncols,
            plot_displacements=args.plot_displacements,
            dry_run=args.dry_run,
        )
    finally:
        os.chdir(cwd)

    mins, secs = divmod(time.time() - start, 60)
    print(f"time used: {int(mins):02d} mins {secs:.1f} secs.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
