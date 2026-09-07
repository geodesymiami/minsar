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
from minsar.utils.dolphin_config_import import (
    is_dolphin_config_path,
    load_algo_mapping,
    merge_imported_into_dolphin_yaml,
    write_stripped_algo_yaml,
)
from minsar.utils.dolphin_presets import (
    DEFAULT_HALF_WINDOW,
    DEFAULT_PRESET,
    DEFAULT_STRIDES,
    DOLPHIN_PRESET_CHOICES,
    DOLPHIN_PRESET_HELP,
    NO_PRESET_NAMING_HELP,
    OPERA_DISP_METHOD_STRING,
    count_opera_cslc_bursts,
    dolphin_method_string,
    dolphin_window_cli_flags,
    dolphin_worker_cli_flags,
    normalize_dolphin_preset,
    resolve_half_window_strides,
)
from minsar.utils.isce3_dolphin_experiment import (
    DEFAULT_DOLPHIN_DIR,
    DEFAULT_FROM_DIR,
    config_yaml_name,
    has_cslc_or_gslc,
    parse_passthrough_pairs,
    passthrough_cli_flags,
    resolve_dolphin_dir,
    stage_dolphin_inputs,
    write_dolphin_dir_sidecar,
    write_run_slice_sidecar,
)


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
RUN_FILES_DIRNAME = "run_files_isce3"
CREATE_CSLC_QUEUE_META = ".isce3_create_cslc_queue"
DEFERRED_TASK_LIST_STAGES = frozenset({"create_cslc"})
DOWNLOAD_STAGE_NAMES = {
    "safe": ("download_safe", "create_cslc"),
    "cslc": ("download_cslc",),
    "disp": ("download_disp", "reformat_disp"),
}
PHASE_CHOICES = ("download", "dolphin", "all")
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
DOLPHIN_MODE_CHOICES = ("single-run", "opera")
DEFAULT_DOLPHIN_MODE = "single-run"
REFERENCE_METHOD_CHOICES = ("NONE", "POINT", "MEDIAN", "BORDER", "HIGH_COHERENCE")
DEFAULT_REFERENCE_METHOD = "HIGH_COHERENCE"
_REFERENCE_METHOD_BY_VALUE = {
    "none": "NONE",
    "point": "POINT",
    "median": "MEDIAN",
    "border": "BORDER",
    "high_coherence": "HIGH_COHERENCE",
}
OPERA_DOLPHIN_STAGES = ("disp_s1_process", "reformat_disp")
# Legacy sidecar run files (pre --dolphin-mode opera); removed on regenerate.
LEGACY_UNNUMBERED_RUN_BASENAMES = (
    "run_disp_s1_process",
    "run_reformat_disp",
)
PROFILE_ALIASES = {
    "disp_s1_process": "run_disp_s1_process",
}
DISP_S1_PRODUCE_DIR = "disp_s1_produce"
DISP_S1_PROCESS_CMD = "disp_s1_process.py"
DEFAULT_DISP_S1_MINISTACK_SIZE = 15
# half_window is (y, x); strides is (y, x). See minsar.utils.dolphin_presets.
IMPORTED_ALGO_YAML = ".minsar_imported_algo.yaml"

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
        "--relativeOrbit",
        "--frame-id",
        "--queue",
        "--long-queue",
        "--config",
        "--sleep",
        "--window-preset",
        "--burst-count-method",
        "--phase",
        "--dolphin-dir",
        "--from-dolphin-dir",
        "--unwrap-method",
        "--ministack-size",
        "--dolphin-mode",
        "--reference-method",
    ),
    "consume_two": (
        "--half-window",
        "--stride",
    ),
    "flags": (
        "--safe",
        "--cslc",
        "--disp",
        "--disp-S1",
        "--dry-run",
        "--run",
        "--no-dolphin-split",
        "--preset-naming",
        "--no-preset-naming",
        "--copy-dolphin-inputs",
    ),
}


def _normalize_dolphin_mode(value: str) -> str:
    """Normalize --dolphin-mode to single-run or opera."""
    token = value.strip().lower().replace("_", "-")
    if token not in DOLPHIN_MODE_CHOICES:
        raise argparse.ArgumentTypeError(
            f"invalid --dolphin-mode {value!r}; use {', '.join(DOLPHIN_MODE_CHOICES)}"
        )
    return token


def _normalize_reference_method(value: str) -> str:
    """Normalize opera-utils disp-s1-reformat --reference-method."""
    token = value.strip().upper().replace("-", "_")
    if token in REFERENCE_METHOD_CHOICES:
        return token
    by_value = _REFERENCE_METHOD_BY_VALUE.get(value.strip().lower().replace("-", "_"))
    if by_value:
        return by_value
    raise argparse.ArgumentTypeError(
        f"invalid --reference-method {value!r}; use {', '.join(REFERENCE_METHOD_CHOICES)}"
    )


_DATA_TYPE_NAME_TOKEN = {"cslc": "CSLC", "disp": "DISP"}
_DATA_TYPE_NAME_SUFFIX_RE = re.compile(r"(CSLC|DISP)$", re.IGNORECASE)
_LEGACY_DOLPHIN_MODE_SUFFIX_RE = re.compile(r"(Opera|Standard)$", re.IGNORECASE)


def _aoi_name_with_data_type(name: str, workflow: str) -> str:
    """Append CSLC or DISP to an AOI project basename from --data-type (safe: no suffix)."""
    base = _LEGACY_DOLPHIN_MODE_SUFFIX_RE.sub("", str(name).strip())
    if not base:
        base = str(name).strip()
    stripped = _DATA_TYPE_NAME_SUFFIX_RE.sub("", base)
    if not stripped:
        stripped = base
    token = _DATA_TYPE_NAME_TOKEN.get(workflow, "")
    if not token:
        return stripped
    return f"{stripped}{token}"


def _normalize_phase(value: str) -> str:
    """Normalize --phase to download, dolphin, or all."""
    token = value.strip().lower().replace("-", "_")
    if token in {"download_create_cslc", "download"}:
        return "download"
    if token in PHASE_CHOICES:
        return token
    raise argparse.ArgumentTypeError(
        f"invalid --phase {value!r}; use download, dolphin, or all"
    )


def _stage_in_phase(name: str, workflow: str, phase: str) -> bool:
    """True when this stage is written for --phase download|dolphin|all."""
    if phase == "all":
        return True
    download_names = DOWNLOAD_STAGE_NAMES.get(workflow, ())
    if phase == "download":
        return name in download_names
    return name not in download_names


def _isce3_run_dir(work_dir: Path) -> Path:
    """Return the ISCE3 run/job files directory under the project."""
    return work_dir / RUN_FILES_DIRNAME


def _run_basename_for_stage(name: str, number: int) -> str:
    """Run-file basename: run_NN_<stage>."""
    return f"run_{number:02d}_{name}"


def _run_file_stage_name(path: Path) -> str | None:
    """Stage name from run_NN_<stage> or run_NN_<stage>_N.job, or None."""
    stem = path.stem if path.suffix == ".job" else path.name
    for basename in LEGACY_UNNUMBERED_RUN_BASENAMES:
        if stem == basename or re.fullmatch(rf"{re.escape(basename)}_\d+", stem):
            return basename.removeprefix("run_")
    match = re.match(r"^run_\d{2}_(.+)$", stem)
    if not match:
        return None
    rest = match.group(1)
    if re.fullmatch(r".+_\d+$", rest):
        return re.sub(r"_\d+$", "", rest)
    return rest


def _format_template_path(template: str) -> str:
    """Return template path, shortening with $TE when under the TE directory."""
    path = str(Path(template).expanduser().resolve())
    te = os.environ.get("TE")
    if te:
        te_path = str(Path(te).expanduser().resolve())
        if path.startswith(te_path):
            suffix = path[len(te_path) :]
            if not suffix.startswith("/"):
                suffix = "/" + suffix
            return "$TE" + suffix
    return path


def _log_command_line(log_dirs: Path | list[Path], script_name: str, argv: list[str]) -> None:
    """Append the invocation to each log_dir/log (deduped by resolved path)."""
    if isinstance(log_dirs, Path):
        destinations = [log_dirs]
    else:
        destinations = list(log_dirs)
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
    seen: set[Path] = set()
    for log_dir in destinations:
        log_dir.mkdir(parents=True, exist_ok=True)
        real = log_dir.resolve()
        if real in seen:
            continue
        seen.add(real)
        with (real / "log").open("a", encoding="utf-8") as handle:
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


def _track_from_template_options(options: dict) -> str:
    """Return relative orbit as string from ssaraopt.relativeOrbit, or '' if missing."""
    raw = options.get("ssaraopt.relativeOrbit")
    if raw is None or str(raw).strip() == "":
        return ""
    return str(int(str(raw).strip()))


def _track_source_for_context(args: argparse.Namespace, options: dict | None = None) -> str:
    """Return 'cli', 'template', or '' for how relative orbit was resolved."""
    if args.track is not None:
        return "cli"
    if options and _track_from_template_options(options):
        return "template"
    return ""


def _resolve_track_for_context(args: argparse.Namespace, options: dict) -> str:
    """CLI --track / --relativeOrbit overrides template ssaraopt.relativeOrbit."""
    if args.track is not None:
        return str(args.track)
    return _track_from_template_options(options)


