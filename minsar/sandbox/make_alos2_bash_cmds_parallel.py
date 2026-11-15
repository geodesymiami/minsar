#!/usr/bin/env python3
"""Background date and interferogram loops in alosStack cmd_*.sh."""

import argparse
import re
import sys
from pathlib import Path

MARKER = "# minsar-parallel-loop"
FOR_RE = re.compile(r"^for \(\(i=0;i<\$\{#([A-Za-z_][A-Za-z0-9_]*)\[@\]\};i\+\+\)\); do\s*$")

DESCRIPTION = "Background date and interferogram loops in alosStack cmd_*.sh."
EXAMPLE = """
Examples:
    make_alos2_bash_cmds_parallel.py alos2_cmds
    make_alos2_bash_cmds_parallel.py /scratch/05861/tg851601/CameroonAlos2D89/alos2_cmds
"""


def create_parser():
    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("alos2_cmds", metavar="ALOS2_CMDS", help="directory that contains cmd_*.sh")
    parser.add_argument("--dry-run", action="store_true", help="print what would change and do not write")
    return parser


def _matching_fi(lines, start):
    """Return the index of the fi that closes an if starting at start."""
    depth = 0
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("if ") or stripped.startswith("if [["):
            depth += 1
        elif stripped == "fi":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"unclosed if at line {start + 1}")


def _loop_end(lines, body_start):
    for index in range(body_start, len(lines)):
        if lines[index].strip() == "done":
            return index
    raise ValueError("for loop has no done")


def _split_loop(lines, for_index):
    """Return (guard_end, body_start, done_index) for a for-loop at for_index."""
    index = for_index + 1
    while index < len(lines) and lines[index].strip() == "":
        index += 1
    guard_end = None
    if index < len(lines) and "${parallel}" in lines[index]:
        guard_end = _matching_fi(lines, index)
        body_start = guard_end + 1
    else:
        body_start = for_index + 1
    done_index = _loop_end(lines, body_start)
    return guard_end, body_start, done_index


def _body_is_parallel(body_lines):
    text = "\n".join(body_lines)
    return "_minsar_pids+=($!)" in text or text.rstrip().endswith(") &")


def _parallel_body(body_lines):
    stripped = list(body_lines)
    while stripped and stripped[0].strip() == "":
        stripped.pop(0)
    while stripped and stripped[-1].strip() == "":
        stripped.pop()
    if not any(line.strip() for line in stripped):
        return None
    block = ["  (", *stripped, "  ) &", "  _minsar_pids+=($!)"]
    return block


def _wait_block():
    return [
        "_minsar_fail=0",
        'for _minsar_pid in "${_minsar_pids[@]}"; do',
        '  wait "$_minsar_pid" || _minsar_fail=1',
        "done",
        "if [[ $_minsar_fail -ne 0 ]]; then",
        "  exit 1",
        "fi",
        "",
    ]


def parallelize_text(text):
    """Return (new_text, converted_arrays, already_arrays)."""
    lines = text.splitlines()
    converted = []
    already = []
    index = 0
    output = []
    while index < len(lines):
        match = FOR_RE.match(lines[index])
        if not match:
            output.append(lines[index])
            index += 1
            continue
        array_name = match.group(1)
        guard_end, body_start, done_index = _split_loop(lines, index)
        body = lines[body_start:done_index]
        previous = output[-1].strip() if output else ""
        if previous == MARKER or _body_is_parallel(body):
            already.append(array_name)
            output.extend(lines[index:done_index + 1])
            index = done_index + 1
            continue
        new_body = _parallel_body(body)
        if new_body is None:
            output.extend(lines[index:done_index + 1])
            index = done_index + 1
            continue
        output.append(MARKER)
        output.append("_minsar_pids=()")
        output.append(lines[index])
        if guard_end is None:
            output.extend(lines[index + 1:body_start])
        else:
            output.extend(lines[index + 1:guard_end + 1])
        output.extend(new_body)
        output.append(lines[done_index])
        output.extend(_wait_block())
        converted.append(array_name)
        index = done_index + 1
    trailer = "\n" if text.endswith("\n") else ""
    return "\n".join(output) + trailer, converted, already


def cmd_scripts(alos2_cmds):
    return sorted(path for path in alos2_cmds.glob("cmd_*.sh") if path.is_file())


def main(argv=None):
    args = create_parser().parse_args(argv)
    alos2_cmds = Path(args.alos2_cmds)
    if not alos2_cmds.is_dir():
        print(f"ERROR: directory not found: {alos2_cmds}", file=sys.stderr)
        return 1
    scripts = cmd_scripts(alos2_cmds)
    if not scripts:
        print(f"ERROR: no cmd_*.sh in {alos2_cmds}", file=sys.stderr)
        return 1
    for script in scripts:
        original = script.read_text()
        updated, converted, already = parallelize_text(original)
        if converted and already:
            state = f"parallelized {', '.join(converted)}; already parallel {', '.join(already)}"
        elif converted:
            state = f"parallelized {', '.join(converted)}"
        elif already:
            state = f"already parallel ({', '.join(already)})"
        else:
            state = "no date or interferogram loops"
        print(f"{script.name}: {state}")
        if converted and not args.dry_run:
            script.write_text(updated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
