# horzvert_timeseries_utils.sh
# Sourced by minsar/bin/horzvert_timeseries.bash (not executed standalone).
#
# Map a resolved geo_*.he5 path to its sibling radar-coded S1*.he5 when present.
# Horzvert must re-reference and geocode from radar LOS; geo-only inputs without
# a sibling are rejected.

hv_he5_radar_los_path() {
    local f="$1"
    local dir base radar

    [[ -z "$f" ]] && {
        echo "hv_he5_radar_los_path: empty path" >&2
        return 1
    }
    dir=$(dirname "$f")
    base=$(basename "$f")

    if [[ "$base" == geo_* ]]; then
        radar="${dir}/${base#geo_}"
        if [[ -f "$radar" ]]; then
            echo "$radar"
            return 0
        fi
        echo "hv_he5_radar_los_path: geo HE5 has no sibling radar file: $f (expected $radar)" >&2
        return 1
    fi

    echo "$f"
    return 0
}

# If directory contains both a short-name MiaplPy HE5 (…_YYYYMMDD_YYYYMMDD_<dataset>.he5) and a
# long-name variant (…_YYYYMMDD_YYYYMMDD_N…E…_…_<dataset>.he5), reference_point_hdfeos5.bash only
# updates the resolved path; the corner-suffix copy stays stale. When the short form matches the
# dataset suffix of the long form, replace the long file by moving the updated short file into
# place (same basename as the long-form file).
hv_promote_miaplpy_short_he5_to_corner_filename() {
    local f dir base prefix suffix c n_matches picked longpath

    f="$1"
    [[ -n "$f" ]] || {
        echo "hv_promote_miaplpy_short_he5_to_corner_filename: empty path" >&2
        return 1
    }
    [[ -f "$f" ]] || {
        echo "hv_promote_miaplpy_short_he5_to_corner_filename: not a file: $f" >&2
        return 1
    }

    dir=$(dirname "$f")
    base=$(basename "$f" .he5)

    # Already using corner-in-name form (e.g. …_20180104_N1314E12362_…)
    if [[ "$base" =~ miaplpy_[0-9]{8}_[0-9]{8}_N[0-9]+[NSEW] ]]; then
        echo "$f"
        return 0
    fi

    # Short form only: two miaplpy dates then one dataset token (no bbox segment)
    if [[ ! "$base" =~ ^(S1_[^_]+_[^_]+_miaplpy_[0-9]{8}_[0-9]{8})_(filt.*DS|filtSingDS)$ ]]; then
        echo "$f"
        return 0
    fi

    prefix="${BASH_REMATCH[1]}"
    suffix="${BASH_REMATCH[2]}"

    if [[ "$base" != "${prefix}_${suffix}" ]]; then
        echo "$f"
        return 0
    fi

    n_matches=0
    picked=""
    for c in "$dir/${prefix}_N"*"_${suffix}.he5"; do
        [[ -f "$c" ]] || continue
        n_matches=$((n_matches + 1))
        picked="$c"
    done

    if [[ $n_matches -eq 0 ]]; then
        echo "$f"
        return 0
    fi

    if [[ $n_matches -gt 1 ]]; then
        echo "hv_promote_miaplpy_short_he5_to_corner_filename: warning: ${n_matches} matches for ${prefix}_N*_${suffix}.he5; using $(basename "$picked")" >&2
    fi

    longpath="$picked"
    if [[ "$(realpath "$f" 2>/dev/null || echo "$f")" == "$(realpath "$longpath" 2>/dev/null || echo "$longpath")" ]]; then
        echo "$f"
        return 0
    fi

    echo "hv_promote_miaplpy_short_he5_to_corner_filename: moving updated $(basename "$f") -> $(basename "$longpath")" >&2
    rm -f "$longpath"
    if ! mv "$f" "$longpath"; then
        echo "hv_promote_miaplpy_short_he5_to_corner_filename: mv failed: $f -> $longpath" >&2
        return 1
    fi
    echo "$longpath"
    return 0
}
