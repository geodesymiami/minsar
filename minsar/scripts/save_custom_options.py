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
    SUBSET_LALO_KEYS,
    parse_template_assignments,
    resolve_custom_path,
)

_EXAMPLES = """Examples:
  save_custom_options.py $TE/TamboraSenD134.template
  save_custom_options.py $TE/CerroAzulSenA106.template -- --no-mintpy --miaplpy
"""


def _defaults_path() -> Path:
    return Path(__file__).resolve().parents[1] / "defaults" / "processing.template"


# Prefix order follows the blocks in processing.template. aoi is first; minsarApp flags are last.
_GROUP_ORDER = ("ssaraopt", "topsStack", "mintpy", "miaplpy", "minsar")
_LAUNCHER_FIRST = ("aoi",)
_LAUNCHER_LAST = ("options", "defaults")


def _prefix(key: str) -> str:
    return key.split(".", 1)[0]


def _sort_group(keys: list[str], key_order: dict[str, int]) -> list[str]:
    def position(item: tuple[int, str]) -> tuple[int, int]:
        index, key = item
        if key in key_order:
            return (0, key_order[key])
        return (1, index)

    indexed = list(enumerate(keys))
    indexed.sort(key=position)
    return [key for _, key in indexed]


def _section_text(stem: str, fields: list[tuple[str, str]], key_order: dict[str, int]) -> str:
    """One dataset section. Keys follow processing.template order, one group after another."""
    values = dict(fields)
    groups: list[list[str]] = []
    first = [key for key in _LAUNCHER_FIRST if key in values]
    if first:
        groups.append(first)
    for prefix in _GROUP_ORDER:
        keys = _sort_group([key for key in values if _prefix(key) == prefix], key_order)
        if keys:
            groups.append(keys)
    known = set(_GROUP_ORDER) | set(_LAUNCHER_FIRST) | set(_LAUNCHER_LAST)
    other = _sort_group([key for key in values if key not in known and _prefix(key) not in _GROUP_ORDER], key_order)
    if other:
        groups.append(other)
    last = [key for key in _LAUNCHER_LAST if key in values]
    if last:
        groups.append(last)
    lines = [f"[{stem}]"]
    for group in groups:
        lines.extend(f"{key} = {values[key]}" for key in group)
    return "\n".join(lines) + "\n"


def _header_name(line: str) -> str | None:
    """Active [section] name. A line that starts with # is not a header."""
    head = line.strip().split("#", 1)[0].strip()
    if len(head) > 2 and head.startswith("[") and head.endswith("]"):
        return head[1:-1].strip()
    return None


def _section_spans(lines: list[str]) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    index = 0
    while index < len(lines):
        name = _header_name(lines[index])
        if name is None:
            index += 1
            continue
        end = index + 1
        while end < len(lines) and _header_name(lines[end]) is None:
            end += 1
        spans.append((index, end, name))
        index = end
    return spans


def _upsert_section(text: str, stem: str, block: str) -> str:
    """Replace every active [stem] section with *block*. Old keys in that section are not kept."""
    if not block.endswith("\n"):
        block += "\n"
    lines = text.splitlines(keepends=True)
    matches = [(start, end) for start, end, name in _section_spans(lines) if name == stem]
    if not matches:
        if not text:
            return block
        if not text.endswith("\n"):
            text += "\n"
        if not text.endswith("\n\n"):
            text += "\n"
        return text + block
    start = matches[0][0]
    drop = {index for begin, end in matches for index in range(begin, end)}
    before = "".join(line for index, line in enumerate(lines) if index < start and index not in drop)
    after = "".join(line for index, line in enumerate(lines) if index >= start and index not in drop)
    if after and not after.startswith("\n") and not block.endswith("\n\n"):
        block += "\n"
    return before + block + after


def save(template: Path, options: str) -> Path:
    custom = resolve_custom_path()
    if custom is None:
        raise FileNotFoundError(
            "Set MINSAR_CUSTOM_OPTIONS or custom_template_options in $HOME/.minsar/config.cfg"
        )
    defaults = parse_template_assignments(_defaults_path().read_text(encoding="utf-8"))
    current = parse_template_assignments(template.read_text(encoding="utf-8"))
    subset = current.get("miaplpy.subset.lalo") or current.get("mintpy.subset.lalo", "")
    if not subset:
        raise ValueError(f"{template} has no miaplpy.subset.lalo or mintpy.subset.lalo")
    fields: list[tuple[str, str]] = [("aoi", subset)]
    for key, val in current.items():
        if key in SKIP_SAVE_KEYS:
            continue
        if defaults.get(key) == val and key not in SUBSET_LALO_KEYS:
            continue
        fields.append((key, val))
    if options.strip():
        fields.append(("options", options.strip()))
    key_order = {key: index for index, key in enumerate(defaults)}
    block = _section_text(template.stem, fields, key_order)
    previous = custom.read_text(encoding="utf-8") if custom.is_file() else ""
    custom.parent.mkdir(parents=True, exist_ok=True)
    custom.write_text(_upsert_section(previous, template.stem, block), encoding="utf-8")
    print(f"Wrote [{template.stem}] to {custom}")
    return custom


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="save_custom_options.py",
        description=(
            "Replace one dataset section from a finished template. A second run replaces that section, including its options line. "
            "Keys are compared to minsar/defaults/processing.template. Order, extra spaces, and comments do not matter. "
            "aoi comes from miaplpy.subset.lalo, or mintpy.subset.lalo when that line is absent. "
            "Those subset lines are saved too. Orbit, dates, coregistration, and mintpy.plot stay with create_template."
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
