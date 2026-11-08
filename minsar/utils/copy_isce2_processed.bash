#!/usr/bin/env bash
# Copy the ISCE2 stack directories MintPy and MiaplPy read.
# Missing MintPy directories (merged/interferograms, ion) are skipped.
set -eo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

print_help() {
    cat <<EOF
usage: $SCRIPT_NAME [--dry-run] [--with-offsets] SRC DST

Copy ISCE2 directories needed to run MintPy and MiaplPy from SRC to DST.
SRC and DST may be a project name under \$SCRATCHDIR (or \$SCRATCH) or a path.
Before copying, prints each item size in GB and the total.
Directories that are not in the stack are skipped. MintPy inputs that
--no-mintpy never creates (merged/interferograms, ion) are optional.

Directories copied when present:
    reference
    baselines
    stack
    geom_reference
    merged/SLC
    merged/geom_reference
    coreg_secondarys
    merged/interferograms
    ion
    Igrams

Also copied when present:
    *.template and reference_date_isce.txt in the project root
    SLC files that merged/reference VRTs still point at

Not copied:
    SLC/ (download tree) secondarys DEM coarse_interferograms interferograms
    run_files configs mintpy* miaplpy* orbits ESD misreg
    coreg_secondarys azimuth_*.off and range_*.off (and overlap/)

Options:
    --dry-run        Print the GB sizes and total, then exit
    --with-offsets   Also copy coregistration azimuth_*.off and range_*.off
    -h, --help       Show this help

Examples:
    $SCRIPT_NAME LengaiSenD152 LengaiSenD152_sav
    $SCRIPT_NAME --dry-run LengaiSenD152 LengaiSenD152_sav
    $SCRIPT_NAME --with-offsets /path/LengaiSenD152 /path/LengaiSenD152_sav
EOF
}

DRY_RUN=0
WITH_OFFSETS=0
POSITIONAL=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            print_help
            exit 0
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --with-offsets)
            WITH_OFFSETS=1
            shift
            ;;
        -?*|--*)
            echo "Error: Unknown option: $1" >&2
            echo "Use $SCRIPT_NAME --help for available options" >&2
            exit 1
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
    esac
done

