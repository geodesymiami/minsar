#!/usr/bin/env python3
"""Live probe: time EGMS archive /search option combinations (timeouts, errors).

Not run by CI. Requires CLMS service key (~/accounts/clms_service_key.json or password_config).

Prints a table and writes a TSV report for tuning egms_download.bash first-layer args.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

from minsar.scripts.egms_search import API_ENDPOINT, aoi_to_egms_bbox, build_search_query, normalize_level
from minsar.utils.clms_auth import auth_headers, get_access_token, resolve_clms_service_key_path

DEFAULT_AOI = "37.51:37.88,15.15:15.16"
DEFAULT_RELEASE = "2020-2024"

EXAMPLE = """\
Probe which egms_search.py /archive/search option combinations succeed or time out.
"""

EPILOG = """\
Examples:
  test_egms_search_options.py
  test_egms_search_options.py --aoi='37.51:37.88,15.15:15.16' --timeout 45 -o egms_search_options_report.tsv
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=EXAMPLE,
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EPILOG,
    )
    parser.add_argument("--aoi", metavar="AOI", default=DEFAULT_AOI, help=f"AOI for all cases (default: {DEFAULT_AOI})")
    parser.add_argument("--timeout", type=float, default=45.0, metavar="SEC", help="Per-request read timeout seconds (default: 45)")
    parser.add_argument("-o", "--output", metavar="FILE", default="egms_search_options_report.tsv", help="TSV report path")
    parser.add_argument("--service-key", "-k", metavar="PATH", default=None, help="CLMS service key JSON")
    parser.add_argument("--releases", default=DEFAULT_RELEASE, metavar="REL", help=f"Release for cases that include it (default: {DEFAULT_RELEASE})")
    return parser


def probe_cases(releases: str) -> list[tuple[str, dict[str, Any]]]:
    """Named search extras layered on AOI+level+releases baseline."""
    rel = [releases]
    return [
        ("aoi_level_releases", {}),
        ("+swath_IW2", {"swath": "IW2"}),
        ("+swath_IW1", {"swath": "IW1"}),
        ("+direction_ascending", {"direction": "ascending"}),
        ("+direction_descending", {"direction": "descending"}),
        ("+relativeOrbit_int_44", {"relative_orbit": 44}),
        ("+relativeOrbit_int_124", {"relative_orbit": 124}),
        ("+swath_IW2+relativeOrbit_44", {"swath": "IW2", "relative_orbit": 44}),
        ("+swath_IW2+direction_ascending", {"swath": "IW2", "direction": "ascending"}),
        ("+swath_IW2+relativeOrbit_44+direction_ascending", {"swath": "IW2", "relative_orbit": 44, "direction": "ascending"}),
        ("releases_omitted_uses_GET", {"_omit_releases": True}),
    ]


def run_search(
    headers: dict[str, str],
    query: dict[str, Any],
    *,
    timeout: float,
) -> tuple[str, float, int, str]:
    """Return (status, elapsed_s, n_hits, message)."""
    t0 = time.time()
    try:
        r = requests.post(
            f"{API_ENDPOINT}/search",
            headers={**headers, "Content-Type": "application/json"},
            data=json.dumps(query),
            timeout=timeout,
        )
        elapsed = time.time() - t0
        if r.status_code != 200:
            return ("http_error", elapsed, 0, f"HTTP {r.status_code}: {r.text[:120]}")
        data = r.json()
        if isinstance(data, dict) and data.get("message") and not data.get("status", True) and not data.get("hits"):
            return ("invalid", elapsed, 0, str(data.get("message", ""))[:200])
        hits = data.get("hits") if isinstance(data, dict) else []
        n = len(hits or [])
        return ("ok", elapsed, n, "")
    except requests.exceptions.Timeout:
        return ("timeout", time.time() - t0, 0, f"timeout after {timeout}s")
    except Exception as exc:  # noqa: BLE001
        return ("error", time.time() - t0, 0, str(exc)[:200])


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    try:
        bbox = aoi_to_egms_bbox(args.aoi)
        level = normalize_level("L2A")
        token_path = resolve_clms_service_key_path(args.service_key)
        headers = auth_headers(get_access_token(token_path))
    except Exception as exc:  # noqa: BLE001
        print(f"Error: setup failed: {exc}", file=sys.stderr)
        return 1

    rows: list[tuple[str, str, str, str, str]] = []
    print(f"AOI={args.aoi}  timeout={args.timeout}s  endpoint={API_ENDPOINT}/search")
    print(f"{'name':<50} {'status':<12} {'sec':>7} {'hits':>5}  message")
    print("-" * 100)

    for name, extras in probe_cases(args.releases):
        omit_releases = bool(extras.pop("_omit_releases", False))
        # build_search_query always needs releases list; for omit case use empty and inject later
        if omit_releases:
            # Force resolve path: call without releases in body? API needs releases —
            # emulate CLI: fetch via GET /releases then pick latest (separate probe).
            t0 = time.time()
            try:
                r = requests.get(f"{API_ENDPOINT}/releases", headers=headers, timeout=args.timeout)
                elapsed = time.time() - t0
                if r.status_code != 200:
                    status, n_hits, msg = "http_error", 0, f"GET /releases HTTP {r.status_code}"
                else:
                    status, n_hits, msg = "ok", len(r.json() if isinstance(r.json(), list) else []), "GET /releases only"
            except requests.exceptions.Timeout:
                elapsed = time.time() - t0
                status, n_hits, msg = "timeout", 0, f"GET /releases timeout after {args.timeout}s"
            except Exception as exc:  # noqa: BLE001
                elapsed = time.time() - t0
                status, n_hits, msg = "error", 0, str(exc)[:200]
        else:
            query = build_search_query(
                bbox=bbox,
                level=level,
                releases=[args.releases],
                direction=extras.get("direction"),
                relative_orbit=extras.get("relative_orbit"),
                swath=extras.get("swath"),
            )
            status, elapsed, n_hits, msg = run_search(headers, query, timeout=args.timeout)

        row = (name, status, f"{elapsed:.1f}", str(n_hits), msg.replace("\t", " "))
        rows.append(row)
        print(f"{name:<50} {status:<12} {elapsed:7.1f} {n_hits:5d}  {msg}")

    out = Path(args.output).expanduser()
    lines = ["name\tstatus\telapsed_s\tn_hits\tmessage"]
    lines.extend("\t".join(r) for r in rows)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
