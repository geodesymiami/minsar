#!/usr/bin/env python3
"""Apply per-dataset template options and plan run_minsar.bash commands."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
from pathlib import Path


def _ensure_repo_on_path() -> None:
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


_ensure_repo_on_path()

from minsar.utils.template_exclude_dates import apply_exclude_dates_to_template

BEGIN = "# BEGIN custom_template_options"
END = "# END custom_template_options"
ALLOWED_PREFIXES = ("mintpy.", "miaplpy.", "minsar.", "topsStack.", "ssaraopt.")
LAUNCHER_KEYS = frozenset({"aoi", "options", "defaults"})
FREEFORM_KEYS = frozenset({"aoi", "options"})
EXCLUDE_KEYS = frozenset({"minsar.excludeDates", "topsStack.excludeDates"})
# create_template rewrites these on every AOI run. aoi is also stored from subset.lalo.
SKIP_SAVE_KEYS = frozenset(
    {
        "ssaraopt.relativeOrbit",
        "ssaraopt.startDate",
        "ssaraopt.endDate",
        "topsStack.coregistration",
        "mintpy.plot",
    }
)
SUBSET_LALO_KEYS = ("miaplpy.subset.lalo", "mintpy.subset.lalo")
_STEM_RE = re.compile(r"^(?P<project>.+?)Sen(?P<letter>[AD])T?(?P<orbit>\d+)$")
_TEMPLATE_SUFFIX = ".template"
_BLOCK_RE = re.compile(
    r"\n?# BEGIN custom_template_options\n.*?\n# END custom_template_options\n?",
    re.S,
)
_ASSIGN_RE = re.compile(r"^(?P<key>[A-Za-z][\w.]*)\s*=\s*(?P<val>\S+)\s*$")
_HEADER_RE = re.compile(r"^\[([^\]]+)\]$")

_EXAMPLES = """Examples:
  custom_template_options.py apply $TE/GalapagosSenA106.template
  custom_template_options.py plan --template-dir $ATE GalapagosSenA106 --start-date 20260101
  custom_template_options.py plan --template-dir $ATE GalapagosSenA106.template --start-date 20260101
  custom_template_options.py plan --template-dir $ATE GalapagosSenA106 --start-date 20260101 CerroAzulSenA106 -- --queue pvc
