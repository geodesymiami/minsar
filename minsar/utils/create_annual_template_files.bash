#!/usr/bin/env bash
# Create annual template variants from a base template and write run_templates.sh to $SCRATCHDIR.
# Usage: create_annual_template_files.bash TEMPLATE_FILE [--years N]

set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

show_help() {
    echo "Usage: $SCRIPT_NAME TEMPLATE_FILE [--years N]"
    echo ""
    echo "Creates annual template files (variant 1..N) from a base template (digit 0)."
    echo "Each variant: startDate = previous endDate + 1 day, endDate = previous endDate + 1 year."
    echo "Writes \$SCRATCHDIR/run_templates.sh to run minsarApp.bash on templates 0..N."
    echo ""
    echo "  --years N    Integer; number of annual variants. If omitted, creates variants up to current year (so an 11-year series yields 11 or 12 template files)."
    echo "  -h, --help   Show this help"
    echo ""
    echo "Example:"
    echo "  $SCRIPT_NAME burstsg0HawaiiSenD87.template"
    echo "  $SCRIPT_NAME burstsg0HawaiiSenD87.template --years 5"
    exit 0
}

# Reject unknown options
for arg in "$@"; do
    case "$arg" in
        -h|--help) show_help ;;
        -?*|--*)
            if [[ "$arg" != "--years" ]]; then
                echo "$SCRIPT_NAME: unknown option: $arg" >&2
                exit 1
            fi
            ;;
    esac
done

TEMPLATE_FILE=""
YEARS=""   # empty = auto (from base end to current year)

while [[ $# -gt 0 ]]; do
    case "$1" in
        --years)
            if [[ $# -lt 2 ]]; then
                echo "$SCRIPT_NAME: --years requires an integer argument" >&2
                exit 1
            fi
            if [[ ! "$2" =~ ^[0-9]+$ ]]; then
                echo "$SCRIPT_NAME: --years must be an integer (got: $2)" >&2
                exit 1
            fi
            YEARS="$2"
            shift 2
            ;;
        -h|--help) show_help ;;
        -*)
            echo "$SCRIPT_NAME: unknown option: $1" >&2
            exit 1
            ;;
        *)
            if [[ -z "$TEMPLATE_FILE" ]]; then
                TEMPLATE_FILE="$1"
            else
                echo "$SCRIPT_NAME: unexpected argument: $1" >&2
                exit 1
            fi
            shift
            ;;
    esac
done

if [[ -z "$TEMPLATE_FILE" ]]; then
    echo "$SCRIPT_NAME: TEMPLATE_FILE is required" >&2
    echo "Use -h or --help for usage." >&2
    exit 1
fi

if [[ ! -f "$TEMPLATE_FILE" ]] || [[ ! -r "$TEMPLATE_FILE" ]]; then
    echo "$SCRIPT_NAME: template file not found or not readable: $TEMPLATE_FILE" >&2
    exit 1
fi

# Basename without path and .template
BASE_NAME=$(basename "$TEMPLATE_FILE" .template)
TEMPLATE_DIR=$(dirname "$TEMPLATE_FILE")

# Require at least one digit in basename
if [[ ! "$BASE_NAME" =~ [0-9] ]]; then
    echo "$SCRIPT_NAME: basename must contain at least one digit: $BASE_NAME" >&2
    exit 1
fi

# Parse ssaraopt.startDate and ssaraopt.endDate (YYYYMMDD)
start_date=$(grep -E '^[^#%]*ssaraopt\.startDate' "$TEMPLATE_FILE" | grep -oE '[0-9]{8}' | head -1)
end_date=$(grep -E '^[^#%]*ssaraopt\.endDate' "$TEMPLATE_FILE" | grep -oE '[0-9]{8}' | head -1)

