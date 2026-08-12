#!/usr/bin/env bash
# clean_dir.bash -- purge stale projects / selected MiaplPy products under $SCRATCHDIR
set -eo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

# Top-level dirs eligible for stale removal must contain a satellite+track token, e.g.:
#   EtnaSenA44, EtnaSenAT44, EtnaSenDT128, EtnaTsxSMD36, KilaueaCskAT10, AlcedotestEnvD140
# Bash ERE (used with [[ =~ ]])
SAT_TRACK_RE='(Sen[AD]T?[0-9]+|Tsx[A-Za-z]*[0-9]+|Csk[A-Za-z]*[0-9]+|Env[A-Za-z]*[0-9]+|Alos[A-Za-z0-9]*[0-9]+)'

# How many largest entries to show (largest last)
SUMMARY_TOP_DIRS=20
SUMMARY_TOP_FILES=50
DRY_RUN_TOP=20
# Stale projects older than this (years) are removed entirely, including pics/
STALE_FULL_YEARS=10

print_help() {
    cat <<EOF
Purge stale top-level projects and selected MiaplPy products under a scratch root,
then report disk usage. With --summary, only report usage (no deletes).

Stale top-level cleanup only applies to dirs whose names contain a satellite+track
abbreviation (e.g. EtnaSenA44, EtnaSenAT44, EtnaTsxSMD36). Never touches famelung
or names without that pattern (e.g. Etna).

For --stale: strip eligible project contents but keep pics/ (full wipe if nothing
newer than ${STALE_FULL_YEARS}y). Also remove *Del4DS*/*Del4PS*.he5 under
miaplpy*/network_* older than --stale YEARS.

Usage: $SCRIPT_NAME [OPTIONS] [PROJECT ...]

  PROJECT   Optional. One or more names under \$SCRATCHDIR (e.g. EtnaSenD124),
            absolute paths, or prefixes (LangilaSen → LangilaSen*). Globs in the
            name (LangilaSen*) are expanded under --root. If omitted, all
            projects under --root are scanned.

Options:
  --root DIR       Scratch parent (default: \$SCRATCHDIR); used to resolve PROJECT
  --stale YEARS    Project strip + Del4DS/Del4PS .he5 age cutoff (default: 2; full wipe >${STALE_FULL_YEARS}y)
  --inputs YEARS   Age cutoff for miaplpy*/inputs/{slcStack,geometryRadar}.h5 (default: 1)
  --pics YEARS     Remove pics/ dirs with no file newer than YEARS (default: 5)
  --dry-run        Preview removals (top ${DRY_RUN_TOP} by size); nothing deleted
  --summary        Print largest top-level dirs and largest files
  -h, --help       Show this help

Examples:
  $SCRIPT_NAME --dry-run
  $SCRIPT_NAME --dry-run EtnaSenD124
  $SCRIPT_NAME LangilaSen --dry-run --stale 1
  $SCRIPT_NAME --dry-run --stale 3 --inputs 2 --pics 5
EOF
}

ROOT=""
TARGET_ARGS=()
STALE_YEARS=2
INPUTS_YEARS=1
PICS_YEARS=5
DRY_RUN=0
SUMMARY_ONLY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --root)
            ROOT="$2"
            shift 2
            ;;
        --stale)
            STALE_YEARS="$2"
            shift 2
            ;;
        --inputs)
            INPUTS_YEARS="$2"
            shift 2
            ;;
        --pics)
            PICS_YEARS="$2"
            shift 2
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

for pair in "STALE_YEARS:$STALE_YEARS" "INPUTS_YEARS:$INPUTS_YEARS" "PICS_YEARS:$PICS_YEARS"; do
    name="${pair%%:*}"
    val="${pair#*:}"
    if [[ ! "$val" =~ ^[0-9]+$ ]]; then
        echo "Error: $name must be a non-negative integer (got: $val)" >&2
        exit 1
    fi
done

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

STALE_DAYS=$((STALE_YEARS * 365))
STALE_FULL_DAYS=$((STALE_FULL_YEARS * 365))
INPUTS_DAYS=$((INPUTS_YEARS * 365))
PICS_DAYS=$((PICS_YEARS * 365))

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

# True if basename is eligible for stale project removal (satellite+track in name).
is_stale_removal_candidate() {
    local base="$1"
    [[ "$base" == "famelung" ]] && return 1
    [[ "$base" =~ $SAT_TRACK_RE ]]
}

# True if any regular file under dir is newer than N days.
has_file_newer_than_days() {
    local dir="$1"
    local days="$2"
    find "$dir" -type f -mtime -"${days}" -print -quit 2>/dev/null | grep -q .
}