if [[ ${#POSITIONAL[@]} -ne 2 ]]; then
    echo "Error: expected SRC and DST." >&2
    echo "Use $SCRIPT_NAME --help for available options" >&2
    exit 1
fi

resolve_dir() {
    local arg="$1" role="$2"
    local scratch=""
    if [[ "$arg" == /* ]]; then
        if [[ ! -d "$arg" ]]; then
            echo "Error: $role is not a directory: $arg" >&2
            return 1
        fi
        (cd "$arg" && pwd)
        return 0
    fi
    if [[ -d "$arg" ]]; then
        (cd "$arg" && pwd)
        return 0
    fi
    if [[ -n "${SCRATCHDIR:-}" ]]; then
        scratch="$SCRATCHDIR"
    elif [[ -n "${SCRATCH:-}" ]]; then
        scratch="$SCRATCH"
    fi
    if [[ -n "$scratch" && -d "$scratch/$arg" ]]; then
        (cd "$scratch/$arg" && pwd)
        return 0
    fi
    echo "Error: cannot find $role '$arg' (not a path, and not under \$SCRATCHDIR or \$SCRATCH)." >&2
    return 1
}

SRC="$(resolve_dir "${POSITIONAL[0]}" "SRC")"
if [[ -d "${POSITIONAL[1]}" ]]; then
    DST="$(cd "${POSITIONAL[1]}" && pwd)"
elif [[ "${POSITIONAL[1]}" == /* ]]; then
    DST="${POSITIONAL[1]}"
else
    scratch_parent=""
    if [[ -n "${SCRATCHDIR:-}" ]]; then
        scratch_parent="$SCRATCHDIR"
    elif [[ -n "${SCRATCH:-}" ]]; then
        scratch_parent="$SCRATCH"
    else
        scratch_parent="$(dirname "$SRC")"
    fi
    DST="${scratch_parent%/}/${POSITIONAL[1]}"
fi

if [[ "$SRC" == "$DST" ]]; then
    echo "Error: SRC and DST are the same directory: $SRC" >&2
    exit 1
fi
case "$DST" in
    "$SRC"/*)
        echo "Error: DST is inside SRC: $DST" >&2
        exit 1
        ;;
esac

# Tops and stripmap inputs. MintPy-only entries are skipped when absent.
COPY_DIRS=(
    reference
    baselines
    stack
    geom_reference
    merged/SLC
    merged/geom_reference
    coreg_secondarys
    merged/interferograms
    ion
    Igrams
)

echo "SRC  $SRC"
echo "DST  $DST"
if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "dry-run"
fi
echo "Measuring sizes..."

plan_list="$(mktemp)"
trap 'rm -f "$plan_list"' EXIT
python3 - "$SRC" "$WITH_OFFSETS" "${COPY_DIRS[@]}" >"$plan_list" <<'PY'
import os
import re
import sys

src = os.path.abspath(sys.argv[1])
with_offsets = sys.argv[2] == "1"
candidates = sys.argv[3:]
pat = re.compile(r"<SourceFilename[^>]*>\s*([^<]+?)\s*</SourceFilename>")
offset_re = re.compile(r"(?:azimuth|range)_\d+\.off(?:\.|$)")

def skip_name(rel):
    base = os.path.basename(rel)
    if not with_offsets and offset_re.search(base):
        return True
    parts = rel.split("/")
    if not with_offsets and "overlap" in parts:
        return True
    return False

def file_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0

def covered(rel, dirs):
    for d in dirs:
        if rel == d or rel.startswith(d + "/"):
            return True
    return False

present = []
pending_vrts = []
for rel in candidates:
    root = os.path.join(src, rel)
    if not os.path.isdir(root):
        print(f"SKIP\t{rel}")
        continue
    exclude = (not with_offsets) and rel == "coreg_secondarys"
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        if exclude:
            dirnames[:] = [n for n in dirnames if n != "overlap"]
        for name in filenames:
            if exclude and offset_re.search(name):
                continue
            path = os.path.join(dirpath, name)
            total += file_size(path)
            if name.endswith(".vrt"):
                pending_vrts.append(path)
    present.append(rel)
    print(f"DIR\t{total}\t{rel}")

for name in sorted(os.listdir(src)):
    path = os.path.join(src, name)
    if name == "reference_date_isce.txt" or (name.endswith(".template") and os.path.isfile(path)):
        print(f"FILE\t{file_size(path)}\t{name}")

seen = set()
for vrt in pending_vrts:
    try:
        text = open(vrt, "r", errors="replace").read()
    except OSError:
        continue
    for raw in pat.findall(text):
        raw = raw.strip()
        if not raw or raw.lower() == "none":
            continue
        if os.path.isabs(raw):
            target = os.path.normpath(raw)
        else:
            target = os.path.normpath(os.path.join(os.path.dirname(vrt), raw))
        try:
            extra = os.path.relpath(target, src)
        except ValueError:
            continue
        if extra.startswith("..") or extra == ".":
            continue
        if skip_name(extra) or covered(extra, present) or extra in seen:
            continue
        if os.path.isfile(target):
            seen.add(extra)
            print(f"FILE\t{file_size(target)}\t{extra}")
PY

fmt_gb() {
    awk -v n="$1" 'BEGIN {
        g = n / 1024 / 1024 / 1024
        if (g >= 0.01)
            printf "%.2f GB\n", g
        else
            printf "%.4f GB\n", g
    }'
}

echo
echo "Will copy:"
total_bytes=0
dir_count=0
while IFS=$'\t' read -r kind nbytes rel; do
    [[ -n "${kind:-}" ]] || continue
    if [[ "$kind" == "SKIP" ]]; then
        echo "  skip  $nbytes  (not present)"
        continue
    fi
    gb="$(fmt_gb "$nbytes")"
    printf '  %12s  %s\n' "$gb" "$rel"
    total_bytes=$((total_bytes + nbytes))
    if [[ "$kind" == "DIR" ]]; then
        dir_count=$((dir_count + 1))
    fi
done <"$plan_list"
echo "  ------------------------------------------------"
printf '  %12s  %s\n' "$(fmt_gb "$total_bytes")" "total"
echo

if [[ "$dir_count" -eq 0 ]]; then
    echo "Error: no ISCE2 MintPy/MiaplPy directories found in $SRC" >&2
    exit 1
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Dry-run only; nothing was written."
    exit 0
fi

echo "Copying..."
while IFS=$'\t' read -r kind nbytes rel; do
    [[ "$kind" == "DIR" || "$kind" == "FILE" ]] || continue
    if [[ "$kind" == "DIR" ]]; then
        mkdir -p "$DST/$rel"
        if [[ "$rel" == "coreg_secondarys" && "$WITH_OFFSETS" -eq 0 ]]; then
            rsync -a \
                --exclude='azimuth_*.off' \
                --exclude='azimuth_*.off.*' \
                --exclude='range_*.off' \
                --exclude='range_*.off.*' \
                --exclude='overlap/' \
                "$SRC/$rel/" "$DST/$rel/"
        else
            rsync -a "$SRC/$rel/" "$DST/$rel/"
        fi
    else
        mkdir -p "$DST/$(dirname "$rel")"
        rsync -a "$SRC/$rel" "$DST/$rel"
    fi
done <"$plan_list"

echo "Done. Copied ${dir_count} directories into $DST"
