#!/usr/bin/env python3
"""Summarize ISCE3 run metadata and per-step SLURM walltimes into walltimes_isce3.log."""

from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

from minsar.utils import process_utilities as putils
from minsar.utils.dolphin_presets import (
    DOLPHIN_PRESETS,
    count_opera_cslc_bursts,
    dolphin_worker_counts,
)

_CSLC_ACQ_DATE_RE = re.compile(r"IW\d+_(\d{8})T", re.IGNORECASE)
_STEP_JOB_RE = re.compile(r"^run_(\d{2})_(.+)\.job$")
_STDOUT_RE = re.compile(r"^run_(\d{2})_(.+)_(\d+)\.o$")
_BAKED_PARALLEL_BURSTS_RE = re.compile(r"--n-parallel-bursts\s+(\d+)")
_BAKED_THREADS_RE = re.compile(r"--worker-settings\.threads-per-worker\s+(\d+)")
_BAKED_N_PARALLEL_JOBS_RE = re.compile(r"--unwrap-options\.n-parallel-jobs\s+(\d+)")


def create_parser() -> argparse.ArgumentParser:
    epilog = """Examples:
 summarize_isce3_runs.py /scratch/.../qxHawaiiCSLCDolphin-autoSenD87/run_files
 summarize_isce3_runs.py run_files
 summarize_isce3_runs.py $TE/qxHawaiiCSLCDolphin-autoSenD87/run_files --outdir $TE/qxHawaiiCSLCDolphin-autoSenD87"""
    parser = argparse.ArgumentParser(
        description="Summarize ISCE3 run metadata and per-step SLURM walltimes into walltimes_isce3.log.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("run_files_dir", help="path to run_files/ directory")
    parser.add_argument("--outdir", default=None, help="output directory for walltimes_isce3.log (default: project dir)")
    return parser


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


def _yx_pair(values: object, default: str = "n/a") -> str:
    if isinstance(values, dict):
        y_val = values.get("y")
        x_val = values.get("x")
        if y_val is not None and x_val is not None:
            return f"{y_val}x{x_val}"
    if isinstance(values, (list, tuple)) and len(values) >= 2:
        return f"{values[0]}x{values[1]}"
    return default


def _fmt_kv(key: str, value: object) -> str:
    if value is None:
        return f"{key}=n/a"
    return f"{key}={value}"


def _parse_sbatch(job_path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not job_path.is_file():
        return out
    text = job_path.read_text(encoding="utf-8", errors="replace")
    for pattern, key in (
        (r"^#SBATCH\s+-p\s+(\S+)", "queue"),
        (r"^#SBATCH\s+-n\s+(\d+)", "cpus"),
        (r"^#SBATCH\s+-N\s+(\d+)", "nnodes"),
        (r"^#SBATCH\s+-t\s+(\S+)", "timelimit"),
        (r"^#SBATCH\s+--mem=(\S+)", "mem"),
    ):
        match = re.search(pattern, text, re.M)
        if match:
            out[key] = match.group(1)
    return out


def _get_launcher_params(job_path: Path) -> dict[str, str | int]:
    params: dict[str, str | int] = {}
    if not job_path.is_file():
        return params
    job_dir = job_path.parent
    launcher_job_file_path: str | None = None
    with job_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            m = re.search(r"LAUNCHER_PPN\s*=\s*(\S+)", line)
            if m:
                params["LAUNCHER_PPN"] = m.group(1).strip().strip("'\"")
            m = re.search(r"LAUNCHER_NHOSTS\s*=\s*(\S+)", line)
            if m:
                params["LAUNCHER_NHOSTS"] = m.group(1).strip().strip("'\"")
            m = re.search(r"OMP_NUM_THREADS\s*=\s*(\S+)", line)
            if m:
                params["OMP_NUM_THREADS"] = m.group(1).strip().strip("'\"")
            m = re.search(r"LAUNCHER_JOB_FILE\s*=\s*(\S+)", line)
            if m:
                launcher_job_file_path = m.group(1).strip().strip("'\"")
    if launcher_job_file_path:
        resolved = launcher_job_file_path if os.path.isabs(launcher_job_file_path) and os.path.isfile(launcher_job_file_path) else None
        if not resolved:
            base = os.path.basename(launcher_job_file_path.split("/")[-1].split("$")[-1])
            candidate = job_dir / base
            if candidate.is_file():
                resolved = str(candidate)
        if resolved and os.path.isfile(resolved):
            with open(resolved, encoding="utf-8", errors="replace") as lf:
                params["launcher_file_lines"] = sum(1 for ln in lf if ln.strip())
    return params


def _resolve_n_bursts(project_dir: Path, sweets: dict) -> int:
    data_dir = project_dir / "data"
    if any(data_dir.glob("OPERA_L2_CSLC-S1_*.h5")):
        return count_opera_cslc_bursts(data_dir)
    search = sweets.get("search") or {}
    bbox = search.get("bbox") or sweets.get("bbox")
    if not bbox or not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        template_files = list(project_dir.glob("*.template"))
        if template_files:
            try:
                from minsar.objects.dataset_template import Template

                opts = Template(str(template_files[0])).get_options()
                subset = opts.get("miaplpy.subset.lalo", "")
                if subset and str(subset).lower() != "no":
                    from minsar.utils.generate_sweets_config import count_bursts_covering_aoi

                    track_raw = opts.get("ssaraopt.relativeOrbit")
                    track = int(track_raw) if track_raw else None
                    return count_bursts_covering_aoi(str(subset), track=track)
            except Exception:
                pass
        return 1
    left, bottom, right, top = bbox[0], bbox[1], bbox[2], bbox[3]
    aoi = f"{bottom}:{top},{left}:{right}"
    from minsar.utils.generate_sweets_config import count_bursts_covering_aoi

    track_raw = search.get("relativeOrbit")
    track = int(track_raw) if track_raw else None
    return count_bursts_covering_aoi(aoi, track=track)


def _count_acquisitions(data_dir: Path) -> int | None:
    if not data_dir.is_dir():
        return None
    dates: set[str] = set()
    for path in data_dir.glob("OPERA_L2_CSLC-S1_*.h5"):
        match = _CSLC_ACQ_DATE_RE.search(path.name)
        if match:
            dates.add(match.group(1))
    return len(dates) if dates else None


def _find_dolphin_job(run_files_dir: Path) -> Path | None:
    wrapped = sorted(run_files_dir.glob("run_*_dolphin_wrapped.job"))
    if wrapped:
        return wrapped[0]
    dolphin = sorted(run_files_dir.glob("run_*_dolphin.job"))
    if dolphin:
        return dolphin[0]
    return None


def _parse_baked_worker_flags(run_script: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    if not run_script.is_file():
        return out
    text = run_script.read_text(encoding="utf-8", errors="replace")
    for pattern, key in (
        (_BAKED_PARALLEL_BURSTS_RE, "n_parallel_bursts"),
        (_BAKED_THREADS_RE, "threads_per_worker"),
        (_BAKED_N_PARALLEL_JOBS_RE, "n_parallel_jobs"),
    ):
        match = pattern.search(text)
        if match:
            out[key] = int(match.group(1))
    return out


def _infer_preset(strides_yx: str, half_window_yx: str) -> str:
    if strides_yx == "n/a" or half_window_yx == "n/a":
        return "n/a"
    try:
        sy, sx = map(int, strides_yx.split("x"))
        hy, hx = map(int, half_window_yx.split("x"))
    except ValueError:
        return "custom"
    if sy == 1 and sx == 1 and hy == 7 and hx == 14:
        return "auto"
    for name, spec in DOLPHIN_PRESETS.items():
        if name == "auto":
            continue
        strides = spec.get("strides")
        hw = spec.get("half_window")
        if strides and hw and sy == strides[0] and sx == strides[1] and hy == hw[0] and hx == hw[1]:
            return name
    return "custom"


def _workflow_from_stages(stages: list[str]) -> str:
    if any(s == "download_cslc" for s in stages):
        return "cslc"
    if any(s == "download_safe" for s in stages):
        return "safe"
    if any(s == "download_disp" for s in stages):
        return "disp"
    return "unknown"


def _elapsed_to_seconds(elapsed: str) -> int:
    parts = elapsed.strip().split(":")
    if len(parts) == 3:
        h, m, s = parts
        if "-" in h:
            days, h = h.split("-", 1)
            h = str(int(days) * 24 + int(h))
        return int(h) * 3600 + int(m) * 60 + int(float(s))
    if len(parts) == 2:
        return int(parts[0]) * 3600 + int(parts[1]) * 60
    return 0


def _tacc_scheduler_available() -> bool:
    try:
        hostname = subprocess.check_output(["hostname", "-f"], text=True).strip().lower()
    except (subprocess.CalledProcessError, FileNotFoundError):
        hostname = ""
    return any(token in hostname for token in ("frontera", "stampede3", "comet", "stampede"))


def _sacct_lookup(job_ids: list[str]) -> dict[str, dict[str, str]]:
    if not job_ids or not _tacc_scheduler_available():
        return {}
    fmt = "JobID,NNodes,CPUs,Timelimit,Reserved,Elapsed,State,MaxRSS,ExitCode"
    cmd = ["sacct", f"--format={fmt}", "-n", "-P", "-j", ",".join(job_ids)]
    try:
        stdout = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print("Warning: sacct failed; step timing fields will be n/a", file=sys.stderr)
        return {}
    rows: dict[str, dict[str, str]] = {}
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) < 9:
            continue
        job_id = parts[0].split(".")[0]
        if not job_id.isdigit():
            continue
        rows[job_id] = {
            "NNodes": parts[1],
            "CPUs": parts[2],
            "Timelimit": parts[3],
            "Reserved": parts[4],
            "Elapsed": parts[5],
            "State": parts[6],
            "MaxRSS": parts[7],
            "ExitCode": parts[8],
        }
    return rows


def _compute_n_unwrap(project_dir: Path) -> int | None:
    try:
        from minsar.scripts.resize_dolphin_unwrap_jobfile import (
            compute_n_parallel_jobs,
            find_representative_ifg,
            infer_queue_from_jobfiles,
            read_ifg_size,
            resolve_project_dir,
            _unwrap_settings,
        )
        from minsar.utils.unwrap_memory import load_queue_row
    except ImportError:
        return None
    try:
        resolved = resolve_project_dir(str(project_dir))
        ifg_path = find_representative_ifg(resolved)
        length, width = read_ifg_size(ifg_path)
        config_path = resolved / "dolphin_config.yaml"
        unwrap_method, num_snaphu_tiles, cpu_tile_parallelism = _unwrap_settings(config_path)
        queue_name = infer_queue_from_jobfiles(resolved) or os.getenv("QUEUENAME") or "skx-dev"
        queue_info = load_queue_row(queue_name)
        queue_info["queue"] = queue_name
        n_jobs, _ = compute_n_parallel_jobs(
            length,
            width,
            queue_info,
            unwrap_method,
            num_snaphu_tiles,
            cpu_tile_parallelism,
            420.0,
        )
        return n_jobs
    except Exception:
        return None


def _discover_steps(run_files_dir: Path) -> list[tuple[str, str, Path]]:
    steps: list[tuple[str, str, Path]] = []
    for job_path in sorted(run_files_dir.glob("run_*.job")):
        match = _STEP_JOB_RE.match(job_path.name)
        if not match:
            continue
        step_num, stage = match.group(1), match.group(2)
        step_key = f"run_{step_num}_{stage}"
        steps.append((step_num, step_key, job_path))
    return steps


def _stdout_files_for_step(run_files_dir: Path, step_key: str) -> list[str]:
    stage = step_key.split("_", 2)[2]
    prefix = step_key + "_"
    files = list(run_files_dir.glob(f"{prefix}*.o"))
    files.extend(run_files_dir.glob(f"stdout_run_*/{prefix}*.o"))
    job_ids: list[str] = []
    for path in files:
        match = _STDOUT_RE.match(path.name)
        if match and match.group(2) == stage:
            job_ids.append(match.group(3))
    return sorted(set(job_ids), key=int)


def _build_line1(
    run_files_dir: Path,
    n_bursts: int,
) -> str:
    dolphin_job = _find_dolphin_job(run_files_dir)
    sbatch = _parse_sbatch(dolphin_job) if dolphin_job else {}
    queue = sbatch.get("queue", "n/a")
    cpus_raw = sbatch.get("cpus")
    cpus = int(cpus_raw) if cpus_raw else None

    parts = [_fmt_kv("Queue", queue), _fmt_kv("CPUs", cpus if cpus is not None else "n/a"), _fmt_kv("n_bursts", n_bursts)]

    baked: dict[str, int] = {}
    if dolphin_job:
        run_script = run_files_dir / dolphin_job.name.replace(".job", "")
        baked = _parse_baked_worker_flags(run_script)

    if baked:
        parts.append(_fmt_kv("n_parallel_bursts", baked.get("n_parallel_bursts")))
        parts.append(_fmt_kv("threads_per_worker", baked.get("threads_per_worker")))
        parts.append(_fmt_kv("n_parallel_jobs", baked.get("n_parallel_jobs")))
    elif cpus is not None:
        n_par, threads, n_jobs = dolphin_worker_counts(cpus, n_bursts)
        parts.append(_fmt_kv("n_parallel_bursts", n_par))
        parts.append(_fmt_kv("threads_per_worker", threads))
        parts.append(_fmt_kv("n_parallel_jobs", n_jobs))

    create_cslc_jobs = sorted(run_files_dir.glob("run_*_create_cslc.job"))
    if create_cslc_jobs:
        launcher = _get_launcher_params(create_cslc_jobs[0])
        if "LAUNCHER_PPN" in launcher:
            parts.append(_fmt_kv("LAUNCHER_PPN", launcher["LAUNCHER_PPN"]))
        if "OMP_NUM_THREADS" in launcher:
            parts.append(_fmt_kv("OMP_NUM_THREADS", launcher["OMP_NUM_THREADS"]))

    return " ".join(parts)


def _build_line2(
    project_dir: Path,
    run_files_dir: Path,
    sweets: dict,
    dolphin_cfg: dict,
    n_bursts: int,
) -> str:
    output_opts = dolphin_cfg.get("output_options") or {}
    strides = output_opts.get("strides") or (sweets.get("dolphin") or {}).get("strides")
    half_window = (dolphin_cfg.get("phase_linking") or {}).get("half_window") or (sweets.get("dolphin") or {}).get("half_window")
    strides_yx = _yx_pair(strides)
    half_window_yx = _yx_pair(half_window)

    slc_posting = sweets.get("slc_posting")
    slc_posting_yx = _yx_pair(slc_posting)
    effective = "n/a"
    if isinstance(slc_posting, (list, tuple)) and len(slc_posting) >= 2 and strides_yx != "n/a":
        try:
            sy, sx = map(int, strides_yx.split("x"))
            effective = f"{float(slc_posting[0]) * sy}x{float(slc_posting[1]) * sx}"
        except ValueError:
            pass

    n_acq = _count_acquisitions(project_dir / "data")
    phase_link = dolphin_cfg.get("phase_linking") or {}
    unwrap = dolphin_cfg.get("unwrap_options") or {}
    snaphu = unwrap.get("snaphu_options") or {}
    timeseries = dolphin_cfg.get("timeseries_options") or {}
    worker = dolphin_cfg.get("worker_settings") or {}

    dolphin_split = "yes" if any(run_files_dir.glob("run_*_dolphin_wrapped.job")) else "no"
    max_bw = (sweets.get("dolphin") or {}).get("max_bandwidth", "n/a")

    parts = [
        _fmt_kv("N_bursts", n_bursts),
        _fmt_kv("N_acquisitions", n_acq if n_acq is not None else "n/a"),
        _fmt_kv("Strides_yx", strides_yx),
        _fmt_kv("HalfWindow_yx", half_window_yx),
        _fmt_kv("SLC_posting_yx_m", slc_posting_yx),
        _fmt_kv("Effective_posting_yx_m", effective),
        _fmt_kv("Preset", _infer_preset(strides_yx, half_window_yx)),
        _fmt_kv("Ministack_size", phase_link.get("ministack_size", "n/a")),
        _fmt_kv("Max_bandwidth", max_bw),
        _fmt_kv("Dolphin_split", dolphin_split),
        _fmt_kv("COMPASS_n_workers", sweets.get("n_workers", "n/a")),
        _fmt_kv("COMPASS_threads_per_worker", sweets.get("threads_per_worker", "n/a")),
    ]

    if worker.get("n_parallel_bursts") is not None:
        parts.append(_fmt_kv("config_n_parallel_bursts", worker.get("n_parallel_bursts")))
    if worker.get("threads_per_worker") is not None:
        parts.append(_fmt_kv("config_threads_per_worker", worker.get("threads_per_worker")))
    if worker.get("block_shape") is not None:
        parts.append(_fmt_kv("Dolphin_block_shape", _yx_pair(worker.get("block_shape"))))
    if unwrap.get("n_parallel_jobs") is not None:
        parts.append(_fmt_kv("config_n_parallel_jobs", unwrap.get("n_parallel_jobs")))
    if snaphu.get("n_parallel_tiles") is not None:
        parts.append(_fmt_kv("Snaphu_n_parallel_tiles", snaphu.get("n_parallel_tiles")))
    if timeseries.get("num_parallel_blocks") is not None:
        parts.append(_fmt_kv("Timeseries_num_parallel_blocks", timeseries.get("num_parallel_blocks")))

    return " ".join(parts)


def _context_lines(project_dir: Path, run_files_dir: Path, workflow: str, sweets: dict) -> list[str]:
    search = sweets.get("search") or {}
    bbox = search.get("bbox") or sweets.get("bbox")
    aoi = "n/a"
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        aoi = f"{bbox[1]}:{bbox[3]},{bbox[0]}:{bbox[2]}"
    track = search.get("relativeOrbit", "n/a")
    start = search.get("start", "n/a")
    end = search.get("end", "n/a")
    data_source = search.get("kind", "n/a")
    n_cslc = len(list((project_dir / "data").glob("OPERA_L2_CSLC-S1_*.h5"))) if (project_dir / "data").is_dir() else "n/a"
    hostname = ""
    try:
        hostname = subprocess.check_output(["hostname", "-f"], text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return [
        _fmt_kv("ProjectDir", project_dir),
        _fmt_kv("RunFilesDir", run_files_dir),
        _fmt_kv("Workflow", workflow),
        _fmt_kv("DataSource", data_source),
        _fmt_kv("Track", track),
        _fmt_kv("AOI_S_N_W_E", aoi),
        _fmt_kv("DateRange", f"{start} .. {end}"),
        _fmt_kv("N_cslc_files", n_cslc),
        _fmt_kv("JOB_SUBMISSION_SCHEME", os.environ.get("JOB_SUBMISSION_SCHEME", "")),
        _fmt_kv("Timestamp", stamp),
        _fmt_kv("Hostname", hostname),
    ]


def _format_step_row(
    step_key: str,
    stage: str,
    job_path: Path,
    job_ids: list[str],
    sacct_rows: dict[str, dict[str, str]],
    project_dir: Path,
    dolphin_cfg: dict,
) -> str:
    sbatch = _parse_sbatch(job_path)
    attempts = len(job_ids)
    elapsed_list: list[str] = []
    reserved_list: list[str] = []
    states: list[str] = []
    maxrss_vals: list[int] = []
    su_total = 0.0

    for jid in job_ids:
        row = sacct_rows.get(jid)
        if not row:
            continue
        elapsed_list.append(row["Elapsed"])
        reserved_list.append(row["Reserved"])
        states.append(row["State"])
        rss = row.get("MaxRSS", "")
        if rss and rss.isdigit():
            maxrss_vals.append(int(rss))
        nnodes = int(row.get("NNodes", "1") or 1)
        su_total += nnodes * _elapsed_to_seconds(row["Elapsed"]) / 3600.0

    elapsed_max_sec = max(_elapsed_to_seconds(e) for e in elapsed_list) if elapsed_list else 0
    elapsed_max = f"{elapsed_max_sec // 3600:02d}:{(elapsed_max_sec % 3600) // 60:02d}:{elapsed_max_sec % 60:02d}" if elapsed_list else "n/a"
    elapsed_sum = putils.sum_time(elapsed_list) if elapsed_list else "n/a"
    reserved_sum = putils.sum_time(reserved_list) if reserved_list else "n/a"
    state_last = states[-1] if states else "n/a"
    maxrss = max(maxrss_vals) if maxrss_vals else "n/a"

    parts = [
        f"{step_key}:",
        _fmt_kv("NAttempts", attempts if attempts else "n/a"),
        _fmt_kv("State_last", state_last),
        _fmt_kv("Queue", sbatch.get("queue", "n/a")),
        _fmt_kv("Elapsed_max", elapsed_max),
        _fmt_kv("Elapsed_sum", elapsed_sum),
        _fmt_kv("Reserved_sum", reserved_sum),
        _fmt_kv("MaxRSS_max", maxrss),
        _fmt_kv("SUs", f"{su_total:.1f}" if su_total else "n/a"),
    ]

    if stage == "create_cslc":
        launcher = _get_launcher_params(job_path)
        for key in ("launcher_file_lines", "LAUNCHER_PPN", "OMP_NUM_THREADS"):
            if key in launcher:
                parts.append(_fmt_kv(key, launcher[key]))

    unwrap = dolphin_cfg.get("unwrap_options") or {}
    timeseries = dolphin_cfg.get("timeseries_options") or {}
    worker = dolphin_cfg.get("worker_settings") or {}

    if stage == "dolphin_unwrap":
        n_unwrap = _compute_n_unwrap(project_dir)
        if n_unwrap is not None:
            parts.append(_fmt_kv("N_UNWRAP", n_unwrap))
        if unwrap.get("n_parallel_jobs") is not None:
            parts.append(_fmt_kv("n_parallel_jobs", unwrap.get("n_parallel_jobs")))

    if stage == "dolphin_timeseries":
        if timeseries.get("num_parallel_blocks") is not None:
            parts.append(_fmt_kv("num_parallel_blocks", timeseries.get("num_parallel_blocks")))
        if timeseries.get("block_shape") is not None:
            parts.append(_fmt_kv("block_shape", _yx_pair(timeseries.get("block_shape"))))

    if stage == "dolphin_wrapped" and worker.get("block_shape") is not None:
        parts.append(_fmt_kv("block_shape", _yx_pair(worker.get("block_shape"))))

    return "  ".join(parts)


def main(iargs: list[str] | None = None) -> int:
    args = create_parser().parse_args(iargs)
    run_files_dir = Path(args.run_files_dir).expanduser().resolve()
    if not run_files_dir.is_dir():
        print(f"Error: run_files directory not found: {run_files_dir}", file=sys.stderr)
        return 1
    if run_files_dir.name != "run_files":
        print(f"Warning: expected a run_files directory; got {run_files_dir}", file=sys.stderr)

    project_dir = run_files_dir.parent
    outdir = Path(args.outdir).expanduser().resolve() if args.outdir else project_dir
    outdir.mkdir(parents=True, exist_ok=True)

    sweets = _load_yaml(project_dir / "sweets_config.yaml")
    dolphin_cfg = _load_yaml(project_dir / "dolphin_config.yaml")
    n_bursts = _resolve_n_bursts(project_dir, sweets)

    steps = _discover_steps(run_files_dir)
    stages = []
    for _, step_key, _ in steps:
        parts = step_key.split("_", 2)
        if len(parts) >= 3:
            stages.append(parts[2])
    workflow = _workflow_from_stages(stages)

    all_job_ids: list[str] = []
    step_job_ids: dict[str, list[str]] = {}
    for step_num, step_key, job_path in steps:
        ids = _stdout_files_for_step(run_files_dir, step_key)
        step_job_ids[step_key] = ids
        all_job_ids.extend(ids)

    sacct_rows = _sacct_lookup(sorted(set(all_job_ids), key=int))

    lines: list[str] = []
    lines.append(
        "# Line1: Queue CPUs create_isce3 worker sizing; Line2: run-length key params; "
        "steps: NAttempts State Elapsed_max Elapsed_sum Reserved_sum MaxRSS SUs + stage parallelism"
    )
    lines.append(_build_line1(run_files_dir, n_bursts))
    lines.append(_build_line2(project_dir, run_files_dir, sweets, dolphin_cfg, n_bursts))
    lines.extend(_context_lines(project_dir, run_files_dir, workflow, sweets))

    total_elapsed: list[str] = []
    total_reserved: list[str] = []
    total_su = 0.0

    for step_num, step_key, job_path in steps:
        stage = step_key.split("_", 2)[2]
        row = _format_step_row(
            step_key,
            stage,
            job_path,
            step_job_ids.get(step_key, []),
            sacct_rows,
            project_dir,
            dolphin_cfg,
        )
        lines.append(row)
        for jid in step_job_ids.get(step_key, []):
            sacct_row = sacct_rows.get(jid)
            if sacct_row:
                total_elapsed.append(sacct_row["Elapsed"])
                total_reserved.append(sacct_row["Reserved"])
                nnodes = int(sacct_row.get("NNodes", "1") or 1)
                total_su += nnodes * _elapsed_to_seconds(sacct_row["Elapsed"]) / 3600.0

    if total_elapsed:
        elapsed_per_burst = putils.multiply_walltime(putils.sum_time(total_elapsed), factor=1 / max(1, n_bursts))
        lines.append(
            f"TOTAL: Elapsed_sum={putils.sum_time(total_elapsed)} Reserved_sum={putils.sum_time(total_reserved)} "
            f"SUs={total_su:.1f} Elapsed_per_burst={elapsed_per_burst}"
        )

    rerun_path = run_files_dir / "rerun.log"
    if rerun_path.is_file():
        lines.append("")
        lines.append("rerun.log:")
        lines.append(rerun_path.read_text(encoding="utf-8", errors="replace").rstrip())

    output = "\n".join(lines) + "\n"
    log_path = outdir / "walltimes_isce3.log"
    log_path.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