def _flight_direction_for_burst_count(context: dict[str, object]) -> str:
    """Return asc/desc from context CLI or template flight-direction fields."""
    flight = str(context.get("flight_direction") or "").strip()
    if flight:
        return flight
    template = str(context.get("template") or "")
    if template:
        from minsar.utils.generate_sweets_config import flight_direction_from_template

        resolved = flight_direction_from_template(template)
        if resolved:
            return resolved
    return ""


def _resolve_n_bursts_for_dolphin(
    work_dir: Path,
    context: dict[str, object],
    *,
    burst_count_method: str = "sar_coverage",
) -> int:
    """Burst count from AOI footprints when track is known, else data/ or ASF coverage."""
    aoi = str(context.get("aoi") or "").strip()
    track_raw = str(context.get("track") or "")
    track = int(track_raw) if track_raw else None
    flight = _flight_direction_for_burst_count(context) or None

    if aoi and track is not None:
        from minsar.utils.generate_sweets_config import count_bursts_covering_aoi

        n_bursts = count_bursts_covering_aoi(aoi, track=track, flight_direction=flight)
        print(
            f"  dolphin n_bursts={n_bursts} from opera-utils footprints (track={track})",
            file=sys.stderr,
        )
        return n_bursts

    data_dir = work_dir / "data"
    if any(data_dir.glob("OPERA_L2_CSLC-S1_*.h5")):
        n_bursts = count_opera_cslc_bursts(data_dir)
        print(f"  dolphin n_bursts={n_bursts} from {data_dir}", file=sys.stderr)
        return n_bursts
    if not aoi:
        return 1

    if burst_count_method == "opera-utils":
        if track is None:
            raise ValueError(
                "--burst-count-method opera-utils requires --track (or template ssaraopt.relativeOrbit)"
            )
        from minsar.utils.generate_sweets_config import count_bursts_covering_aoi

        n_bursts = count_bursts_covering_aoi(aoi, track=track, flight_direction=flight)
        print(f"  dolphin n_bursts={n_bursts} from opera-utils (track={track})", file=sys.stderr)
        return n_bursts

    from minsar.scripts.create_template import _run_get_sar_coverage
    from minsar.scripts.get_sar_coverage import count_bursts_on_orbit

    if track is not None:
        track_source = str(context.get("track_source") or "")
        if track_source == "cli":
            print(f"  dolphin track={track} from CLI", file=sys.stderr)
        elif track_source == "template":
            print(f"  dolphin track={track} from template", file=sys.stderr)
        else:
            print(f"  dolphin track={track}", file=sys.stderr)
    else:
        if not flight:
            raise ValueError(
                "--burst-count-method sar_coverage requires --flight-dir "
                "(or template flight direction) when --track is not set"
            )
        coverage = _run_get_sar_coverage(aoi, "S1")
        orbit_key = "desc_relorbit" if flight.lower().startswith("d") else "asc_relorbit"
        if orbit_key not in coverage:
            raise RuntimeError(f"get_sar_coverage.py did not return {orbit_key} for AOI {aoi!r}")
        track = int(coverage[orbit_key])
        print(f"  dolphin track={track} from get_sar_coverage.py ({flight})", file=sys.stderr)
    if not flight:
        raise ValueError(
            "--burst-count-method sar_coverage requires --flight-dir when estimating bursts from ASF"
        )
    n_bursts = count_bursts_on_orbit(aoi, track, flight)
    print(f"  dolphin n_bursts={n_bursts} from get_sar_coverage.py (track={track})", file=sys.stderr)
    return n_bursts


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
        'pixi run --as-is --manifest-path "$MINSAR_HOME/tools/sweets/pyproject.toml" -- bash <<\'ISCE3_PIXI_BODY\'\n'
        "set -euo pipefail\n"
        "\n"
        f"{body}\n"
        "\n"
        "ISCE3_PIXI_BODY\n"
    )


def _disp_s1_run_script(commands: str) -> str:
    """Run disp_s1_process in the disp-s1 conda env (not SWEETS pixi)."""
    body = _strip_bash_script_header(commands)
    if not body:
        body = "true"
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'export PATH="${MINSAR_HOME}/minsar/scripts:${PATH}"\n'
        'source "${MINSAR_HOME}/minsar/scripts/activate_disp_s1_env.bash"\n'
        "\n"
        f"{body}\n"
    )


def _pixi_run_script_with_tail(pixi_commands: str, tail_commands: list[str]) -> str:
    """Pixi heredoc for SWEETS/dolphin, then minsar-env commands (e.g. create_html needs MintPy)."""
    pixi_body = _strip_bash_script_header(pixi_commands)
    if not pixi_body:
        pixi_body = "true"
    tail = "\n".join(tail_commands) + "\n" if tail_commands else ""
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'pixi run --as-is --manifest-path "$MINSAR_HOME/tools/sweets/pyproject.toml" -- bash <<\'ISCE3_PIXI_BODY\'\n'
        "set -euo pipefail\n"
        "\n"
        f"{pixi_body}\n"
        "\n"
        "ISCE3_PIXI_BODY\n"
        f"{tail}"
    )


# Dolphin stages that run plot_dolphin_summary_pngs / create_html outside pixi (MintPy not in SWEETS).
_DOLPHIN_PIXI_PLOT_TAIL_STAGES = frozenset({"dolphin", "dolphin_timeseries"})


def _is_deferred_batch_job(path: Path, deferred_names: set[str]) -> bool:
    """True when path is run_NN_<stage>_N.job for a deferred task-list stage."""
    if path.suffix != ".job":
        return False
    match = re.match(r"run_\d{2}_(.+)_\d+$", path.stem)
    return bool(match and match.group(1) in deferred_names)


def _dolphin_stop_after_stitch_flags() -> str:
    """Dolphin config flags for wrapped + stitch only (no unwrap or timeseries)."""
    return (
        "--unwrap-options.no-run-unwrap "
        "--timeseries-options.no-run-inversion "
        "--timeseries-options.no-run-velocity"
    )


