"""
Shared --platform token normalization for get_sar_coverage, create_template, and related CLIs.
"""

from __future__ import annotations

import os

# Short internal tokens accepted everywhere after normalization
SAR_PLATFORM_KNOWN = frozenset({"S1", "NISAR", "ALOS2"})


def normalize_sar_platform_token(name: str) -> str:
    """
    Map one user platform string to a short token (S1, NISAR, ALOS2) or return an
    uppercased cleaned token for unknown values (callers can reject).

    Aligned with get_sar_coverage.py: S1 (incl. Sentinel-1 / S1 / Sen), NISAR (any
    case, Nisar, Turkish ı/İ), ALOS-2 (ALOS2 / ALOS).
    """
    n = name.strip().upper().replace("-", "").replace("_", "")
    if n in ("S1", "SENTINEL1", "SEN"):
        return "S1"
    k = name.strip().casefold().replace("-", "").replace("_", "")
    if k in ("nisar", "nısar") or n in ("NISAR", "N\u0130SAR"):
        return "NISAR"
    if n in ("ALOS2", "ALOS"):
        return "ALOS2"
    return n


# Data-search options: asf.* for platforms served by ASF, ssaraopt.* for the ones downloaded with ssara.
SEARCH_PREFIXES = ("asf", "ssaraopt")
SEARCH_KEY_PATTERN = r"(?:asf|ssaraopt)"


def is_asf_platform(value) -> bool:
    """True for a Sentinel-1, ALOS or NISAR platform value (SENTINEL-1A,SENTINEL-1B / ALOS-2 / NISAR)."""
    text = str(value or "").split("#", 1)[0].strip().strip("'\"")
    token = text.replace(",", " ").split()[0] if text else ""
    token = token.upper().replace("-", "").replace("_", "")
    return token.startswith(("SENTINEL1", "S1", "ALOS", "NISAR"))


def _sed_fix(source: str, old: str, new: str) -> str:
    """'Fix: sed ...' line that renames the prefix in *source*, or '' when *source* is not a file."""
    if not os.path.isfile(str(source)):
        return ""
    return f"\nFix: sed -i.bak -E 's/^([[:space:]]*){old}\\./\\1{new}./' {source}"


def search_prefix(options, source: str = "template") -> str:
    """Return the search prefix the template uses (asf or ssaraopt). Raise ValueError on a mixed or mismatched one."""
    present = [p for p in SEARCH_PREFIXES if any(str(key).startswith(p + ".") for key in options)]
    if len(present) == 2:
        raise ValueError(f"both asf.* and ssaraopt.* options in {source}")
    if not present:
        return "asf"
    prefix = present[0]
    platform = options.get(f"{prefix}.platform")
    if platform not in (None, "", "None"):
        if prefix == "ssaraopt" and is_asf_platform(platform):
            raise ValueError(f"ssaraopt.* is not valid for ASF platform {platform} (asf.* expected): {source}" + _sed_fix(source, "ssaraopt", "asf"))
        if prefix == "asf" and not is_asf_platform(platform):
            raise ValueError(f"asf.* is not valid for platform {platform} (ssaraopt.* expected): {source}" + _sed_fix(source, "asf", "ssaraopt"))
    return prefix


def search_key(options, name: str, source: str = "template") -> str:
    """Full template key for a search option name, e.g. relativeOrbit -> asf.relativeOrbit."""
    return f"{search_prefix(options, source)}.{name}"


def search_option(options, name: str, default=None, source: str = "template"):
    """Value of a search option (platform, relativeOrbit, startDate, ...) under the template's prefix."""
    return options.get(search_key(options, name, source), default)


def move_search_defaults(defaults: dict, prefix: str) -> dict:
    """Rename default search keys to *prefix* so merged options carry one prefix only."""
    for key in list(defaults):
        head, _, name = str(key).partition(".")
        if head in SEARCH_PREFIXES and head != prefix and name:
            defaults.setdefault(f"{prefix}.{name}", defaults[key])
            del defaults[key]
    return defaults
