#!/usr/bin/env python3
"""
Check NASA Earthdata status. Exits 0 if All Applications OK, 1 otherwise.
No wait/loop logic - use check_nasa_earthdata_status.bash for retry with --wait.
"""
import sys
import urllib.request
import ssl

STATUS_URL = "https://status.earthdata.nasa.gov"
TIMEOUT = 30  # seconds


def check_earthdata_status():
    """Fetch status page and return True if OK, False otherwise."""
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(STATUS_URL)
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"NASA Earthdata status check failed: {e}", file=sys.stderr)
        return False

    if "All Applications OK" in body:
        return True
    if "Outage" in body or "Issue" in body:
        print("NASA Earthdata status: outage or issue detected.", file=sys.stderr)
        return False
    # Ambiguous or unexpected content
    print("NASA Earthdata status: could not confirm OK.", file=sys.stderr)
    return False


def main():
    if check_earthdata_status():
        print("NASA Earthdata status: OK")
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()
