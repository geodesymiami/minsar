#!/usr/bin/env bash
########################################################################
# Download CSLC (coregistered SLC) data for Miami 2025 from ASF.
# Area: miaplpy.subset.lalo = 25.765:25.98,-80.147:-80.1146  [S:N,W:E]
# Output: $SCRATCHDIR/dolphin_test/CSLC (or --dir path)
#
# Uses minsar asf_search_args.py. Set MINSAR_REPO to the minsar repo root
# (parent of minsar/) if not running from the minsar tree.
#
# Usage: bash download_cslc_miami.bash [OPTIONS]
#   --dir PATH         Output directory for CSLC downloads (default: $SCRATCHDIR/dolphin_test/CSLC)
#   --startDate DATE   Start date YYYY-MM-DD (default: 2025-01-01)
#   --endDate DATE     End date YYYY-MM-DD (default: 2025-12-31)
#   --print-only       Search and print results only; do not download
########################################################################
set -euo pipefail

WORKDIR="${SCRATCHDIR:?SCRATCHDIR must be set}/dolphin_test"
CSLC_DIR="${WORKDIR}/CSLC"
START_DATE="2025-01-01"
END_DATE="2025-12-31"
PRINT_ONLY=""

# Parse optional --dir, --startDate, --endDate, --print-only
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dir)
            if [[ -z "${2:-}" ]]; then
                echo "Error: --dir requires PATH" >&2
                exit 1
            fi
            CSLC_DIR="$2"
            shift 2
            ;;
        --startDate)
            if [[ -z "${2:-}" ]]; then
                echo "Error: --startDate requires DATE (YYYY-MM-DD)" >&2
                exit 1
            fi
            START_DATE="$2"
            shift 2
            ;;
        --endDate)
            if [[ -z "${2:-}" ]]; then
                echo "Error: --endDate requires DATE (YYYY-MM-DD)" >&2
                exit 1
            fi
            END_DATE="$2"
            shift 2
            ;;
        --print-only)
            PRINT_ONLY="--print"
            shift
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--dir PATH] [--startDate YYYY-MM-DD] [--endDate YYYY-MM-DD] [--print-only]" >&2
            exit 1
            ;;
    esac
done
# Miami subset: 25.765:25.98,-80.147:-80.1146  (S:N, W:E) -> POLYGON (lon lat, ...)
# Polygon: (W min_lat, E min_lat, E max_lat, W max_lat, W min_lat)
POLYGON="POLYGON((-80.147 25.765, -80.1146 25.765, -80.1146 25.98, -80.147 25.98, -80.147 25.765))"

# Path to minsar asf_search_args.py (repo root = parent of minsar/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MINSAR_REPO="${MINSAR_REPO:-$(cd "${SCRIPT_DIR}/../../.." 2>/dev/null && pwd)}"
ASF_SCRIPT="${MINSAR_REPO}/minsar/src/minsar/cli/asf_search_args.py"

if [[ ! -f "${ASF_SCRIPT}" ]]; then
    echo "Error: asf_search_args.py not found at ${ASF_SCRIPT}" >&2
    echo "Set MINSAR_REPO to the minsar repo root (directory containing minsar/)." >&2
    exit 1
fi

mkdir -p "${CSLC_DIR}"
cd "${WORKDIR}"

# platform SENTINEL1 is set by asf_search_args when using CSLC
echo "Searching and downloading CSLC for Miami (${START_DATE} to ${END_DATE}, area: ${POLYGON})"
if [[ -n "${PRINT_ONLY}" ]]; then
    python "${ASF_SCRIPT}" \
        --processingLevel=CSLC \
        --start="${START_DATE}" \
        --end="${END_DATE}" \
        --intersectsWith="${POLYGON}" \
        --platform=SENTINEL1 \
        --dir="${CSLC_DIR}" \
        --parallel=4 \
        --print
else
    python "${ASF_SCRIPT}" \
        --processingLevel=CSLC \
        --start="${START_DATE}" \
        --end="${END_DATE}" \
        --intersectsWith="${POLYGON}" \
        --platform=SENTINEL1 \
        --dir="${CSLC_DIR}" \
        --parallel=4 \
        --download
fi

echo "CSLC files (if downloaded) are in: ${CSLC_DIR}"
