#!/usr/bin/env python3
"""Validate expected outputs from local or SLURM ISCE3 workflow execution."""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path


DEFAULT_VALIDATION_FILE = Path(__file__).resolve().parents[3] / "defaults/isce3_validation.json"


def create_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    epilog = """Examples:
 validate_isce3_outputs.py
 validate_isce3_outputs.py --step dolphin
 validate_isce3_outputs.py --data-type disp --step 2
 validate_isce3_outputs.py --json validation_report.json"""
    parser = argparse.ArgumentParser(
        description="Validate generated ISCE3 step outputs in the current processing directory.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--data-type", choices=("safe", "cslc", "disp"), help="workflow type; inferred from job files by default")
    parser.add_argument("--step", action="append", help="step name or number to check; may be repeated")
    parser.add_argument("--json", dest="json_output", type=Path, help="write a machine-readable report")
    parser.add_argument("--allow-empty", action="store_true", help="return success when outputs are missing")
    return parser


def _discover_steps(work_dir: Path) -> list[dict[str, object]]:
    """Discover ordered workflow steps from generated job filenames."""
    steps: list[dict[str, object]] = []
    for job_file in sorted((work_dir / "run_files").glob("run_[0-9][0-9]_*.job")):
        match = re.fullmatch(r"run_(\d{2})_(.+)\.job", job_file.name)
        if match:
            steps.append({"number": int(match.group(1)), "name": match.group(2), "run_file": job_file.stem})
    if not steps:
        raise ValueError(f"no run_NN_*.job files found in {work_dir / 'run_files'}")
    return steps


def _workflow_rules(config: dict[str, object], steps: list[dict[str, object]], data_type: str | None) -> tuple[str, dict[str, list[str]]]:
    """Select validation rules explicitly or from the discovered step names."""
    workflows = config.get("workflows")
    if not isinstance(workflows, dict):
        raise ValueError("validation defaults are missing workflows")
    step_names = {str(step["name"]) for step in steps}
    if data_type:
        candidates = [data_type]
    else:
        candidates = [
            name
            for name, rules in workflows.items()
            if isinstance(rules, dict) and step_names.issubset(set(rules))
        ]
    if len(candidates) != 1:
        raise ValueError("could not infer one workflow from the generated job files; use --data-type")
    workflow = candidates[0]
    rules = workflows.get(workflow)
    if not isinstance(rules, dict):
        raise ValueError(f"validation defaults contain no {workflow} workflow")
    missing = sorted(step_names - set(rules))
    if missing:
        raise ValueError(f"{workflow} validation defaults contain no rules for: {', '.join(missing)}")
    return workflow, rules


def _selected(step: dict[str, object], values: list[str] | None) -> bool:
    if not values:
        return True
    return any(value in {str(step["name"]), str(step["number"]), str(step["run_file"])} for value in values)


def main(iargs: list[str] | None = None) -> int:
    args = create_parser().parse_args(iargs)
    try:
        work_dir = Path.cwd().resolve()
        config = json.loads(DEFAULT_VALIDATION_FILE.read_text())
        if config.get("schema_version") != 1:
            raise ValueError("unsupported validation schema")
        steps = _discover_steps(work_dir)
        workflow, rules = _workflow_rules(config, steps, args.data_type)
        results: list[dict[str, object]] = []
        for step in steps:
            if not _selected(step, args.step):
                continue
            checks = []
            for pattern in rules[str(step["name"])]:
                absolute_pattern = str(work_dir / str(pattern))
                matches = sorted(glob.glob(absolute_pattern, recursive=True))
                checks.append({"pattern": pattern, "matches": matches, "ok": bool(matches)})
            ok = all(check["ok"] for check in checks)
            results.append({"number": step["number"], "name": step["name"], "ok": ok, "checks": checks})
            marker = "OK" if ok else "MISSING"
            print(f"[{marker:7}] {step['number']:02d} {step['name']}")
            for check in checks:
                print(f"          {check['pattern']}: {len(check['matches'])}")
        if args.step and not results:
            raise ValueError("none of the requested steps exist")
        report = {"data_type": workflow, "work_dir": str(work_dir), "ok": all(item["ok"] for item in results), "steps": results}
        if args.json_output:
            args.json_output.write_text(json.dumps(report, indent=2) + "\n")
        return 0 if report["ok"] or args.allow_empty else 1
    except (json.JSONDecodeError, KeyError, OSError, TypeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
