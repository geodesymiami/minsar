#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    helptext="
usage: $SCRIPT_NAME TEMPLATE.template MIAPLPY_SRC_DIR MIN_TEMP_COH

Temporarily set minTempCoh and minsar.product.suffix=coherenceThreshold, copy
MIAPLPY_SRC_DIR to a suffix-tagged dest, run minsarApp --miaplpy-start 8, then
restore the original minTempCoh values and set product.suffix to auto.

Arguments:
    TEMPLATE.template   MinSAR template (must end with .template)
    MIAPLPY_SRC_DIR     Source miaplpy_* directory for copy_miaplpy_network
    MIN_TEMP_COH        New temporal coherence threshold (e.g. 0.80)

Examples:
    $SCRIPT_NAME \$SAMPLESDIR/unittestGalapagosSenD128.template miaplpy_SN_201606_201608 0.80
    $SCRIPT_NAME \$TE/GalapagosSenDT128.template miaplpy_SN_201606_201608 0.55
"
    printf "%b" "$helptext"
    exit 0
fi

if [[ $# -ne 3 ]]; then
    echo "Error: expected 3 arguments (TEMPLATE MIAPLPY_SRC_DIR MIN_TEMP_COH)" >&2
    echo "Use $SCRIPT_NAME --help for available options" >&2
    exit 1
fi

template_file="$1"
src_miaplpy="${2%/}"
new_coh="$3"

if [[ "$template_file" != *.template ]]; then
    echo "Error: first argument must be a *.template file (got: $template_file)" >&2
    exit 1
fi
[[ -f "$template_file" ]] || { echo "Error: template not found: $template_file" >&2; exit 1; }
[[ -d "$src_miaplpy" ]] || { echo "Error: miaplpy source dir not found: $src_miaplpy" >&2; exit 1; }

if [[ ! "$new_coh" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "Error: MIN_TEMP_COH must be a decimal number (got: $new_coh)" >&2
    exit 1
fi

if ! declare -F copy_miaplpy_network >/dev/null 2>&1; then
    # shellcheck source=/dev/null
    source "${SCRIPT_DIR}/../lib/common_helpers.sh"
fi

coh_tag="$(python3 -c "v=float('${new_coh}'); print(f'{int(round(v*100)):03d}')")"
dst_miaplpy="${src_miaplpy}_${coh_tag}"

read_min_temp_coh() {
    local key="$1"
    awk -F= -v k="$key" '
        $0 ~ "^[[:space:]]*"k"[[:space:]]*=" {
            v=$2
            sub(/#.*/, "", v)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", v)
            print v
            exit
        }
    ' "$template_file"
}

orig_mintpy_coh="$(read_min_temp_coh 'mintpy.networkInversion.minTempCoh')"
orig_miaplpy_coh="$(read_min_temp_coh 'miaplpy.timeseries.minTempCoh')"

if [[ -z "$orig_mintpy_coh" || -z "$orig_miaplpy_coh" ]]; then
    echo "Error: could not read both minTempCoh keys from $template_file" >&2
    echo "  mintpy.networkInversion.minTempCoh='${orig_mintpy_coh}'" >&2
    echo "  miaplpy.timeseries.minTempCoh='${orig_miaplpy_coh}'" >&2
    exit 1
fi

echo "Original mintpy.networkInversion.minTempCoh = ${orig_mintpy_coh}"
echo "Original miaplpy.timeseries.minTempCoh      = ${orig_miaplpy_coh}"

PRODUCT_SUFFIX_COMMENT='#[auto / no / coherenceThreshold / TAG] auto for no extra suffix'
restored=0

set_product_suffix() {
    local value="$1"
    local line="minsar.product.suffix                = ${value}  ${PRODUCT_SUFFIX_COMMENT}"
    if grep -Eq '^[[:space:]]*minsar\.product\.suffix[[:space:]]*=' "$template_file"; then
        sed -i.bak -E "s|^[[:space:]]*minsar\.product\.suffix[[:space:]]*=.*|${line}|" "$template_file"
    else
        awk -v line="$line" '
            /^[[:space:]]*miaplpy\.timeseries\.minTempCoh[[:space:]]*=/ {
                print
                print line
                inserted=1
                next
            }
            { print }
            END {
                if (!inserted) print line
            }
        ' "$template_file" > "${template_file}.tmp"
        mv "${template_file}.tmp" "$template_file"
    fi
    rm -f "${template_file}.bak"
}

set_min_temp_coh_pair() {
    local mintpy_val="$1"
    local miaplpy_val="$2"
    sed -i.bak -E "s/(mintpy\.networkInversion\.minTempCoh[[:space:]]*=[[:space:]]*)([0-9.]+|auto)/\1${mintpy_val}/" "$template_file"
    sed -i.bak -E "s/(miaplpy\.timeseries\.minTempCoh[[:space:]]*=[[:space:]]*)([0-9.]+|auto)/\1${miaplpy_val}/" "$template_file"
    rm -f "${template_file}.bak"
}

restore_template() {
    [[ "$restored" == "1" ]] && return 0
    set_min_temp_coh_pair "$orig_mintpy_coh" "$orig_miaplpy_coh"
    set_product_suffix "auto"
    restored=1
    echo "Reinstated mintpy.networkInversion.minTempCoh = ${orig_mintpy_coh}"
    echo "Reinstated miaplpy.timeseries.minTempCoh      = ${orig_miaplpy_coh}"
    echo "Set minsar.product.suffix = auto"
}

trap restore_template EXIT

set_min_temp_coh_pair "$new_coh" "$new_coh"
set_product_suffix "coherenceThreshold"

echo "Set minTempCoh to ${new_coh}; minsar.product.suffix = coherenceThreshold"
echo "Source: $src_miaplpy"
echo "Dest:   $dst_miaplpy"

if declare -F rmd >/dev/null 2>&1; then
    rmd "$dst_miaplpy" || true
else
    rm -rf "$dst_miaplpy"
fi

copy_miaplpy_network "$src_miaplpy" "$dst_miaplpy"

minsarApp.bash "$template_file" --miaplpy-start 8

restore_template
trap - EXIT
echo "Done: $SCRIPT_NAME completed successfully."
