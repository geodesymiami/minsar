#!/usr/bin/env python3
"""
Helpers so argparse accepts S:N,W:E bbox strings whose latitude starts negative
(e.g. -23.3:-23.1,-68.4:-68.2). Without inserting '--', argparse treats '-23...' as flags.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

__all__ = [
    "looks_like_sn_we_bbox",
    "fix_argv_for_negative_bbox_sn_we",
    "CONVERT_BBOX_ARGV_KW",
    "CREATE_TEMPLATE_ARGV_KW",
    "GET_SAR_COVERAGE_ARGV_KW",
    "DISPLAY_BBOX_ARGV_KW",
]


def looks_like_sn_we_bbox(s: str) -> bool:
    """True if token looks like lat_min:lat_max,lon_min:lon_max (not POLYGON)."""
    if not s or "," not in s or ":" not in s:
        return False
    t = s.strip()
    if t.upper().startswith("POLYGON"):
        return False
    return bool(re.match(r"^-?\d", t))


def _negative_sn_we_bbox_token(a: str) -> bool:
    """True if token is S:N,W:E bbox and latitude range starts with '-<digit>'."""
    if not looks_like_sn_we_bbox(a):
        return False
    return len(a) > 1 and a[0] == "-" and (a[1].isdigit() or a[1] == ".")


def _drain_known_options(
    tail: list[str],
    *,
    one: frozenset[str],
    two: frozenset[str],
    flagset: frozenset[str],
) -> tuple[list[str], list[str]]:
    """Split tail into (known_option_tokens, remainder). Stops at first unknown token."""
    opt_prefix: list[str] = []
    k, n = 0, len(tail)
    while k < n:
        t = tail[k]
        if t == "--":
            opt_prefix.extend(tail[k:])
            break
        if t in flagset:
            opt_prefix.append(t)
            k += 1
            continue
        if t in two:
            if k + 2 >= n:
                opt_prefix.extend(tail[k:])
                break
            opt_prefix.extend(tail[k : k + 3])
            k += 3
            continue
        if t in one:
            # Match argparse.Optional: --quick-run may appear without a following YEAR.
            if t == "--quick-run" and (k + 1 >= n or tail[k + 1].startswith("-")):
                opt_prefix.append(t)
                k += 1
            elif k + 1 < n:
                opt_prefix.extend(tail[k : k + 2])
                k += 2
            else:
                opt_prefix.append(t)
                k += 1
            continue
        if t.startswith("--") and "=" in t:
            opt_prefix.append(t)
            k += 1
            continue
        break
    return opt_prefix, tail[k:]


def fix_argv_for_negative_bbox_sn_we(
    argv: Sequence[str],
    *,
    consume_one: Iterable[str] = (),
    consume_two: Iterable[str] = (),
    flags: Iterable[str] = (),
    multiple_initial_positionals: bool = False,
) -> list[str]:
    """
    Fix argv so an S:N,W:E bbox whose latitude starts with '-' is not parsed as flags.

    Skips known long options and their arguments (consume_one / consume_two),
    boolean flags, and '--opt=value' forms.

    Default (multiple_initial_positionals=False): same as convert_bbox.py — move the bbox
    after options and prefix with '--' so one trailing positional works.

    multiple_initial_positionals=True: for CLIs with two leading positionals (AOI then name),
    insert '--' before the bbox without swapping AOI/name. If options appear after the name
    (e.g. ``AOI name --quick-run 2026``), those are moved before ``--`` so argparse still
    parses them as options.
    """
    argv = list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        return argv

    one = frozenset(consume_one)
    two = frozenset(consume_two)
    flagset = frozenset(flags)

    i, n = 0, len(argv)
    while i < n:
        a = argv[i]
        if a == "--":
            return argv
        if a in ("-h", "--help"):
            return argv
        if a in flagset:
            i += 1
            continue
        if a in two:
            if i + 2 >= n:
                return argv
            i += 3
            continue
        if a in one:
            if i + 1 >= n:
                return argv
            i += 2
            continue
        if a.startswith("--") and "=" in a:
            i += 1
            continue
        if _negative_sn_we_bbox_token(a):
            if multiple_initial_positionals:
                if i + 1 >= n:
                    return argv[:i] + ["--"] + argv[i:]
                bbox, name = argv[i], argv[i + 1]
                tail = argv[i + 2 :]
                opt_first, rest = _drain_known_options(
                    tail, one=one, two=two, flagset=flagset
                )
                return argv[:i] + opt_first + ["--", bbox, name] + rest
            # Put all tokens AFTER the bbox first, then '--' + bbox, so trailing
            # options (e.g. --platform S1) are not swallowed as positionals.
            return argv[:i] + argv[i + 1 :] + ["--", a]
        return argv
    return argv


# Keyword dicts for each CLI (option names must match add_argument longopts).

CONVERT_BBOX_ARGV_KW = {
    "consume_one": ("--lat_delta", "--lon_delta", "--start", "--end"),
    "consume_two": (),
    "flags": ("--asf",),
}

CREATE_TEMPLATE_ARGV_KW = {
    "consume_one": ("--start-date", "--end-date", "--period", "--type", "--quick-run"),
    "consume_two": (),
    "flags": ("--last-year",),
}

GET_SAR_COVERAGE_ARGV_KW = {
    "consume_one": (
        "--platform",
        "--start",
        "--end",
        "--startDate",
        "--endDate",
        "--max-discovery",
    ),
    "consume_two": (),
    "flags": ("--all", "--verbose", "--show-removed", "--select", "-v"),
}

DISPLAY_BBOX_ARGV_KW = {
    "consume_one": (),
    "consume_two": ("--lat", "--lon"),
    "flags": ("--satellite", "--asf"),
}
