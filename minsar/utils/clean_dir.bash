#!/usr/bin/env bash
# clean_dir.bash -- purge stale miaplpy/mintpy trees and selected products under $SCRATCHDIR
set -eo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

SUMMARY_TOP_DIRS=20
SUMMARY_TOP_FILES=50
DRY_RUN_TOP=20

print_help() {
    cat <<EOF

purge stale miaplpy*, mintpy* and inputs dirs (keep pic/).

Usage: $SCRIPT_NAME [OPTIONS] [PROJECT ...]

  PROJECT   Optional. One or more names under \$SCRATCHDIR (e.g. EtnaSenD124 or EtnaSen)

Options:
  --root DIR       Scratch parent (default: \$SCRATCHDIR)
  --miaplpy YEARS  Strip stale *miaplpy* (keep pic/; default 2; YEARS may be decimal)
  --mintpy YEARS   Strip stale *mintpy* (keep pic/; default 2)
  --keep-filt      Under *miaplpy*, only remove old *_Del4DS*/*_Del4PS* (no full strip)
  --keep-he5       Never delete *.he5 files
  --inputs YEARS   Remove old miaplpy*/inputs/{slcStack,geometryRadar}.h5 (default 1)
  --pic YEARS      Remove old pic/ outside *miaplpy*/*mintpy* (default 5)
  --dry-run        Preview removals (top ${DRY_RUN_TOP} by size); nothing deleted
  --show-all       List all removed/would-remove paths (not only top ${DRY_RUN_TOP})
  --summary        Print largest top-level dirs and largest files
  -h, --help       Show this help

Examples:
  $SCRIPT_NAME --dry-run
  $SCRIPT_NAME --dry-run EtnaSenD124
  $SCRIPT_NAME LangilaSen --dry-run --miaplpy 0.5 --keep-filt
  $SCRIPT_NAME LangilaSen --miaplpy 0.5 --keep-he5 --show-all
  $SCRIPT_NAME --dry-run --miaplpy 3 --mintpy 3 --inputs 2 --pic 5
EOF
}

ROOT=""
TARGET_ARGS=()
MIAPLPY_YEARS=2
MINTPY_YEARS=2
INPUTS_YEARS=1
PIC_YEARS=5
DRY_RUN=0
SUMMARY_ONLY=0
KEEP_FILT=0
KEEP_HE5=0
SHOW_ALL=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --root)
            ROOT="$2"
            shift 2
            ;;
        --miaplpy)
            MIAPLPY_YEARS="$2"
            shift 2
            ;;
        --mintpy)
            MINTPY_YEARS="$2"
            shift 2
            ;;
        --inputs)
            INPUTS_YEARS="$2"
            shift 2
            ;;
        --pic)
            PIC_YEARS="$2"
            shift 2
            ;;
        --keep-filt)
            KEEP_FILT=1
            shift
            ;;
        --keep-he5)
            KEEP_HE5=1
            shift
            ;;
        --show-all)
            SHOW_ALL=1
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --summary)
            SUMMARY_ONLY=1
            shift
            ;;
        -h|--help)
            print_help
            exit 0
            ;;
        -?*|--*)
            echo "Error: Unknown option: $1" >&2
            echo "Use $SCRIPT_NAME --help for available options" >&2
            exit 1
            ;;
        *)
            TARGET_ARGS+=("$1")
            shift
            ;;
    esac
done

if [[ -z "$ROOT" ]]; then
    if [[ -z "${SCRATCHDIR:-}" ]]; then
        echo "Error: --root not set and SCRATCHDIR is unset" >&2
        exit 1
    fi
    ROOT="$SCRATCHDIR"
fi

if [[ ! -d "$ROOT" ]]; then
    echo "Error: root directory does not exist: $ROOT" >&2
    exit 1
fi

for pair in "MIAPLPY_YEARS:$MIAPLPY_YEARS" "MINTPY_YEARS:$MINTPY_YEARS" "INPUTS_YEARS:$INPUTS_YEARS" "PIC_YEARS:$PIC_YEARS"; do
    name="${pair%%:*}"
    val="${pair#*:}"
    if [[ ! "$val" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
        echo "Error: $name must be a non-negative number (got: $val)" >&2
        exit 1
    fi
done

# find -mtime needs integer days; round years*365 to nearest day.
years_to_days() {
    awk -v y="$1" 'BEGIN { d = y * 365; if (d < 0) d = 0; printf "%d", int(d + 0.5) }'
}

ROOT="$(cd "$ROOT" && pwd)"

# Append absolute dirs matching one PROJECT arg into array named by $2 (nameref).
resolve_project_arg() {
    local arg="$1"
    local -n _resolved_out="$2"
    local matches=() m abs pattern
    local saved_nullglob=0

    if [[ "$arg" == /* ]]; then
        if [[ ! -d "$arg" ]]; then
            echo "Error: project/directory does not exist: $arg" >&2
            return 1
        fi
        _resolved_out+=("$(cd "$arg" && pwd)")
        return 0
    fi

    if [[ -d "$ROOT/$arg" ]]; then
        _resolved_out+=("$(cd "$ROOT/$arg" && pwd)")
        return 0
    fi

    if [[ "$arg" == *[\*\?\[]* ]]; then
        pattern="$arg"
    else
        pattern="${arg}*"
    fi

    shopt -q nullglob && saved_nullglob=1
    shopt -s nullglob
    # Intentional unquoted pattern for glob under ROOT
    matches=("$ROOT"/$pattern)
    if [[ "$saved_nullglob" -eq 0 ]]; then
        shopt -u nullglob
    fi

    if [[ ${#matches[@]} -eq 0 ]]; then
        echo "Error: no project matching under $ROOT: $arg" >&2
        return 1
    fi

    local added=0
    for m in "${matches[@]}"; do
        [[ -d "$m" ]] || continue
        abs="$(cd "$m" && pwd)"
        _resolved_out+=("$abs")
        added=1
    done
    if [[ "$added" -eq 0 ]]; then
        echo "Error: no project directory matching under $ROOT: $arg" >&2
        return 1
    fi
    return 0
}

dedupe_paths() {
    local -n _paths="$1"
    local out=() p e dup
    for p in "${_paths[@]}"; do
        dup=0
        for e in "${out[@]}"; do
            if [[ "$e" == "$p" ]]; then
                dup=1
                break
            fi
        done
        if [[ "$dup" -eq 0 ]]; then
            out+=("$p")
        fi
    done
    _paths=("${out[@]}")
}

# SCOPES: dirs to scan (ROOT alone = full tree; else one or more projects)
SCOPES=()
FULL_TREE=1
if [[ ${#TARGET_ARGS[@]} -gt 0 ]]; then
    FULL_TREE=0
    for targ in "${TARGET_ARGS[@]}"; do
        resolve_project_arg "$targ" SCOPES || exit 1
    done
    dedupe_paths SCOPES
    if [[ ${#SCOPES[@]} -eq 0 ]]; then
        echo "Error: no projects resolved" >&2
        exit 1
    fi
else
    SCOPES=("$ROOT")
fi

MIAPLPY_DAYS="$(years_to_days "$MIAPLPY_YEARS")"
MINTPY_DAYS="$(years_to_days "$MINTPY_YEARS")"
INPUTS_DAYS="$(years_to_days "$INPUTS_YEARS")"
PIC_DAYS="$(years_to_days "$PIC_YEARS")"

# Candidate list: lines are "BYTES<TAB>PATH" (used for dry-run and quiet execute summary)
CAND_FILE=""
cleanup_cand() {
    if [[ -n "$CAND_FILE" && -f "$CAND_FILE" ]]; then
        rm -f "$CAND_FILE"
    fi
    return 0
}
trap cleanup_cand EXIT

log_cmd() {
    local log_file="${PWD}/log"
    if [[ -w "$PWD" ]] || [[ -w "$log_file" ]]; then
        echo "$(date +"%Y%m%d:%H-%M") * $SCRIPT_NAME $*" >> "$log_file" 2>/dev/null || true
    fi
}

# True if any regular file under dir is newer than N days.
has_file_newer_than_days() {
    local dir="$1"
    local days="$2"
    find "$dir" -type f -mtime -"${days}" -print -quit 2>/dev/null | grep -q .
}

# Like has_file_newer_than_days, but ignore pic/ (kept separately).
has_file_newer_than_days_excluding_pic() {
    local dir="$1"
    local days="$2"
    find "$dir" -type f ! -path '*/pic/*' -mtime -"${days}" -print -quit 2>/dev/null | grep -q .
}

# True if path is a pic/ directory under a *miaplpy* or *mintpy* tree.
is_miaplpy_or_mintpy_pic() {
    local p="$1"
    local d b
    [[ "$(basename "$p")" == "pic" ]] || return 1
    d="$(dirname "$p")"
    while [[ -n "$d" && "$d" != "/" && "$d" != "." ]]; do
        b="$(basename "$d")"
        if [[ "$b" == *miaplpy* || "$b" == *mintpy* ]]; then
            return 0
        fi
        d="$(dirname "$d")"
    done
    return 1
}

# True if directory contains any *.he5 file.
dir_has_he5() {
    local dir="$1"
    find "$dir" -type f -name '*.he5' -print -quit 2>/dev/null | grep -q .
}

# Strip dir contents but keep every pic/ directory anywhere in the tree.
# With --keep-he5, also leave all *.he5 files in place.
remove_dir_keep_pic() {
    local dir="$1"
    local reason="${2:-strip}"
    local item base
    local saved_nullglob=0
    shopt -q nullglob && saved_nullglob=1
    shopt -s nullglob
    for item in "$dir"/*; do
        base="$(basename "$item")"
        if [[ "$base" == "pic" ]]; then
            continue
        fi
        if [[ -f "$item" && "$KEEP_HE5" -eq 1 && "$base" == *.he5 ]]; then
            continue
        fi
        if [[ -d "$item" && ! -L "$item" ]]; then
            if find "$item" -type d -name pic -print -quit 2>/dev/null | grep -q . \
                || { [[ "$KEEP_HE5" -eq 1 ]] && dir_has_he5 "$item"; }; then
                # Nested pic/ and/or .he5: clean inside, do not remove wholesale
                remove_dir_keep_pic "$item" "$reason"
            else
                remove_dir "$item" "$reason"
            fi
        else
            remove_file "$item" "$reason"
        fi
    done
    if [[ "$saved_nullglob" -eq 0 ]]; then
        shopt -u nullglob
    fi
}

# Strip matching processing dirs older than DAYS (always keep pic/ anywhere under them).
strip_stale_named_dirs() {
    local name_glob="$1"
    local days="$2"
    local reason="$3"
    local procdir
    while IFS= read -r -d $'\0' procdir; do
        if has_file_newer_than_days_excluding_pic "$procdir" "$days"; then
            continue
        fi
        remove_dir_keep_pic "$procdir" "$reason"
    done < <(find "${SCOPES[@]}" -type d -name "$name_glob" -print0 2>/dev/null)
}

# Under *miaplpy*: remove *_Del4DS* / *_Del4PS* older than DAYS (keeps filtDel4* and other .he5).
remove_keepfilt_del4_files() {
    local days="$1"
    local f
    if [[ "$KEEP_HE5" -eq 1 ]]; then
        return 0
    fi
    while IFS= read -r -d $'\0' f; do
        remove_file "$f" "keepfilt"
    done < <(find "${SCOPES[@]}" -type f -path '*/miaplpy*/*' \( -name '*_Del4DS*' -o -name '*_Del4PS*' \) \
        -mtime +"${days}" -print0 2>/dev/null)
}

file_bytes() {
    local f="$1"
    if stat -c '%s' "$f" &>/dev/null; then
        stat -c '%s' "$f"
    elif stat -f '%z' "$f" &>/dev/null; then
        stat -f '%z' "$f"
    else
        wc -c < "$f" | tr -d ' \n'
    fi
}

path_bytes() {
    local p="$1"
    if [[ -d "$p" ]]; then
        if du -sb "$p" &>/dev/null; then
            du -sb "$p" 2>/dev/null | awk '{print $1}'
        elif du -sk "$p" &>/dev/null; then
            du -sk "$p" 2>/dev/null | awk '{print $1 * 1024}'
        else
            echo 0
        fi
    else
        file_bytes "$p" 2>/dev/null || echo 0
    fi
}

human_gib() {
    awk -v b="$1" 'BEGIN { printf "%.2f GiB", b/1024/1024/1024 }'
}

# Record a path that will be / was removed (size before delete).
# CAND_FILE lines: BYTES<TAB>REASON<TAB>PATH
record_candidate() {
    local p="$1"
    local reason="${2:-remove}"
    local sz
    sz="$(path_bytes "$p")"
    printf '%s\t%s\t%s\n' "$sz" "$reason" "$p" >> "$CAND_FILE"
}

remove_file() {
    local f="$1"
    local reason="${2:-remove}"
    local base
    base="$(basename "$f")"
    if [[ "$KEEP_HE5" -eq 1 && "$base" == *.he5 ]]; then
        return 0
    fi
    record_candidate "$f" "$reason"
    if [[ "$DRY_RUN" -eq 0 ]]; then
        rm -f "$f"
    fi
}

remove_dir() {
    local d="$1"
    local reason="${2:-remove}"
    if [[ "$KEEP_HE5" -eq 1 ]] && dir_has_he5 "$d"; then
        remove_dir_keep_pic "$d" "$reason"
        return 0
    fi
    record_candidate "$d" "$reason"
    if [[ "$DRY_RUN" -eq 0 ]]; then
        rm -rf "$d"
    fi
}

# CLI options line for dry-run (includes optional PROJECT args as given).
options_used_line() {
    local line="$SCRIPT_NAME --miaplpy $MIAPLPY_YEARS --mintpy $MINTPY_YEARS --inputs $INPUTS_YEARS --pic $PIC_YEARS"
    if [[ "$KEEP_FILT" -eq 1 ]]; then
        line="$line --keep-filt"
    fi
    if [[ "$KEEP_HE5" -eq 1 ]]; then
        line="$line --keep-he5"
    fi
    if [[ "$SHOW_ALL" -eq 1 ]]; then
        line="$line --show-all"
    fi
    local t
    for t in "${TARGET_ARGS[@]}"; do
        line="$line $t"
    done
    echo "$line"
}

# Totals + top N largest. Dry-run shows the equivalent CLI options used.
print_removal_report() {
    local n_total=0
    local bytes_total=0
    local sz reason
    local has_miaplpy=0 has_mintpy=0 has_inputs=0 has_pic=0 has_keepfilt=0
    local summary_bits=() summary_txt=""

    if [[ ! -s "$CAND_FILE" ]]; then
        echo ""
        if [[ "$DRY_RUN" -eq 1 ]]; then
            echo "======== Dry-run: nothing would be removed ========"
            echo "Options used (lower those years for more candidates):"
            echo "  $(options_used_line)"
        else
            echo "======== Nothing removed ========"
        fi
        return 0
    fi

    while IFS=$'\t' read -r sz reason _; do
        n_total=$((n_total + 1))
        bytes_total=$((bytes_total + sz))
        case "$reason" in
            "miaplpy strip") has_miaplpy=1 ;;
            "mintpy strip") has_mintpy=1 ;;
            "old inputs") has_inputs=1 ;;
            "old pic") has_pic=1 ;;
            "keepfilt") has_keepfilt=1 ;;
        esac
    done < "$CAND_FILE"

    [[ "$has_miaplpy" -eq 1 ]] && summary_bits+=("miaplpy strip")
    [[ "$has_keepfilt" -eq 1 ]] && summary_bits+=("keep-filt")
    [[ "$has_mintpy" -eq 1 ]] && summary_bits+=("mintpy strip")
    [[ "$has_inputs" -eq 1 ]] && summary_bits+=("old inputs")
    [[ "$has_pic" -eq 1 ]] && summary_bits+=("old pic")
    if [[ ${#summary_bits[@]} -gt 0 ]]; then
        summary_txt=$(IFS=', '; echo "${summary_bits[*]}")
        summary_txt=": ${summary_txt}"
    fi

    echo ""
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "======== Dry-run: would remove $n_total path(s), ~$(human_gib "$bytes_total")${summary_txt} ========"
        echo "Options used (lower those years for more candidates):"
        echo "  $(options_used_line)"
    else
        echo "======== Removed $n_total path(s), ~$(human_gib "$bytes_total")${summary_txt} ========"
    fi
    echo ""
    (
        set +o pipefail
        if [[ "$SHOW_ALL" -eq 1 ]]; then
            sort -n "$CAND_FILE" \
                | awk -F'\t' '{ printf "%10.2f GiB  %s\n", $1/1024/1024/1024, $3 }'
        else
            sort -n "$CAND_FILE" | tail -n "$DRY_RUN_TOP" \
                | awk -F'\t' '{ printf "%10.2f GiB  %s\n", $1/1024/1024/1024, $3 }'
        fi
    )
}

# Print disk free space, then largest files, then largest top-level dirs (under SCOPES).
print_usage_report() {
    echo ""
    echo "======== Disk free space ========"
    df -h "${SCOPES[0]}" || true

    echo ""
    echo "======== ${SUMMARY_TOP_FILES} largest files ========"
    (
        set +o pipefail
        if find "${SCOPES[@]}" -maxdepth 0 -printf '%s' -quit &>/dev/null; then
            find "${SCOPES[@]}" -type f -printf '%s\t%p\n' 2>/dev/null \
                | sort -nr \
                | head -n "$SUMMARY_TOP_FILES" \
                | sort -n \
                | awk '{ printf "%10.2f GiB  %s\n", $1/1024/1024/1024, substr($0, index($0,$2)) }'
        else
            find "${SCOPES[@]}" -type f -exec stat -f '%z %N' {} \; 2>/dev/null \
                | sort -nr \
                | head -n "$SUMMARY_TOP_FILES" \
                | sort -n \
                | awk '{ printf "%10.2f GiB  %s\n", $1/1024/1024/1024, substr($0, index($0,$2)) }' \
                || echo "(could not list largest files)"
        fi
    )

    echo ""
    echo "======== ${SUMMARY_TOP_DIRS} largest top-level dirs ========"
    local entries=()
    if [[ "$FULL_TREE" -eq 1 ]]; then
        shopt -s nullglob
        entries=("$ROOT"/*)
        shopt -u nullglob
    else
        entries=("${SCOPES[@]}")
    fi
    if [[ ${#entries[@]} -eq 0 ]]; then
        echo "(empty)"
    else
        if du -sb "${entries[@]}" 2>/dev/null | sort -n | tail -n "$SUMMARY_TOP_DIRS" \
            | awk '{ printf "%10.2f GiB  %s\n", $1/1024/1024/1024, substr($0, index($0,$2)) }'; then
            :
        elif du -sk "${entries[@]}" 2>/dev/null | sort -n | tail -n "$SUMMARY_TOP_DIRS" \
            | awk '{ printf "%10.2f GiB  %s\n", ($1*1024)/1024/1024/1024, substr($0, index($0,$2)) }'; then
            :
        else
            echo "(could not list top-level sizes)"
        fi
    fi
}

log_cmd "$@"
[[ "$DRY_RUN" -eq 1 ]] && echo "Mode: DRY-RUN"
[[ "$SUMMARY_ONLY" -eq 1 ]] && echo "Mode: SUMMARY only"
[[ "$KEEP_FILT" -eq 1 ]] && echo "Mode: keep-filt (miaplpy Del4 only)"
[[ "$KEEP_HE5" -eq 1 ]] && echo "Mode: keep-he5"
[[ "$SHOW_ALL" -eq 1 ]] && echo "Mode: show-all"

if [[ "$SUMMARY_ONLY" -eq 1 ]]; then
    print_usage_report
    exit 0
fi

CAND_FILE="$(mktemp)"

#######################################
# 1. Miaplpy: full strip, or --keep-filt Del4 files only
#######################################
if [[ "$KEEP_FILT" -eq 1 ]]; then
    remove_keepfilt_del4_files "$MIAPLPY_DAYS"
else
    strip_stale_named_dirs '*miaplpy*' "$MIAPLPY_DAYS" "miaplpy strip"
fi

#######################################
# 2. Stale *mintpy* dirs (keep pic/)
#######################################
strip_stale_named_dirs '*mintpy*' "$MINTPY_DAYS" "mintpy strip"

#######################################
# 3. Old inputs slcStack / geometryRadar
#######################################
while IFS= read -r -d $'\0' f; do
    remove_file "$f" "old inputs"
done < <(find "${SCOPES[@]}" -type f \( -path "*/miaplpy*/inputs/slcStack.h5" -o -path "*/miaplpy*/inputs/geometryRadar.h5" \) -mtime +"${INPUTS_DAYS}" -print0 2>/dev/null)

#######################################
# 4. Old pic/ directories (never under *miaplpy* / *mintpy*)
#######################################
while IFS= read -r -d $'\0' picdir; do
    if is_miaplpy_or_mintpy_pic "$picdir"; then
        continue
    fi
    if has_file_newer_than_days "$picdir" "$PIC_DAYS"; then
        continue
    fi
    remove_dir "$picdir" "old pic"
done < <(find "${SCOPES[@]}" -type d -name pic -print0 2>/dev/null)

#######################################
# 5. Report (same top-N list for dry-run and execute)
#######################################
print_removal_report

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo ""
    echo "(nothing deleted)"
    exit 0
fi

echo ""
echo "$SCRIPT_NAME completed."