def _normalize_dolphin_preset(value: str) -> str:
    try:
        return normalize_dolphin_preset(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _parse_yx_pair(values: list[str], option: str) -> tuple[int, int]:
    """Parse Y X integers for --half-window / --stride."""
    if len(values) != 2:
        raise argparse.ArgumentTypeError(f"{option} requires Y X")
    try:
        y_val = int(values[0])
        x_val = int(values[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{option} requires integer Y X") from exc
    if y_val < 1 or x_val < 1:
        raise argparse.ArgumentTypeError(f"{option} values must be >= 1")
    return y_val, x_val


def _dolphin_window_cli_flags(
    half_window: tuple[int, int] | None,
    strides: tuple[int, int] | None,
) -> str:
    """CLI flags for run_interpolation plus strides and half-window."""
    return dolphin_window_cli_flags(half_window, strides)


def _geometry_stitch_command(
    strides: tuple[int, int] | None,
    config_name: str = SWEETS_CONFIG,
) -> str:
    """stitch_sweets_geometry command with effective strides."""
    if strides is None:
        # auto / omitted: native CSLC posting (match dolphin package strides 1×1)
        sy, sx = 1, 1
    else:
        sy, sx = strides
    return f"stitch_sweets_geometry.py --config {config_name} --sy {sy} --sx {sx} --overwrite"


def _merge_algo_cli(
    yaml_name: str,
    imported_path: str,
    half_window: tuple[int, int] | None,
    strides: tuple[int, int] | None,
    ministack_size: int | None = None,
) -> str:
    """Shell command to merge imported algorithm fields into generated YAML."""
    parts = [
        f"merge_dolphin_algo_config.py --target {shlex.quote(yaml_name)} "
        f"--from {shlex.quote(imported_path)}"
    ]
    if half_window is not None:
        parts.append(f"--hwy {half_window[0]} --hwx {half_window[1]}")
    if strides is not None:
        parts.append(f"--sy {strides[0]} --sx {strides[1]}")
    if ministack_size is not None:
        parts.append(f"--ministack-size {int(ministack_size)}")
    return " ".join(parts)


def _normalize_dolphin_config_positionals(args: argparse.Namespace) -> None:
    """Move a .yaml/.yml/.nc from name into dolphin_config when needed."""
    config = getattr(args, "dolphin_config", None)
    name = getattr(args, "name", None)
    if config is None and name is not None and is_dolphin_config_path(name):
        args.dolphin_config = name
        args.name = None
    if getattr(args, "dolphin_config", None) is not None:
        path = Path(str(args.dolphin_config)).expanduser()
        if not is_dolphin_config_path(path):
            raise ValueError(
                f"dolphin config must be .yaml, .yml, or .nc; got {args.dolphin_config!r}"
            )
        args.dolphin_config = str(path)


def _hdfeos5_method_string(preset: str, preset_naming: bool = True) -> str:
    """HE5 post_processing_method label for dolphin2hdfeos5."""
    if not preset_naming:
        return "dolphin"
    return dolphin_method_string(preset)


def _hdfeos5_command(preset: str, preset_naming: bool = True, dolphin_dir: str = DEFAULT_DOLPHIN_DIR) -> str:
    """dolphin2hdfeos5 run-file line with explicit HE5 method label."""
    method = _hdfeos5_method_string(preset, preset_naming)
    watermask = f"{dolphin_dir}/unwrapped/warped_watermask.tif"
    return f"dolphin2hdfeos5.py {dolphin_dir} --method-string {method} --watermask {watermask}"


def _opera_hdfeos5_command(context: dict[str, object]) -> str:
    """dolphin2hdfeos5 from a locally produced DISP-S1 stack NetCDF."""
    project = str(context["project"])
    stack = f"{project}-stack.nc"
    return f"dolphin2hdfeos5.py {stack} --method-string {OPERA_DISP_METHOD_STRING} --watermask {stack}"


def _opera_ingest_command() -> str:
    """Ingest HE5 written from an OPERA-style stack at project timeseries/."""
    return "ingest_insarmaps.bash timeseries"


def _cslc_slc_files_arg(context: dict[str, object]) -> str:
    """Per-burst OPERA CSLC globs for bursts intersecting the AOI."""
    from minsar.utils.generate_sweets_config import burst_id_jpl_to_cslc_glob, burst_ids_covering_aoi

    aoi = str(context.get("aoi") or "").strip()
    if not aoi:
        raise ValueError("CSLC dolphin config requires AOI in template context")
    track_raw = str(context.get("track") or "")
    track = int(track_raw) if track_raw else None
    flight = str(context.get("flight_direction") or "") or None
    burst_ids = burst_ids_covering_aoi(aoi, track=track, flight_direction=flight)
    globs = [burst_id_jpl_to_cslc_glob(bid) for bid in burst_ids]
    return " ".join(globs)


def _safe_slc_files_arg(work_dir: Path) -> str:
    """COMPASS GSLC HDF5s, or a glob when they are not on disk yet."""
    hits = sorted(
        path for path in work_dir.glob("gslcs/**/*.h5") if path.name.startswith("t")
    )
    if hits:
        return " ".join(str(path.relative_to(work_dir)) for path in hits)
    return "gslcs/*/*/t*.h5"


def _dolphin_config_line(
    config_line: str,
    cpus_per_node: int,
    n_bursts_aoi: int,
    slc_files: str,
    extra_flags: str = "",
    outfile: str = "dolphin_config.yaml",
    half_window: tuple[int, int] | None = None,
    strides: tuple[int, int] | None = None,
    runtime_workers: bool = False,
    dolphin_dir: str = DEFAULT_DOLPHIN_DIR,
) -> str:
    """One-line dolphin config command with worker, window, and DIR flags."""
    west, south, east, north = _bbox_wsene_from_sweets_line(config_line)
    worker_flags = (
        "$DOLPHIN_WORKER_FLAGS"
        if runtime_workers
        else dolphin_worker_cli_flags(cpus_per_node, n_bursts_aoi)
    )
    window_flags = _dolphin_window_cli_flags(half_window, strides)
    parts = [
        f"dolphin config --slc-files {slc_files} --subdataset /data/VV "
        f"--work-directory {dolphin_dir} --mask-file watermask.tif "
        f"--output-options.bounds {west} {south} {east} {north} "
        f"{worker_flags}"
    ]
    if window_flags:
        parts.append(f" {window_flags}")
    if extra_flags:
        parts.append(f" {extra_flags}")
    parts.append(f" --outfile {outfile}")
    return "".join(parts)


def _cslc_dolphin_config_line(
    config_line: str,
    cpus_per_node: int,
    n_bursts_aoi: int,
    context: dict[str, object],
    extra_flags: str = "",
    outfile: str = "dolphin_config.yaml",
    half_window: tuple[int, int] | None = None,
    strides: tuple[int, int] | None = None,
    runtime_workers: bool = False,
    dolphin_dir: str = DEFAULT_DOLPHIN_DIR,
) -> str:
    """One-line dolphin config command with worker and window flags."""
    return _dolphin_config_line(
        config_line,
        cpus_per_node,
        n_bursts_aoi,
        _cslc_slc_files_arg(context),
        extra_flags=extra_flags,
        outfile=outfile,
        half_window=half_window,
        strides=strides,
        runtime_workers=runtime_workers,
        dolphin_dir=dolphin_dir,
    )


def _dolphin_body_commands(
    *,
    config_line: str,
    cpus_per_node: int,
    n_bursts: int,
    slc_files: str,
    half_window: tuple[int, int] | None,
    strides: tuple[int, int] | None,
    extra_flags: str,
    dolphin_dir: str,
    yaml_name: str,
    embed_config: bool,
    prefix: list[str] | None = None,
    wrapped_only: bool = False,
    merge_algo_cmd: str | None = None,
) -> list[str]:
    """cleanup, optional dolphin config (+ algo merge), then dolphin run (or wrapped-only)."""
    commands = list(prefix or [])
    commands.append(f"cleanup_dolphin_ministacks.py {dolphin_dir}")
    if embed_config:
        commands.append(
            _dolphin_config_line(
                config_line,
                cpus_per_node,
                n_bursts,
                slc_files,
                extra_flags=extra_flags,
                outfile=yaml_name,
                half_window=half_window,
                strides=strides,
                runtime_workers=False,
                dolphin_dir=dolphin_dir,
            )
        )
        if merge_algo_cmd:
            commands.append(merge_algo_cmd)
    if wrapped_only:
        commands.append(f"run_dolphin_wrapped.py --config {yaml_name}")
    else:
        commands.append(f"dolphin run {yaml_name}")
    return commands


def _cslc_dolphin_commands(
    config_line: str,
    cpus_per_node: int,
    n_bursts: int,
    context: dict[str, object],
    half_window: tuple[int, int] | None = None,
    strides: tuple[int, int] | None = None,
    extra_flags: str = "",
    dolphin_dir: str = DEFAULT_DOLPHIN_DIR,
    yaml_name: str = "dolphin_config.yaml",
    embed_config: bool = True,
    wrapped_only: bool = False,
    merge_algo_cmd: str | None = None,
) -> list[str]:
    """Shell commands for CSLC dolphin config + run (worker flags set at generate time)."""
    return _dolphin_body_commands(
        config_line=config_line,
        cpus_per_node=cpus_per_node,
        n_bursts=n_bursts,
        slc_files=_cslc_slc_files_arg(context),
        half_window=half_window,
        strides=strides,
        extra_flags=extra_flags,
        dolphin_dir=dolphin_dir,
        yaml_name=yaml_name,
        embed_config=embed_config,
        wrapped_only=wrapped_only,
        merge_algo_cmd=merge_algo_cmd,
    )


def _cslc_dolphin_wrapped_commands(
    config_line: str,
    cpus_per_node: int,
    n_bursts: int,
    context: dict[str, object],
    half_window: tuple[int, int] | None = None,
    strides: tuple[int, int] | None = None,
    extra_flags: str = "",
    dolphin_dir: str = DEFAULT_DOLPHIN_DIR,
    yaml_name: str = "dolphin_config.yaml",
    embed_config: bool = True,
    merge_algo_cmd: str | None = None,
) -> list[str]:
    """CSLC dolphin_wrapped: per-burst phase linking only; writes DIR YAML."""
    stop = _dolphin_stop_after_stitch_flags()
    flags = f"{extra_flags} {stop}".strip() if extra_flags else stop
    return _cslc_dolphin_commands(
        config_line,
        cpus_per_node,
        n_bursts,
        context,
        half_window=half_window,
        strides=strides,
        extra_flags=flags,
        dolphin_dir=dolphin_dir,
        yaml_name=yaml_name,
        embed_config=embed_config,
        wrapped_only=True,
        merge_algo_cmd=merge_algo_cmd,
    )


def _cslc_dolphin_unwrap_commands(yaml_name: str = "dolphin_config.yaml", dolphin_dir: str = DEFAULT_DOLPHIN_DIR) -> list[str]:
    """CSLC dolphin_unwrap: stitch burst ifgs, size n_parallel_jobs, then unwrap."""
    return [
        f"run_dolphin_stitch.py --config {yaml_name}",
        f'N_UNWRAP=$(resize_dolphin_unwrap_jobfile.py . --dolphin-config {yaml_name} --dolphin-dir {dolphin_dir})',
        f'run_dolphin_unwrap.py --config {yaml_name} --n-parallel-jobs "$N_UNWRAP"',
    ]


def _dolphin_plot_commands(dolphin_dir: str = DEFAULT_DOLPHIN_DIR) -> list[str]:
    return [
        f"plot_dolphin_summary_pngs.py --dir {dolphin_dir}",
        f"create_html.py {dolphin_dir}/pic",
    ]


def _cslc_dolphin_timeseries_commands(yaml_name: str = "dolphin_config.yaml") -> list[str]:
    """CSLC dolphin_timeseries: inversion/velocity only (plot/HTML run outside pixi)."""
    return [f"run_dolphin_timeseries.py --config {yaml_name}"]


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
        job_stem = job_file.stem
        lines = self.job_submit.get_job_file_lines(
            job_stem,
            job_stem,
            number_of_nodes=1,
            work_dir=str(job_file.parent),
        )
        work_dir = run_file.parent.parent.resolve()
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
        job_file.write_text("".join(lines))
        _make_executable(job_file)


def _parse_data_type(value: str) -> str:
    """Normalize --data-type to an internal workflow name."""
    token = value.strip().lower().replace("_", "-")
    if token not in DATA_TYPE_ALIASES:
        raise argparse.ArgumentTypeError(f"invalid data type {value!r}; use safe, cslc, disp-S1, or disp-NI")
    return DATA_TYPE_ALIASES[token]


def create_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    epilog = """Examples:
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type safe --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --dolphin-mode single-run --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --dolphin-mode opera --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --window-preset auto --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --window-preset standard --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --window-preset dry --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --window-preset wet --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --window-preset arctic --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --window-preset disp-s1 --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --window-preset dry --stride 2 4 --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --half-window 6 12 --stride 3 6 --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --dolphin-mode single-run --window-preset disp-s1 --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --dolphin-mode opera --window-preset disp-s1 --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --dolphin-mode opera --window-preset standard --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --dolphin-mode opera --reference-method BORDER --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna dolphin_config.yaml --flight-dir desc --data-type cslc --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna OPERA_L3_DISP-S1.nc --flight-dir desc --data-type cslc --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type disp --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type disp-S1 --start-date 20220101 --end-date 20241212
 create_isce3_runfiles.py 18.985:19.054,-98.686:-98.58 Popo --flight-dir desc --start-date 20170101 --end-date 20211231
 create_isce3_runfiles.py 18.985:19.054,-98.686:-98.58 Popo --flight-dir desc --data-type safe --start-date 20170101 --end-date 20211231
 create_isce3_runfiles.py 18.985:19.054,-98.686:-98.58 Popo --flight-dir desc --data-type cslc --start-date 20170101 --end-date 20211231
 create_isce3_runfiles.py 18.985:19.054,-98.686:-98.58 Popo --flight-dir desc --data-type cslc --dolphin-mode single-run --start-date 20170101 --end-date 20211231
 create_isce3_runfiles.py 18.985:19.054,-98.686:-98.58 Popo --flight-dir desc --data-type cslc --dolphin-mode opera --start-date 20170101 --end-date 20211231
 create_isce3_runfiles.py 18.985:19.054,-98.686:-98.58 Popo --flight-dir desc --data-type cslc --window-preset dry --start-date 20170101 --end-date 20211231
 create_isce3_runfiles.py 18.985:19.054,-98.686:-98.58 Popo --flight-dir desc --data-type cslc --dolphin-mode opera --window-preset disp-s1 --start-date 20170101 --end-date 20211231
 create_isce3_runfiles.py 18.985:19.054,-98.686:-98.58 Popo --flight-dir desc --data-type disp --start-date 20170101 --end-date 20211231
 create_isce3_runfiles.py 18.985:19.054,-98.686:-98.58 Popo --flight-dir desc --data-type disp-S1 --start-date 20170101 --end-date 20211231
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --start-date 20220101 --end-date 20241212 --phase download
 create_isce3_runfiles.py 19.45:19.51,-154.915:-154.835 HawaiiPuna --flight-dir desc --data-type cslc --start-date 20220101 --end-date 20241212 --no-dolphin-split"""
    parser = argparse.ArgumentParser(
        description=(
            "Create run files and SLURM job files for SAFE, CSLC, or DISP-S1 processing. "
            "Default data type: safe. "
            "AOI NAME HawaiiPuna becomes HawaiiPuna, HawaiiPunaCSLC, or HawaiiPunaDISP from --data-type. "
            "Workflow: --data-type {safe,cslc,disp-S1,disp-NI} or --safe / --cslc / --disp-S1. "
            "--phase download writes sweets_config.yaml and download jobs; "
            "--phase dolphin writes DIR YAML when CSLCs/GSLCs exist. "
            "Leftover --section.option flags go to dolphin config. Use --dolphin-dir, not --work-directory."
        ),
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument("input", help="MinSAR template, or AOI when followed by NAME")
    parser.add_argument("name", nargs="?", help="project name when INPUT is an AOI; CSLC or DISP is appended from --data-type")
    parser.add_argument(
        "dolphin_config",
        nargs="?",
        help=(
            "optional dolphin_config.yaml/.yml, or OPERA DISP-S1 .nc "
            "(uses metadata/dolphin_workflow_config when present)"
        ),
    )
    parser.add_argument("--safe", action="store_true", help="SAFE workflow (same as --data-type safe)")
    parser.add_argument("--cslc", action="store_true", help="CSLC workflow (same as --data-type cslc)")
    parser.add_argument(
        "--disp-S1",
        "--disp",
        dest="disp",
        action="store_true",
        help="DISP-S1 workflow (same as --data-type disp-S1); use --frame-id for OPERA frame",
    )
    parser.add_argument(
        "--data-type",
        type=_parse_data_type,
        metavar="TYPE",
        help="data type {safe,cslc,disp-S1,disp-NI}; default safe (or use --safe, --cslc, --disp-S1)",
    )
    parser.add_argument("--platform", default="S1", help="platform: S1 or NISAR/NI")
    parser.add_argument("--flight-dir", choices=("asc", "desc"), help="flight direction for AOI input")
    parser.add_argument("--start-date", "--start", dest="start_date", help="first date YYYYMMDD (default: ssaraopt.startDate from template)")
    parser.add_argument("--end-date", "--end", dest="end_date", help="last date YYYYMMDD (default: ssaraopt.endDate from template)")
    parser.add_argument("--track", "--relativeOrbit", type=int, dest="track", help="relative orbit (overrides template ssaraopt.relativeOrbit)")
    parser.add_argument("--frame-id", type=int, help="OPERA DISP-S1 frame ID (required for --disp-S1 / --data-type disp-S1)")
    parser.add_argument(
        "--queue",
        default=os.getenv("QUEUENAME"),
        help="SLURM partition for restart-safe jobs (default: $QUEUENAME)",
    )
    parser.add_argument("--long-queue", default="skx", help="SLURM partition for unsafe or unknown restart behavior")
    parser.add_argument("--config", type=Path, help="ISCE3 job defaults file")
    parser.add_argument(
        "--stride",
        nargs=2,
        metavar=("Y", "X"),
        default=None,
        help=f"output strides (Y X or from --window-preset) (default: {DEFAULT_STRIDES[0]} {DEFAULT_STRIDES[1]})",
    )
    parser.add_argument(
        "--half-window",
        nargs=2,
        metavar=("Y", "X"),
        default=None,
        help=f"phase-linking half-window (Y X or from --window-preset) (default: {DEFAULT_HALF_WINDOW[0]} {DEFAULT_HALF_WINDOW[1]})",
    )
    parser.add_argument(
        "--window-preset",
        type=_normalize_dolphin_preset,
        choices=DOLPHIN_PRESET_CHOICES,
        default=DEFAULT_PRESET,
        dest="preset",
        help=DOLPHIN_PRESET_HELP,
    )
    parser.add_argument(
        "--preset-naming",
        action="store_true",
        default=True,
        dest="preset_naming",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--no-preset-naming",
        action="store_false",
        dest="preset_naming",
        help=NO_PRESET_NAMING_HELP,
    )
    parser.add_argument("--dry-run", action="store_true", help="print the workflow without writing files or querying services")
    parser.add_argument(
        "--no-dolphin-split",
        action="store_true",
        help="SAFE/CSLC single-run mode: one dolphin stage instead of dolphin_wrapped, dolphin_unwrap, dolphin_timeseries",
    )
    parser.add_argument(
        "--dolphin-mode",
        type=_normalize_dolphin_mode,
        default=DEFAULT_DOLPHIN_MODE,
        metavar="MODE",
        help="CSLC path: single-run (one Dolphin stack) or opera (local DISP-S1 produce); default: single-run",
    )
    parser.add_argument(
        "--sleep",
        type=int,
        metavar="SECS",
        default=None,
        help="sleep seconds in each SLURM job file before the stage runs",
    )
    parser.add_argument(
        "--burst-count-method",
        choices=("sar_coverage", "opera-utils"),
        default="sar_coverage",
        help="estimate n_bursts when data/ is empty: sar_coverage (get_sar_coverage.py) or opera-utils (track from CLI or template)",
    )
    parser.add_argument(
        "--phase",
        type=_normalize_phase,
        default="all",
        metavar="NAME",
        help="download (includes create_cslc for SAFE), dolphin, or all (default: all). Alias: download_create_cslc",
    )
    parser.add_argument(
        "--dolphin-dir",
        default=None,
        metavar="DIR",
        help="Dolphin work directory name (default: dolphin, or auto-name from science-option diffs)",
    )
    parser.add_argument(
        "--from-dolphin-dir",
        default=DEFAULT_FROM_DIR,
        metavar="DIR",
        help="source DIR for YAML comparison and interferogram/unwrapped inputs (default: dolphin)",
    )
    parser.add_argument("--unwrap-method", metavar="NAME", help="shortcut for --unwrap-options.unwrap-method")
    parser.add_argument("--ministack-size", metavar="N", help="shortcut for --phase-linking.ministack-size")
    parser.add_argument(
        "--reference-method",
        type=_normalize_reference_method,
        default=DEFAULT_REFERENCE_METHOD,
        metavar="METHOD",
        help="opera-utils disp-s1-reformat reference: NONE, POINT, MEDIAN, BORDER, HIGH_COHERENCE (default: HIGH_COHERENCE)",
    )
    parser.add_argument(
        "--copy-dolphin-inputs",
        action="store_true",
        help="copy interferograms/unwrapped from --from-dolphin-dir instead of symlink",
    )
    parser.add_argument("--run", action="store_true", help="after creating files, run run_isce3_workflow.bash run_files_isce3 --start 1 --end N")
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
    """Run the generated workflow from step 1 through end_step in the project directory."""
    runner = Path(__file__).resolve().parent / "run_isce3_workflow.bash"
    if not runner.is_file():
        raise RuntimeError(f"run_isce3_workflow.bash not found: {runner}")
    os.chdir(work_dir)
    command = [str(runner), RUN_FILES_DIRNAME, "--start", "1", "--end", str(end_step)]
    print(f"cd $SCRATCHDIR/{work_dir.name}")
    print(f"Running: {' '.join(command)}")
    completed = subprocess.run(command, check=False)
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
    from minsar.utils.generate_sweets_config import flight_direction_from_template

    template = Template(str(template_file))
    template.get_options()
    options = template.options
    project = template_file.stem.replace(".template", "")
    subset = options.get("miaplpy.subset.lalo", "")
    if not subset:
        raise ValueError(f"template requires miaplpy.subset.lalo: {template_file}")
    start_date = args.start_date or _ssaraopt_date_yyyymmdd(options, "ssaraopt.startDate")
    end_date = args.end_date or _ssaraopt_date_yyyymmdd(options, "ssaraopt.endDate")
    flight_dir = args.flight_dir or flight_direction_from_template(str(template_file)) or ""
    return {
        "project": project,
        "template": str(template_file.resolve()),
        "aoi": str(subset).strip().strip("'\""),
        "start_date": start_date or "",
        "end_date": end_date or "",
        "track": _resolve_track_for_context(args, options),
        "track_source": _track_source_for_context(args, options),
        "frame_id": str(args.frame_id or ""),
        "flight_direction": flight_dir,
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
        "track_source": "cli" if args.track is not None else "",
        "frame_id": str(args.frame_id or ""),
        "flight_direction": args.flight_dir,
    }


def _subset_lalo_assignment(key: str, subset: str) -> str:
    """Return a template assignment in convert_bbox / miaplpy.subset.lalo layout."""
    return f"{key}                  = {subset}    #[S:N,W:E / no], auto for no"


def _fill_aoi_subset_lines(template_file: Path, aoi: str) -> None:
    """Write miaplpy.subset.lalo and dolphin.subset.lalo from the AOI (S:N,W:E)."""
    from minsar.scripts.create_template import _aoi_to_subset_lalo

    subset = _aoi_to_subset_lalo(aoi)
    miaplpy_line = _subset_lalo_assignment("miaplpy.subset.lalo", subset)
    dolphin_line = _subset_lalo_assignment("dolphin.subset.lalo", subset)
    lines = template_file.read_text().splitlines()
    out: list[str] = []
    miaplpy_idx: int | None = None
    have_dolphin = False
    for line in lines:
        if re.match(r"^\s*miaplpy\.subset\.lalo\s*=", line):
            miaplpy_idx = len(out)
            out.append(miaplpy_line)
            continue
        if re.match(r"^\s*dolphin\.subset\.lalo\s*=", line):
            have_dolphin = True
            out.append(dolphin_line)
            continue
        out.append(line)
    if miaplpy_idx is None:
        out.append(miaplpy_line)
        miaplpy_idx = len(out) - 1
    if not have_dolphin:
        out.insert(miaplpy_idx + 1, dolphin_line)
    template_file.write_text("\n".join(out) + "\n")


def _templates_dir() -> Path:
    """Return $TEMPLATES or $TE. AOI templates are always written here."""
    raw = os.environ.get("TEMPLATES") or os.environ.get("TE")
    if not raw:
        raise ValueError("TEMPLATES or TE must be set; source setup/environment.bash")
    return Path(raw).expanduser()


def _create_template_from_aoi(args: argparse.Namespace) -> Path:
    """Create the MinSAR template under $TE, independent of the invocation directory."""
    from minsar.scripts.create_template import main as create_template

    if not args.name:
        raise ValueError("AOI input requires a project NAME")
    if not args.flight_dir:
        raise ValueError("AOI input requires --flight-dir asc or desc")
    te_dir = _templates_dir()
    te_dir.mkdir(parents=True, exist_ok=True)
    command = [args.input, args.name, "--flight-dir", args.flight_dir, "--platform", "S1"]
    if args.start_date:
        command.extend(["--start-date", args.start_date])
    if args.end_date:
        command.extend(["--end-date", args.end_date])
    cwd = Path.cwd()
    os.chdir(te_dir)
    try:
        status, template_file, _, _ = create_template(command)
    finally:
        os.chdir(cwd)
    if status or template_file is None:
        raise RuntimeError("create_template.py could not resolve the AOI into a MinSAR template")
    path = Path(template_file).resolve()
    desired = (path.parent / f"{args.name}.template").resolve()
    if desired != path:
        desired.write_text(path.read_text())
        path = desired
    _fill_aoi_subset_lines(path, args.input)
    return path


def _runner_command(command: str) -> str:
    return f'pixi run --as-is --manifest-path "$MINSAR_HOME/tools/sweets/pyproject.toml" {command}'


def _use_dolphin_split(workflow: str, no_dolphin_split: bool) -> bool:
    """Return True when SAFE/CSLC should use split dolphin stages (default)."""
    return workflow in {"cslc", "safe"} and not no_dolphin_split


def _dolphin_stage_specs(split_dolphin: bool) -> list[tuple[str, str]]:
    if split_dolphin:
        return [
            ("dolphin_wrapped", "Run Dolphin per-burst phase linking"),
            ("dolphin_unwrap", "Stitch burst interferograms and unwrap"),
            ("dolphin_timeseries", "Run Dolphin timeseries inversion"),
        ]
    return [("dolphin", "Run Dolphin displacement processing")]


def _build_stage_specs(
    workflow: str,
    context: dict[str, object],
    split_dolphin: bool = False,
    dolphin_mode: str = DEFAULT_DOLPHIN_MODE,
) -> list[tuple[str, str, str]]:
    dolphin_specs = [(name, title, "") for name, title in _dolphin_stage_specs(split_dolphin)]
    if workflow == "safe":
        return [
            ("download_safe", "Download and verify SAFE data, then prepare COMPASS runconfigs", ""),
            ("create_cslc", "Create CSLCs and static layers with COMPASS", ""),
            *dolphin_specs,
            ("dolphin_2_hdfeos5", "Convert dolphin timeseries to HDF-EOS5", ""),
            ("ingest_insarmaps", "Ingest HDF-EOS5 product into InsarMaps", ""),
        ]
    if workflow == "cslc":
        if dolphin_mode == "opera":
            return [
                ("download_cslc", "Download and verify OPERA CSLCs, then prepare geometry", ""),
                (
                    "disp_s1_process",
                    "Produce OPERA DISP-S1 NetCDF products locally (sequential ministacks)",
                    "",
                ),
                (
                    "reformat_disp",
                    "Reformat locally produced DISP-S1 products into a stack",
                    "",
                ),
                ("dolphin_2_hdfeos5", "Convert DISP-S1 stack to HDF-EOS5", ""),
                ("ingest_insarmaps", "Ingest HDF-EOS5 product into InsarMaps", ""),
            ]
        return [
            ("download_cslc", "Download and verify OPERA CSLCs, then prepare geometry", ""),
            *dolphin_specs,
            ("dolphin_2_hdfeos5", "Convert dolphin timeseries to HDF-EOS5", ""),
            ("ingest_insarmaps", "Ingest HDF-EOS5 product into InsarMaps", ""),
        ]
    template = str(context["template"])
    generate = "" if template else "true"
    return [
        ("download_disp", "Download and verify OPERA DISP-S1 products", generate),
        ("reformat_disp", "Reformat DISP-S1 products into a stack", generate),
        ("dolphin_2_hdfeos5", "Convert stack to HDF-EOS5", generate),
        ("ingest_insarmaps", "Ingest HDF-EOS5 product into InsarMaps", generate),
    ]


def _profile_for(name: str, profiles: dict[str, ResourceProfile]) -> ResourceProfile:
    return profiles.get(PROFILE_ALIASES.get(name, name), profiles["default"])


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
    *,
    dolphin_dir: str = DEFAULT_DOLPHIN_DIR,
    yaml_name: str = "dolphin_config.yaml",
    extra_flags: str = "",
    embed_config: bool = True,
) -> list[Stage]:
    run_dir = _isce3_run_dir(work_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    phase = getattr(args, "phase", "all") or "all"
    dolphin_mode = getattr(args, "dolphin_mode", DEFAULT_DOLPHIN_MODE)
    all_specs = _build_stage_specs(
        workflow,
        context,
        split_dolphin=_use_dolphin_split(workflow, args.no_dolphin_split),
        dolphin_mode=dolphin_mode,
    )
    split_dolphin = _use_dolphin_split(workflow, args.no_dolphin_split)
    dolphin_profile_name = "dolphin_wrapped" if split_dolphin else "dolphin"
    dolphin_profile = _profile_for(dolphin_profile_name, profiles)
    dolphin_queue = args.queue if dolphin_profile.queue_class == "short" else args.long_queue
    science_stage_names = {"dolphin", *DOLPHIN_SPLIT_STAGES}
    if dolphin_mode == "opera":
        science_stage_names = set(OPERA_DOLPHIN_STAGES)
    need_dolphin_cpus = any(
        _stage_in_phase(name, workflow, phase) and name in science_stage_names
        for name, _, _ in all_specs
    )
    dolphin_cpus = 1
    if need_dolphin_cpus:
        profile_name = "disp_s1_process" if dolphin_mode == "opera" else dolphin_profile_name
        profile = _profile_for(profile_name, profiles)
        queue = args.queue if profile.queue_class == "short" else args.long_queue
        dolphin_cpus = int(_make_job_submit(work_dir, run_dir, queue, profile).number_of_cores_per_node)
    if workflow == "disp":
        bodies = _disp_stage_bodies(context, work_dir, reference_method=args.reference_method)
    elif workflow in {"safe", "cslc"}:
        bodies = _sweets_stage_bodies(
            workflow,
            context,
            dolphin_cpus,
            work_dir,
            split_dolphin=split_dolphin,
            preset=args.preset,
            preset_naming=args.preset_naming,
            burst_count_method=args.burst_count_method,
            phase=phase,
            dolphin_dir=dolphin_dir,
            yaml_name=yaml_name,
            extra_flags=extra_flags,
            embed_config=embed_config,
            half_window=getattr(args, "half_window_yx", None),
            strides=getattr(args, "strides_yx", None),
            imported_algo=getattr(args, "imported_algo", None),
            ministack_size=(
                int(args.ministack_size) if getattr(args, "ministack_size", None) else None
            ),
            dolphin_mode=dolphin_mode,
            reference_method=args.reference_method,
        )
    else:
        bodies = None
    if bodies is not None:
        missing = [
            name
            for name, _, _ in all_specs
            if _stage_in_phase(name, workflow, phase) and name not in bodies
        ]
        if missing:
            raise RuntimeError(f"{workflow} stage commands missing: {', '.join(missing)}")
        specs = [
            (name, title, bodies[name])
            for name, title, _ in all_specs
            if _stage_in_phase(name, workflow, phase)
        ]
    else:
        specs = [(name, title, command) for name, title, command in all_specs if _stage_in_phase(name, workflow, phase)]
    phase_names = {name for name, _, _ in specs}
    expected_names = set()
    deferred_stage_names = set()
    number_by_name = {name: number for number, (name, _, _) in enumerate(all_specs, 1)}
    for name, _, _ in specs:
        number = number_by_name[name]
        run_name = _run_basename_for_stage(name, number)
        expected_names.add(run_name)
        if name in DEFERRED_TASK_LIST_STAGES:
            deferred_stage_names.add(name)
        else:
            expected_names.add(f"{run_name}.job")
    if "create_cslc" in phase_names:
        expected_names.add(CREATE_CSLC_QUEUE_META)
    for path in sorted(run_dir.glob("run_[0-9][0-9]_run_disp_s1_process*")):
        path.unlink(missing_ok=True)
    candidates = [
        path
        for path in run_dir.glob("run_[0-9][0-9]_*")
        if path.suffix in {"", ".job"}
        and path.name not in expected_names
        and not _is_deferred_batch_job(path, deferred_stage_names)
    ]
    for basename in LEGACY_UNNUMBERED_RUN_BASENAMES:
        for suffix in ("", ".job"):
            path = run_dir / f"{basename}{suffix}"
            if path.exists() and path.name not in expected_names:
                candidates.append(path)
    if phase == "all":
        stale_files = sorted(candidates)
    else:
        stale_names = set(phase_names)
        if phase == "dolphin":
            stale_names.update({"dolphin", *DOLPHIN_SPLIT_STAGES, *OPERA_DOLPHIN_STAGES})
        stale_files = sorted(
            path for path in candidates if _run_file_stage_name(path) in stale_names
        )
    for path in stale_files:
        path.unlink()
    stages: list[Stage] = []
    for name, title, command in specs:
        number = number_by_name[name]
        profile = _profile_for(name, profiles)
        run_name = _run_basename_for_stage(name, number)
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
            _stage_queue(name, profile, args),
            profile.walltime,
            profile.memory_mb,
            profile.num_threads,
        )
        run_command = command
        if name == "disp_s1_process":
            run_command = _disp_s1_run_script(command)
        elif name in PIXI_STAGES and profile.execution_mode != "launcher-task-list":
            if name in _DOLPHIN_PIXI_PLOT_TAIL_STAGES:
                run_command = _pixi_run_script_with_tail(command, _dolphin_plot_commands(dolphin_dir))
            else:
                run_command = _pixi_run_script(command)
        _write_run_file(
            run_file,
            title,
            run_command,
            task_list=profile.execution_mode == "launcher-task-list",
            raw=_run_file_uses_raw_body(name, profile, run_command),
        )
        if name in DEFERRED_TASK_LIST_STAGES:
            (run_dir / CREATE_CSLC_QUEUE_META).write_text(stage.queue + "\n")
        else:
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
    preset_naming: bool = True,
    dolphin_dir: str | None = None,
    phase: str | None = None,
    layer: str | None = None,
    dolphin_mode: str | None = None,
) -> None:
    print(f"Workflow: {workflow.upper()} ({platform})")
    print(f"Project:  $SCRATCHDIR/{context['project']}")
    print(f"Run dir:  {RUN_FILES_DIRNAME}")
    template = str(context.get("template") or "").strip()
    if template:
        print(f"Template: {_format_template_path(template)}")
    if phase:
        print(f"Phase:    {phase}")
    if dolphin_mode and workflow == "cslc":
        print(f"Dolphin mode: {dolphin_mode}")
    if dolphin_dir and workflow in {"cslc", "safe"}:
        print(f"Dolphin:  {dolphin_dir}")
    if layer and workflow in {"cslc", "safe"} and dolphin_mode != "opera":
        print(f"Layer:    {layer}")
    if preset is not None and workflow in {"cslc", "safe"}:
        if dolphin_mode == "opera":
            print(f"HE5 name: {OPERA_DISP_METHOD_STRING}")
        elif preset_naming:
            print(f"HE5 name: {_hdfeos5_method_string(preset)}")
        else:
            print("HE5 name: dolphin (--no-preset-naming)")
    if queue is not None:
        print(f"Queue:    {queue} (long: {long_queue})")
    if stages is None:
        run_files = [
            f"run_{number:02d}_{name}"
            for number, (name, _, _) in enumerate(specs or [], 1)
            if not phase or _stage_in_phase(name, workflow, phase)
        ]
        print(f"run_files to create: {', '.join(run_files)}")


def _run_in_sweets(work_dir: Path, command: list[str]) -> None:
    """Run one command in the canonical SWEETS Pixi environment."""
    minsar_home = Path(os.environ.get("MINSAR_HOME", Path(__file__).resolve().parents[4]))
    pixi_command = [
        "pixi",
        "run",
        "--as-is",
        "--manifest-path",
        str(minsar_home / "tools/sweets/pyproject.toml"),
        *command,
    ]
    env = os.environ.copy()
    env["MINSAR_HOME"] = str(minsar_home)
    env["PYTHONPATH"] = str(minsar_home)
    pixi_bin = Path.home() / ".pixi" / "bin"
    env["PATH"] = f"{pixi_bin}:{env.get('PATH', '')}"
    subprocess.run(pixi_command, cwd=work_dir, env=env, check=True)


def _configure_sweets(workflow: str, template: Path, work_dir: Path) -> None:
    """Build and run only the SWEETS config command, leaving processing split by stage."""
    from minsar.utils.generate_sweets_config import build_from_template

    source = "burst" if workflow == "safe" else "cslc"
    command, _ = build_from_template(str(template), source)
    config_command = command.splitlines()[0] + " --overwrite"
    transparent_command = _runner_command(config_command)
    config_script = work_dir / "sweets_config_command.bash"
    config_script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        + transparent_command
        + "\n"
    )
    _make_executable(config_script)
    subprocess.run([str(config_script)], cwd=work_dir, check=True)


def _write_sweets_config(workflow: str, context: dict[str, object], work_dir: Path) -> None:
    """Write sweets_config.yaml on the login node (download run files start at sweets_download)."""
    line = _sweets_config_line(workflow, context)
    _run_in_sweets(work_dir, ["bash", "-c", line])


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
    n_bursts: int,
    context: dict[str, object],
    half_window: tuple[int, int] | None = None,
    strides: tuple[int, int] | None = None,
    extra_flags: str = "",
    dolphin_dir: str = DEFAULT_DOLPHIN_DIR,
    yaml_name: str = "dolphin_config.yaml",
    embed_config: bool = True,
    merge_algo_cmd: str | None = None,
) -> str:
    """Commands for CSLC dolphin config + run."""
    return (
        "\n".join(
            _cslc_dolphin_commands(
                config_line,
                cpus_per_node,
                n_bursts,
                context,
                half_window=half_window,
                strides=strides,
                extra_flags=extra_flags,
                dolphin_dir=dolphin_dir,
                yaml_name=yaml_name,
                embed_config=embed_config,
                merge_algo_cmd=merge_algo_cmd,
            )
        )
        + "\n"
    )


