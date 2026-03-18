#!/usr/bin/env bash
# Count (and optionally list) completed MiaplPy phase_linking patches via flag.npy in inverted/PATCHES.
set -euo pipefail

usage() {
    cat << EOF
Usage: ${0##*/} [OPTIONS] [PATCHES_PATH]
       ${0##*/} [OPTIONS]

Report MiaplPy phase_linking patch status: total PATCH_ dirs, how many complete (flag.npy),
how many in progress (files but no flag.npy), and how many empty. With no argument,
auto-detect the miaplpy directory.

Options:
  --list     List each PATCH_*/flag.npy with modification date (default: only print count).
  --help     Show this help and exit.

Arguments:
  PATCHES_PATH   Path to inverted/PATCHES, or to a miaplpy* directory (then uses .../inverted/PATCHES).
                 Omitted: look for miaplpy* in the current directory.
                 - If exactly one miaplpy* directory exists, use its inverted/PATCHES.
                 - If multiple exist, use the miaplpy directory that has the most recently
                   modified inverted/PATCHES/PATCH_*/flag.npy.

Examples:
  ${0##*/}
  ${0##*/} --list
  ${0##*/} miaplpy_201410_202603/inverted/PATCHES
  ${0##*/} --list miaplpy_201410_202603/inverted/PATCHES
  ${0##*/} miaplpy_201410_202603
  cd /path/to/workdir && ${0##*/} --list
EOF
}

LIST_FLAG=false
PATCHES_PATH=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            usage
            exit 0
            ;;
        --list)
            LIST_FLAG=true
            shift
            ;;
        -?*|--*)
            echo "Error: Unknown option '$1'." >&2
            usage >&2
            exit 1
            ;;
        *)
            if [[ -n "$PATCHES_PATH" ]]; then
                echo "Error: Unexpected second argument '$1'." >&2
                usage >&2
                exit 1
            fi
            PATCHES_PATH="$1"
            shift
            ;;
    esac
done

# Portable: find most recent flag.npy when find -printf is not available (e.g. macOS)
find_newest_flag_in_patches() {
    local patches="$1"
    local newest=""
    local newest_ts=0
    local f t
    if find --version &>/dev/null; then
        # GNU find
        newest=$(find "$patches" -maxdepth 2 -name 'flag.npy' -type f -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    else
        # BSD/macOS: use stat (no find -printf)
        while IFS= read -r -d '' f; do
            t=$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null) || continue
            if [[ -n "$t" && "$t" -gt "$newest_ts" ]]; then
                newest_ts=$t
                newest="$f"
            fi
        done < <(find "$patches" -maxdepth 2 -name 'flag.npy' -type f -print0 2>/dev/null)
    fi
    echo "$newest"
}

# Resolve PATCHES dir when no arg: handle multiple miaplpy without find -printf
pick_best_miaplpy_dir() {
    local miaplpy_dirs=()
    local d
    for d in ./miaplpy*/; do
        [[ -d "$d" && "$d" != "./miaplpy*/" ]] || continue
        miaplpy_dirs+=("$d")
    done
    if [[ ${#miaplpy_dirs[@]} -eq 0 ]]; then
        echo "Error: No miaplpy* directory found in current directory." >&2
        exit 1
    fi
    if [[ ${#miaplpy_dirs[@]} -eq 1 ]]; then
        echo "${miaplpy_dirs[0]%/}/inverted/PATCHES"
        return
    fi
    local best_patches=""
    local best_ts=0
    for d in "${miaplpy_dirs[@]}"; do
        d="${d%/}"
        local patches="${d}/inverted/PATCHES"
        [[ -d "$patches" ]] || continue
        local newest
        newest=$(find_newest_flag_in_patches "$patches")
        [[ -n "$newest" ]] || continue
        local t
        t=$(stat -c %Y "$newest" 2>/dev/null || stat -f %m "$newest" 2>/dev/null) || continue
        if [[ -n "$t" && "$t" -gt "$best_ts" ]]; then
            best_ts=$t
            best_patches=$patches
        fi
    done
    if [[ -z "$best_patches" ]]; then
        echo "Error: No inverted/PATCHES with flag.npy found under any miaplpy* directory." >&2
        exit 1
    fi
    echo "$best_patches"
}

PATCHES_DIR=""
if [[ -n "$PATCHES_PATH" ]]; then
    if [[ -d "$PATCHES_PATH" ]]; then
        if [[ -d "${PATCHES_PATH}/inverted/PATCHES" ]]; then
            PATCHES_DIR="${PATCHES_PATH}/inverted/PATCHES"
        elif [[ "$PATCHES_PATH" == *"PATCHES" ]]; then
            PATCHES_DIR="$PATCHES_PATH"
        else
            PATCHES_DIR="${PATCHES_PATH}/inverted/PATCHES"
        fi
    else
        PATCHES_DIR="$PATCHES_PATH"
    fi
    if [[ ! -d "$PATCHES_DIR" ]]; then
        echo "Error: PATCHES directory does not exist: $PATCHES_DIR" >&2
        exit 1
    fi
else
    PATCHES_DIR=$(pick_best_miaplpy_dir)
fi

# MiaplPy dir name (e.g. miaplpy_201410_202603): parent of parent of PATCHES_DIR when it matches miaplpy*
MIAPLPY_NAME=$(basename "$(dirname "$(dirname "$PATCHES_DIR")")")
if [[ -z "$MIAPLPY_NAME" || "$MIAPLPY_NAME" != miaplpy* ]]; then
    MIAPLPY_NAME="$PATCHES_DIR"
fi

# Classify each PATCH_* directory: completed (flag.npy), started (files but no flag.npy), empty
total=0
completed=0
started=0
empty=0
shopt -s nullglob
for patch_dir in "$PATCHES_DIR"/PATCH_*; do
    [[ -d "$patch_dir" ]] || continue
    (( total++ )) || true
    if [[ -f "${patch_dir}/flag.npy" ]]; then
        (( completed++ )) || true
    elif [[ -n "$(ls -A "$patch_dir" 2>/dev/null)" ]]; then
        (( started++ )) || true
    else
        (( empty++ )) || true
    fi
done
shopt -u nullglob

echo "PATCHES directory: ${PATCHES_DIR}"
echo "Total PATCH_ dirs: $total"
echo "  complete (flag.npy):       $completed"
echo "  not completed (empty dirs): $empty"

if [[ "$LIST_FLAG" == true ]]; then
    echo ""
    echo "Completed patches (flag.npy with modification date):"
    find "$PATCHES_DIR" -maxdepth 2 -name 'flag.npy' -type f 2>/dev/null | sort | while read -r f; do
        [[ -z "$f" ]] && continue
        ls -l "$f" 2>/dev/null || echo "  $f"
    done
fi
