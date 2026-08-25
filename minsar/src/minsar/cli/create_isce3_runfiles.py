#!/usr/bin/env python3
"""Create transparent run files, SLURM job files, and output checks for ISCE3 workflows."""

from __future__ import annotations

import argparse
import os
import shlex
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from minsar.utils.bbox_cli_argv import fix_argv_for_negative_bbox_sn_we


WORKFLOW_CHOICES = ("safe", "cslc", "disp")
ARGV_FIX_KW = {
    "consume_one": (
        "--data-type",
        "--platform",
        "--flight-dir",
        "--start-date",
        "--end-date",
        "--track",
        "--frame-id",
        "--queue",
        "--long-queue",
        "--config",
    ),
    "consume_two": (),
    "flags": ("--safe", "--cslc", "--disp", "--dry-run"),
}


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


class Isce3JobAdapter:
    """Use JOB_SUBMIT job rendering without changing the ISCE2 configuration path."""

    def __init__(self, work_dir: Path, queue: str, profile: ResourceProfile) -> None:
        self.queue = queue
        self.cpus_per_node, self.memory_per_node_mb = _queue_resources(queue)
        self.launcher_ppn = min(
            max(1, self.cpus_per_node // profile.num_threads),
            max(1, self.memory_per_node_mb // profile.memory_mb),
        )
        self.job_submit = None
        if os.getenv("JOBSHEDULER_PROJECTNAME"):
            try:
                from minsar.job_submission import JOB_SUBMIT

                self.job_submit = JOB_SUBMIT.__new__(JOB_SUBMIT)
            except ImportError:
                pass
        values = {
            "scheduler": "SLURM",
            "queue": queue,
            "default_wall_time": profile.walltime,
            "default_memory": profile.memory_mb,
            "default_num_threads": profile.num_threads,
            "number_of_cores_per_node": self.cpus_per_node,
            "number_of_parallel_tasks_per_node": self.launcher_ppn,
            "max_memory_per_node": self.memory_per_node_mb,
            "submission_scheme": "launcher_multiTask_singleNode",
            "copy_to_tmp": False,
            "remora": False,
            "email_notif": bool(os.getenv("NOTIFICATIONEMAIL")),
            "out_dir": str(work_dir),
        }
        if self.job_submit is not None:
            for name, value in values.items():
                setattr(self.job_submit, name, value)

    def render(self, stage: Stage, run_file: Path, job_file: Path, workflow: str) -> None:
        """Render a script or LAUNCHER job using JOB_SUBMIT's existing methods."""
        if self.job_submit is not None:
            lines = self.job_submit.get_job_file_lines(
                stage.name,
                job_file.stem,
                number_of_nodes=1,
                work_dir=str(job_file.parent),
            )
        else:
            output_prefix = job_file.parent.resolve() / job_file.stem
            lines = [
                "#!/bin/bash\n",
                f"#SBATCH -J {stage.name}\n",
                "#SBATCH -N 1\n",
                f"#SBATCH -n {self.launcher_ppn if stage.execution_mode == 'launcher-task-list' else 1}\n",
                f"#SBATCH -p {self.queue}\n",
                f"#SBATCH -t {stage.walltime}\n",
                f"#SBATCH -o {output_prefix}_%J.o\n",
                f"#SBATCH -e {output_prefix}_%J.e\n",
            ]
        if stage.execution_mode == "launcher-task-list":
            lines.extend(
                [
                    "\nset -euo pipefail\n",
                    f"export OMP_NUM_THREADS={stage.num_threads}\n",
                    f"export LAUNCHER_PPN={self.launcher_ppn}\n",
                    "export LAUNCHER_NHOSTS=1\n",
                    f"export LAUNCHER_JOB_FILE={shlex.quote(str(run_file.resolve()))}\n",
                    "export LAUNCHER_WORKDIR=/dev/shm\n",
                    'cd "$LAUNCHER_WORKDIR"\n',
                    'if [[ -z "${LAUNCHER_DIR:-}" ]]; then echo "LAUNCHER_DIR is not set" >&2; exit 2; fi\n',
                    '"$LAUNCHER_DIR/paramrun"\n',
                ]
            )
        else:
            lines.extend(["\nset -euo pipefail\n", f"{shlex.quote(str(run_file.resolve()))}\n"])
        lines.extend(
            [
                f"cd {shlex.quote(str(run_file.parent.parent.resolve()))}\n",
                f"validate_isce3_outputs.py --data-type {shlex.quote(workflow)} --step {shlex.quote(stage.name)}\n",
            ]
        )
        job_file.write_text("".join(lines))
        _make_executable(job_file)


def create_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    epilog = """Examples:
 create_isce3_runfiles.py HawaiiSenD87.template
 create_isce3_runfiles.py HawaiiSenD87.template --cslc
 create_isce3_runfiles.py HawaiiSenD87.template --disp
 create_isce3_runfiles.py 19.4:19.54,-155.02:-154.80 HawaiiPuna --flight-dir desc --disp"""
    parser = argparse.ArgumentParser(
        description="Create run files and SLURM job files for SAFE, CSLC, or DISP-S1 processing.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="MinSAR template, or AOI when followed by NAME")
    parser.add_argument("name", nargs="?", help="project name when INPUT is an AOI")
    workflow = parser.add_mutually_exclusive_group()
    workflow.add_argument("--safe", action="store_true", help="start from Sentinel-1 SAFE data (default)")
    workflow.add_argument("--cslc", action="store_true", help="start from OPERA CSLC data")
    workflow.add_argument("--disp", action="store_true", help="start from OPERA DISP-S1 data")
    parser.add_argument("--data-type", choices=WORKFLOW_CHOICES, help="starting data type; equivalent to --safe, --cslc, or --disp")
    parser.add_argument("--platform", default="S1", help="platform: S1 or NISAR/NI")
    parser.add_argument("--flight-dir", choices=("asc", "desc"), help="flight direction for AOI input")
    parser.add_argument("--start-date", help="first acquisition date (YYYYMMDD)")
    parser.add_argument("--end-date", help="last acquisition date (YYYYMMDD)")
    parser.add_argument("--track", type=int, help="relative orbit/track number")
    parser.add_argument("--frame-id", type=int, help="OPERA DISP-S1 frame ID")
    parser.add_argument("--queue", default="skx-dev", help="SLURM partition for restart-safe jobs")
    parser.add_argument("--long-queue", default="skx", help="SLURM partition for unsafe or unknown restart behavior")
    parser.add_argument("--config", type=Path, help="ISCE3 job defaults file")
    parser.add_argument("--dry-run", action="store_true", help="print the workflow without writing files or querying services")
    return parser


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _q(value: str | Path) -> str:
    return shlex.quote(str(value))


def _queue_resources(queue: str) -> tuple[int, int]:
    """Return CPU and memory capacity for a queue from queues.cfg."""
    config = Path(__file__).resolve().parents[3] / "defaults/queues.cfg"
    lines = [line.split() for line in config.read_text().splitlines() if line.strip() and not line.startswith("#")]
    header = lines[0]
    rows = [dict(zip(header, fields)) for fields in lines[1:]]
    platform = os.getenv("PLATFORM_NAME", "stampede3")
    matches = [row for row in rows if row["PLATFORM_NAME"] == platform and row["QUEUENAME"] == queue]
    if not matches:
        matches = [row for row in rows if row["PLATFORM_NAME"] == "stampede3" and row["QUEUENAME"] == queue]
    if not matches:
        raise ValueError(f"queues.cfg contains no resources for PLATFORM_NAME={platform}, QUEUENAME={queue}")
    return int(matches[0]["CPUS_PER_NODE"]), int(matches[0]["MEM_PER_NODE"])


def _workflow_name(args: argparse.Namespace) -> str:
    flags = [name for name in WORKFLOW_CHOICES if getattr(args, name)]
    if args.data_type and flags and args.data_type != flags[0]:
        raise ValueError(f"--data-type {args.data_type} conflicts with --{flags[0]}")
    return args.data_type or (flags[0] if flags else "safe")


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


def _template_context(template_file: Path, args: argparse.Namespace) -> dict[str, object]:
    from minsar.objects.dataset_template import Template

    template = Template(str(template_file))
    template.get_options()
    options = template.options
    project = template_file.stem.replace(".template", "")
    subset = options.get("topsStack.subset", options.get("miaplpy.subset.lalo", ""))
    start = args.start_date or options.get("topsStack.startDate", options.get("minopy.subset.startDate", ""))
    end = args.end_date or options.get("topsStack.endDate", options.get("minopy.subset.endDate", ""))
    track = args.track or options.get("topsStack.trackNumber", "")
    frame = args.frame_id or options.get("topsStack.dispFrameId", options.get("opera.dispFrameId", ""))
    return {
        "project": project,
        "template": str(template_file.resolve()),
        "aoi": subset,
        "start_date": str(start),
        "end_date": str(end),
        "track": str(track),
        "frame_id": str(frame),
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


def _sweets_config_command(context: dict[str, object], source: str) -> str:
    template = str(context["template"])
    if not template:
        return "# Generate a MinSAR template before creating this workflow."
    return f"# The download action creates sweets_config.yaml from {_q(template)} with source={source}."


def _runner_command(command: str) -> str:
    return f'pixi run --manifest-path "$MINSAR_HOME/tools/sweets/pyproject.toml" {command}'


def _stage_command(
    action: str,
    workflow: str,
    context: dict[str, object],
    delete: bool = False,
    allow_failure: bool = False,
) -> str:
    parts = ["create_isce3_runfiles.py", "--execute-stage", action, "--workflow", workflow]
    for option, key in (
        ("--template", "template"),
        ("--start-date", "start_date"),
        ("--end-date", "end_date"),
        ("--frame-id", "frame_id"),
    ):
        value = str(context[key])
        if value:
            parts.extend([option, value])
    command = " ".join(_q(part) for part in parts)
    if delete:
        command = f"{command} --delete"
    return f"{command} || true" if allow_failure else command


def _build_stage_specs(workflow: str, context: dict[str, object]) -> list[tuple[str, str, str]]:
    if workflow == "safe":
        return [
            (
                "download_safe",
                "Download and verify SAFE data, then prepare COMPASS runconfigs",
                "\n".join(
                    [
                        _sweets_config_command(context, "burst"),
                        _stage_command("download-safe", workflow, context, allow_failure=True),
                        _stage_command("check-safe", workflow, context, delete=True),
                        _stage_command("download-safe", workflow, context, allow_failure=True),
                        _stage_command("check-safe", workflow, context),
                        _stage_command("prepare-safe-runconfigs", workflow, context),
                    ]
                ),
            ),
            (
                "create_cslc",
                "Create CSLCs and static layers with COMPASS",
                "# Tasks are materialized by run_01_download_safe.",
            ),
            ("run_dolphin", "Run Dolphin displacement processing", _stage_command("run-dolphin", workflow, context)),
            ("create_hdfeos5", "Create HDF-EOS5 product", _stage_command("create-hdfeos5", workflow, context)),
            ("ingest_insarmaps", "Ingest HDF-EOS5 product into InsarMaps", _stage_command("ingest-insarmaps", workflow, context)),
        ]
    if workflow == "cslc":
        return [
            (
                "download_cslc",
                "Download and verify OPERA CSLCs, then prepare geometry",
                "\n".join(
                    [
                        _sweets_config_command(context, "cslc"),
                        _stage_command("download-cslc", workflow, context, allow_failure=True),
                        _stage_command("check-cslc", workflow, context, delete=True),
                        _stage_command("download-cslc", workflow, context, allow_failure=True),
                        _stage_command("check-cslc", workflow, context),
                        _stage_command("prepare-cslc-geometry", workflow, context),
                    ]
                ),
            ),
            ("run_dolphin", "Run Dolphin displacement processing", _stage_command("run-dolphin", workflow, context)),
            ("create_hdfeos5", "Create HDF-EOS5 product", _stage_command("create-hdfeos5", workflow, context)),
            ("ingest_insarmaps", "Ingest HDF-EOS5 product into InsarMaps", _stage_command("ingest-insarmaps", workflow, context)),
        ]
    template = str(context["template"])
    if not template:
        generate = "# Generate a MinSAR template before creating this workflow."
    else:
        generate = f"# DISP-S1 commands are derived from {_q(template)} and saved in disp-s1_commands.bash."
    return [
        (
            "download_disp",
            "Download and verify OPERA DISP-S1 products",
            "\n".join(
                [
                    generate,
                    _stage_command("download-disp", workflow, context, allow_failure=True),
                    _stage_command("check-disp", workflow, context, delete=True),
                    _stage_command("download-disp", workflow, context, allow_failure=True),
                    _stage_command("check-disp", workflow, context),
                ]
            ),
        ),
        ("reformat_disp", "Reformat DISP-S1 products into a stack", _stage_command("reformat-disp", workflow, context)),
        ("create_hdfeos5", "Create HDF-EOS5 product", _stage_command("create-hdfeos5", workflow, context)),
        ("ingest_insarmaps", "Ingest HDF-EOS5 product into InsarMaps", _stage_command("ingest-insarmaps", workflow, context)),
    ]


def _profile_for(name: str, profiles: dict[str, ResourceProfile]) -> ResourceProfile:
    return profiles.get(name, profiles["default"])


def _write_run_file(path: Path, title: str, command: str, task_list: bool = False) -> None:
    if task_list:
        path.write_text("# Generated after SAFE download by run_01_download_safe.\n")
    else:
        path.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"# {title}\n"
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'WORK_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"\n'
            'cd "$WORK_DIR"\n'
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
    specs = _build_stage_specs(workflow, context)
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
        _write_run_file(run_file, title, command, profile.execution_mode == "launcher-task-list")
        Isce3JobAdapter(run_dir, stage.queue, profile).render(stage, run_file, job_file, workflow)
        stages.append(stage)
    return stages


def _print_plan(workflow: str, platform: str, context: dict[str, object], stages: list[Stage] | None, specs: list[tuple[str, str, str]] | None = None) -> None:
    print(f"Workflow: {workflow.upper()} ({platform})")
    print(f"Project:  {context['project']}")
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


def _run_sweets_snippet(work_dir: Path, code: str) -> None:
    _run_in_sweets(work_dir, ["python", "-c", code])


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
    minsar_home = Path(os.environ.get("MINSAR_HOME", Path(__file__).resolve().parents[4]))
    module_path = minsar_home / "minsar/utils/generate_disp-s1_commands.py"
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


def _materialize_compass_tasks(work_dir: Path) -> None:
    cslc = sorted(work_dir.rglob("runconfigs/*.yaml"))
    if not cslc:
        raise RuntimeError("SWEETS did not create COMPASS CSLC runconfigs")
    sweets_bin = '"$MINSAR_HOME/tools/sweets/.pixi/envs/default/bin"'
    commands = [f"{sweets_bin}/s1_cslc.py {_q(path)}" for path in cslc]
    first_per_burst: dict[str, Path] = {}
    for path in cslc:
        parts = path.stem.split("_")
        key = "_".join(parts[3:]) if len(parts) > 3 else path.stem
        first_per_burst.setdefault(key, path)
    commands.extend(f"{sweets_bin}/s1_static_layers.py {_q(path)}" for path in first_per_burst.values())
    run_files = sorted((work_dir / "run_files").glob("run_*_create_cslc"))
    if len(run_files) != 1:
        raise RuntimeError("expected exactly one create_cslc run file")
    run_file = run_files[0]
    run_file.write_text("\n".join(commands) + "\n")


def _safe_is_readable(path: Path) -> tuple[bool, str]:
    """Return whether a burst2safe SAFE has the files COMPASS needs."""
    import xml.etree.ElementTree as ET

    import rasterio

    required = [path / "manifest.safe", path / "preview/map-overlay.kml"]
    missing = [item.relative_to(path) for item in required if not item.is_file()]
    annotations = sorted((path / "annotation").glob("*.xml"))
    measurements = sorted((path / "measurement").glob("*.tiff"))
    if missing:
        return False, f"missing {', '.join(map(str, missing))}"
    if not annotations:
        return False, "no annotation XML files"
    if not measurements:
        return False, "no measurement TIFF files"
    try:
        ET.parse(path / "manifest.safe")
        for annotation in annotations:
            ET.parse(annotation)
        for measurement in measurements:
            with rasterio.open(measurement) as dataset:
                if dataset.width < 1 or dataset.height < 1 or dataset.count < 1:
                    return False, f"empty raster {measurement.name}"
    except Exception as exc:
        return False, str(exc)
    return True, ""


def _check_safe_download(work_dir: Path, delete: bool) -> int:
    """Check expected SAFE absolute orbits and optionally delete bad products."""
    import re
    import shutil

    from burst2safe import utils as burst_utils
    from burst2safe.search import find_group
    from sweets.core import Workflow, setup_nasa_netrc

    workflow = Workflow.from_yaml(work_dir / "sweets_config.yaml")
    search = workflow.search
    setup_nasa_netrc()
    results = find_group(
        search.track,
        search.aoi,
        search.polarizations,
        search.swaths,
        "IW",
        search.min_bursts,
        use_relative_orbit=True,
        start_date=search.start,
        end_date=search.end,
    )
    infos = burst_utils.get_burst_infos(results, search.out_dir)
    if search.flight_direction:
        infos = [info for info in infos if info.direction.upper() == search.flight_direction.upper()]
    expected = {
        (int(info.absolute_orbit), info.date.strftime("%Y%m%d"))
        for info in infos
        if info.date is not None
    }
    if not expected:
        raise RuntimeError("check-safe found no expected SAFE acquisitions")

    valid: set[tuple[int, str]] = set()
    bad: list[tuple[Path, str]] = []
    for path in sorted(search.out_dir.glob("S1[AB]_*.SAFE")):
        match = re.search(r"_(\d{8})T\d{6}_.*_(\d{6})_[0-9A-F]{6}_", path.name)
        readable, reason = _safe_is_readable(path)
        if not match:
            readable, reason = False, "absolute orbit missing from SAFE name"
        if readable:
            valid.add((int(match.group(2)), match.group(1)))
        else:
            bad.append((path, reason))

    for path, reason in bad:
        print(f"Invalid SAFE: {path.name}: {reason}", file=sys.stderr)
        if delete:
            shutil.rmtree(path)
            print(f"Deleted {path}", file=sys.stderr)
    missing = sorted(expected - valid)
    if missing:
        print(
            "Missing SAFE acquisitions: "
            + ", ".join(f"{date}/orbit-{orbit:06d}" for orbit, date in missing),
            file=sys.stderr,
        )
    if bad or missing:
        return 0 if delete else 1
    print(f"check-safe: {len(valid)} complete SAFE products")
    return 0


def _hdf5_has_datasets(path: Path, datasets: tuple[str, ...]) -> tuple[bool, str]:
    """Return whether an HDF5 file opens and contains required datasets."""
    import h5py

    if path.stat().st_size < 1024 * 1024:
        return False, "file is smaller than 1 MiB"
    try:
        with h5py.File(path, "r") as handle:
            missing = [dataset for dataset in datasets if dataset not in handle]
            if missing:
                return False, f"missing {', '.join(missing)}"
            for dataset in datasets:
                value = handle[dataset]
                if value.size < 1:
                    return False, f"empty {dataset}"
                if value.ndim >= 2:
                    _ = value[0, 0]
    except Exception as exc:
        return False, str(exc)
    return True, ""


def _check_cslc_download(work_dir: Path, delete: bool) -> int:
    """Check expected OPERA CSLC and static-layer products."""
    from opera_utils.download import L2Product, search_cslcs
    from sweets.core import Workflow, setup_nasa_netrc

    workflow = Workflow.from_yaml(work_dir / "sweets_config.yaml")
    search = workflow.search
    setup_nasa_netrc()
    burst_ids = search._resolve_burst_ids()
    cslc_results = search_cslcs(start=search.start, end=search.end, track=search.track, burst_ids=burst_ids)
    static_results = search_cslcs(burst_ids=burst_ids, product=L2Product.CSLC_STATIC)
    def result_name(result: object) -> str:
        properties = result.properties  # type: ignore[attr-defined]
        return str(properties.get("fileName") or Path(properties["url"]).name)

    expected_cslc = {result_name(result) for result in cslc_results}
    expected_static = {result_name(result) for result in static_results}
    if not expected_cslc or not expected_static:
        raise RuntimeError("check-cslc found no expected CSLC or static-layer products")

    checks = [
        (
            search.out_dir,
            expected_cslc,
            ("/data/VV", "/data/x_coordinates", "/data/y_coordinates", "/data/projection"),
        ),
        (
            search.static_layers_dir,
            expected_static,
            (
                "/data/los_east",
                "/data/los_north",
                "/data/local_incidence_angle",
                "/data/layover_shadow_mask",
            ),
        ),
    ]
    failures = False
    for directory, expected, datasets in checks:
        existing = {path.name: path for path in directory.glob("*.h5")}
        for name in sorted(expected & existing.keys()):
            path = existing[name]
            readable, reason = _hdf5_has_datasets(path, datasets)
            if not readable:
                failures = True
                print(f"Invalid CSLC product: {path}: {reason}", file=sys.stderr)
                if delete:
                    path.unlink()
                    print(f"Deleted {path}", file=sys.stderr)
        missing = sorted(expected - existing.keys())
        if missing:
            failures = True
            print(f"Missing {len(missing)} product(s) in {directory}:", file=sys.stderr)
            for name in missing:
                print(f"  {name}", file=sys.stderr)
    if failures:
        return 0 if delete else 1
    print(f"check-cslc: {len(expected_cslc)} CSLC and {len(expected_static)} static-layer products")
    return 0


def _run_sweets_check(action: str, work_dir: Path, delete: bool) -> int:
    """Run a SAFE or CSLC checker inside the SWEETS environment."""
    return _check_safe_download(work_dir, delete) if action == "check-safe" else _check_cslc_download(work_dir, delete)


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
        command = [
            "python",
            str(Path(__file__).resolve()),
            "--run-sweets-check",
            action,
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
        needs_burst_db = ";get_burst_db()" if action == "download-safe" else ""
        code = (
            "from sweets.core import Workflow,setup_nasa_netrc,get_burst_db,create_dem,create_water_mask;"
            "w=Workflow.from_yaml('sweets_config.yaml');setup_nasa_netrc();w.work_dir.mkdir(parents=True,exist_ok=True);"
            "create_dem(w.dem_filename,w._dem_bbox);create_water_mask(w.water_mask_filename,w._water_mask_bbox)"
            f"{needs_burst_db};w.search.download();"
            "w.search.download_static_layers() if hasattr(w.search,'download_static_layers') else None"
        )
        _run_sweets_snippet(work_dir, code)
        return 0
    if action == "prepare-safe-runconfigs":
        code = (
            "from sweets.core import Workflow,download_orbits,get_burst_db,create_config_files;"
            "w=Workflow.from_yaml('sweets_config.yaml');db=get_burst_db();s=w._existing_safes();"
            "download_orbits(w.search.out_dir,w.orbit_dir);"
            "create_config_files(slc_dir=s[0].parent,burst_db_file=db,dem_file=w.dem_filename,orbit_dir=w.orbit_dir,"
            "bbox=w.bbox,y_posting=w.slc_posting[0],x_posting=w.slc_posting[1],pol_type=w.pol_type,"
            "out_dir=w.gslc_dir,overwrite=True,using_zipped=s[0].suffix=='.zip',gpu_enabled=w.gpu_enabled)"
        )
        _run_sweets_snippet(work_dir, code)
        _materialize_compass_tasks(work_dir)
        return 0
    if action == "prepare-cslc-geometry":
        code = (
            "from sweets.core import Workflow;"
            "w=Workflow.from_yaml('sweets_config.yaml');w._stitch_geometry(w._existing_static_layers())"
        )
        _run_sweets_snippet(work_dir, code)
        return 0
    if action == "run-dolphin":
        if workflow == "safe":
            code = (
                "from sweets.core import Workflow;"
                "w=Workflow.from_yaml('sweets_config.yaml');w.overwrite=True;"
                "w._stitch_geometry(w._existing_static_layers());w.run(starting_step=3)"
            )
        else:
            code = "from sweets.core import Workflow;w=Workflow.from_yaml('sweets_config.yaml');w.overwrite=True;w.run(starting_step=3)"
        _run_sweets_snippet(work_dir, code)
        return 0
    if action == "create-hdfeos5":
        timeseries_dir = work_dir / "timeseries"
        for path in timeseries_dir.glob("*.he5"):
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
        products = sorted((work_dir / "timeseries").glob("*.he5"))
        if not products:
            raise RuntimeError("no timeseries/*.he5 product found")
        subprocess.run(["ingest_insarmaps.bash", str(products[-1])], cwd=work_dir, check=True)
        return 0
    raise ValueError(f"unknown internal stage action {action!r}")


def main(iargs: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if iargs is None else iargs)
    internal = argparse.ArgumentParser(add_help=False)
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
        invocation_dir = Path.cwd().resolve()
        workflow = _workflow_name(args)
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
        specs = _build_stage_specs(workflow, context)
        if args.dry_run:
            _print_plan(workflow, platform, context, None, specs)
            return 0
        os.chdir(scratch_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        stages = _create_files(args, workflow, context, profiles, work_dir)
        _print_plan(workflow, platform, context, stages)
        if not input_is_template:
            print(f"Template: {invocation_dir / Path(str(context['template'])).name}")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