def _sweets_download_script(kind: str) -> str:
    """Download/check/retry script for SAFE or CSLC (sweets_config.yaml already written)."""
    cfg = SWEETS_CONFIG
    steps = [
        f"sweets_download.py --config {cfg}",
        f"check_sweets_download.py --config {cfg} --kind {kind} --delete --redownload",
        f"check_sweets_download.py --config {cfg} --kind {kind}",
    ]
    if kind == "cslc":
        steps.append(f"filter_cslc_missing_data.py --config {cfg}")
    return _bash_script(*steps)


def _sweets_stage_bodies(
    workflow: str,
    context: dict[str, object],
    cpus_per_node: int,
    work_dir: Path,
    split_dolphin: bool = False,
    preset: str = DEFAULT_PRESET,
    preset_naming: bool = True,
    burst_count_method: str = "sar_coverage",
    phase: str = "all",
    dolphin_dir: str = DEFAULT_DOLPHIN_DIR,
    yaml_name: str = "dolphin_config.yaml",
    extra_flags: str = "",
    embed_config: bool = True,
    half_window: tuple[int, int] | None = None,
    strides: tuple[int, int] | None = None,
    imported_algo: dict | None = None,
    ministack_size: int | None = None,
    dolphin_mode: str = DEFAULT_DOLPHIN_MODE,
    reference_method: str = DEFAULT_REFERENCE_METHOD,
) -> dict[str, str]:
    """Resolve concrete SAFE or CSLC run-file bodies at generate time."""
    config_line = _sweets_config_line(workflow, context)
    kind = "safe" if workflow == "safe" else "cslc"
    cfg = SWEETS_CONFIG
    download = _sweets_download_script(kind)
    hdfeos5 = _hdfeos5_command(preset, preset_naming, dolphin_dir=dolphin_dir)
    ingest = f"ingest_insarmaps.bash {dolphin_dir}/timeseries"
    geom = _geometry_stitch_command(strides, cfg)
    if workflow == "cslc" and dolphin_mode == "opera":
        disp_s1_process = _disp_s1_process_command(
            context,
            ministack_size=ministack_size,
            half_window=half_window,
            strides=strides,
        )
        reformat_disp = _reformat_disp_command(context, reference_method=reference_method) + "\n"
        if phase == "download":
            return {"download_cslc": download.rstrip("\n") + f"\n{geom}\n"}
        return {
            "download_cslc": download.rstrip("\n") + f"\n{geom}\n",
            "disp_s1_process": disp_s1_process,
            "reformat_disp": reformat_disp,
            "dolphin_2_hdfeos5": _opera_hdfeos5_command(context),
            "ingest_insarmaps": _opera_ingest_command(),
        }
    disp_s1_process = ""
    reformat_disp = ""
    merge_algo_cmd = None
    imported_path: Path | None = None
    if imported_algo is not None:
        imported_path = work_dir / IMPORTED_ALGO_YAML
        write_stripped_algo_yaml(imported_algo, imported_path)
        merge_algo_cmd = _merge_algo_cli(
            yaml_name,
            IMPORTED_ALGO_YAML,
            half_window,
            strides,
            ministack_size=ministack_size,
        )
    if phase == "download":
        if workflow == "safe":
            return {
                "download_safe": download.rstrip("\n") + f"\nprepare_compass_runconfigs.py --config {cfg}\n",
                "create_cslc": "",
            }
        return {"download_cslc": download.rstrip("\n") + f"\n{geom}\n"}
    n_bursts = _resolve_n_bursts_for_dolphin(
        work_dir, context, burst_count_method=burst_count_method
    )
    slc_files = _safe_slc_files_arg(work_dir) if workflow == "safe" else _cslc_slc_files_arg(context)
    if not embed_config:
        flags = extra_flags
        if split_dolphin:
            stop = _dolphin_stop_after_stitch_flags()
            flags = f"{extra_flags} {stop}".strip() if extra_flags else stop
        yaml_cmd = _dolphin_config_line(
            config_line,
            cpus_per_node,
            n_bursts,
            slc_files,
            extra_flags=flags,
            outfile=yaml_name,
            half_window=half_window,
            strides=strides,
            runtime_workers=False,
            dolphin_dir=dolphin_dir,
        )
        _run_in_sweets(work_dir, ["bash", "-c", yaml_cmd])
        if imported_algo is not None and imported_path is not None:
            merge_imported_into_dolphin_yaml(
                work_dir / yaml_name,
                imported_algo,
                half_window=half_window,
                strides=strides,
                ministack_size=ministack_size,
            )
    unwrap_cmds = "\n".join(_cslc_dolphin_unwrap_commands(yaml_name, dolphin_dir)) + "\n"
    ts_cmds = "\n".join(_cslc_dolphin_timeseries_commands(yaml_name)) + "\n"
    if workflow == "safe":
        bodies: dict[str, str] = {
            "download_safe": download.rstrip("\n") + f"\nprepare_compass_runconfigs.py --config {cfg}\n",
            "create_cslc": "",
            "dolphin_2_hdfeos5": hdfeos5,
            "ingest_insarmaps": ingest,
        }
        if split_dolphin:
            wrapped = _dolphin_body_commands(
                config_line=config_line,
                cpus_per_node=cpus_per_node,
                n_bursts=n_bursts,
                slc_files=slc_files,
                half_window=half_window,
                strides=strides,
                extra_flags=(
                    f"{extra_flags} {_dolphin_stop_after_stitch_flags()}".strip()
                    if extra_flags
                    else _dolphin_stop_after_stitch_flags()
                ),
                dolphin_dir=dolphin_dir,
                yaml_name=yaml_name,
                embed_config=embed_config,
                prefix=[geom],
                wrapped_only=True,
                merge_algo_cmd=merge_algo_cmd,
            )
            bodies["dolphin_wrapped"] = "\n".join(wrapped) + "\n"
            bodies["dolphin_unwrap"] = unwrap_cmds
            bodies["dolphin_timeseries"] = ts_cmds
        else:
            bodies["dolphin"] = _bash_script(
                *_dolphin_body_commands(
                    config_line=config_line,
                    cpus_per_node=cpus_per_node,
                    n_bursts=n_bursts,
                    slc_files=slc_files,
                    half_window=half_window,
                    strides=strides,
                    extra_flags=extra_flags,
                    dolphin_dir=dolphin_dir,
                    yaml_name=yaml_name,
                    embed_config=embed_config,
                    prefix=[geom],
                    merge_algo_cmd=merge_algo_cmd,
                )
            )
        return bodies
    if split_dolphin:
        return {
            "download_cslc": download.rstrip("\n") + f"\n{geom}\n",
            "dolphin_wrapped": "\n".join(
                _cslc_dolphin_wrapped_commands(
                    config_line,
                    cpus_per_node,
                    n_bursts,
                    context,
                    half_window=half_window,
                    strides=strides,
                    extra_flags=extra_flags,
                    dolphin_dir=dolphin_dir,
                    yaml_name=yaml_name,
                    embed_config=embed_config,
                    merge_algo_cmd=merge_algo_cmd,
                )
            )
            + "\n",
            "dolphin_unwrap": unwrap_cmds,
            "dolphin_timeseries": ts_cmds,
            "dolphin_2_hdfeos5": hdfeos5,
            "ingest_insarmaps": ingest,
        }
    return {
        "download_cslc": download.rstrip("\n") + f"\n{geom}\n",
        "dolphin": _cslc_dolphin_script(
            config_line,
            cpus_per_node,
            n_bursts,
            context,
            half_window=half_window,
            strides=strides,
            extra_flags=extra_flags,
            dolphin_dir=dolphin_dir,
            yaml_name=yaml_name,
            embed_config=embed_config,
            merge_algo_cmd=merge_algo_cmd,
        ),
        "dolphin_2_hdfeos5": hdfeos5,
        "ingest_insarmaps": ingest,
    }


