#!/usr/bin/env python3
"""Write a finished template's extra keys into the user's custom options file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_repo_on_path() -> None:
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


_ensure_repo_on_path()

from minsar.utils.custom_template_options import (
    SKIP_SAVE_KEYS,
    parse_template_assignments,
    resolve_custom_path,
)

_EXAMPLES = """Examples:
  save_custom_options.py $TE/TamboraSenD134.template
  save_custom_options.py $TE/CerroAzulSenA106.template -- --no-mintpy --miaplpy
"""


def _defaults_path() -> Path:
    return Path(__file__).resolve().parents[1] / "defaults" / "processing.template"


def _section_text(stem: str, fields: list[tuple[str, str]]) -> str:
    lines = [f"[{stem}]"]
    lines.extend(f"{key} = {val}" for key, val in fields)
    return "\n".join(lines) + "\n"


def _upsert_section(text: str, stem: str, block: str) -> str:
    lines = text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        head = line.strip().split("#", 1)[0].strip()
        if head == f"[{stem}]":
            start = i
            break
    if start is None:
        if not text:
            return block
        if not text.endswith("\n"):
            text += "\n"
        if not text.endswith("\n\n"):
            text += "\n"
        return text + block
    end = len(lines)
    for j in range(start + 1, len(lines)):
        head = lines[j].strip().split("#", 1)[0].strip()
        if head.startswith("[") and head.endswith("]") and len(head) > 2:
            end = j
            break
    return "".join(lines[:start]) + block + "".join(lines[end:])


def save(template: Path, options: str) -> Path:
    custom = resolve_custom_path()
    if custom is None:
        raise FileNotFoundError(
            "Set MINSAR_CUSTOM_OPTIONS or custom_template_options in $HOME/.minsar/config.cfg"
        )
    defaults = parse_template_assignments(_defaults_path().read_text(encoding="utf-8"))
    current = parse_template_assignments(template.read_text(encoding="utf-8"))
    subset = current.get("miaplpy.subset.lalo", "")
    if not subset:
        raise ValueError(f"{template} has no miaplpy.subset.lalo")
    fields: list[tuple[str, str]] = [("aoi", subset)]
    for key, val in current.items():
        if key in SKIP_SAVE_KEYS or defaults.get(key) == val:
            continue
        fields.append((key, val))
    if options.strip():
        fields.append(("options", options.strip()))
    block = _section_text(template.stem, fields)
    previous = custom.read_text(encoding="utf-8") if custom.is_file() else ""
    custom.parent.mkdir(parents=True, exist_ok=True)
    custom.write_text(_upsert_section(previous, template.stem, block), encoding="utf-8")
    print(f"Wrote [{template.stem}] to {custom}")
    return custom


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="save_custom_options.py",
        description=(
            "Replace one section in the custom options file from a finished template. "
            "Keys are compared to minsar/defaults/processing.template. Order, extra spaces, and comments do not matter. "
            "miaplpy.subset.lalo is stored as aoi. Orbit, dates, subset, coregistration, and mintpy.plot are left to create_template."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EXAMPLES,
    )
    parser.add_argument("template", type=Path, help="finished template, usually under $TE")
    parser.add_argument("options", nargs=argparse.REMAINDER, help="after --, minsarApp flags stored as the options line")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    options = list(args.options)
    if options[:1] == ["--"]:
        options = options[1:]
    try:
        save(args.template, " ".join(options))
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
