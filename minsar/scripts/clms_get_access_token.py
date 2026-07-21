#!/usr/bin/env python3
"""Obtain a CLMS OAuth2 Bearer access token from a JWT service key JSON file.

When the previous access token expires (~1 hour), re-run this script. It signs a
fresh JWT grant (also ~1 hour lifetime) and POSTs to the service key token_uri
(e.g. https://land.copernicus.eu/@@oauth2-token).

Service key path: --service-key, or password_config.py clms_service_key="...".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from minsar.utils.clms_auth import (
    build_jwt_grant,
    load_service_key,
    request_token_response,
    resolve_clms_service_key_path,
)

EXAMPLE = """\
Exchange a Copernicus Land Monitoring Service (CLMS) API service key for a
Bearer access_token (typically valid 3600 seconds).
"""

EPILOG = """\
Examples:
  clms_get_access_token.py
  clms_get_access_token.py --service-key ~/accounts/clms_service_key.json
  clms_get_access_token.py --service-key ~/accounts/clms_service_key.json --json
  clms_get_access_token.py --service-key ~/accounts/clms_service_key.json --print-grant
  clms_get_access_token.py --service-key ~/accounts/clms_service_key.json -o /tmp/clms_access_token.txt
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=EXAMPLE,
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EPILOG,
    )
    parser.add_argument(
        "--service-key",
        "-k",
        metavar="PATH",
        default=None,
        help="CLMS service key JSON (default: ~/accounts/clms_service_key.json or password_config.clms_service_key)",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Print full token response JSON (access_token, expires_in, token_type)",
    )
    parser.add_argument(
        "--print-grant",
        action="store_true",
        help="Print JWT grant assertion only (do not request access_token)",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        default=None,
        help="Write access_token (or --json body) to FILE instead of stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    try:
        key_path = resolve_clms_service_key_path(args.service_key)
        if args.print_grant:
            grant = build_jwt_grant(load_service_key(key_path))
            text = grant if isinstance(grant, str) else grant.decode("utf-8")
        else:
            resp = request_token_response(key_path)
            text = json.dumps(resp, indent=2) if args.as_json else str(resp["access_token"])
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.output:
        out = Path(args.output).expanduser()
        out.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")
        print(f"Wrote {out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