def _extent_from_aoi(aoi: str) -> str:
    """Return disp_s1_process --extent value from S:N,W:E subset string."""
    from minsar.utils.generate_sweets_config import bbox_wsene

    west, south, east, north = bbox_wsene(aoi)
    return f"{west},{south} : {east},{north}"


def _stage_queue(name: str, profile: ResourceProfile, args: argparse.Namespace) -> str:
    """Queue for a stage from job_defaults queue_class and --queue / --long-queue."""
    return args.queue if profile.queue_class == "short" else args.long_queue


def _run_file_uses_raw_body(name: str, profile: ResourceProfile, run_command: str) -> bool:
    """True when the run file body is written verbatim (pixi script, task list, or existing bash script)."""
    if name == "disp_s1_process":
        return True
    if profile.execution_mode == "launcher-task-list":
        return True
    if name in PIXI_STAGES:
        return True
    return run_command.lstrip().startswith("#!")


def _resolve_disp_s1_frame_id(context: dict[str, object]) -> int:
    """OPERA DISP-S1 frame ID from CLI or largest-overlap frame for the AOI."""
    frame_raw = str(context.get("frame_id") or "").strip()
    if frame_raw:
        return int(frame_raw)
    from minsar.utils.generate_sweets_config import bbox_wsene

    module = runpy.run_path(str(_disp_module_path()))
    resolve_frame_id = module["resolve_frame_id"]
    aoi = str(context["aoi"])
    bbox = bbox_wsene(aoi)
    track_raw = str(context.get("track") or "")
    track = int(track_raw) if track_raw else None
    flight = str(context.get("flight_direction") or "") or None
    return resolve_frame_id(bbox, track=track, flight_direction=flight)


