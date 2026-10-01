"""Normalize and apply minsar/topsStack excludeDates in MinSAR template files."""

from __future__ import annotations

import re
import sys
from pathlib import Path

_EXCLUDE_DATE_KEYS = ("topsStack.excludeDates", "minsar.excludeDates")
_DATE_RE = re.compile(r"^\d{8}$")
_LINE_RE = re.compile(
    r"^(?P<comment>#)?(?P<key>topsStack\.excludeDates|minsar\.excludeDates)\s*=\s*(?P<val>[^\s#]+)"
)


def normalize_exclude_dates_arg(raw: str) -> str:
    """Parse CLI or template value into a sorted, comma-separated YYYYMMDD list."""
    if not raw or not str(raw).strip():
        return ""
    parts: list[str] = []
    for chunk in re.split(r"[\s,]+", str(raw).strip()):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.lower() in ("auto", "none", "no"):
            continue
        if not _DATE_RE.match(chunk):
            raise ValueError(
                f"Invalid exclude date {chunk!r}; expected YYYYMMDD (e.g. 20260619)."
            )
        parts.append(chunk)
    return ",".join(sorted(set(parts)))


def merge_exclude_date_csv(existing: str | None, new_csv: str) -> str:
    """Union of two comma-separated date lists (ignores auto/none)."""
    combined: set[str] = set()
    for blob in (existing, new_csv):
        if not blob:
            continue
        for chunk in blob.split(","):
            chunk = chunk.strip()
            if chunk and chunk.lower() not in ("auto", "none", "no"):
                if not _DATE_RE.match(chunk):
                    raise ValueError(f"Invalid exclude date in template: {chunk!r}")
                combined.add(chunk)
    return ",".join(sorted(combined))


def _existing_from_content(content: str) -> str:
    found: set[str] = set()
    for line in content.splitlines():
        m = _LINE_RE.match(line.strip())
        if not m or m.group("comment"):
            continue
        val = m.group("val").strip()
        if val.lower() in ("auto", "none", "no"):
            continue
        for chunk in val.split(","):
            chunk = chunk.strip()
            if chunk:
                found.add(chunk)
    return ",".join(sorted(found))


def patch_template_text(content: str, dates_csv: str, *, merge: bool = False) -> str:
    """Return template text with both excludeDates keys set to dates_csv."""
    if not dates_csv:
        return content
    if merge:
        dates_csv = merge_exclude_date_csv(_existing_from_content(content), dates_csv)
        if not dates_csv:
            return content

    lines = content.splitlines()
    out: list[str] = []
    matched: set[str] = set()
    for line in lines:
        m = _LINE_RE.match(line.strip())
        if m and m.group("key") in _EXCLUDE_DATE_KEYS:
            key = m.group("key")
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f"{indent}{key} = {dates_csv}")
            matched.add(key)
            continue
        out.append(line)

    missing = [k for k in _EXCLUDE_DATE_KEYS if k not in matched]
    if missing:
        insert_at = len(out)
        for i, line in enumerate(out):
            if re.match(r"^\s*topsStack\.subswath\s*=", line):
                insert_at = i
                break
        block = [f"{k} = {dates_csv}" for k in missing]
        out[insert_at:insert_at] = block

    text = "\n".join(out)
    if content.endswith("\n"):
        text += "\n"
    return text


def apply_exclude_dates_to_template(
    template_path: Path | str,
    raw_dates: str,
    *,
    merge: bool = False,
) -> str:
    """Write normalized exclude dates into a template file; return final CSV."""
    dates_csv = normalize_exclude_dates_arg(raw_dates)
    if not dates_csv:
        return ""
    path = Path(template_path)
    content = path.read_text()
    path.write_text(patch_template_text(content, dates_csv, merge=merge))
    if merge:
        return merge_exclude_date_csv(_existing_from_content(content), dates_csv)
    return dates_csv


def _main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) not in (2, 3) or args[0] in ("-h", "--help"):
        print(
            "Usage: template_exclude_dates.py TEMPLATE YYYYMMDD[,YYYYMMDD...] [--merge]",
            file=sys.stderr,
        )
        return 0 if args and args[0] in ("-h", "--help") else 1
    merge = "--merge" in args
    if merge:
        args = [a for a in args if a != "--merge"]
    try:
        apply_exclude_dates_to_template(args[0], args[1], merge=merge)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main())
