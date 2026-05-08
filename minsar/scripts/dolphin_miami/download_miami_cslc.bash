#!/usr/bin/env bash
########################################################################
# Download CSLC (coregistered SLC) data for Miami 2025 via ASF.
# Area: miaplpy.subset.lalo = 25.765:25.98,-80.147:-80.1146  [S:N, W:E]
# Uses minsar asf_search_args.py (requires asf_search; use minsar conda env).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Minsar package root (contains src/, scripts/)
MINSAR_ROOT="${MINSAR_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
ASF_SCRIPT="${MINSAR_ROOT}/src/minsar/cli/asf_search_args.py"

# Miami subset: S:N = 25.765:25.98, W:E = -80.147:-80.1146
# POLYGON (lon lat): W S, E S, E N, W N, W S
MIA_POLYGON="POLYGON((-80.147 25.765, -80.1146 25.765, -80.1146 25.98, -80.147 25.98, -80.147 25.765))"

# Defaults: 2025, download to ./CSLC
START_DATE="${START_DATE:-2025-01-01}"
END_DATE="${END_DATE:-2025-12-31}"
DOWNLOAD_DIR="${DOWNLOAD_DIR:-$(pwd)/CSLC}"
PARALLEL="${PARALLEL:-4}"

usage() {
    echo "Usage: ${0##*/} [OPTIONS]"
    echo ""
    echo "Download CSLC data for Miami (25.765:25.98 N, -80.147:-80.1146 W) from ASF."
    echo "Requires: conda env with asf_search (e.g. minsar env)."
    echo ""
    echo "Options:"
    echo "  --start YYYY-MM-DD   Start date (default: ${START_DATE})"
    echo "  --end YYYY-MM-DD    End date (default: ${END_DATE})"
    echo "  --dir DIR           Download directory (default: ${DOWNLOAD_DIR})"
    echo "  --parallel N        Parallel downloads (default: ${PARALLEL})"
    echo "  --print-only        Only search and print results, do not download"
    echo "  -h, --help          Show this help"
}

PRINT_ONLY=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --start)   START_DATE="$2"; shift 2 ;;
        --end)     END_DATE="$2";   shift 2 ;;
        --dir)     DOWNLOAD_DIR="$2"; shift 2 ;;
        --parallel) PARALLEL="$2"; shift 2 ;;
        --print-only) PRINT_ONLY="--print"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

if [[ ! -f "${ASF_SCRIPT}" ]]; then
    echo "Error: asf_search_args.py not found at ${ASF_SCRIPT}" >&2
    echo "Set MINSAR_ROOT to the repo root containing minsar/src/minsar/cli/asf_search_args.py" >&2
    exit 1
fi

mkdir -p "${DOWNLOAD_DIR}"
DOWNLOAD_DIR="$(cd "${DOWNLOAD_DIR}" && pwd)"

CMD=(
    python "${ASF_SCRIPT}"
    --processingLevel=CSLC
    --platform=SENTINEL1
    --start="${START_DATE}"
    --end="${END_DATE}"
    --intersectsWith="${MIA_POLYGON}"
    --dir="${DOWNLOAD_DIR}"
    --parallel="${PARALLEL}"
)
if [[ -n "${PRINT_ONLY}" ]]; then
    CMD+=( "${PRINT_ONLY}" )
else
    CMD+=( --download )
fi

echo "Running: ${CMD[*]}"
exec "${CMD[@]}"
