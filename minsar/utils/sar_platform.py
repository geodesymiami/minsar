"""
Shared --platform token normalization for get_sar_coverage, create_template, and related CLIs.
"""

from __future__ import annotations

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