if [[ -z "$start_date" ]] || [[ ${#start_date} -ne 8 ]]; then
    echo "$SCRIPT_NAME: could not parse ssaraopt.startDate (YYYYMMDD) from: $TEMPLATE_FILE" >&2
    exit 1
fi
if [[ -z "$end_date" ]] || [[ ${#end_date} -ne 8 ]]; then
    echo "$SCRIPT_NAME: could not parse ssaraopt.endDate (YYYYMMDD) from: $TEMPLATE_FILE" >&2
    exit 1
fi

# First digit position in basename (0-based)
first_digit_pos=""
for (( i = 0; i < ${#BASE_NAME}; i++ )); do
    if [[ "${BASE_NAME:$i:1}" =~ [0-9] ]]; then
        first_digit_pos=$i
        break
    fi
done

if [[ -z "$first_digit_pos" ]]; then
    echo "$SCRIPT_NAME: no digit found in basename: $BASE_NAME" >&2
    exit 1
fi

# If --years not set, create variants until last endDate includes current year
if [[ -z "$YEARS" ]]; then
    base_end_year="${end_date:0:4}"
    current_year=$(date +%Y)
    YEARS=$(( current_year - base_end_year ))
    if [[ $YEARS -lt 0 ]]; then
        YEARS=0
    fi
    echo "Creating $YEARS variant(s) (base end year $base_end_year -> current year $current_year)"
fi

# Date arithmetic: add 1 day or 1 year to YYYYMMDD (GNU date)
date_add_day() {
    local yyyymmdd=$1
    date -d "${yyyymmdd:0:4}-${yyyymmdd:4:2}-${yyyymmdd:6:2} + 1 day" +%Y%m%d
}
date_add_year() {
    local yyyymmdd=$1
    date -d "${yyyymmdd:0:4}-${yyyymmdd:4:2}-${yyyymmdd:6:2} + 1 year" +%Y%m%d
}

# Build basename with first digit replaced by index
basename_for_index() {
    local idx=$1
    echo "${BASE_NAME:0:$first_digit_pos}${idx}${BASE_NAME:$(( first_digit_pos + 1 ))}"
}

# Write a template file with startDate and endDate replaced (preserve line style)
write_template_with_dates() {
    local src=$1
    local dest=$2
    local new_start=$3
    local new_end=$4
    while IFS= read -r line; do
        if [[ "$line" =~ ^[^#%]*ssaraopt\.startDate[[:space:]]*= ]]; then
            echo "$line" | sed -E "s/([^0-9])[0-9]{8}(.*)/\1${new_start}\2/"
        elif [[ "$line" =~ ^[^#%]*ssaraopt\.endDate[[:space:]]*= ]]; then
            echo "$line" | sed -E "s/([^0-9])[0-9]{8}(.*)/\1${new_end}\2/"
        else
            echo "$line"
        fi
    done < "$src" > "$dest"
}

# Create variant templates 1..N
prev_end=$end_date
for (( i = 1; i <= YEARS; i++ )); do
    new_start=$(date_add_day "$prev_end")
    new_end=$(date_add_year "$prev_end")
    variant_base=$(basename_for_index "$i")
    variant_path="$TEMPLATE_DIR/${variant_base}.template"
    write_template_with_dates "$TEMPLATE_FILE" "$variant_path" "$new_start" "$new_end"
    echo "Created: $variant_path (start=$new_start end=$new_end)"
    prev_end=$new_end
done

# Write $SCRATCHDIR/run_templates.sh (0..N)
if [[ -z "${SCRATCHDIR:-}" ]]; then
    echo "$SCRIPT_NAME: SCRATCHDIR is not set; cannot write run_templates.sh" >&2
    exit 1
fi

RUN_SCRIPT="${SCRATCHDIR}/run_templates.sh"

{
    echo '#!/usr/bin/env bash'
    echo '# Run minsarApp.bash on annual templates (0..N). Stop on first failure.'
    echo 'set -euo pipefail'
    echo ''
    for (( i = 0; i <= YEARS; i++ )); do
        base=$(basename_for_index "$i")
        echo "minsarApp.bash \"\$TE/${base}.template\" --no-mintpy --no-insarmaps --no-upload || { echo \"run_templates.sh: minsarApp.bash failed for template \$TE/${base}.template\" >&2; exit 1; }"
    done
} > "$RUN_SCRIPT"
chmod +x "$RUN_SCRIPT"
echo "Created: $RUN_SCRIPT ($(( YEARS + 1 )) templates: 0..$YEARS)"
