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

# Move newer short HE5 onto long corner-suffix path when save_hdfeos5.py wrote a short name.
_hv_promote_merge_newer_short_onto_long() {
    local f="$1" short_sibling="$2"
    if [[ -f "$short_sibling" && "$short_sibling" -nt "$f" ]]; then
        echo "hv_promote_short_he5_to_corner_filename: moving updated $(basename "$short_sibling") -> $(basename "$f")" >&2
        rm -f "$f"
        if ! mv "$short_sibling" "$f"; then
            echo "hv_promote_short_he5_to_corner_filename: mv failed: $short_sibling -> $f" >&2
            return 1
        fi
    fi
    echo "$f"
    return 0
}

# If directory contains both a short-name HE5 and a long-name variant with corner suffix,
# reference_point_hdfeos5.bash + save_hdfeos5.py often update only the short basename
# (metadata + --update --suffix; corner segments are not in the output name). Unify by
# moving the updated short file onto the long corner-suffix path when they are siblings.
# Handles MiaplPy (…_miaplpy_…_filt*DS) and MintPy (…_mintpy_… with no dataset suffix).
hv_promote_short_he5_to_corner_filename() {
    local f dir base prefix suffix c n_matches picked longpath
    local long_prefix long_suffix short_sibling mintpy_prefix

    f="$1"
    [[ -n "$f" ]] || {
        echo "hv_promote_short_he5_to_corner_filename: empty path" >&2
        return 1
    }
    [[ -f "$f" ]] || {
        echo "hv_promote_short_he5_to_corner_filename: not a file: $f" >&2
        return 1
    }

    dir=$(dirname "$f")
    base=$(basename "$f" .he5)

    # --- MiaplPy: long form with corner suffix + optional filt*DS suffix ---
    long_prefix=""
    long_suffix=""
    if [[ "$base" =~ ^(S1_[^_]+_[^_]+_miaplpy_[0-9]{8}_[0-9]{8})_N[^_]+_N[^_]+_N[^_]+_N[^_]+_(filt.*DS|filtSingDS)$ ]]; then
        long_prefix="${BASH_REMATCH[1]}"
        long_suffix="${BASH_REMATCH[2]}"
    elif [[ "$base" =~ ^(S1_[^_]+_[^_]+_miaplpy_[0-9]{8}_XXXXXXXX)_N[^_]+_N[^_]+_N[^_]+_N[^_]+_(filt.*DS|filtSingDS)$ ]]; then
        long_prefix="${BASH_REMATCH[1]}"
        long_suffix="${BASH_REMATCH[2]}"
    fi
    if [[ -n "$long_prefix" && -n "$long_suffix" ]]; then
        short_sibling="${dir}/${long_prefix}_${long_suffix}.he5"
        _hv_promote_merge_newer_short_onto_long "$f" "$short_sibling"
        return $?
    fi

    # --- MintPy: long form with corner suffix (no filt*DS token) ---
    mintpy_prefix=""
    if [[ "$base" =~ ^(S1_[^_]+_[^_]+_mintpy_[0-9]{8})_(XXXXXXXX)_N[^_]+_N[^_]+_N[^_]+_N[^_]+$ ]]; then
        mintpy_prefix="${BASH_REMATCH[1]}_${BASH_REMATCH[2]}"
    elif [[ "$base" =~ ^(S1_[^_]+_[^_]+_mintpy_[0-9]{8}_[0-9]{8})_N[^_]+_N[^_]+_N[^_]+_N[^_]+$ ]]; then
        mintpy_prefix="${BASH_REMATCH[1]}"
    fi
    if [[ -n "$mintpy_prefix" ]]; then
        for short_sibling in \
            "${dir}/${mintpy_prefix}.he5" \
            "${dir}/${mintpy_prefix}_XXXXXXXX.he5"; do
            if [[ -f "$short_sibling" && "$short_sibling" -nt "$f" ]]; then
                _hv_promote_merge_newer_short_onto_long "$f" "$short_sibling"
                return $?
            fi
        done
        echo "$f"
        return 0
    fi

    # Corner-suffix basename without a matching promote rule: leave as-is.
    if [[ "$base" =~ _miaplpy_[0-9]{8}_[0-9]{8}_N ]] || [[ "$base" =~ _miaplpy_[0-9]{8}_XXXXXXXX_N ]]; then
        echo "$f"
        return 0
    fi
    if [[ "$base" =~ _mintpy_[0-9]{8}_(XXXXXXXX|[0-9]{8})_N ]]; then
        echo "$f"
        return 0
    fi

    # --- MiaplPy: short form only ---
    prefix=""
    suffix=""
    if [[ "$base" =~ ^(S1_[^_]+_[^_]+_miaplpy_[0-9]{8}_[0-9]{8})_(filt.*DS|filtSingDS)$ ]]; then
        prefix="${BASH_REMATCH[1]}"
        suffix="${BASH_REMATCH[2]}"
    elif [[ "$base" =~ ^(S1_[^_]+_[^_]+_miaplpy_[0-9]{8}_XXXXXXXX)_(filt.*DS|filtSingDS)$ ]]; then
        prefix="${BASH_REMATCH[1]}"
        suffix="${BASH_REMATCH[2]}"
    fi
    if [[ -n "$prefix" && -n "$suffix" && "$base" == "${prefix}_${suffix}" ]]; then
        n_matches=0
        picked=""
        for c in "$dir/${prefix}_N"*"_${suffix}.he5"; do
            [[ -f "$c" ]] || continue
            n_matches=$((n_matches + 1))
            picked="$c"
        done
        if [[ $n_matches -gt 0 ]]; then
            if [[ $n_matches -gt 1 ]]; then
                echo "hv_promote_short_he5_to_corner_filename: warning: ${n_matches} matches for ${prefix}_N*_${suffix}.he5; using $(basename "$picked")" >&2
            fi
            longpath="$picked"
            if [[ "$(realpath "$f" 2>/dev/null || echo "$f")" != "$(realpath "$longpath" 2>/dev/null || echo "$longpath")" ]]; then
                echo "hv_promote_short_he5_to_corner_filename: moving updated $(basename "$f") -> $(basename "$longpath")" >&2
                rm -f "$longpath"
                if ! mv "$f" "$longpath"; then
                    echo "hv_promote_short_he5_to_corner_filename: mv failed: $f -> $longpath" >&2
                    return 1
                fi
                echo "$longpath"
                return 0
            fi
        fi
    fi

    # --- MintPy: short form only (no corner segments) ---
    mintpy_prefix=""
    if [[ "$base" =~ ^(S1_[^_]+_[^_]+_mintpy_[0-9]{8})_(XXXXXXXX)$ ]]; then
        mintpy_prefix="${BASH_REMATCH[1]}_${BASH_REMATCH[2]}"
    elif [[ "$base" =~ ^(S1_[^_]+_[^_]+_mintpy_[0-9]{8})_([0-9]{8})$ ]]; then
        mintpy_prefix="${BASH_REMATCH[1]}_${BASH_REMATCH[2]}"
    elif [[ "$base" =~ ^(S1_[^_]+_[^_]+_mintpy_[0-9]{8}_XXXXXXXX)_XXXXXXXX$ ]]; then
        mintpy_prefix="${BASH_REMATCH[1]}"
    fi
    if [[ -n "$mintpy_prefix" && ( "$base" == "$mintpy_prefix" || "$base" == "${mintpy_prefix}_XXXXXXXX" ) ]]; then
        n_matches=0
        picked=""
        for c in "$dir/${mintpy_prefix}_N"*.he5; do
            [[ -f "$c" ]] || continue
            n_matches=$((n_matches + 1))
            picked="$c"
        done
        if [[ $n_matches -gt 0 ]]; then
            if [[ $n_matches -gt 1 ]]; then
                echo "hv_promote_short_he5_to_corner_filename: warning: ${n_matches} matches for ${mintpy_prefix}_N*.he5; using $(basename "$picked")" >&2
            fi
            longpath="$picked"
            if [[ "$(realpath "$f" 2>/dev/null || echo "$f")" != "$(realpath "$longpath" 2>/dev/null || echo "$longpath")" ]]; then
                echo "hv_promote_short_he5_to_corner_filename: moving updated $(basename "$f") -> $(basename "$longpath")" >&2
                rm -f "$longpath"
                if ! mv "$f" "$longpath"; then
                    echo "hv_promote_short_he5_to_corner_filename: mv failed: $f -> $longpath" >&2
                    return 1
                fi
                echo "$longpath"
                return 0
            fi
        fi
    fi

    echo "$f"
    return 0
}

# Backward-compatible alias (MiaplPy-only name retained for callers and tests).
hv_promote_miaplpy_short_he5_to_corner_filename() {
    hv_promote_short_he5_to_corner_filename "$@"
}