def _disp_s1_stride_window_flags(
    half_window: tuple[int, int] | None,
    strides: tuple[int, int] | None,
) -> str:
    """CLI flags for disp_s1_process half-window and output strides."""
    parts: list[str] = []
    if half_window is not None:
        parts.append(f" --half-window {half_window[0]} {half_window[1]}")
    if strides is not None:
        parts.append(f" --stride {strides[0]} {strides[1]}")
    return "".join(parts)


def _disp_s1_process_command(
    context: dict[str, object],
    *,
    ministack_size: int | None = None,
    cslc_dir: str = "data",
    work_subdir: str = DISP_S1_PRODUCE_DIR,
    half_window: tuple[int, int] | None = None,
    strides: tuple[int, int] | None = None,
) -> str:
    """Shell command for tools/disp-s1/scripts/disp_s1_process.py (process stage only)."""
    frame_id = _resolve_disp_s1_frame_id(context)
    extent = _extent_from_aoi(str(context["aoi"]))
    ms = int(ministack_size) if ministack_size is not None else DEFAULT_DISP_S1_MINISTACK_SIZE
    args = (
        f" --cslc-dir {cslc_dir}"
        f" --work-dir {work_subdir}"
        f" --frame-id {frame_id}"
        f' --extent "{extent}"'
        f" --gslc-glob 'OPERA_L2_CSLC-S1_*.h5'"
        f" --ministack-size {ms}"
        f" --buffer 500"
        f" --stages process"
        f"{_disp_s1_stride_window_flags(half_window, strides)}"
    )
    return (
        f"{DISP_S1_PROCESS_CMD}{args}"
    )


