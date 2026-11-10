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
    "argv_kw_from_parser",
    "get_create_template_argv_kw",
    "union_argv_kw",
    "CONVERT_BBOX_ARGV_KW",
    "MINSAR_APP_ARGV_KW",
    "SHARED_AOI_BRIDGE_OPTIONS",
    "GET_SAR_COVERAGE_ARGV_KW",
    "DISPLAY_BBOX_ARGV_KW",
    "EGMS_DOWNLOAD_ARGV_KW",
    "CALCULATE_MIAPLPY_SUBSET_ARGV_KW",
]

_NUMERIC_TOKEN = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")


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
    optional_unless_dash: frozenset[str] = frozenset(),
    optional_numeric: frozenset[str] = frozenset(),
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
        if t in optional_numeric:
            if k + 1 < n and _NUMERIC_TOKEN.match(tail[k + 1]):
                opt_prefix.extend(tail[k : k + 2])
                k += 2
            else:
                opt_prefix.append(t)
                k += 1
            continue
        if t in optional_unless_dash or (t == "--quick-run" and t in one):
            if k + 1 < n and not tail[k + 1].startswith("-"):
                opt_prefix.extend(tail[k : k + 2])
                k += 2
            else:
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
            if k + 1 < n:
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
    optional_unless_dash: Iterable[str] = (),
    optional_numeric: Iterable[str] = (),
    multiple_initial_positionals: bool = False,
) -> list[str]:
    """
    Fix argv so an S:N,W:E bbox whose latitude starts with '-' is not parsed as flags.

    Skips known long options and their arguments (consume_one / consume_two),
    boolean flags, and '--opt=value' forms.

    Default (multiple_initial_positionals=False): same as convert_bbox.py — move the bbox
    after options and prefix with '--' so one trailing positional works.

    multiple_initial_positionals=True: for CLIs with two or more leading positionals
    (AOI then name, optional dolphin config), insert '--' before the bbox without
    swapping those positionals. If options appear after the name (e.g.
    ``AOI name --quick-run 2026``), those are moved before ``--`` so argparse still
    parses them as options.
    """
    argv = list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        return argv

    one = frozenset(consume_one)
    two = frozenset(consume_two)
    flagset = frozenset(flags)
    opt_dash = frozenset(optional_unless_dash)
    opt_num = frozenset(optional_numeric)

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
        if a in opt_num:
            if i + 1 < n and _NUMERIC_TOKEN.match(argv[i + 1]):
                i += 2
            else:
                i += 1
            continue
        if a in opt_dash or (a == "--quick-run" and a in one):
            if i + 1 < n and not str(argv[i + 1]).startswith("-"):
                i += 2
            else:
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
                # Keep AOI, NAME, and any further leading positionals (e.g. dolphin_config).
                pos: list[str] = [argv[i]]
                j = i + 1
                while j < n and not str(argv[j]).startswith("-"):
                    pos.append(argv[j])
                    j += 1
                tail = argv[j:]
                opt_first, rest = _drain_known_options(
                    tail,
                    one=one,
                    two=two,
                    flagset=flagset,
                    optional_unless_dash=opt_dash,
                    optional_numeric=opt_num,
                )
                return argv[:i] + opt_first + ["--"] + pos + rest
            # Put all tokens AFTER the bbox first, then '--' + bbox, so trailing
            # options (e.g. --platform S1) are not swallowed as positionals.
            return argv[:i] + argv[i + 1 :] + ["--", a]
        return argv
    return argv


# Keyword dicts for each CLI (option names must match add_argument longopts).

CONVERT_BBOX_ARGV_KW = {
    "consume_one": ("--lat_delta", "--lon_delta", "--start-date", "--end-date"),
    "consume_two": (),
    "flags": ("--asf",),
}

