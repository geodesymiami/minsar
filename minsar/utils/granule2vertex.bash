#!/usr/bin/env bash
# Build an ASF Vertex (search.asf.alaska.edu) URL that opens a Sentinel-1 SLC granule
# in Geographic Search (selected granule + map), not List Search.
#
# Looks up metadata via the public ASF Search API (product_list), then builds a URL like:
#   ...&granule=<PRODUCT>-SLC&path=<rel>-<rel>&flightDirs=Ascending&center=lon,lat&...
#
# Prints the URL to stdout. On macOS, opens it in Safari (same pattern as burst2stack2vertex.bash).
#
# Usage: granule2vertex.bash GRANULE_OR_PRODUCT_ID
#   ID may be SAFE-style without -SLC (suffix added for Vertex/API) or with -SLC / .zip stripped.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<'EOF'
Usage: granule2vertex.bash GRANULE_OR_PRODUCT_ID

  Queries ASF Search API for the product, then prints a Vertex Geographic Search URL
  that selects the granule (granule=...-SLC), path, dates, center, beam, flight direction.

  Requires network access to api.daac.asf.alaska.edu.

Example:
  granule2vertex.bash S1A_IW_SLC__1SDV_20250113T043052_20250113T043122_057421_07119A_4733
EOF
    exit 0
}

for a in "$@"; do
    [[ "$a" == "-h" ]] || [[ "$a" == "--help" ]] && usage
done

granule=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -?*)
            echo "$0: unknown option: $1" >&2
            exit 1
            ;;
        *)
            if [[ -n "$granule" ]]; then
                echo "$0: unexpected extra argument: $1" >&2
                exit 1
            fi
            granule="$1"
            shift
            ;;
    esac
done

if [[ -z "$granule" ]]; then
    echo "$0: GRANULE_OR_PRODUCT_ID is required (see --help)" >&2
    exit 1
fi

url="$(
    GRANULE_ID="$granule" python3 - <<'PY'
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.daac.asf.alaska.edu/services/search/param"
VERTEX = "https://search.asf.alaska.edu/#/"

raw_id = os.environ["GRANULE_ID"].strip()
# Strip .zip if present
base = re.sub(r"\.zip$", "", raw_id, flags=re.IGNORECASE)
# Normalize to product id without -SLC for granuleName match; Vertex needs ...-SLC
if base.upper().endswith("-SLC"):
    product_core = base[:-4]
    product_file_id = base
else:
    product_core = base
    product_file_id = f"{base}-SLC"


def die(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


def first_record(payload):
    """ASF json for product_list is often [[{...}]]."""
    if isinstance(payload, dict) and "error" in payload:
        err = payload.get("error") or {}
        die(f"ASF Search API error: {err.get('report', payload)}")
    if isinstance(payload, list) and payload:
        el = payload[0]
        if isinstance(el, list) and el and isinstance(el[0], dict):
            return el[0]
        if isinstance(el, dict):
            return el
    return None


def flight_dir_vertex(fd: str) -> str:
    if not fd:
        return "Ascending"
    u = fd.upper()
    if u.startswith("A"):
        return "Ascending"
    return "Descending"


qs = urllib.parse.urlencode({"product_list": product_file_id, "output": "json"})
url_api = f"{API}?{qs}"
try:
    with urllib.request.urlopen(url_api, timeout=120) as resp:
        body = resp.read().decode("utf-8", errors="replace")
except urllib.error.HTTPError as e:
    die(f"ASF Search API HTTP {e.code}: {e.reason}")
except urllib.error.URLError as e:
    die(f"ASF Search API request failed: {e}")

try:
    data = json.loads(body)
except json.JSONDecodeError as e:
    die(f"ASF Search API returned invalid JSON: {e}")

rec = first_record(data)
if not rec:
    die(
        f"No product found for product_list={product_file_id!r}. "
        f"Check the ID (see ASF product_list / granule_list keywords)."
    )

granule_param = rec.get("product_file_id") or product_file_id
rel = int(rec.get("relativeOrbit") or rec.get("track") or 0)
if rel <= 0:
    die("ASF metadata missing relativeOrbit/track")

try:
    lat = float(rec["centerLat"])
    lon = float(rec["centerLon"])
except (KeyError, TypeError, ValueError):
    die("ASF metadata missing centerLat/centerLon")

beam = rec.get("beamMode") or rec.get("beamModeType") or "IW"
if not beam:
    beam = "IW"

start_s = rec.get("startTime") or rec.get("sceneDate")
if not start_s:
    die("ASF metadata missing startTime/sceneDate")
# ISO Z
start_s = str(start_s).replace(" ", "T")
if start_s.endswith("UTC"):
    start_s = start_s[:-3] + "Z"
if not start_s.endswith("Z"):
    start_s = start_s.rstrip("+00:00") + "Z"

try:
    t0 = datetime.fromisoformat(start_s.replace("Z", "+00:00"))
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
except ValueError:
    die(f"Could not parse start time: {start_s!r}")

# Bracket acquisition (similar to Vertex "Copy Search Link" style)
t_start = t0 - timedelta(days=2)
t_end = t0 + timedelta(days=3)
start_param = t_start.strftime("%Y-%m-%dT%H:%M:%SZ")
end_param = t_end.strftime("%Y-%m-%dT%H:%M:%SZ")

fd = flight_dir_vertex(rec.get("flightDirection") or "")

# Zoom: mild constant; map centers on API centroid
zoom = 8.142

# Match Vertex "Copy Search Link" style: comma in center stays unescaped.
rest = {
    "flightDirs": fd,
    "path": f"{rel}-{rel}",
    "start": start_param,
    "end": end_param,
    "resultsLoaded": "true",
    "productTypes": "SLC",
    "granule": granule_param,
    "beamModes": beam,
}
tail = urllib.parse.urlencode(rest)
print(
    f"{VERTEX}?zoom={zoom:.3f}&center={lon:.3f},{lat:.3f}&{tail}"
)
PY
)" || exit $?

echo "$url"

repo_root="$(cd "$SCRIPT_DIR/../.." && pwd)"
detected_os=""
if [[ -n "$repo_root" ]]; then
    detected_os=$(
        PYTHONPATH="$repo_root" python3 -c "
from minsar.utils.system_utils import detect_operating_system
print(detect_operating_system())
" 2>/dev/null
    ) || true
fi
if [[ "$detected_os" == "macOS" ]]; then
    open -a Safari "$url"
fi
