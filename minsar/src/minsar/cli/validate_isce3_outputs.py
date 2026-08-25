#!/usr/bin/env python3
"""Validate expected outputs from local or SLURM ISCE3 workflow execution."""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path


def create_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    epilog = """Examples:
 validate_isce3_outputs.py isce3_workflow.json
 validate_isce3_outputs.py isce3_workflow.json --stage run_dolphin
 validate_isce3_outputs.py isce3_workflow.json --json validation.json"""
    parser = argparse.ArgumentParser(
        description="Check manifest output patterns independently of the execution backend.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("manifest", type=Path, help="generated isce3_workflow.json")
    parser.add_argument("--stage", action="append", help="stage name or number to check; may be repeated")
    parser.add_argument("--json", dest="json_output", type=Path, help="write a machine-readable report")
    parser.add_argument("--allow-empty", action="store_true", help="return success when outputs are missing")
    return parser


def _selected(stage: dict[str, object], values: list[str] | None) -> bool:
    if not values:
        return True
    return any(value in {str(stage["name"]), str(stage["number"]), Path(str(stage["run_file"])).name} for value in values)


def main(iargs: list[str] | None = None) -> int:
    args = create_parser().parse_args(iargs)
    try:
        manifest = json.loads(args.manifest.read_text())
        if manifest.get("schema_version") != 1:
            raise ValueError("unsupported manifest schema")
        work_dir = Path(str(manifest["work_dir"]))
        results: list[dict[str, object]] = []
        for stage in manifest["stages"]:
            if not _selected(stage, args.stage):
                continue
            checks = []
            for pattern in stage["expected_outputs"]:
                absolute_pattern = str(work_dir / str(pattern))
                matches = sorted(glob.glob(absolute_pattern, recursive=True))
                checks.append({"pattern": pattern, "matches": matches, "ok": bool(matches)})
            ok = all(check["ok"] for check in checks)
            results.append({"number": stage["number"], "name": stage["name"], "ok": ok, "checks": checks})
            marker = "OK" if ok else "MISSING"
            print(f"[{marker:7}] {stage['number']:02d} {stage['name']}")
            for check in checks:
                print(f"          {check['pattern']}: {len(check['matches'])}")
        if args.stage and not results:
            raise ValueError("none of the requested stages exist")
        report = {"manifest": str(args.manifest.resolve()), "work_dir": str(work_dir), "ok": all(item["ok"] for item in results), "stages": results}
        if args.json_output:
            args.json_output.write_text(json.dumps(report, indent=2) + "\n")
        return 0 if report["ok"] or args.allow_empty else 1
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