def _reformat_disp_command(
    context: dict[str, object],
    *,
    work_subdir: str = DISP_S1_PRODUCE_DIR,
    reference_method: str = DEFAULT_REFERENCE_METHOD,
) -> str:
    """Shell command to reformat disp_s1_process .nc outputs into one stack (same as disp workflow reformat)."""
    module = runpy.run_path(str(_disp_module_path()))
    format_reformat = module["format_disp_s1_reformat_command"]
    project = str(context["project"])
    return format_reformat(
        input_files=f"{work_subdir}/output_*/OPERA*.nc",
        output_name=f"{project}-stack.nc",
        reference_method=reference_method,
    )


def _disp_module_path() -> Path:
    minsar_home = Path(os.environ.get("MINSAR_HOME", Path(__file__).resolve().parents[4]))
    return minsar_home / "minsar/utils/generate_disp-s1_commands.py"


def _disp_stage_bodies(
    context: dict[str, object],
    work_dir: Path,
    *,
    reference_method: str = DEFAULT_REFERENCE_METHOD,
) -> dict[str, str]:
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
        "reference_method": reference_method,
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
        "end_date=sys.argv[4] or None,frame_id=int(sys.argv[5]) if sys.argv[5] else None,url_type='HTTPS',"
        "reference_method=sys.argv[6] or 'HIGH_COHERENCE');"
        "Path(sys.argv[7]).write_text(json.dumps(stages))"
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
                reference_method,
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
    run_dir = _isce3_run_dir(work_dir)
    if action == "dolphin":
        dolphin_files = sorted(run_dir.glob("run_*_dolphin"))
        if not dolphin_files:
            raise RuntimeError(
                f"dolphin run file not found under {RUN_FILES_DIRNAME}/; "
                "run create_isce3_runfiles.py first"
            )
        subprocess.run(["bash", str(dolphin_files[-1])], cwd=work_dir, check=True)
        return 0
    if action in DOLPHIN_SPLIT_STAGES:
        stage_files = sorted(run_dir.glob(f"run_*_{action}"))
        if not stage_files:
            raise RuntimeError(
                f"{action} run file not found under {RUN_FILES_DIRNAME}/; "
                "run create_isce3_runfiles.py first"
            )
        subprocess.run(["bash", str(stage_files[-1])], cwd=work_dir, check=True)
        return 0
    if action in ("dolphin-2-hdfeos5", "dolphin_2_hdfeos5"):
        stage_files = sorted(run_dir.glob("run_*_dolphin_2_hdfeos5"))
        if not stage_files:
            raise RuntimeError(
                f"dolphin_2_hdfeos5 run file not found under {RUN_FILES_DIRNAME}/; "
                "run create_isce3_runfiles.py first"
            )
        subprocess.run(["bash", str(stage_files[-1])], cwd=work_dir, check=True)
        return 0
    if action == "ingest-insarmaps":
        stage_files = sorted(run_dir.glob("run_*_ingest_insarmaps"))
        if not stage_files:
            raise RuntimeError(
                f"ingest_insarmaps run file not found under {RUN_FILES_DIRNAME}/; "
                "run create_isce3_runfiles.py first"
            )
        subprocess.run(["bash", str(stage_files[-1])], cwd=work_dir, check=True)
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
    args, extras = create_parser().parse_known_args(argv)
    try:
        if any(token == "--preset" or token.startswith("--preset=") for token in (*argv, *extras)):
            raise ValueError("use --window-preset, not --preset")
        _normalize_dolphin_config_positionals(args)
        half_window_cli = None
        if args.half_window is not None:
            half_window_cli = _parse_yx_pair(args.half_window, "--half-window")
        strides_cli = None
        if args.stride is not None:
            strides_cli = _parse_yx_pair(args.stride, "--stride")
        imported_algo = None
        if args.dolphin_config:
            config_path = Path(args.dolphin_config).expanduser().resolve()
            if not config_path.is_file():
                raise ValueError(f"dolphin config not found: {config_path}")
            if config_path.suffix.lower() == ".nc":
                from minsar.utils.extract_dolphin_config_yaml import extract_config_yaml

                src_name, _ = extract_config_yaml(config_path)
                print(f"Using OPERA DISP config from NetCDF dataset: {src_name}")
            imported_algo = load_algo_mapping(config_path)
        args.half_window_yx, args.strides_yx = resolve_half_window_strides(
            args.preset,
            half_window=half_window_cli,
            strides=strides_cli,
            imported=imported_algo,
        )
        args.imported_algo = imported_algo
        parse_passthrough_pairs(extras)
        passthrough = list(extras)
        if getattr(args, "unwrap_method", None):
            passthrough = ["--unwrap-options.unwrap-method", args.unwrap_method, *passthrough]
        if getattr(args, "ministack_size", None):
            passthrough = ["--phase-linking.ministack-size", str(args.ministack_size), *passthrough]
        extra_flags = passthrough_cli_flags(passthrough)
        if not args.queue:
            raise ValueError("No queue: set QUEUENAME or pass --queue")
        if args.run and args.dry_run:
            raise ValueError("--run cannot be combined with --dry-run")
        if args.sleep is not None and args.sleep < 0:
            raise ValueError("--sleep must be a non-negative integer")
        invocation_dir = Path.cwd().resolve()
        workflow = _workflow_name(args)
        if args.dolphin_mode == "opera" and workflow != "cslc":
            raise ValueError("--dolphin-mode opera requires --data-type cslc")
        if args.dolphin_mode == "opera" and args.no_dolphin_split:
            raise ValueError("--no-dolphin-split does not apply to --dolphin-mode opera")
        split_dolphin = _use_dolphin_split(workflow, args.no_dolphin_split)
        platform = _normalize_platform(args.platform)
        if platform == "NISAR":
            raise ValueError("NISAR is accepted but processing is not implemented until RSLC/GSLC commands are defined")
        input_path = Path(args.input).expanduser()
        input_is_template = input_path.is_file()
        if not input_is_template and args.name:
            args.name = _aoi_name_with_data_type(args.name, workflow)
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
        layer = "wrapped"
        dolphin_dir = DEFAULT_DOLPHIN_DIR
        yaml_name = "dolphin_config.yaml"
        embed_config = True
        if workflow == "disp":
            if args.dolphin_dir:
                raise ValueError("--dolphin-dir does not apply to DISP-S1")
        else:
            extra_pairs: list[tuple[str, str | None]] = []
            if args.preset and args.preset != "auto":
                extra_pairs.append(("preset", args.preset))
            dolphin_dir, _diffs, layer = resolve_dolphin_dir(
                explicit_dir=args.dolphin_dir,
                passthrough=passthrough,
                from_dir=args.from_dolphin_dir,
                work_dir=work_dir,
                extra_pairs=extra_pairs,
            )
            yaml_name = config_yaml_name(dolphin_dir)
            if args.phase == "dolphin" and not has_cslc_or_gslc(work_dir, workflow):
                raise ValueError("CSLCs/GSLCs not found; run `--start download` first")
            data_ready = has_cslc_or_gslc(work_dir, workflow)
            embed_config = not (args.phase in {"dolphin", "all"} and data_ready)
        specs = _build_stage_specs(
            workflow, context, split_dolphin=split_dolphin, dolphin_mode=args.dolphin_mode
        )
        _log_command_line([invocation_dir, work_dir], Path(__file__).name, argv)
        if args.dry_run:
            _print_plan(
                workflow, platform, context, None, specs, args.queue, args.long_queue,
                preset=args.preset, preset_naming=args.preset_naming,
                dolphin_dir=dolphin_dir, phase=args.phase, layer=layer,
                dolphin_mode=args.dolphin_mode,
            )
            return 0
        work_dir.mkdir(parents=True, exist_ok=True)
        template_src = Path(str(context.get("template") or ""))
        if template_src.is_file():
            template_dest = work_dir / template_src.name
            if template_dest.resolve() != template_src.resolve():
                template_dest.write_text(template_src.read_text())
        os.chdir(work_dir)
        if workflow in {"safe", "cslc"} and args.phase in {"download", "all"}:
            _write_sweets_config(workflow, context, work_dir)
        if workflow in {"safe", "cslc"} and args.phase != "download":
            if not (workflow == "cslc" and args.dolphin_mode == "opera"):
                stage_dolphin_inputs(
                    work_dir,
                    src_dir=args.from_dolphin_dir,
                    dst_dir=dolphin_dir,
                    layer=layer,
                    copy=args.copy_dolphin_inputs,
                )
            write_dolphin_dir_sidecar(work_dir, dolphin_dir)
            write_run_slice_sidecar(
                work_dir,
                dolphin_dir=dolphin_dir,
                layer=layer,
                phase=args.phase,
                yaml_name=yaml_name,
                dolphin_mode=args.dolphin_mode,
            )
        stages = _create_files(
            args,
            workflow,
            context,
            profiles,
            work_dir,
            dolphin_dir=dolphin_dir,
            yaml_name=yaml_name,
            extra_flags=extra_flags,
            embed_config=embed_config,
        )
        _print_plan(
            workflow, platform, context, stages, queue=args.queue, long_queue=args.long_queue,
            preset=args.preset, preset_naming=args.preset_naming,
            dolphin_dir=dolphin_dir, phase=args.phase, layer=layer,
            dolphin_mode=args.dolphin_mode,
        )
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