"""


def resolve_custom_path() -> Path | None:
    """Return the user's custom file, or None when no path is configured."""
    env = os.environ.get("MINSAR_CUSTOM_OPTIONS", "").strip()
    if env:
        path = Path(env).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Custom options file not found: {path}")
        return path
    cfg = Path.home() / ".minsar" / "config.cfg"
    if not cfg.is_file():
        return None
    for lineno, raw in enumerate(cfg.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or not line.startswith("custom_template_options"):
            continue
        if "=" not in line:
            raise ValueError(f"{cfg}:{lineno}: custom_template_options needs a path")
        val = line.split("=", 1)[1].split("#", 1)[0].strip()
        path = Path(val).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Custom options file not found: {path}")
        return path
    return None


def parse_sections(text: str) -> dict[str, dict[str, str]]:
    """Parse [section] blocks. Comments and blank lines are ignored."""
    sections: dict[str, dict[str, str]] = {}
    current: str | None = None
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        code = line.split("#", 1)[0].strip()
        header = _HEADER_RE.match(code)
        if header:
            name = header.group(1).strip()
            if name in sections:
                raise ValueError(f"duplicate section [{name}]")
            current = name
            sections[name] = {}
            continue
        if current is None:
            raise ValueError(f"line {lineno}: assignment before a [section]")
        if "=" not in code:
            raise ValueError(f"line {lineno}: expected key = value")
        key, val = code.split("=", 1)
        key = key.strip()
        val = val.strip()
        if not key:
            raise ValueError(f"line {lineno}: empty key")
        if key not in FREEFORM_KEYS:
            parts = val.split()
            if len(parts) != 1:
                raise ValueError(f"line {lineno}: {key} value must be one token")
            val = parts[0]
        sections[current][key] = val
    return sections


def select_section(sections: dict[str, dict[str, str]], stem: str) -> str | None:
    """Longest header contained in *stem*. Equal-length matches are an error."""
    matches = [name for name in sections if name in stem]
    if not matches:
        return None
    matches.sort(key=len, reverse=True)
    if len(matches) >= 2 and len(matches[0]) == len(matches[1]):
        raise ValueError(
            f"two headers of length {len(matches[0])} match {stem}: {matches[0]}, {matches[1]}"
        )
    return matches[0]


def parse_template_assignments(text: str) -> dict[str, str]:
    """Last uncommented assignment wins. Order, spacing, and comments do not matter."""
    found: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGN_RE.match(line.split("#", 1)[0].strip())
        if match:
            found[match.group("key")] = match.group("val")
    return found


def parse_dataset_name(stem: str) -> tuple[str, str]:
    """Return (project, flight-dir) from a SenA/SenD or SenAT/SenDT stem."""
    match = _STEM_RE.match(stem)
    if not match:
        raise ValueError(f"{stem} has no SenA or SenD orbit label")
    flight = "asc" if match.group("letter") == "A" else "desc"
    return match.group("project"), flight


_HELD_PREFIX = "# custom_template_options: "
_ASSIGN_KEY_RE = re.compile(r"^\s*([A-Za-z][\w.]*)\s*=")


def _strip_block(text: str) -> str:
    if not _BLOCK_RE.search(text):
        return text
    return _BLOCK_RE.sub("\n", text, count=1)


def _restore_held(text: str) -> str:
    """Put back lines commented on a previous apply so a dropped key uses the template again."""
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith(_HELD_PREFIX):
            out.append(line[len(_HELD_PREFIX) :])
        else:
            out.append(line)
    return "".join(out)


def _hold_active_keys(text: str, keys: set[str]) -> str:
    """Comment active assignments that the top block replaces. Later lines would otherwise win."""
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        content = line[:-1] if line.endswith("\n") else line
        nl = "\n" if line.endswith("\n") else ""
        if content.lstrip().startswith("#"):
            out.append(line)
            continue
        match = _ASSIGN_KEY_RE.match(content)
        if match and match.group(1) in keys:
            out.append(f"{_HELD_PREFIX}{content}{nl}")
        else:
            out.append(line)
    return "".join(out)


def _replace_block(text: str, assignments: list[str]) -> str:
    """Write the custom keys at the top. Comment the same keys in the rest of the file."""
    text = _restore_held(_strip_block(text))
    if text.startswith("\n"):
        text = text[1:]
    keys = {line.split("=", 1)[0].strip() for line in assignments}
    text = _hold_active_keys(text, keys)
    if not assignments:
        return text
    block = f"{BEGIN}\n" + "\n".join(assignments) + f"\n{END}\n"
    return block + text


def _template_lines(section: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for key, val in section.items():
        if key in LAUNCHER_KEYS or key in EXCLUDE_KEYS:
            continue
        if not key.startswith(ALLOWED_PREFIXES):
            raise ValueError(f"unsupported custom key {key}")
        lines.append(f"{key} = {val}")
    return lines


def _exclude_csv(section: dict[str, str]) -> str:
    dates = {key: section[key] for key in EXCLUDE_KEYS if key in section}
    if not dates:
        return ""
    values = set(dates.values())
    if len(values) != 1:
        raise ValueError("minsar.excludeDates and topsStack.excludeDates differ")
    return next(iter(values))


def apply_to_template(template_path: Path, custom_path: Path | None = None) -> list[str]:
    """Write the matching custom section onto *template_path*. Return applied keys."""
    path = custom_path if custom_path is not None else resolve_custom_path()
    if path is None:
        return []
    sections = parse_sections(path.read_text(encoding="utf-8"))
    name = select_section(sections, template_path.stem)
    if name is None:
        return []
    section = sections[name]
    text = template_path.read_text(encoding="utf-8")
    applied: list[str] = []
    exclude_csv = _exclude_csv(section)
    if exclude_csv:
        apply_exclude_dates_to_template(template_path, exclude_csv, merge=False)
        text = template_path.read_text(encoding="utf-8")
        applied.append(f"minsar.excludeDates = {exclude_csv}")
        applied.append(f"topsStack.excludeDates = {exclude_csv}")
    lines = _template_lines(section)
    template_path.write_text(_replace_block(text, lines), encoding="utf-8")
    print(f"custom_template_options: [{name}]")
    for line in applied:
        print(f"custom_template_options: {line}")
    for line in lines:
        print(f"custom_template_options: {line}")
    return applied + lines


def _dataset_stem(tok: str) -> str | None:
    """Stem from a dataset name. A trailing .template is optional."""
    stem = tok[: -len(_TEMPLATE_SUFFIX)] if tok.endswith(_TEMPLATE_SUFFIX) else tok
    if _STEM_RE.match(stem):
        return stem
    return None


def _split_run_args(argv: list[str]) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """Dataset names with their flags, plus flags after a bare --."""
    if "--" in argv:
        cut = argv.index("--")
        body, global_flags = argv[:cut], argv[cut + 1 :]
    else:
        body, global_flags = argv, []
    groups: list[tuple[str, list[str]]] = []
    for tok in body:
        stem = _dataset_stem(tok)
        if stem is not None:
            groups.append((stem, []))
            continue
        if not groups:
            raise ValueError(f"expected a dataset name, got {tok}")
        groups[-1][1].append(tok)
    if not groups:
        raise ValueError("give at least one dataset name")
    return groups, global_flags


def plan_commands(argv: list[str], template_dir: Path) -> list[str]:
    """Shell-quoted minsarApp commands. Does not read or write $TE."""
    custom = resolve_custom_path()
    if custom is None:
        raise FileNotFoundError(
            "Set MINSAR_CUSTOM_OPTIONS or custom_template_options in $HOME/.minsar/config.cfg"
        )
    sections = parse_sections(custom.read_text(encoding="utf-8"))
    groups, global_flags = _split_run_args(argv)
    commands: list[str] = []
    for stem, flags in groups:
        project, flight = parse_dataset_name(stem)
        name = select_section(sections, stem)
        if name is None:
            raise ValueError(f"no custom section is contained in {stem}")
        section = sections[name]
        aoi = section.get("aoi", "").strip()
        if not aoi:
            raise ValueError(f"[{name}] has no aoi")
        cmd = [
            "minsarApp.bash",
            aoi,
            project,
            "--flight-dir",
            flight,
            "--template-dir",
            str(template_dir),
        ]
        options = section.get("options", "").strip()
        if options:
            cmd.extend(shlex.split(options))
        cmd.extend(flags)
        cmd.extend(global_flags)
        commands.append(shlex.join(cmd))
    return commands


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="custom_template_options.py",
        description=(
            "Apply a matching section from the user's custom file, or print minsarApp commands. "
            "The file is MINSAR_CUSTOM_OPTIONS, or custom_template_options in $HOME/.minsar/config.cfg. "
            "A section applies when its header is contained in the template stem. The longest header wins."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EXAMPLES,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    apply_p = sub.add_parser("apply", help="write the matching section onto TEMPLATE", epilog=_EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    apply_p.add_argument("template", type=Path, help="template to update")
    plan_p = sub.add_parser("plan", help="print one minsarApp command per dataset", epilog=_EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    plan_p.add_argument("--template-dir", required=True, type=Path, metavar="DIR", help="directory for the generated template")
    plan_p.add_argument("datasets", nargs=argparse.REMAINDER, help="STEM[.template] [flags] [STEM[.template] [flags] ...] [-- flags]")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.cmd == "apply":
            apply_to_template(args.template)
            return 0
        datasets = list(args.datasets)
        if datasets[:1] == ["--"]:
            datasets = datasets[1:]
        for line in plan_commands(datasets, args.template_dir.expanduser()):
            print(line)
        return 0
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
