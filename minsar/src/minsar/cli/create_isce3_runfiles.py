#!/usr/bin/env python3
"""Create transparent run files, SLURM job files, and output checks for ISCE3 workflows."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import runpy
import shlex
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from minsar.utils.bbox_cli_argv import fix_argv_for_negative_bbox_sn_we


WORKFLOW_CHOICES = ("safe", "cslc", "disp")
SWEETS_CONFIG = "sweets_config.yaml"
DATA_TYPE_ALIASES = {
    "safe": "safe",
    "cslc": "cslc",
    "disp": "disp",
    "disps1": "disp",
    "disp-s1": "disp",
    "disp-ni": "disp-ni",
    "dispni": "disp-ni",
}
PIXI_STAGES = frozenset({
    "download_disp",
    "reformat_disp",
    "download_cslc",
    "download_safe",
    "dolphin",
    "dolphin_wrapped",
    "dolphin_unwrap",
    "dolphin_timeseries",
})
DOLPHIN_SPLIT_STAGES = ("dolphin_wrapped", "dolphin_unwrap", "dolphin_timeseries")
# Named dolphin parameter sets for CSLC (strides + half-window).
# half_window is (y, x); strides is (y, x). Non-dolphin presets use OPERA 30 m posting.
# User-facing half-window sizes are given as x×y (range × azimuth).
DOLPHIN_PRESETS: dict[str, dict[str, tuple[int, int] | None]] = {
    "dolphin": {"strides": None, "half_window": None},  # package defaults (1×1, hwy=7,hwx=14)
    "standard": {"strides": (3, 6), "half_window": (8, 16)},
    "dry": {"strides": (3, 6), "half_window": (6, 12)},
    "wet": {"strides": (3, 6), "half_window": (9, 18)},
    "arctic": {"strides": (3, 6), "half_window": (9, 19)},
}
DOLPHIN_PRESET_CHOICES = tuple(DOLPHIN_PRESETS)
_OPERA_BURST_ID_RE = re.compile(r"(T\d{3}-\d+-IW\d)")

ARGV_FIX_KW = {
    "consume_one": (
        "--data-type",
        "--platform",
        "--flight-dir",
        "--start-date",
        "--start",
        "--end-date",
        "--end",
        "--track",
        "--frame-id",
        "--queue",
        "--long-queue",
        "--config",
        "--sleep",
        "--preset",
    ),
    "consume_two": (),
    "flags": ("--safe", "--cslc", "--disp", "--disp-S1", "--dry-run", "--run", "--no-dolphin-split"),
}


def _log_command_line(log_dir: Path, script_name: str, argv: list[str]) -> None:
    """Append the invocation to log_dir/log (cwd where the program was run)."""
    simplified = []
    for arg in argv:
        if os.environ.get("SCRATCHDIR") and arg.startswith(os.environ["SCRATCHDIR"]):
            simplified.append("$SCRATCHDIR" + arg[len(os.environ["SCRATCHDIR"]):])
        elif os.environ.get("SAMPLESDIR") and arg.startswith(os.environ["SAMPLESDIR"]):
            simplified.append("$SAMPLESDIR" + arg[len(os.environ["SAMPLESDIR"]):])
        elif os.environ.get("TE") and arg.startswith(os.environ["TE"]):
            simplified.append("$TE" + arg[len(os.environ["TE"]):])
        else:
            simplified.append(arg)
    stamp = datetime.datetime.now().strftime("%Y%m%d:%H-%M")
    line = f"{stamp} + {script_name}"
    if simplified:
        line += " " + " ".join(simplified)
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


@dataclass(frozen=True)
class ResourceProfile:
    """Resource and execution policy for one workflow stage."""

    execution_mode: str
    walltime: str
    memory_mb: int
    num_threads: int
    queue_class: str


@dataclass
class Stage:
    """One ordered workflow stage used to generate run and job files."""

    number: int
    name: str
    title: str
    execution_mode: str
    run_file: str
    job_file: str
    command: str
    queue: str
    walltime: str
    memory_mb: int
    num_threads: int


def _require_job_env() -> None:
    """Fail early when MinSAR job-submission environment is incomplete."""
    missing = [
        name
        for name in ("JOBSHEDULER_PROJECTNAME", "JOBSCHEDULER", "PLATFORM_NAME", "MINSAR_HOME")
        if not os.getenv(name)
    ]
    if missing:
        raise RuntimeError(
            "MinSAR job environment incomplete (missing "
            + ", ".join(missing)
            + "); source setup/environment.bash (or equivalent) before creating job files"
        )
    if not os.getenv("ISCE_STACK"):
        # JOB_SUBMIT always builds a topsStack/stripmapStack path; a placeholder is enough for headers.
        os.environ["ISCE_STACK"] = str(Path(os.environ["MINSAR_HOME"]) / "tools" / "isce2" / "contrib" / "stack")


def _cap_walltime_for_queue(walltime: str, queue: str, wall_time_factor: float) -> str:
    """Apply queues.cfg WALLTIME_FACTOR then cap at MAX_WALLTIME for the queue."""
    import minsar.utils.process_utilities as putils

    scaled = putils.multiply_walltime(walltime, factor=wall_time_factor)
    platform = os.getenv("PLATFORM_NAME", "stampede3")
    queue_params = putils.get_queue_rerun_params(platform, queue)
    max_wt = queue_params["MAX_WALLTIME"]
    if max_wt.lower() in ("n/a", "na", ""):
        return scaled
    max_sec = putils.walltime_to_seconds(max_wt)
    cur_sec = putils.walltime_to_seconds(scaled)
    if cur_sec <= max_sec:
        return scaled
    hours = max_sec // 3600
    minutes = (max_sec % 3600) // 60
    seconds = max_sec % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _make_job_submit(project_dir: Path, run_dir: Path, queue: str, profile: ResourceProfile):
    """Construct JOB_SUBMIT so set_job_queue_values loads queues.cfg for this queue."""
    _require_job_env()
    from minsar.job_submission import JOB_SUBMIT

    inps = argparse.Namespace(
        queue=queue,
        work_dir=str(project_dir),
        out_dir=str(run_dir),
        num_data=1,
        wall_time=profile.walltime,
        memory=str(profile.memory_mb),
        num_memory_units=None,
        copy_to_tmp=False,
        remora=False,
        custom_template_file=None,
        reserve_node=1,
    )
    job = JOB_SUBMIT(inps)
    job.default_wall_time = _cap_walltime_for_queue(profile.walltime, queue, float(job.wall_time_factor))
    job.default_memory = profile.memory_mb
    job.default_num_threads = profile.num_threads
    job.number_of_parallel_tasks_per_node = min(
        max(1, int(job.number_of_cores_per_node) // max(1, profile.num_threads)),
        max(1, int(job.max_memory_per_node) // max(1, profile.memory_mb)),
    )
    job.email_notif = bool(os.getenv("NOTIFICATIONEMAIL"))
    job.queue = queue
    return job


def _dolphin_worker_counts(cpus_per_node: int, n_bursts_aoi: int) -> tuple[int, int, int]:
    """Choose dolphin parallel knobs from node CPUs and distinct burst count.

    Returns (n_parallel_bursts, threads_per_worker, n_parallel_jobs).
    Linking: fill the node with min(bursts, cpus//4) workers and the rest as threads.
    Unwrap: ~cpus/4 concurrent snaphu jobs (unchanged by burst count).
    """
    cpus = max(1, int(cpus_per_node))
    n_bursts = max(1, int(n_bursts_aoi))
    n_parallel = max(1, min(n_bursts, cpus // 4))
    threads = max(1, cpus // n_parallel)
    n_unwrap = max(1, cpus // 4)
    return n_parallel, threads, n_unwrap


def _dolphin_worker_cli_flags(cpus_per_node: int, n_bursts_aoi: int) -> str:
    """CLI flags so dolphin uses most of a 1-node allocation (type B defaults)."""
    n_parallel, threads, n_unwrap = _dolphin_worker_counts(cpus_per_node, n_bursts_aoi)
    return (
        f"--n-parallel-bursts {n_parallel} "
        f"--worker-settings.threads-per-worker {threads} "
        f"--unwrap-options.n-parallel-jobs {n_unwrap}"
    )


def _count_opera_cslc_bursts(data_dir: Path) -> tuple[int, bool]:
    """Return distinct OPERA burst count under data/ and whether files were found."""
    burst_ids: set[str] = set()
    for path in sorted(data_dir.glob("OPERA_L2_CSLC-S1_*.h5")):
        match = _OPERA_BURST_ID_RE.search(path.name)
        if match:
            burst_ids.add(match.group(1))
    if not burst_ids:
        return 1, False
    return len(burst_ids), True


def _strip_bash_script_header(text: str) -> str:
    """Return command body without shebang or leading set -e lines."""
    body: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not body:
            if not stripped or stripped.startswith("#!"):
                continue
            if stripped.startswith("set -"):
                continue
        body.append(line)
    return "\n".join(body).strip()


def _pixi_run_script(commands: str) -> str:
    """Executable run file that runs stage commands inside the SWEETS pixi environment."""
    body = _strip_bash_script_header(commands)
    if not body:
        body = "true"
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'export PATH="$MINSAR_HOME/minsar/utils:$MINSAR_HOME/minsar/bin:$MINSAR_HOME/minsar/scripts:$PATH"\n'
        'export PYTHONPATH="$MINSAR_HOME${PYTHONPATH:+:$PYTHONPATH}"\n'
        'pixi run --manifest-path "$MINSAR_HOME/tools/sweets/pyproject.toml" -- bash <<\'ISCE3_PIXI_BODY\'\n'
        "set -euo pipefail\n"
        "\n"
        f"{body}\n"
        "\n"
        "ISCE3_PIXI_BODY\n"
    )


def _dolphin_stop_after_stitch_flags() -> str:
    """Dolphin config flags for wrapped + stitch only (no unwrap or timeseries)."""
    return (
        "--unwrap-options.no-run-unwrap "
        "--timeseries-options.no-run-inversion "
        "--timeseries-options.no-run-velocity"
    )


def _normalize_dolphin_preset(value: str) -> str:
    token = value.strip().lower().replace("_", "-")
    if token in {"disp", "disp-s1", "disps1"}:
        raise argparse.ArgumentTypeError(
            f"preset {value!r} is not defined; use one of {', '.join(DOLPHIN_PRESET_CHOICES)}"
        )
    if token not in DOLPHIN_PRESETS:
        raise argparse.ArgumentTypeError(
            f"invalid preset {value!r}; use {', '.join(DOLPHIN_PRESET_CHOICES)}"
        )
    return token


def _dolphin_preset_cli_flags(preset: str) -> str:
    """CLI flags for strides and half-window; empty string for dolphin package defaults."""
    spec = DOLPHIN_PRESETS[preset]
    strides = spec["strides"]
    half_window = spec["half_window"]
    if strides is None and half_window is None:
        return ""
    parts: list[str] = []
    if strides is not None:
        sy, sx = strides
        parts.append(f"--sy {sy} --sx {sx}")
    if half_window is not None:
        hwy, hwx = half_window
        parts.append(f"--hwy {hwy} --hwx {hwx}")
    return " ".join(parts)


def _geometry_stitch_command(preset: str, config_name: str = SWEETS_CONFIG) -> str:
    """stitch_sweets_geometry command with strides matching the dolphin preset."""
    spec = DOLPHIN_PRESETS[preset]
    strides = spec["strides"]
    if strides is None:
        # dolphin preset: native CSLC posting (match dolphin package strides 1×1)
        sy, sx = 1, 1
    else:
        sy, sx = strides
    return f"stitch_sweets_geometry.py --config {config_name} --sy {sy} --sx {sx} --overwrite"


def _cslc_dolphin_config_line(
    config_line: str,
    cpus_per_node: int,
    n_bursts_aoi: int,
    extra_flags: str = "",
    outfile: str = "dolphin_config.yaml",
    preset: str = "dolphin",
) -> str:
    """One-line dolphin config command with worker and preset flags baked in."""
    west, south, east, north = _bbox_wsene_from_sweets_line(config_line)
    worker_flags = _dolphin_worker_cli_flags(cpus_per_node, n_bursts_aoi)
    preset_flags = _dolphin_preset_cli_flags(preset)
    parts = [
        "dolphin config --slc-files data/OPERA_L2_CSLC-S1_*.h5 --subdataset /data/VV "
        "--work-directory dolphin --mask-file watermask.tif "
        f"--output-options.bounds {west} {south} {east} {north} "
        f"{worker_flags}"
    ]
    if preset_flags:
        parts.append(f" {preset_flags}")
    if extra_flags:
        parts.append(f" {extra_flags}")
    parts.append(f" --outfile {outfile}")
    return "".join(parts)


def _cslc_dolphin_commands(
    config_line: str,
    cpus_per_node: int,
    n_bursts_aoi: int,
    preset: str = "dolphin",
) -> list[str]:
    """Shell commands for CSLC dolphin config + run with worker flags baked in."""
    return [
        _cslc_dolphin_config_line(config_line, cpus_per_node, n_bursts_aoi, preset=preset),
        "dolphin run dolphin_config.yaml",
    ]


def _cslc_dolphin_wrapped_commands(
    config_line: str,
    cpus_per_node: int,
    n_bursts_aoi: int,
    preset: str = "dolphin",
) -> list[str]:
    """CSLC dolphin_wrapped: phase linking + stitch; writes dolphin_config.yaml."""
    return [
        _cslc_dolphin_config_line(
            config_line,
            cpus_per_node,
            n_bursts_aoi,
            extra_flags=_dolphin_stop_after_stitch_flags(),
            preset=preset,
        ),
        "dolphin run dolphin_config.yaml",
    ]


def _cslc_dolphin_unwrap_commands() -> list[str]:
    """CSLC dolphin_unwrap: memory-aware n_parallel_jobs then unwrap-only."""
    return [
        'N_UNWRAP=$(resize_dolphin_unwrap_jobfile.py .)',
        'run_dolphin_unwrap.py --n-parallel-jobs "$N_UNWRAP"',
    ]


def _cslc_dolphin_timeseries_commands() -> list[str]:
    """CSLC dolphin_timeseries: inversion/velocity only."""
    return ["run_dolphin_timeseries.py"]


class Isce3JobAdapter:
    """Render ISCE3 job files via JOB_SUBMIT (queues.cfg-backed resources)."""

    def __init__(
        self,
        project_dir: Path,
        run_dir: Path,
        queue: str,
        profile: ResourceProfile,
        sleep_secs: int | None = None,
    ) -> None:
        self.queue = queue
        self.sleep_secs = sleep_secs
        self.job_submit = _make_job_submit(project_dir, run_dir, queue, profile)
        self.launcher_ppn = int(self.job_submit.number_of_parallel_tasks_per_node)
        self.cpus_per_node = int(self.job_submit.number_of_cores_per_node)

    def _sleep_lines(self) -> list[str]:
        if not self.sleep_secs:
            return []
        return [
            f"echo Sleeping {self.sleep_secs} seconds before starting...\n",
            f"sleep {self.sleep_secs}\n",
        ]

    def render(self, stage: Stage, run_file: Path, job_file: Path, workflow: str) -> None:
        """Render a script or LAUNCHER job using JOB_SUBMIT's existing methods."""
        stage.walltime = self.job_submit.default_wall_time
        lines = self.job_submit.get_job_file_lines(
            stage.name,
            job_file.stem,
            number_of_nodes=1,
            work_dir=str(job_file.parent),
        )
        work_dir = run_file.parent.parent.resolve()
        validate_cmd = f"validate_isce3_outputs.py --data-type {shlex.quote(workflow)} --step {shlex.quote(stage.name)}"
        sleep_lines = self._sleep_lines()
        if stage.execution_mode == "launcher-task-list":
            lines.extend(
                [
                    "\nset -euo pipefail\n",
                    *sleep_lines,
                    f"export OMP_NUM_THREADS={stage.num_threads}\n",
                    f"export LAUNCHER_PPN={self.launcher_ppn}\n",
                    "export LAUNCHER_NHOSTS=1\n",
                    f"export LAUNCHER_JOB_FILE={shlex.quote(str(run_file.resolve()))}\n",
                    "export LAUNCHER_WORKDIR=/dev/shm\n",
                    'cd "$LAUNCHER_WORKDIR"\n',
                    'if [[ -z "${LAUNCHER_DIR:-}" ]]; then echo "LAUNCHER_DIR is not set" >&2; exit 2; fi\n',
                    '"$LAUNCHER_DIR/paramrun"\n',
                    f"cd {shlex.quote(str(work_dir))}\n",
                ]
            )
        else:
            lines.extend(["\nset -euo pipefail\n", *sleep_lines, f"cd {shlex.quote(str(work_dir))}\n"])
            lines.append(f"bash {shlex.quote(str(run_file.relative_to(work_dir)))}\n")
        lines.append(f"{validate_cmd}\n")
        job_file.write_text("".join(lines))
        _make_executable(job_file)


def _parse_data_type(value: str) -> str:
    """Normalize --data-type to an internal workflow name."""
    token = value.strip().lower().replace("_", "-")
    if token not in DATA_TYPE_ALIASES:
        raise argparse.ArgumentTypeError(f"invalid data type {value!r}; use safe, cslc, dispS1, or disp-NI")
    return DATA_TYPE_ALIASES[token]


def create_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    epilog = """Examples:
 create_isce3_runfiles.py HawaiiSenD87.template
 create_isce3_runfiles.py HawaiiSenD87.template --data-type cslc
 create_isce3_runfiles.py HawaiiSenD87.template --data-type cslc --no-dolphin-split
 create_isce3_runfiles.py HawaiiSenD87.template --data-type dispS1 --run
 create_isce3_runfiles.py HawaiiSenD87.template --data-type cslc --preset standard
 create_isce3_runfiles.py HawaiiSenD87.template --data-type cslc --sleep 3600
 create_isce3_runfiles.py 19.4:19.54,-155.02:-154.80 HawaiiPuna --flight-dir desc --disp-S1"""
    parser = argparse.ArgumentParser(
        description="Create run files and SLURM job files for SAFE, CSLC, or DISP-S1 processing.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="MinSAR template, or AOI when followed by NAME")
    parser.add_argument("name", nargs="?", help="project name when INPUT is an AOI")
    parser.add_argument("--safe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cslc", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--disp-S1", "--disp", dest="disp", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--data-type",
        type=_parse_data_type,
        metavar="TYPE",
        help="starting data type {safe,cslc,dispS1,disp-NI} (else use --safe, etc)",
    )
    parser.add_argument("--platform", default="S1", help="platform: S1 or NISAR/NI")
    parser.add_argument("--flight-dir", choices=("asc", "desc"), help="flight direction for AOI input")
    parser.add_argument("--start-date", "--start", dest="start_date", help="first date YYYYMMDD (default: ssaraopt.startDate from template)")
    parser.add_argument("--end-date", "--end", dest="end_date", help="last date YYYYMMDD (default: ssaraopt.endDate from template)")
    parser.add_argument("--track", type=int, help="relative orbit/track number")
    parser.add_argument("--frame-id", type=int, help="OPERA DISP-S1 frame ID")
    parser.add_argument(
        "--queue",
        default=os.getenv("QUEUENAME"),
        help="SLURM partition for restart-safe jobs (default: $QUEUENAME)",
    )
    parser.add_argument("--long-queue", default="skx", help="SLURM partition for unsafe or unknown restart behavior")
    parser.add_argument("--config", type=Path, help="ISCE3 job defaults file")
    parser.add_argument(
        "--preset",
        type=_normalize_dolphin_preset,
        default="dolphin",
        metavar="NAME",
        help=(
            "dolphin strides/half-window preset for CSLC: "
            f"{', '.join(DOLPHIN_PRESET_CHOICES)} (default: dolphin)"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="print the workflow without writing files or querying services")
    parser.add_argument(
        "--no-dolphin-split",
        action="store_true",
        help="CSLC only: one dolphin stage instead of dolphin_wrapped, dolphin_unwrap, dolphin_timeseries",
    )
    parser.add_argument(
        "--sleep",
        type=int,
        metavar="SECS",
        default=None,
        help="sleep seconds in each SLURM job file before the stage runs",
    )
    parser.add_argument("--run", action="store_true", help="after creating files, run run_isce3_workflow.bash --start 1 --end N")
    return parser


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _q(value: str | Path) -> str:
    return shlex.quote(str(value))


def _workflow_name(args: argparse.Namespace) -> str:
    flag_labels = {"safe": "--safe", "cslc": "--cslc", "disp": "--disp-S1"}
    flags = [name for name in WORKFLOW_CHOICES if getattr(args, name, False)]
    if len(flags) > 1:
        raise ValueError(f"conflicting data-type flags: {', '.join(flag_labels[name] for name in flags)}")
    if args.data_type and flags and args.data_type != flags[0]:
        raise ValueError(f"--data-type {args.data_type} conflicts with {flag_labels[flags[0]]}")
    name = args.data_type or (flags[0] if flags else "safe")
    if name == "disp-ni":
        raise ValueError("disp-NI is accepted but processing is not implemented")
    return name


def _run_isce3_workflow(work_dir: Path, end_step: int) -> int:
    """cd to the project dir and run the generated workflow from step 1 through end_step."""
    runner = Path(__file__).resolve().parent / "run_isce3_workflow.bash"
    if not runner.is_file():
        raise RuntimeError(f"run_isce3_workflow.bash not found: {runner}")
    command = [str(runner), "--start", "1", "--end", str(end_step)]
    print(f"Running: {' '.join(command)} (cwd={work_dir})")
    completed = subprocess.run(command, cwd=work_dir, check=False)
    return completed.returncode


def _normalize_platform(value: str) -> str:
    token = value.strip().upper().replace("-", "")
    if token in {"S1", "SENTINEL1", "SEN"}:
        return "S1"
    if token in {"NI", "NISAR"}:
        return "NISAR"
    raise ValueError(f"unknown platform {value!r}; use S1 or NISAR")


def _read_profiles(path: Path) -> dict[str, ResourceProfile]:
    columns = [
        "jobname",
        "c_walltime",
        "s_walltime",
        "seconds_factor",
        "c_memory",
        "s_memory",
        "num_threads",
        "io_load",
        "rerun_walltime_factor",
        "switch_queue",
        "rerun_walltime_factor_switch",
        "execution_mode",
        "queue_class",
    ]
    profiles: dict[str, ResourceProfile] = {}
    header_found = False
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        text = line.strip()
        if not text or text.startswith("#") or text.startswith("-"):
            continue
        fields = text.split()
        if fields[0] == "jobname":
            if fields != columns:
                raise ValueError(f"{path}:{line_number}: unexpected column header")
            header_found = True
            continue
        if not header_found:
            raise ValueError(f"{path}:{line_number}: data found before jobname header")
        if len(fields) != len(columns):
            raise ValueError(f"{path}:{line_number}: expected {len(columns)} columns, found {len(fields)}")
        values = dict(zip(columns, fields))
        name = values["jobname"]
        mode = values["execution_mode"]
        if mode not in {"sequential", "single-multicore", "launcher-task-list"}:
            raise ValueError(f"{path}:{line_number}: unsupported execution mode {mode!r}")
        queue_class = values["queue_class"]
        if queue_class not in {"short", "long"}:
            raise ValueError(f"{path}:{line_number}: unsupported queue class {queue_class!r}")
        profiles[name] = ResourceProfile(
            mode,
            values["c_walltime"],
            int(values["c_memory"]),
            int(values["num_threads"]),
            queue_class,
        )
    if not header_found:
        raise ValueError(f"{path}: missing jobname header")
    if "default" not in profiles:
        raise ValueError(f"{path}: missing default profile")
    return profiles


def _ssaraopt_date_yyyymmdd(options: dict, key: str) -> str:
    """Return template ssaraopt date as YYYYMMDD, or '' if missing/invalid."""
    from minsar.utils.ssaraopt_to_mintpy_plot import parse_ssaraopt_date

    parsed = parse_ssaraopt_date(options.get(key))
    if parsed is None:
        return ""
    return parsed.strftime("%Y%m%d")


def _template_context(template_file: Path, args: argparse.Namespace) -> dict[str, object]:
    from minsar.objects.dataset_template import Template

    template = Template(str(template_file))
    template.get_options()
    options = template.options
    project = template_file.stem.replace(".template", "")
    subset = options.get("miaplpy.subset.lalo", "")
    if not subset:
        raise ValueError(f"template requires miaplpy.subset.lalo: {template_file}")
    start_date = args.start_date or _ssaraopt_date_yyyymmdd(options, "ssaraopt.startDate")
    end_date = args.end_date or _ssaraopt_date_yyyymmdd(options, "ssaraopt.endDate")
    return {
        "project": project,
        "template": str(template_file.resolve()),
        "aoi": str(subset).strip().strip("'\""),
        "start_date": start_date or "",
        "end_date": end_date or "",
        "track": str(args.track or ""),
        "frame_id": str(args.frame_id or ""),
        "flight_direction": args.flight_dir or "",
    }


def _aoi_context(args: argparse.Namespace) -> dict[str, object]:
    if not args.name:
        raise ValueError("AOI input requires a project NAME")
    if not args.flight_dir:
        raise ValueError("AOI input requires --flight-dir asc or desc")
    return {
        "project": args.name,
        "template": "",
        "aoi": args.input,
        "start_date": args.start_date or "",
        "end_date": args.end_date or "",
        "track": str(args.track or ""),
        "frame_id": str(args.frame_id or ""),
        "flight_direction": args.flight_dir,
    }


def _create_template_from_aoi(args: argparse.Namespace) -> Path:
    """Create the standard MinSAR template used by downstream generators."""
    from minsar.scripts.create_template import main as create_template

    if not args.name:
        raise ValueError("AOI input requires a project NAME")
    if not args.flight_dir:
        raise ValueError("AOI input requires --flight-dir asc or desc")
    command = [args.input, args.name, "--flight-dir", args.flight_dir, "--platform", "S1"]
    if args.start_date:
        command.extend(["--start-date", args.start_date])
    if args.end_date:
        command.extend(["--end-date", args.end_date])
    status, template_file, _, _ = create_template(command)
    if status or template_file is None:
        raise RuntimeError("create_template.py could not resolve the AOI into a MinSAR template")
    return Path(template_file)


def _runner_command(command: str) -> str:
    return f'pixi run --manifest-path "$MINSAR_HOME/tools/sweets/pyproject.toml" {command}'


def _use_dolphin_split(workflow: str, no_dolphin_split: bool) -> bool:
    """Return True when CSLC workflow should use split dolphin stages (default)."""
    return workflow == "cslc" and not no_dolphin_split


def _dolphin_stage_specs(split_dolphin: bool) -> list[tuple[str, str]]:
    if split_dolphin:
        return [
            ("dolphin_wrapped", "Run Dolphin phase linking and stitch"),
            ("dolphin_unwrap", "Unwrap stitched interferograms"),
            ("dolphin_timeseries", "Run Dolphin timeseries inversion"),
        ]
    return [("dolphin", "Run Dolphin displacement processing")]


def _build_stage_specs(workflow: str, context: dict[str, object], split_dolphin: bool = False) -> list[tuple[str, str, str]]:
    dolphin_specs = [(name, title, "") for name, title in _dolphin_stage_specs(split_dolphin)]
    if workflow == "safe":
        return [
            ("download_safe", "Download and verify SAFE data, then prepare COMPASS runconfigs", ""),
            ("create_cslc", "Create CSLCs and static layers with COMPASS", ""),
            *dolphin_specs,
            ("create_hdfeos5", "Create HDF-EOS5 product", ""),
            ("ingest_insarmaps", "Ingest HDF-EOS5 product into InsarMaps", ""),
        ]
    if workflow == "cslc":
        return [
            ("download_cslc", "Download and verify OPERA CSLCs, then prepare geometry", ""),
            *dolphin_specs,
            ("create_hdfeos5", "Create HDF-EOS5 product", ""),
            ("ingest_insarmaps", "Ingest HDF-EOS5 product into InsarMaps", ""),
        ]
    template = str(context["template"])
    generate = "" if template else "true"
    return [
        ("download_disp", "Download and verify OPERA DISP-S1 products", generate),
        ("reformat_disp", "Reformat DISP-S1 products into a stack", generate),
        ("create_hdfeos5", "Create HDF-EOS5 product", generate),
        ("ingest_insarmaps", "Ingest HDF-EOS5 product into InsarMaps", generate),
    ]


def _profile_for(name: str, profiles: dict[str, ResourceProfile]) -> ResourceProfile:
    return profiles.get(name, profiles["default"])


def _write_run_file(path: Path, title: str, command: str, task_list: bool = False, raw: bool = False) -> None:
    if task_list:
        text = command if command.endswith("\n") else f"{command}\n"
        path.write_text(text)
        return
    if raw:
        text = command if command.endswith("\n") else f"{command}\n"
        path.write_text(text)
        if text.startswith("#!"):
            _make_executable(path)
        return
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"{command}\n"
    )
    _make_executable(path)


def _create_files(
    args: argparse.Namespace,
    workflow: str,
    context: dict[str, object],
    profiles: dict[str, ResourceProfile],
    work_dir: Path,
) -> list[Stage]:
    run_dir = work_dir / "run_files"
    run_dir.mkdir(parents=True, exist_ok=True)
    specs = _build_stage_specs(
        workflow, context, split_dolphin=_use_dolphin_split(workflow, args.no_dolphin_split)
    )
    split_dolphin = _use_dolphin_split(workflow, args.no_dolphin_split)
    dolphin_profile_name = "dolphin_wrapped" if split_dolphin else "dolphin"
    dolphin_profile = _profile_for(dolphin_profile_name, profiles)
    dolphin_queue = args.queue if dolphin_profile.queue_class == "short" else args.long_queue
    dolphin_cpus = int(_make_job_submit(work_dir, run_dir, dolphin_queue, dolphin_profile).number_of_cores_per_node)
    if workflow == "disp":
        bodies = _disp_stage_bodies(context, work_dir)
    elif workflow in {"safe", "cslc"}:
        bodies = _sweets_stage_bodies(
            workflow,
            context,
            dolphin_cpus,
            work_dir,
            split_dolphin=split_dolphin,
            preset=args.preset,
        )
    else:
        bodies = None
    if bodies is not None:
        missing = [name for name, _, _ in specs if name not in bodies]
        if missing:
            raise RuntimeError(f"{workflow} stage commands missing: {', '.join(missing)}")
        specs = [(name, title, bodies[name]) for name, title, _ in specs]
    expected_names = {
        filename
        for number, (name, _, _) in enumerate(specs, 1)
        for filename in (f"run_{number:02d}_{name}", f"run_{number:02d}_{name}.job")
    }
    stale_files = sorted(
        path
        for path in run_dir.glob("run_[0-9][0-9]_*")
        if path.suffix in {"", ".job"} and path.name not in expected_names
    )
    for path in stale_files:
        path.unlink()
    stages: list[Stage] = []
    for number, (name, title, command) in enumerate(specs, 1):
        profile = _profile_for(name, profiles)
        run_name = f"run_{number:02d}_{name}"
        job_name = f"{run_name}.job"
        run_file = run_dir / run_name
        job_file = run_dir / job_name
        stage = Stage(
            number,
            name,
            title,
            profile.execution_mode,
            str(run_file.relative_to(work_dir)),
            str(job_file.relative_to(work_dir)),
            command,
            args.queue if profile.queue_class == "short" else args.long_queue,
            profile.walltime,
            profile.memory_mb,
            profile.num_threads,
        )
        run_command = command
        if name in PIXI_STAGES and profile.execution_mode != "launcher-task-list":
            run_command = _pixi_run_script(command)
        _write_run_file(
            run_file,
            title,
            run_command,
            task_list=profile.execution_mode == "launcher-task-list",
            raw=True,
        )
        Isce3JobAdapter(
            work_dir, run_dir, stage.queue, profile, sleep_secs=args.sleep
        ).render(stage, run_file, job_file, workflow)
        stages.append(stage)
    return stages


def _print_plan(
    workflow: str,
    platform: str,
    context: dict[str, object],
    stages: list[Stage] | None,
    specs: list[tuple[str, str, str]] | None = None,
    queue: str | None = None,
    long_queue: str | None = None,
    preset: str | None = None,
) -> None:
    print(f"Workflow: {workflow.upper()} ({platform})")
    print(f"Project:  {context['project']}")
    if preset is not None and workflow in {"cslc", "safe"}:
        print(f"Preset:   {preset}")
    if queue is not None:
        print(f"Queue:    {queue} (long: {long_queue})")
    if stages is not None:
        run_files = [Path(stage.run_file).name for stage in stages]
        print(f"run_files created: {', '.join(run_files)}")
    else:
        run_files = [f"run_{number:02d}_{name}" for number, (name, _, _) in enumerate(specs or [], 1)]
        print(f"run_files to create: {', '.join(run_files)}")


def _run_in_sweets(work_dir: Path, command: list[str]) -> None:
    """Run one command in the canonical SWEETS Pixi environment."""
    minsar_home = Path(os.environ.get("MINSAR_HOME", Path(__file__).resolve().parents[4]))
    pixi_command = [
        "pixi",
        "run",
        "--manifest-path",
        str(minsar_home / "tools/sweets/pyproject.toml"),
        *command,
    ]
    env = os.environ.copy()
    env["MINSAR_HOME"] = str(minsar_home)
    env["PYTHONPATH"] = str(minsar_home)
    subprocess.run(pixi_command, cwd=work_dir, env=env, check=True)


def _configure_sweets(workflow: str, template: Path, work_dir: Path) -> None:
    """Build and run only the SWEETS config command, leaving processing split by stage."""
    from minsar.utils.generate_sweets_config import build_from_template

    source = "burst" if workflow == "safe" else "cslc"
    command, _ = build_from_template(str(template), source)
    config_command = command.splitlines()[0] + " --overwrite"
    transparent_command = _runner_command(config_command)
    config_script = work_dir / "sweets_config_command.bash"
    config_script.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + transparent_command + "\n")
    _make_executable(config_script)
    subprocess.run([str(config_script)], cwd=work_dir, check=True)


def _sweets_config_line(workflow: str, context: dict[str, object]) -> str:
    """Return the one-line sweets config command with --overwrite."""
    from minsar.utils.generate_sweets_config import build_from_template

    template = str(context["template"])
    if not template:
        raise ValueError(f"{workflow} workflow requires a MinSAR template")
    source = "burst" if workflow == "safe" else "cslc"
    start_date = str(context["start_date"] or "") or None
    end_date = str(context["end_date"] or "") or None
    track_raw = str(context["track"] or "")
    track = int(track_raw) if track_raw else None
    flight_direction = str(context["flight_direction"] or "") or None
    command, _ = build_from_template(
        template,
        source,
        start_date=start_date,
        end_date=end_date,
        track=track,
        flight_direction=flight_direction,
    )
    line = command.splitlines()[0]
    if "--overwrite" not in line.split():
        line += " --overwrite"
    return line


def _bash_script(*commands: str) -> str:
    """Shebang script with set -e, one command per line."""
    return "#!/usr/bin/env bash\nset -e\n" + "".join(f"{command}\n" for command in commands)


def _bbox_wsene_from_sweets_line(line: str) -> tuple[str, str, str, str]:
    """Return west south east north from a sweets config command line."""
    parts = line.split()
    try:
        idx = parts.index("--bbox")
        return parts[idx + 1], parts[idx + 2], parts[idx + 3], parts[idx + 4]
    except (IndexError, ValueError) as exc:
        raise RuntimeError("sweets config command is missing --bbox") from exc


def _cslc_dolphin_script(
    config_line: str,
    cpus_per_node: int,
    n_bursts_aoi: int,
    preset: str = "dolphin",
) -> str:
    """Commands for CSLC dolphin config + run with worker flags baked in."""
    return (
        "\n".join(
            _cslc_dolphin_commands(config_line, cpus_per_node, n_bursts_aoi, preset=preset)
        )
        + "\n"
    )


def _sweets_download_script(config_line: str, kind: str) -> str:
    """Download/check/retry script for SAFE or CSLC with explicit config and kind."""
    cfg = SWEETS_CONFIG
    return _bash_script(
        config_line,
        f"sweets_download.py --config {cfg}",
        f"check_sweets_download.py --config {cfg} --kind {kind} --delete --redownload",
        f"check_sweets_download.py --config {cfg} --kind {kind}",
    )


def _sweets_stage_bodies(
    workflow: str,
    context: dict[str, object],
    cpus_per_node: int,
    work_dir: Path,
    split_dolphin: bool = False,
    preset: str = "dolphin",
) -> dict[str, str]:
    """Resolve concrete SAFE or CSLC run-file bodies at generate time."""
    config_line = _sweets_config_line(workflow, context)
    kind = "safe" if workflow == "safe" else "cslc"
    cfg = SWEETS_CONFIG
    download = _sweets_download_script(config_line, kind)
    hdfeos5 = "dolphin2hdfeos5.py dolphin"
    ingest = "ingest_insarmaps.bash dolphin/timeseries"
    geom = _geometry_stitch_command(preset, cfg)
    if workflow == "safe":
        return {
            "download_safe": download.rstrip("\n") + f"\nprepare_compass_runconfigs.py --config {cfg}\n",
            "create_cslc": "",
            "dolphin": _bash_script(
                geom,
                f"sweets run {cfg} --starting-step 3",
            ),
            "create_hdfeos5": hdfeos5,
            "ingest_insarmaps": ingest,
        }
    n_bursts, from_files = _count_opera_cslc_bursts(work_dir / "data")
    if not from_files:
        print(
            f"Warning: no OPERA CSLC under {work_dir / 'data'}; "
            f"dolphin worker flags assume n_bursts=1 (re-run create_isce3_runfiles after download)",
            file=sys.stderr,
        )
    if split_dolphin:
        return {
            "download_cslc": download.rstrip("\n") + f"\n{geom}\n",
            "dolphin_wrapped": "\n".join(
                _cslc_dolphin_wrapped_commands(
                    config_line, cpus_per_node, n_bursts, preset=preset
                )
            )
            + "\n",
            "dolphin_unwrap": "\n".join(_cslc_dolphin_unwrap_commands()) + "\n",
            "dolphin_timeseries": "\n".join(_cslc_dolphin_timeseries_commands()) + "\n",
            "create_hdfeos5": hdfeos5,
            "ingest_insarmaps": ingest,
        }
    return {
        "download_cslc": download.rstrip("\n") + f"\n{geom}\n",
        "dolphin": _cslc_dolphin_script(
            config_line, cpus_per_node, n_bursts, preset=preset
        ),
        "create_hdfeos5": hdfeos5,
        "ingest_insarmaps": ingest,
    }


def _disp_module_path() -> Path:
    minsar_home = Path(os.environ.get("MINSAR_HOME", Path(__file__).resolve().parents[4]))
    return minsar_home / "minsar/utils/generate_disp-s1_commands.py"


def _disp_stage_bodies(context: dict[str, object], work_dir: Path) -> dict[str, str]:
    """Resolve concrete DISP-S1 run-file bodies at generate time."""
    template = str(context["template"])
    if not template:
        raise ValueError("DISP workflow requires a MinSAR template")
    start_date = str(context["start_date"] or "") or None
    end_date = str(context["end_date"] or "") or None
    frame_raw = str(context["frame_id"] or "")
    frame_id = int(frame_raw) if frame_raw else None
    module_path = _disp_module_path()
    kwargs = {
        "start_date": start_date,
        "end_date": end_date,
        "frame_id": frame_id,
        "url_type": "HTTPS",
    }

    def build_here() -> dict[str, str]:
        module = runpy.run_path(str(module_path))
        return module["build_stage_commands_from_template"](template, **kwargs)

    try:
        return build_here()
    except (ImportError, ModuleNotFoundError):
        pass
    except RuntimeError as exc:
        if "opera-utils" not in str(exc) and "disp extra" not in str(exc):
            raise

    out_json = work_dir / ".isce3_disp_stage_commands.json"
    code = (
        "import json,runpy,sys;"
        "from pathlib import Path;"
        "m=runpy.run_path(sys.argv[1]);"
        "stages=m['build_stage_commands_from_template'](sys.argv[2],start_date=sys.argv[3] or None,"
        "end_date=sys.argv[4] or None,frame_id=int(sys.argv[5]) if sys.argv[5] else None,url_type='HTTPS');"
        "Path(sys.argv[6]).write_text(json.dumps(stages))"
    )
    try:
        _run_in_sweets(
            work_dir,
            [
                "python",
                "-c",
                code,
                str(module_path),
                template,
                start_date or "",
                end_date or "",
                frame_raw,
                str(out_json),
            ],
        )
        stages = json.loads(out_json.read_text(encoding="utf-8"))
    finally:
        out_json.unlink(missing_ok=True)
    return stages


def _disp_script(
    template: Path | None,
    start_date: str,
    end_date: str,
    frame_id: int | None,
    work_dir: Path,
    force: bool = False,
) -> Path:
    """Create or return the transparent combined DISP-S1 command source."""
    path = work_dir / "disp-s1_commands.bash"
    if path.exists() and not force:
        return path
    if template is None:
        raise ValueError("--template is required to create disp-s1_commands.bash")
    frame = str(frame_id or "")
    module_path = _disp_module_path()
    code = (
        "import runpy,sys;"
        "from pathlib import Path;"
        "m=runpy.run_path(sys.argv[1]);"
        "command,_=m['build_from_template'](sys.argv[2],start_date=sys.argv[3] or None,"
        "end_date=sys.argv[4] or None,frame_id=int(sys.argv[5]) if sys.argv[5] else None,url_type='HTTPS');"
        "Path(sys.argv[6]).write_text(command)"
    )
    _run_in_sweets(
        work_dir,
        [
            "python",
            "-c",
            code,
            str(module_path),
            str(template),
            start_date,
            end_date,
            frame,
            str(path),
        ],
    )
    _make_executable(path)
    return path


def _run_disp_action(
    action: str,
    work_dir: Path,
    template: Path | None,
    start_date: str,
    end_date: str,
    frame_id: int | None,
    delete: bool = False,
) -> None:
    force_script = action in {"download-disp", "reformat-disp"}
    lines = [
        line.strip()
        for line in _disp_script(template, start_date, end_date, frame_id, work_dir, force=force_script).read_text().splitlines()
        if line.strip() and not line.startswith("#") and not line.startswith("set ")
    ]
    if action == "download-disp":
        downloads = [line for line in lines if "disp-s1-download" in line]
        selected = [line for line in lines if line.startswith("mkdir ")] + downloads[:1]
    elif action == "check-disp":
        selected = [
            line
            for line in lines
            if "check_opera_download.py" in line and (("--delete" in line) == delete)
        ]
    elif action == "reformat-disp":
        for path in work_dir.glob("*stack.nc"):
            path.unlink()
        selected = [line for line in lines if "disp-s1-reformat" in line]
    else:
        raise ValueError(f"unknown DISP-S1 action {action!r}")
    if not selected:
        raise RuntimeError(f"no commands found for {action} in disp-s1_commands.bash")
    minsar_home = Path(os.environ.get("MINSAR_HOME", Path(__file__).resolve().parents[4]))
    checker = minsar_home / "minsar/utils/check_opera_download.py"
    selected = [line.replace("check_opera_download.py", f"python {_q(checker)}", 1) for line in selected]
    _run_in_sweets(work_dir, ["bash", "-c", "set -euo pipefail\n" + "\n".join(selected)])


def _run_sweets_check(action: str, work_dir: Path, delete: bool) -> int:
    """Run a SAFE or CSLC checker inside the SWEETS environment."""
    from minsar.utils.check_sweets_download import check_download

    kind = "safe" if action == "check-safe" else "cslc"
    return check_download(work_dir, delete, kind=kind)


def _execute_stage(
    action: str,
    workflow: str,
    template: Path | None,
    start_date: str,
    end_date: str,
    frame_id: int | None,
    delete: bool = False,
) -> int:
    work_dir = Path.cwd().resolve()
    if action in {"check-safe", "check-cslc"}:
        kind = "safe" if action == "check-safe" else "cslc"
        command = [
            "python",
            "-m",
            "minsar.utils.check_sweets_download",
            "--config",
            SWEETS_CONFIG,
            "--kind",
            kind,
        ]
        if delete:
            command.append("--delete")
        _run_in_sweets(work_dir, command)
        return 0
    if action in {"download-disp", "check-disp", "reformat-disp"}:
        _run_disp_action(action, work_dir, template, start_date, end_date, frame_id, delete=delete)
        return 0
    if action in {"download-safe", "download-cslc"}:
        if template is None:
            raise ValueError(f"--template is required for {action}")
        _configure_sweets(workflow, template, work_dir)
        _run_in_sweets(work_dir, ["python", "-m", "minsar.utils.sweets_download", "--config", SWEETS_CONFIG])
        return 0
    if action == "prepare-safe-runconfigs":
        _run_in_sweets(
            work_dir,
            ["python", "-m", "minsar.utils.prepare_compass_runconfigs", "--config", SWEETS_CONFIG],
        )
        return 0
    if action == "prepare-cslc-geometry":
        _run_in_sweets(
            work_dir,
            ["python", "-m", "minsar.utils.stitch_sweets_geometry", "--config", SWEETS_CONFIG],
        )
        return 0
    if action == "dolphin":
        if workflow == "safe":
            _run_in_sweets(
                work_dir,
                ["python", "-m", "minsar.utils.stitch_sweets_geometry", "--config", SWEETS_CONFIG],
            )
            _run_in_sweets(work_dir, ["sweets", "run", SWEETS_CONFIG, "--starting-step", "3"])
        else:
            dolphin_files = sorted((work_dir / "run_files").glob("run_*_dolphin"))
            if not dolphin_files:
                raise RuntimeError(
                    "dolphin run file not found under run_files/; "
                    "run create_isce3_runfiles.py first"
                )
            subprocess.run(["bash", str(dolphin_files[-1])], cwd=work_dir, check=True)
        return 0
    if action in DOLPHIN_SPLIT_STAGES:
        stage_files = sorted((work_dir / "run_files").glob(f"run_*_{action}"))
        if not stage_files:
            raise RuntimeError(
                f"{action} run file not found under run_files/; "
                "run create_isce3_runfiles.py first"
            )
        subprocess.run(["bash", str(stage_files[-1])], cwd=work_dir, check=True)
        return 0
    if action == "create-hdfeos5":
        if workflow == "disp":
            he5_dirs = [work_dir / "timeseries"]
        else:
            he5_dirs = [work_dir / "dolphin" / "timeseries"]
        for he5_dir in he5_dirs:
            for path in he5_dir.glob("*.he5"):
                path.unlink()
        command = ["dolphin2hdfeos5.py"]
        if workflow == "disp":
            stacks = sorted(work_dir.glob("*stack.nc"))
            if not stacks:
                raise RuntimeError("no *stack.nc input found")
            command.append(str(stacks[0]))
        else:
            command.append(str(work_dir / "dolphin"))
        subprocess.run(command, cwd=work_dir, check=True)
        return 0
    if action == "ingest-insarmaps":
        if workflow == "disp":
            ingest_dir = "timeseries"
        else:
            ingest_dir = "dolphin/timeseries"
        he5_glob = work_dir / ingest_dir
        if not any(he5_glob.glob("*.he5")):
            raise RuntimeError(f"no {ingest_dir}/*.he5 product found")
        subprocess.run(["ingest_insarmaps.bash", ingest_dir], cwd=work_dir, check=True)
        return 0
    raise ValueError(f"unknown internal stage action {action!r}")


def main(iargs: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if iargs is None else iargs)
    internal = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    internal.add_argument("--execute-stage")
    internal.add_argument("--run-sweets-check")
    internal.add_argument("--workflow", choices=WORKFLOW_CHOICES)
    internal.add_argument("--template", type=Path)
    internal.add_argument("--start-date", default="")
    internal.add_argument("--end-date", default="")
    internal.add_argument("--frame-id", type=int)
    internal.add_argument("--delete", action="store_true")
    internal_args, _ = internal.parse_known_args(argv)
    if internal_args.run_sweets_check:
        return _run_sweets_check(internal_args.run_sweets_check, Path.cwd().resolve(), internal_args.delete)
    if internal_args.execute_stage:
        if not internal_args.workflow:
            raise ValueError("--execute-stage requires --workflow")
        return _execute_stage(
            internal_args.execute_stage,
            internal_args.workflow,
            internal_args.template,
            internal_args.start_date,
            internal_args.end_date,
            internal_args.frame_id,
            delete=internal_args.delete,
        )

    argv = fix_argv_for_negative_bbox_sn_we(argv, **ARGV_FIX_KW, multiple_initial_positionals=True)
    args = create_parser().parse_args(argv)
    try:
        if not args.queue:
            raise ValueError("No queue: set QUEUENAME or pass --queue")
        if args.run and args.dry_run:
            raise ValueError("--run cannot be combined with --dry-run")
        if args.sleep is not None and args.sleep < 0:
            raise ValueError("--sleep must be a non-negative integer")
        invocation_dir = Path.cwd().resolve()
        workflow = _workflow_name(args)
        split_dolphin = _use_dolphin_split(workflow, args.no_dolphin_split)
        platform = _normalize_platform(args.platform)
        if platform == "NISAR":
            raise ValueError("NISAR is accepted but processing is not implemented until RSLC/GSLC commands are defined")
        input_path = Path(args.input).expanduser()
        input_is_template = input_path.is_file()
        if input_is_template:
            context = _template_context(input_path.resolve(), args)
        elif args.dry_run:
            context = _aoi_context(args)
        else:
            context = _template_context(_create_template_from_aoi(args).resolve(), args)
        config = args.config or Path(__file__).resolve().parents[3] / "defaults/job_defaults_isce3.cfg"
        profiles = _read_profiles(config)
        scratch_dir = Path(os.environ["SCRATCHDIR"]).expanduser().resolve()
        work_dir = scratch_dir / str(context["project"])
        specs = _build_stage_specs(workflow, context, split_dolphin=split_dolphin)
        _log_command_line(invocation_dir, Path(__file__).name, argv)
        if args.dry_run:
            _print_plan(
                workflow, platform, context, None, specs, args.queue, args.long_queue, preset=args.preset
            )
            return 0
        os.chdir(scratch_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        stages = _create_files(args, workflow, context, profiles, work_dir)
        _print_plan(
            workflow, platform, context, stages, queue=args.queue, long_queue=args.long_queue, preset=args.preset
        )
        if not input_is_template:
            print(f"Template: {invocation_dir / Path(str(context['template'])).name}")
        if args.run:
            if args.sleep:
                print(f"Sleeping {args.sleep} seconds before starting ...")
                time.sleep(args.sleep)
            return _run_isce3_workflow(work_dir, stages[-1].number)
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
