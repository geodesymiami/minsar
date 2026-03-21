#!/usr/bin/env bash
# Create a MinSAR template for the opposite Sentinel pass (orbit label) from an existing template.
# Uses miaplpy.subset.lalo when set (last non-commented), else mintpy.subset.lalo, then
# get_sar_coverage.py --select to find asc/desc labels and relative orbits.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GET_SAR_COVERAGE="${SCRIPT_DIR}/get_sar_coverage.py"

usage() {
    cat <<'EOF'
Usage: create_opposite_orbit_template.bash [options] TEMPLATE_PATH

Copy TEMPLATE_PATH into the output directory and rename the basename so the orbit label
matches the complementary pass (asc vs desc) for the same AOI. Updates ssaraopt.relativeOrbit
to the opposite pass relative orbit number.

Options:
  --outdir DIR   Output directory (default: $AUTO_TEMPLATES, or sibling AUTO_TEMPLATES next
                 to $TEMPLATES if AUTO_TEMPLATES is unset)
  --platform P   Single platform for get_sar_coverage.py --select (default: S1)

Environment:
  TEMPLATES, AUTO_TEMPLATES — used for default --outdir (see above)

After a successful write, opposite_orbit.txt is written in the current working directory
(typically the MinSAR project / WORK_DIR) with one line: absolute path to the new template.

Example:
  create_opposite_orbit_template.bash $TE/ChilesSenA120.template
EOF
}

die() {
    echo "create_opposite_orbit_template.bash: $*" >&2
    exit 1
}

# Last non-commented assignment value for KEY (literal, e.g. miaplpy.subset.lalo) in FILE.
last_active_key_value() {
    local file="$1"
    local KEY="$2"
    awk -v KEY="$KEY" '
    function ltrim(s) { sub(/^[[:space:]]+/, "", s); return s }
    {
        raw = $0
        if (ltrim(raw) ~ /^#/) next
        t = ltrim(raw)
        if (index(t, KEY) != 1) next
        rest = substr(t, length(KEY) + 1)
        if (rest !~ /^[[:space:]]*=/) next
        sub(/^[[:space:]]*=[[:space:]]*/, "", rest)
        sub(/#.*/, "", rest)
        sub(/[[:space:]]+$/, "", rest)
        last = rest
    }
    END { print last }
    ' "$file"
}

# True if two paths refer to the same directory (string match or realpath).
_dirs_same() {
    local a="${1%/}" b="${2%/}"
    [[ "$a" == "$b" ]] && return 0
    if command -v realpath >/dev/null 2>&1 && [[ -d "$a" ]] && [[ -d "$b" ]]; then
        [[ "$(realpath "$a")" == "$(realpath "$b")" ]]
        return $?
    fi
    return 1
}

# Print WROTE line: use $AUTO_TEMPLATES in the message when outdir is that location.
print_wrote_line() {
    local outdir="$1" out_base="$2"
    if [[ -n "${AUTO_TEMPLATES:-}" ]] && _dirs_same "$outdir" "$AUTO_TEMPLATES"; then
        printf 'WROTE $AUTO_TEMPLATES/%s.template\n' "$out_base"
        return
    fi
    if [[ -n "${TEMPLATES:-}" ]]; then
        local sib_auto
        sib_auto="$(dirname "$TEMPLATES")/AUTO_TEMPLATES"
        if _dirs_same "$outdir" "$sib_auto"; then
            printf 'WROTE $AUTO_TEMPLATES/%s.template\n' "$out_base"
            return
        fi
    fi
    printf 'WROTE %s/%s.template\n' "${outdir%/}" "$out_base"
}

outdir=""
platform="S1"
template_path=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --outdir)
            [[ $# -ge 2 ]] || die "--outdir requires an argument"
            outdir="$2"
            shift 2
            ;;
        --platform)
            [[ $# -ge 2 ]] || die "--platform requires an argument"
            platform="$2"
            shift 2
            ;;
        -*)
            die "unknown option: $1"
            ;;
        *)
            [[ -z "$template_path" ]] || die "extra argument: $1"
            template_path="$1"
            shift
            ;;
    esac
done

[[ -n "$template_path" ]] || { usage >&2; die "TEMPLATE_PATH is required"; }
[[ -f "$template_path" ]] || die "not a file: $template_path"
[[ -f "$GET_SAR_COVERAGE" ]] || die "missing: $GET_SAR_COVERAGE"

if [[ -z "$outdir" ]]; then
    if [[ -n "${AUTO_TEMPLATES:-}" ]]; then
        outdir="$AUTO_TEMPLATES"
    elif [[ -n "${TEMPLATES:-}" ]]; then
        outdir="$(dirname "$TEMPLATES")/AUTO_TEMPLATES"
    else
        die "set AUTO_TEMPLATES or TEMPLATES, or pass --outdir"
    fi
fi

subset=""
subset="$(last_active_key_value "$template_path" "miaplpy.subset.lalo")"
if [[ -z "$subset" ]]; then
    subset="$(last_active_key_value "$template_path" "mintpy.subset.lalo")"
fi
[[ -n "$subset" ]] || die "no active miaplpy.subset.lalo or mintpy.subset.lalo in $template_path"

echo "Running get_sar_coverage.py \"$subset\" --platform \"$platform\" --select ..."
# shellcheck disable=SC1090
eval "$(python3 "$GET_SAR_COVERAGE" "$subset" --platform "$platform" --select)"

[[ -n "${asc_label:-}" && -n "${desc_label:-}" ]] || die "get_sar_coverage.py did not set asc_label/desc_label (check AOI and platform)"
[[ -n "${asc_relorbit:-}" && -n "${desc_relorbit:-}" ]] || die "get_sar_coverage.py did not set asc_relorbit/desc_relorbit"

base="$(basename "$template_path" .template)"
opposite_label=""
opposite_relorbit=""
if [[ "$base" == *"$asc_label"* ]]; then
    out_base="${base//${asc_label}/${desc_label}}"
    opposite_label="$desc_label"
    opposite_relorbit="$desc_relorbit"
elif [[ "$base" == *"$desc_label"* ]]; then
    out_base="${base//${desc_label}/${asc_label}}"
    opposite_label="$asc_label"
    opposite_relorbit="$asc_relorbit"
else
    die "basename $base.template does not contain asc_label=$asc_label or desc_label=$desc_label"
fi

[[ "$out_base" != "$base" ]] || die "could not substitute orbit label in basename (base=$base opposite=$opposite_label)"

mkdir -p "$outdir"
out_file="${outdir}/${out_base}.template"
cp -f "$template_path" "$out_file"

# Update ssaraopt.relativeOrbit on non-comment lines (first number after =).
tmp="${out_file}.$$"
awk -v rorb="$opposite_relorbit" '
    /^[[:space:]]*#/ { print; next }
    /^[[:space:]]*ssaraopt\.relativeOrbit[[:space:]]*=/ {
        sub(/=[[:space:]]*[0-9]+/, "= " rorb)
    }
    { print }
' "$out_file" >"$tmp"
mv -f "$tmp" "$out_file"

# Record path in the caller's project directory (current working dir, e.g. WORK_DIR).
_opposite_record="$out_file"
if command -v realpath >/dev/null 2>&1; then
    _opposite_record=$(realpath "$out_file")
else
    _opposite_record="$(cd "$(dirname "$out_file")" && pwd)/$(basename "$out_file")"
fi
printf '%s\n' "$_opposite_record" > "${PWD}/opposite_orbit.txt"

print_wrote_line "$outdir" "$out_base"