def argv_kw_from_parser(parser) -> dict[str, tuple[str, ...]]:
    """Map a parser's long options to the token classes used by argv fixing."""
    import argparse

    consume_one: list[str] = []
    consume_two: list[str] = []
    flags: list[str] = []
    optional_unless_dash: list[str] = []
    for action in parser._actions:
        strings = [s for s in action.option_strings if s.startswith("--")]
        if not strings or getattr(action, "dest", None) == "help":
            continue
        if isinstance(
            action,
            (
                argparse._StoreTrueAction,
                argparse._StoreFalseAction,
                argparse._StoreConstAction,
                argparse._HelpAction,
                argparse._CountAction,
            ),
        ):
            flags.extend(strings)
            continue
        nargs = getattr(action, "nargs", None)
        if nargs == "?":
            optional_unless_dash.extend(strings)
        elif nargs == 2:
            consume_two.extend(strings)
        else:
            consume_one.extend(strings)
    return {
        "consume_one": tuple(consume_one),
        "consume_two": tuple(consume_two),
        "flags": tuple(flags),
        "optional_unless_dash": tuple(optional_unless_dash),
        "optional_numeric": (),
    }


_CREATE_TEMPLATE_ARGV_KW: dict[str, tuple[str, ...]] | None = None


def get_create_template_argv_kw() -> dict[str, tuple[str, ...]]:
    """Token classes for create_template.py, taken from its parser."""
    global _CREATE_TEMPLATE_ARGV_KW
    if _CREATE_TEMPLATE_ARGV_KW is None:
        from minsar.scripts.create_template import create_parser

        _CREATE_TEMPLATE_ARGV_KW = argv_kw_from_parser(create_parser(add_help=False))
    return _CREATE_TEMPLATE_ARGV_KW


def union_argv_kw(*parts: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    """Merge argv keyword dicts. Earlier entries win when a name is repeated."""
    keys = (
        "consume_one",
        "consume_two",
        "flags",
        "optional_unless_dash",
        "optional_numeric",
    )
    merged: dict[str, tuple[str, ...]] = {}
    for key in keys:
        seen: list[str] = []
        for part in parts:
            for item in part.get(key, ()):
                if item not in seen:
                    seen.append(item)
        merged[key] = tuple(seen)
    return merged


# minsarApp.bash template-mode options. create_template options come from its parser.
# --delta-lat takes a following number when one is present; a bare flag does not.
# --suffix takes a following token when it is not another flag.
MINSAR_APP_ARGV_KW: dict[str, tuple[str, ...]] = {
    "consume_one": (
        "--start",
        "--stop",
        "--dostep",
        "--isce-start",
        "--isce-stop",
        "--isce-step",
        "--queue",
        "--miaplpy-start",
        "--miaplpy-stop",
        "--miaplpy-step",
        "--sleep",
        "--download-method",
        "--minsar.excludeDates",
        "--exclude-dates",
        "--miaplpy.load.startDate",
        "--miaplpy.load.endDate",
    ),
    "consume_two": (),
    "flags": (
        "--mintpy",
        "--no-mintpy",
        "--miaplpy",
        "--insarmaps",
        "--no-insarmaps",
        "--upload",
        "--no-upload",
        "--opposite-orbit",
        "--no-opposite-orbit",
        "--horzvert",
        "--no-horzvert",
        "--no-orbit-download",
        "--chunks",
        "--clean-start",
        "--debug",
        "--skip-mintpy",
        "--skip-miaplpy",
    ),
    "optional_unless_dash": ("--suffix",),
    "optional_numeric": ("--delta-lat",),
}

# One occurrence is copied onto both the create_template argv and the minsarApp re-exec.
SHARED_AOI_BRIDGE_OPTIONS = frozenset(
    {
        "--exclude-dates",
        "--minsar.excludeDates",
    }
)

GET_SAR_COVERAGE_ARGV_KW = {
    "consume_one": (
        "--platform",
        "--start-date",
        "--end-date",
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

EGMS_SEARCH_ARGV_KW = {
    "consume_one": (
        "--aoi",
        "--intersectsWith",
        "--level",
        "--releases",
        "--dir",
        "--direction",
        "--relativeOrbit",
        "--swath",
        "--write-curl",
        "--json-out",
        "--service-key",
        "-k",
    ),
    "consume_two": (),
    "flags": ("--print",),
}
# Backward-compatible alias (old egms_download.py name).
EGMS_DOWNLOAD_ARGV_KW = EGMS_SEARCH_ARGV_KW

CALCULATE_MIAPLPY_SUBSET_ARGV_KW = {
    "consume_one": (
        "--orbit",
        "--mode",
        "--asc-heading",
        "--desc-heading",
        "--decimals",
    ),
    "consume_two": (),
    "flags": (),
}
