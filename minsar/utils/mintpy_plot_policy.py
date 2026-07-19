"""Policy for MintPy ``mintpy.plot`` from ssaraopt date span.

Default is off; enable full plotting only when ``(end - start).days <= 365``.
``ssaraopt.endDate = auto`` is treated as today. Missing/unparseable dates → ``no``.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

_MINTPY_PLOT_LINE_RE = re.compile(r"^(\s*mintpy\.plot\s*=\s*)(\S+)", re.MULTILINE)


def parse_ssaraopt_date(
    value: Optional[str],
    *,
    today: Optional[date] = None,
    allow_auto: bool = True,
) -> Optional[date]:
    """Parse ssaraopt start/end date to ``date``.

    Accepts ``YYYYMMDD``, ``YYYY-MM-DD``, or ``auto`` (only if ``allow_auto``; means *today*).
    Returns ``None`` if missing or invalid.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.lower() == "auto":
        if not allow_auto:
            return None
        return today if today is not None else date.today()
    if "-" in s:
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            return None
    if len(s) == 8 and s.isdigit():
        try:
            return datetime.strptime(s, "%Y%m%d").date()
        except ValueError:
            return None
    return None


def mintpy_plot_from_ssaraopt_span(
    start: Optional[str],
    end: Optional[str],
    *,
    today: Optional[date] = None,
) -> str:
    """Return ``\"yes\"`` if span days ``<= 365``, else ``\"no\"``.

    ``end`` may be ``auto`` (today). ``start`` as ``auto`` is treated as unknown → ``no``.
    """
    start_d = parse_ssaraopt_date(start, today=today, allow_auto=False)
    end_d = parse_ssaraopt_date(end, today=today, allow_auto=True)
    if start_d is None or end_d is None:
        return "no"
    if end_d < start_d:
        return "no"
    if (end_d - start_d).days <= 365:
        return "yes"
    return "no"


def resolve_mintpy_plot_value(
    start: Optional[str],
    end: Optional[str],
    *,
    cli_override: Optional[str] = None,
    today: Optional[date] = None,
) -> str:
    """Resolve ``mintpy.plot`` value: CLI override (``yes``/``no``) wins over span rule."""
    if cli_override is not None:
        v = str(cli_override).strip().lower()
        if v in ("yes", "no"):
            return v
        raise ValueError(f"cli_override must be 'yes' or 'no', got {cli_override!r}")
    return mintpy_plot_from_ssaraopt_span(start, end, today=today)


def template_has_explicit_mintpy_plot(content: str) -> bool:
    """True if content sets ``mintpy.plot`` to yes/no (not auto / empty)."""
    for line in content.splitlines():
        if line.strip().startswith("#"):
            continue
        m = re.match(r"^\s*mintpy\.plot\s*=\s*(\S+)", line)
        if m:
            val = m.group(1).lower()
            if val in ("yes", "no", "true", "false", "0", "1"):
                return True
            return False
    return False


def apply_mintpy_plot_line(content: str, value: str) -> str:
    """Set or insert ``mintpy.plot = {value}`` in template/cfg text."""
    v = str(value).strip().lower()
    if v not in ("yes", "no"):
        raise ValueError(f"mintpy.plot value must be 'yes' or 'no', got {value!r}")
    if _MINTPY_PLOT_LINE_RE.search(content):
        return _MINTPY_PLOT_LINE_RE.sub(rf"\g<1>{v}", content, count=1)
    plot_line = f"mintpy.plot                       = {v}"
    lines = content.splitlines()
    out: list[str] = []
    inserted = False
    for line in lines:
        if not inserted and re.match(r"^\s*mintpy\.plot\.maxMemory\s*=", line):
            out.append(plot_line)
            out.append(line)
            inserted = True
            continue
        out.append(line)
    if not inserted:
        out = []
        for line in lines:
            if not inserted and re.match(r"^\s*mintpy\.", line):
                out.append(plot_line)
                inserted = True
            out.append(line)
    if not inserted:
        out.append(plot_line)
    text = "\n".join(out)
    if content.endswith("\n") or not content:
        text += "\n"
    return text


def read_template_option(content: str, key: str) -> Optional[str]:
    """Return first non-comment assignment value for ``key``, or None."""
    pat = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(\S+)")
    for line in content.splitlines():
        if line.strip().startswith("#"):
            continue
        m = pat.match(line)
        if m:
            return m.group(1)
    return None
