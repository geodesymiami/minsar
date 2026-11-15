"""Build MinSAR run files from an alosStack no-ionosphere cmd_1.sh, cmd_2.sh, and cmd_4.sh."""

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

ARRAY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=\((.*)\)\s*$")
FOR_RE = re.compile(r"^for \(\(i=0;i<\$\{#([A-Za-z_][A-Za-z0-9_]*)\[@\]\};i\+\+\)\); do\s*$")
PROGRAM_RE = re.compile(r"([A-Za-z0-9_]+)\.py(?:\s|$)")

# (run-file stem, (program, is_loop) for each step joined into one task)
RUN_FILES = (
    ("run_01_read_baseline_burst", (("read_data.py", False), ("compute_baseline.py", False), ("compute_burst_sync.py", False))),
    ("run_02_estimate_slc_offset", (("estimate_slc_offset.py", True),)),
    ("run_03_estimate_swath_frame_offset", (("estimate_swath_offset.py", False), ("estimate_frame_offset.py", False))),
    ("run_04_resample_common_grid", (("resample_common_grid.py", True),)),
    ("run_05_mosaic_rdr2geo", (("mosaic_parameter.py", False), ("rdr2geo.py", False))),
    ("run_06_geo2rdr", (("geo2rdr.py", True),)),
    ("run_07_pair_up", (("pair_up.py", False),)),
    ("run_08_form_interferogram", (("form_interferogram.py", True),)),
    ("run_09_mosaic_interferogram", (("mosaic_interferogram.py", True),)),
    ("run_10_radar_dem_offset", (("radar_dem_offset.py", False),)),
    ("run_11_rect_range_offset", (("rect_range_offset.py", True),)),
    ("run_12_diff_look_filt", (("diff_interferogram.py", True), ("look_coherence.py", True), ("filt.py", True))),
    ("run_13_look_geom", (("look_geom.py", False),)),
    ("run_14_geocode_los", (("geocode.py", False),)),
    ("run_15_unwrap", (("unwrap_snaphu.py", True),)),
    ("run_16_geocode", (("geocode.py", True),)),
)


@dataclass
class Step:
    program: str
    loop: bool
    tasks: list
    keys: list
    used: bool = field(default=False)


def write_alos2_run_files(alos2_cmds, run_dir, work_dir):
    """Write run_01..run_16 and, where a task cds more than once, a bash file per task."""
    planned = plan_alos2_run_files(alos2_cmds)
    run_dir = Path(run_dir)
    work_dir = Path(work_dir)
    tasks_dir = run_dir / "tasks"
    run_dir.mkdir(parents=True, exist_ok=True)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    _clear_previous(run_dir, tasks_dir)
    written = []
    for name, tasks in planned:
        lines = []
        for key, body in tasks:
            if _cd_count(body) > 1:
                task_name = f"{name}.bash" if key is None else f"{name}_{key}.bash"
                task_path = tasks_dir / task_name
                _write_task(task_path, work_dir, body)
                lines.append(f"bash {_bash_command(task_path, work_dir)}")
            else:
                lines.append(" && ".join(body))
        path = run_dir / name
        path.write_text("".join(f"{line}\n" for line in lines))
        written.append(path)
    if run_dir.resolve() == (work_dir / "run_files").resolve():
        list_path = work_dir / "run_files_list"
        list_path.write_text("".join(f"{path.resolve()}\n" for path in written))
    return written


def plan_alos2_run_files(alos2_cmds):
    """Return (run-file stem, [(key or None, shell lines), ...]) in plan order."""
    alos2_cmds = Path(alos2_cmds)
    _reject_ionosphere(alos2_cmds / "cmd_3.sh")
    steps = []
    for index in (1, 2, 4):
        path = alos2_cmds / f"cmd_{index}.sh"
        if not path.is_file():
            raise RuntimeError(f"missing {path}")
        steps.extend(_parse_cmd(path))
    planned = []
    for name, spec in RUN_FILES:
        chosen = [_take(steps, program, loop) for program, loop in spec]
        planned.append((name, _combine(name, chosen)))
    unused = [step.program for step in steps if not step.used]
    if unused:
        raise RuntimeError(f"alosStack commands not in the run-file plan: {', '.join(unused)}")
    return planned


def _reject_ionosphere(cmd_3):
    if cmd_3.is_file() and ".py" in cmd_3.read_text():
        raise RuntimeError(f"{cmd_3} contains ionosphere commands; this layout is the no-ionosphere run")


