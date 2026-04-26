#!/usr/bin/env python3
"""Utilities for recurring seasonal date exclusion."""

from __future__ import annotations

import datetime as _dt
import re


_EXCLUDE_SEASON_RE = re.compile(r"^(\d{4})-(\d{4})$")


def _validate_mmdd(mmdd: str) -> tuple[int, int]:
    """Validate MMDD and return (month, day)."""
    month = int(mmdd[:2])
    day = int(mmdd[2:])
    # Use leap year so 0229 is accepted.
    _dt.date(2000, month, day)
    return month, day


def parse_exclude_season(exclude_season: str | None) -> tuple[str, str] | None:
    """Parse and validate MMDD-MMDD seasonal exclusion token."""
    if not exclude_season:
        return None
    token = exclude_season.strip()
    match = _EXCLUDE_SEASON_RE.match(token)
    if not match:
        raise ValueError(
            f"Invalid --exclude-season '{exclude_season}'. Expected MMDD-MMDD, e.g. 1005-0320."
        )
    start_mmdd, end_mmdd = match.group(1), match.group(2)
    _validate_mmdd(start_mmdd)
    _validate_mmdd(end_mmdd)
    return start_mmdd, end_mmdd


def iso_date_to_date(iso_date: str) -> _dt.date:
    """Parse YYYY-MM-DD to a date object."""
    return _dt.datetime.strptime(iso_date, "%Y-%m-%d").date()


def date_in_exclude_season(date_obj: _dt.date, start_mmdd: str, end_mmdd: str) -> bool:
    """Return True if date_obj month/day is inside inclusive seasonal window."""
    md = (date_obj.month, date_obj.day)
    start_md = _validate_mmdd(start_mmdd)
    end_md = _validate_mmdd(end_mmdd)

    if start_md <= end_md:
        return start_md <= md <= end_md
    return md >= start_md or md <= end_md

