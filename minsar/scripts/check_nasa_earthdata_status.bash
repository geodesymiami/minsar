#!/usr/bin/env bash
# Check NASA Earthdata status before ASF downloads.
# Without --wait: runs the Python check once and exits with its code.
# With --wait [interval] [max_wait]: loops until OK or max_wait elapsed.
#
# Environment variables (used when --wait is given without explicit args):
#   EARTHDATA_CHECK_INTERVAL  seconds between checks (default: 300)
#   EARTHDATA_MAX_WAIT        max total wait seconds before exit 1 (default: 86400)
#
# Usage: check_nasa_earthdata_status.bash [--wait [interval] [max_wait]]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK_PY="${SCRIPT_DIR}/check_nasa_earthdata_status.py"

usage() {
    echo "Usage: check_nasa_earthdata_status.bash [--wait [interval] [max_wait]]"
    echo "  Without --wait: run check once, exit with its code."
    echo "  With --wait: retry every interval seconds until OK or max_wait elapsed."
    echo "  interval and max_wait override EARTHDATA_CHECK_INTERVAL and EARTHDATA_MAX_WAIT."
    exit 0
}

if [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
    usage
fi

if [[ "$1" != "--wait" ]]; then
    exec "$CHECK_PY"
fi

# --wait mode
shift  # consume --wait

interval="${1:-${EARTHDATA_CHECK_INTERVAL:-300}}"
max_wait="${2:-${EARTHDATA_MAX_WAIT:-86400}}"

start=$(date +%s)
elapsed=0

while [[ $elapsed -lt $max_wait ]]; do
    if "$CHECK_PY"; then
        exit 0
    fi
    echo "NASA Earthdata not OK; will retry in ${interval}s (elapsed: ${elapsed}s, max: ${max_wait}s)" >&2
    sleep "$interval"
    elapsed=$(($(date +%s) - start))
done

echo "NASA Earthdata status check gave up after ${max_wait}s." >&2
exit 1