def _parse_cmd(path):
    lines = path.read_text().splitlines()
    arrays = {}
    for line in lines:
        match = ARRAY_RE.match(line.strip())
        if match:
            arrays[match.group(1)] = shlex.split(match.group(2))
    steps = []
    serial = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        match = FOR_RE.match(stripped)
        if match:
            steps.extend(_serial_steps(serial))
            serial = []
            body, index = _loop_body(lines, index + 1)
            array_name = match.group(1)
            if array_name not in arrays:
                raise RuntimeError(f"cannot find {array_name}=() in {path}")
            steps.extend(_loop_steps(body, arrays[array_name], array_name, path))
            continue
        if stripped and not stripped.startswith("#") and not _skip(stripped) and not ARRAY_RE.match(stripped):
            serial.append(stripped)
        index += 1
    steps.extend(_serial_steps(serial))
    return steps


def _loop_body(lines, start):
    body = []
    index = start
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped == "done":
            return body, index + 1
        if stripped and not stripped.startswith("#") and not _skip(stripped):
            body.append(stripped)
        index += 1
    raise RuntimeError("for loop has no done")


def _skip(stripped):
    if stripped in {"continue", "fi", "do", "done", "(", ") &", ")&"} or stripped.startswith(") &"):
        return True
    if stripped.startswith("if ") or stripped.startswith("IFS=") or stripped.startswith("ref_date=") or stripped.startswith("sec_date="):
        return True
    if stripped.startswith("for ") or "_minsar_" in stripped or stripped.startswith("wait ") or stripped == "exit 1":
        return True
    return False


def _serial_steps(lines):
    for line in lines:
        if "${" in line:
            raise RuntimeError(f"unexpanded shell variable outside a date or pair loop: {line}")
    return [
        Step(program, False, [body], [None])
        for program, body in _chunk(lines)
    ]


def _loop_steps(body, values, array_name, path):
    if not values:
        return []
    expanded = []
    for value in values:
        lines = [_substitute(line, array_name, value, path) for line in body]
        expanded.append(_chunk(lines))
    width = len(expanded[0])
    steps = []
    for column in range(width):
        program = expanded[0][column][0]
        tasks = []
        for item, value in zip(expanded, values):
            if len(item) != width or item[column][0] != program:
                raise RuntimeError(f"loop body in {path} does not have the same commands for every {array_name}")
            tasks.append(item[column][1])
        steps.append(Step(program, True, tasks, list(values)))
    return steps


def _substitute(line, array_name, value, path):
    text = line.replace(f"${{{array_name}[i]}}", value)
    if array_name == "insarpair":
        ref, sec = value.split("-", 1)
        text = text.replace("${ref_date}", ref).replace("${sec_date}", sec)
    if "${" in text:
        raise RuntimeError(f"unexpanded shell variable in {path}: {text}")
    return text


def _chunk(lines):
    chunks = []
    program = None
    current = []
    pending = []
    for line in lines:
        found = _program(line)
        if found:
            if program and found != program:
                chunks.append((program, current))
                current = pending + [line]
            else:
                current.extend(pending)
                current.append(line)
            pending = []
            program = found
        else:
            pending.append(line)
    if program:
        current.extend(pending)
        chunks.append((program, current))
    elif pending:
        raise RuntimeError(f"shell lines are not attached to an alosStack program: {pending[0]}")
    return chunks


def _program(line):
    match = PROGRAM_RE.search(line.strip())
    if not match:
        return None
    return f"{match.group(1)}.py"


def _take(steps, program, loop):
    for step in steps:
        if not step.used and step.program == program and step.loop == loop:
            step.used = True
            return step
    kind = "loop" if loop else "single call"
    raise RuntimeError(f"missing {kind} of {program}")


def _combine(name, steps):
    count = len(steps[0].tasks)
    keys = steps[0].keys
    for step in steps[1:]:
        if len(step.tasks) != count or step.keys != keys:
            raise RuntimeError(f"{name} joins steps that do not share the same dates or pairs")
    tasks = []
    for index in range(count):
        body = []
        for step in steps:
            body.extend(step.tasks[index])
        tasks.append((keys[index], body))
    return tasks


def _cd_count(lines):
    return sum(1 for line in lines if line.startswith("cd "))


def _write_task(path, work_dir, body):
    lines = ["#!/usr/bin/env bash", "set -eo pipefail", f"cd {shlex.quote(str(work_dir))}"]
    lines.extend(body)
    path.write_text("".join(f"{line}\n" for line in lines))
    path.chmod(0o755)


def _bash_command(task_path, work_dir):
    try:
        relative = task_path.resolve().relative_to(work_dir.resolve())
    except ValueError:
        return shlex.quote(str(task_path))
    return relative.as_posix()


def _clear_previous(run_dir, tasks_dir):
    for path in run_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix in {".job", ".e", ".o"}:
            continue
        if re.match(r"run_\d\d_", path.name):
            path.unlink()
    for path in tasks_dir.glob("run_*.bash"):
        path.unlink()