# Remove all top-level entries in project except pics/
remove_project_keep_pics() {
    local proj="$1"
    local item base
    local saved_nullglob=0
    shopt -q nullglob && saved_nullglob=1
    shopt -s nullglob
    for item in "$proj"/*; do
        base="$(basename "$item")"
        if [[ "$base" == "pics" ]]; then
            continue
        fi
        if [[ -d "$item" && ! -L "$item" ]]; then
            remove_dir "$item"
        else
            remove_file "$item"
        fi
    done
    if [[ "$saved_nullglob" -eq 0 ]]; then
        shopt -u nullglob
    fi
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
# CAND_FILE lines: BYTES<TAB>PATH
record_candidate() {
    local p="$1"
    local sz
    sz="$(path_bytes "$p")"
    printf '%s\t%s\n' "$sz" "$p" >> "$CAND_FILE"
}

remove_file() {
    local f="$1"
    record_candidate "$f"
    if [[ "$DRY_RUN" -eq 0 ]]; then
        rm -f "$f"
    fi
}

remove_dir() {
    local d="$1"
    record_candidate "$d"
    if [[ "$DRY_RUN" -eq 0 ]]; then
        rm -rf "$d"
    fi
}

# CLI options line for dry-run (includes optional PROJECT args as given).
options_used_line() {
    local line="$SCRIPT_NAME --stale $STALE_YEARS --inputs $INPUTS_YEARS --pics $PICS_YEARS"
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
    local sz

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

    while IFS=$'\t' read -r sz _; do
        n_total=$((n_total + 1))
        bytes_total=$((bytes_total + sz))
    done < "$CAND_FILE"

    echo ""
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "======== Dry-run: would remove $n_total path(s), ~$(human_gib "$bytes_total") ========"
        echo "Options used (lower those years for more candidates):"
        echo "  $(options_used_line)"
    else
        echo "======== Removed $n_total path(s), ~$(human_gib "$bytes_total") ========"
    fi
    echo ""
    (
        set +o pipefail
        sort -n "$CAND_FILE" | tail -n "$DRY_RUN_TOP" \
            | awk -F'\t' '{ printf "%10.2f GiB  %s\n", $1/1024/1024/1024, $2 }'
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
echo "Root: $ROOT"
if [[ "$FULL_TREE" -eq 0 ]]; then
    echo "Projects (${#SCOPES[@]}):"
    for _p in "${SCOPES[@]}"; do
        echo "  $_p"
    done
fi
[[ "$DRY_RUN" -eq 1 ]] && echo "Mode: DRY-RUN"
[[ "$SUMMARY_ONLY" -eq 1 ]] && echo "Mode: SUMMARY only"

if [[ "$SUMMARY_ONLY" -eq 1 ]]; then
    print_usage_report
    exit 0
fi

CAND_FILE="$(mktemp)"

#######################################
# 1. Stale projects (satellite+track names only)
#######################################
stale_projects=()
shopt -s nullglob
if [[ "$FULL_TREE" -eq 1 ]]; then
    stale_projects=("$ROOT"/*)
else
    stale_projects=("${SCOPES[@]}")
fi
shopt -u nullglob
for proj in "${stale_projects[@]}"; do
    [[ -d "$proj" ]] || continue
    base="$(basename "$proj")"
    if ! is_stale_removal_candidate "$base"; then
        continue
    fi
    if has_file_newer_than_days "$proj" "$STALE_DAYS"; then
        continue
    elif has_file_newer_than_days "$proj" "$STALE_FULL_DAYS"; then
        # Stale but not ancient: strip contents, keep pics/
        remove_project_keep_pics "$proj"
    else
        # Nothing newer than STALE_FULL_YEARS: remove entire project
        remove_dir "$proj"
    fi
done

#######################################
# 2. Del4DS / Del4PS HE5 under miaplpy*/network_* (older than --stale)
#######################################
while IFS= read -r -d $'\0' netdir; do
    while IFS= read -r -d $'\0' he5; do
        remove_file "$he5"
    done < <(find "$netdir" -type f \( -name "*Del4DS*.he5" -o -name "*Del4PS*.he5" \) \
        -mtime +"${STALE_DAYS}" -print0 2>/dev/null)
done < <(find "${SCOPES[@]}" -type d -path "*/miaplpy*/network_*" -print0 2>/dev/null)

#######################################
# 3. *timeseries*.h5 under miaplpy*/network_*
#######################################
while IFS= read -r -d $'\0' netdir; do
    while IFS= read -r -d $'\0' ts; do
        remove_file "$ts"
    done < <(find "$netdir" -type f -name "*timeseries*.h5" -print0 2>/dev/null)
done < <(find "${SCOPES[@]}" -type d -path "*/miaplpy*/network_*" -print0 2>/dev/null)

#######################################
# 4. Old inputs slcStack / geometryRadar
#######################################
while IFS= read -r -d $'\0' f; do
    remove_file "$f"
done < <(find "${SCOPES[@]}" -type f \( -path "*/miaplpy*/inputs/slcStack.h5" -o -path "*/miaplpy*/inputs/geometryRadar.h5" \) -mtime +"${INPUTS_DAYS}" -print0 2>/dev/null)

#######################################
# 5. Old pics/ directories
#######################################
while IFS= read -r -d $'\0' picsdir; do
    if has_file_newer_than_days "$picsdir" "$PICS_DAYS"; then
        continue
    fi
    remove_dir "$picsdir"
done < <(find "${SCOPES[@]}" -type d -name pics -print0 2>/dev/null)

#######################################
# 6. Report (same top-N list for dry-run and execute)
#######################################
print_removal_report

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo ""
    echo "(nothing deleted)"
    exit 0
fi

print_usage_report
echo ""
echo "$SCRIPT_NAME completed."
