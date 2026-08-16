# horzvert_timeseries_utils.sh
# Sourced by minsar/bin/horzvert_timeseries.bash and reference_point_hdfeos5.bash.
#
# Map a resolved geo_*.he5 path to its sibling radar-coded S1*.he5 when present.
# Horzvert must re-reference and geocode from radar LOS; geo-only inputs without
# a sibling are rejected.

# User-facing path: $SCRATCHDIR/relative/... when under SCRATCHDIR, else absolute.
hv_scratchdir_display_path() {
    local path="$1"
    local abs_dir scratch_abs rel

    [[ -z "$path" ]] && return 0
    abs_dir=$(realpath "$path" 2>/dev/null || echo "$path")
    abs_dir="${abs_dir%/}/"

    if [[ -n "${SCRATCHDIR:-}" ]]; then
        scratch_abs=$(realpath "$SCRATCHDIR" 2>/dev/null || (cd "$SCRATCHDIR" && pwd))
        scratch_abs="${scratch_abs%/}/"
        if [[ "$abs_dir" == "$scratch_abs"* ]]; then
            rel="${abs_dir#$scratch_abs}"
            printf '$SCRATCHDIR/%s' "$rel"
            return 0
        fi
    fi
    printf '%s' "$abs_dir"
}

# Append one run_workflow-style line to log in the given directory.
hv_append_dir_log() {
    local dir="$1"
    local line="$2"
    local abs_dir

    [[ -z "$line" || -z "$dir" ]] && return 0
    abs_dir=$(realpath "$dir" 2>/dev/null || echo "$dir")
    [[ -d "$abs_dir" ]] && echo "$line" >> "${abs_dir}/log"
}

# Print "In $SCRATCHDIR/..." then "Running: ..." and log to that directory's log.
hv_announce_command() {
    local work_dir="$1"
    local cmd_line="$2"
    local ts

    [[ -z "$work_dir" || -z "$cmd_line" ]] && return 0
    ts=$(date +"%Y%m%d:%H-%M")
    echo "In $(hv_scratchdir_display_path "$work_dir")"
    echo "Running: $cmd_line"
    hv_append_dir_log "$work_dir" "${ts} + ${cmd_line}"
}

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

# Print False | login_node | compute_node (via minsar.utils.system_utils).
hv_are_we_on_slurm_system() {
    python3 -c 'from minsar.utils.system_utils import are_we_on_slurm_system; r = are_we_on_slurm_system(); print(r if r else "False")'
}

# True when we should wrap a script-style run file as one SLURM .job (HPC login, not already in a job).
hv_should_use_slurm_jobfile() {
    if declare -F minsar_should_use_slurm_jobfile >/dev/null 2>&1; then
        minsar_should_use_slurm_jobfile
        return
    fi
    local status
    status=$(hv_are_we_on_slurm_system 2>/dev/null || echo "False")
    [[ "$status" == "login_node" && -z "${SLURM_JOB_ID:-}" ]]
}

# True on the Jetstream / insarmaps host that serves HDF5EOS (do not upload to self).
hv_is_on_data_server() {
    local host_s host_f remote
    [[ "${PLATFORM_NAME:-}" == "jetstream" ]] && return 0
    [[ "${HOSTNAME:-}" == "perfectly-elegant-tapir" ]] && return 0
    [[ "${HOSTNAME:-}" =~ ^insarmaps[123]$ ]] && return 0
    host_s=$(hostname -s 2>/dev/null || hostname)
    host_f=$(hostname -f 2>/dev/null || hostname)
    [[ "$host_s" == "perfectly-elegant-tapir" ]] && return 0
    remote="${REMOTEHOST_DATA:-}"
    if [[ -n "$remote" ]]; then
        [[ "$host_s" == "$remote" || "$host_f" == "$remote" ]] && return 0
    fi
    return 1
}

# Rewrite insarmaps.log start lat/lon to the vert product and disable flyToDatasetCenter.
hv_normalize_insarmaps_coordinates() {
    local log_file="$1"
    local vert_lat vert_lon

    [[ -f "$log_file" ]] || return 0
    echo "Normalizing coordinates in insarmaps.log to use vert coordinates..."
    vert_lat=$(grep "vert" "$log_file" | head -n 1 | cut -d/ -f5)
    vert_lon=$(grep "vert" "$log_file" | head -n 1 | cut -d/ -f6)
    echo "Using vert coordinates: $vert_lat, $vert_lon"
    sed -i.bak -E "s|(/start/)[^/]+/[^/]+/|\1${vert_lat}/${vert_lon}/|" "$log_file"
    sed -i.bak -E "s|flyToDatasetCenter=true|flyToDatasetCenter=false|g" "$log_file"
    rm -f "${log_file}.bak"
    echo "Updated all coordinates in insarmaps.log and disabled flyToDatasetCenter"
}

hv_data_files_contains() {
    local data_files="$1"
    local path="$2"
    [[ -f "$data_files" ]] && grep -qxF "$path" "$data_files"
}

# Geometry file for save_qgis.py (-g): geo/vert/horz HDFEOS use self; radar uses inputs/geometryRadar.h5.
hv_geom_for_save_qgis_he5() {
    local he5="$1"
    local dir base

    [[ -n "$he5" && -f "$he5" ]] || return 1
    dir=$(dirname "$he5")
    base=$(basename "$he5")

    if [[ "$base" == geo_* || "$base" == *vert* || "$base" == *horz* ]]; then
        echo "$he5"
        return 0
    fi
    if [[ -f "${dir}/inputs/geometryRadar.h5" ]]; then
        echo "${dir}/inputs/geometryRadar.h5"
        return 0
    fi
    echo "$he5"
    return 0
}

# Ensure MinSAR patched save_qgis (HDFEOS .he5) is linked into MintPy (install_minsar.bash step).
hv_ensure_minsar_save_qgis_links() {
    local mh="${MINSAR_HOME:-}"
    local mod cli mintpy_src

    if [[ -z "$mh" ]]; then
        mh="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    fi
    mod="${mh}/additions/mintpy/save_qgis.py"
    cli="${mh}/additions/mintpy/cli/save_qgis.py"
    mintpy_src="${mh}/tools/MintPy/src/mintpy"
    [[ -f "$mod" && -f "$cli" && -d "${mintpy_src}/cli" ]] || return 1
    ln -sf "$mod" "${mintpy_src}/save_qgis.py"
    ln -sf "$cli" "${mintpy_src}/cli/save_qgis.py"
    return 0
}

# save_qgis.py wrapper: MinSAR HDFEOS-aware save_qgis; always pass -g.
hv_save_qgis_he5() {
    local he5="$1"
    local geom

    [[ -n "$he5" && -f "$he5" ]] || {
        echo "hv_save_qgis_he5: missing .he5: $he5" >&2
        return 1
    }
    geom=$(hv_geom_for_save_qgis_he5 "$he5") || return 1
    if ! hv_ensure_minsar_save_qgis_links; then
        echo "hv_save_qgis_he5: MinSAR save_qgis additions not found (MINSAR_HOME=$MINSAR_HOME)" >&2
        return 1
    fi
    save_qgis.py "$he5" -g "$geom"
}

hv_append_gpkg_for_he5() {
    local data_files="$1"
    local he5_path="$2"
    local gpkg_path="${he5_path%.he5}.gpkg"
    [[ -z "$he5_path" || "$he5_path" != *.he5 ]] && return 0
    if [[ ! -f "$he5_path" ]]; then
        echo "Error: --save-qgis expected .he5 missing: $he5_path" >&2
        return 1
    fi
    if [[ ! -f "$gpkg_path" ]]; then
        echo "Error: --save-qgis expected GeoPackage missing: $gpkg_path" >&2
        return 1
    fi
    hv_data_files_contains "$data_files" "$he5_path" || echo "$he5_path" >> "$data_files"
    hv_data_files_contains "$data_files" "$gpkg_path" || echo "$gpkg_path" >> "$data_files"
}

# Upload product dir to Jetstream unless this host is the data server.
hv_maybe_upload_horzvert_dir() {
    local product_dir="$1"
    if hv_is_on_data_server; then
        echo "Skipping Jetstream upload (on data server)"
        return 0
    fi
    echo ""
    echo "##############################################"
    echo "Uploading $product_dir to Jetstream"
    upload_horzvert.py "$product_dir"
}

# Write data_files.txt, InsarMaps HTML/urls, download commands; optionally upload.
# Args: OUTDIR LAT_STEP LON_STEP RADAR1 RADAR2 INGEST_INSARMAPS INGEST_LOS SAVE_QGIS DO_UPLOAD HORZVERT_REL
hv_finish_horzvert_run() {
    local outdir="$1"
    local lat_step="$2"
    local lon_step="$3"
    local radar1="$4"
    local radar2="$5"
    local ingest_insarmaps="$6"
    local ingest_los="$7"
    local save_qgis="$8"
    local do_upload="$9"
    local horzvert_rel="${10}"
    local data_files vert horz geo1 geo2 html_source lib_dir

    outdir=$(realpath "$outdir")
    if [[ -n "${SCRATCHDIR:-}" && -d "$SCRATCHDIR" ]]; then
        cd "$SCRATCHDIR"
    fi

    vert="${VERT:-}"
    horz="${HORZ:-}"
    if [[ -z "$vert" || ! -f "$vert" ]]; then
        vert=$(ls -t "$outdir"/*vert*.he5 2>/dev/null | head -1 || true)
    fi
    if [[ -z "$horz" || ! -f "$horz" ]]; then
        horz=$(ls -t "$outdir"/*horz*.he5 2>/dev/null | head -1 || true)
    fi
    if [[ -z "$vert" || -z "$horz" || ! -f "$vert" || ! -f "$horz" ]]; then
        echo "Error: missing *vert*/*horz*.he5 under $outdir" >&2
        return 1
    fi
    vert=$(realpath "$vert")
    horz=$(realpath "$horz")
    if ! radar1=$(hv_promote_short_he5_to_corner_filename "$(realpath "$radar1")"); then return 1; fi
    if ! radar2=$(hv_promote_short_he5_to_corner_filename "$(realpath "$radar2")"); then return 1; fi
    radar1=$(realpath "$radar1")
    radar2=$(realpath "$radar2")
    geo1="$(dirname "$radar1")/geo_$(basename "$radar1")"
    geo2="$(dirname "$radar2")/geo_$(basename "$radar2")"

    data_files="$outdir/data_files.txt"
    {
        echo "# geocode-lalo-step $lat_step $lon_step"
        echo "$vert"
        echo "$horz"
        echo "$radar1"
        if [[ "$radar1" != "$radar2" ]]; then
            echo "$radar2"
        fi
        [[ -f "$geo1" ]] && echo "$geo1"
        if [[ "$geo1" != "$geo2" && -f "$geo2" ]]; then
            echo "$geo2"
        fi
    } > "$data_files"
    if [[ "$save_qgis" != "off" && -n "$save_qgis" ]]; then
        hv_append_gpkg_for_he5 "$data_files" "$vert" || return 1
        hv_append_gpkg_for_he5 "$data_files" "$horz" || return 1
        hv_append_gpkg_for_he5 "$data_files" "$geo1" || return 1
        hv_append_gpkg_for_he5 "$data_files" "$geo2" || return 1
        if [[ "$save_qgis" == "all" ]]; then
            hv_append_gpkg_for_he5 "$data_files" "$radar1" || return 1
            hv_append_gpkg_for_he5 "$data_files" "$radar2" || return 1
        fi
    fi

    if [[ "$ingest_insarmaps" == "1" ]]; then
        hv_normalize_insarmaps_coordinates "$outdir/insarmaps.log"
        echo ""
        echo "##############################################"
        echo "Write InsarMaps HTML / urls / download commands"
        lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        html_source="${lib_dir}/../html"
        cp "$html_source/overlay.html" "$outdir/"
        cp "$outdir/overlay.html" "$outdir/index.html"
        write_insarmaps_framepage_urls.py "${horzvert_rel:-$outdir}" --outdir "${horzvert_rel:-$outdir}"
        create_data_download_commands.py "$data_files"
        if [[ -f "$outdir/urls.log" ]]; then
            echo "insarmaps frames created:"
            cat "$outdir/urls.log"
        fi
    elif [[ "$save_qgis" != "off" && -n "$save_qgis" ]]; then
        create_data_download_commands.py "$data_files"
    fi

    if [[ "$do_upload" == "1" ]]; then
        hv_maybe_upload_horzvert_dir "${horzvert_rel:-$outdir}"
    fi
}

# Path for run_horzvert2timeseries: under $SCRATCHDIR → relative; else absolute.
hv_runfile_path() {
    local path="$1"
    local abs scratch_abs

    [[ -z "$path" ]] && return 0
    abs=$(realpath "$path" 2>/dev/null || echo "$path")
    if [[ -n "${SCRATCHDIR:-}" ]]; then
        scratch_abs=$(realpath "$SCRATCHDIR" 2>/dev/null || (cd "$SCRATCHDIR" && pwd))
        scratch_abs="${scratch_abs%/}"
        if [[ "$abs" == "$scratch_abs"/* ]]; then
            printf '%s' "${abs#$scratch_abs/}"
            return 0
        fi
    fi
    printf '%s' "$abs"
}

# mintpy/miaplpy path component from a file or directory (e.g. miaplpy_202001_202410).
hv_extract_processing_method_dir() {
    local path="$1"
    local dir
    [[ -z "$path" ]] && return 1
    dir="$([ -f "$path" ] && dirname "$path" || echo "$path")"
    echo "$dir" | tr '/' '\n' | grep -E '^(mintpy|miaplpy)(_|$)' | head -1
}

# Comparable period length for a processing-method dir name (months or days).
# Bare mintpy/miaplpy (no dates) → 0 so dated names win when picking the longer span.
hv_processing_method_dir_span() {
    local name="$1"
    local s e sm em sd ed

    if [[ "$name" =~ ^(mintpy|miaplpy)_([0-9]{6})_([0-9]{6})$ ]]; then
        s="${BASH_REMATCH[2]}"
        e="${BASH_REMATCH[3]}"
        sm=$((10#${s:0:4} * 12 + 10#${s:4:2}))
        em=$((10#${e:0:4} * 12 + 10#${e:4:2}))
        echo $((em - sm))
        return 0
    fi
    if [[ "$name" =~ ^(mintpy|miaplpy)_([0-9]{8})_([0-9]{8})$ ]]; then
        s="${BASH_REMATCH[2]}"
        e="${BASH_REMATCH[3]}"
        sd=$(date -d "${s:0:4}-${s:4:2}-${s:6:2}" +%s 2>/dev/null || true)
        ed=$(date -d "${e:0:4}-${e:4:2}-${e:6:2}" +%s 2>/dev/null || true)
        if [[ -n "$sd" && -n "$ed" ]]; then
            echo $(((ed - sd) / 86400))
            return 0
        fi
        echo $((10#$e - 10#$s))
        return 0
    fi
    echo 0
}

# Among two input paths, keep the mintpy/miaplpy dir covering the longer period.
# Example: miaplpy_202001_202412 vs miaplpy_202001_202410 → miaplpy_202001_202412
hv_longest_processing_method_dir() {
    local path1="$1"
    local path2="$2"
    local d1 d2 s1 s2

    d1=$(hv_extract_processing_method_dir "$path1" || true)
    d2=$(hv_extract_processing_method_dir "$path2" || true)
    [[ -z "$d1" && -z "$d2" ]] && {
        echo "mintpy"
        return 0
    }
    [[ -z "$d1" ]] && {
        echo "$d2"
        return 0
    }
    [[ -z "$d2" || "$d1" == "$d2" ]] && {
        echo "$d1"
        return 0
    }
    s1=$(hv_processing_method_dir_span "$d1")
    s2=$(hv_processing_method_dir_span "$d2")
    if ((s1 >= s2)); then
        echo "$d1"
    else
        echo "$d2"
    fi
}

# Exit 0 if radar must be geocoded (missing geo, radar newer, or posting mismatch).
need_geocode() {
    local radar="$1"
    local geo="$2"
    local lat_step="${3:-}"
    local lon_step="${4:-}"
    [[ ! -f "$geo" ]] && return 0
    [[ "$radar" -nt "$geo" ]] && return 0
    if [[ -n "$lat_step" && -n "$lon_step" ]]; then
        hv_he5_posting_matches "$geo" "$lat_step" "$lon_step" && return 1
        return 0
    fi
    return 1
}

# True when HE5 Y_STEP/X_STEP match lat/lon step (sign ignored).
hv_he5_posting_matches() {
    local he5="$1"
    local lat_step="$2"
    local lon_step="$3"
    HV_HE5="$he5" HV_LAT_STEP="$lat_step" HV_LON_STEP="$lon_step" python3 - <<'PY'
import os
import sys

from mintpy.utils import readfile

he5 = os.environ["HV_HE5"]
try:
    atr = readfile.read_attribute(he5)
    y_step = abs(float(atr["Y_STEP"]))
    x_step = abs(float(atr["X_STEP"]))
    lat_step = abs(float(os.environ["HV_LAT_STEP"]))
    lon_step = abs(float(os.environ["HV_LON_STEP"]))
except Exception:
    sys.exit(1)
sys.exit(0 if abs(y_step - lat_step) <= 1e-8 and abs(x_step - lon_step) <= 1e-8 else 1)
PY
}

# Wait for background PIDs; fail if any exited non-zero (set -e friendly).
hv_wait_pids() {
    local pid status=0
    for pid in "$@"; do
        wait "$pid" || status=1
    done
    return "$status"
}

# Run ingest_insarmaps.bash and append the same command line to scratch_log (SCRATCHDIR/log).
# Usage: hv_ingest_insarmaps_logged SCRATCH_LOG [ingest_insarmaps.bash args...]
# Call from product dir cwd so ingest writes insarmaps.log next to overlay.html.
hv_ingest_insarmaps_logged() {
    local scratch_log="$1"
    shift
    local log_cmd="ingest_insarmaps.bash" arg

    for arg in "$@"; do
        log_cmd+=" $(printf '%q' "$arg")"
    done
    if [[ -n "$scratch_log" ]]; then
        mkdir -p "$(dirname "$scratch_log")"
        echo "$(date +%Y%m%d:%H-%M) * ${log_cmd}" >> "$scratch_log"
    fi
    ingest_insarmaps.bash "$@"
}

# Write script-style run file run_horzvert2timeseries (may contain & / wait).
# Paths under $SCRATCHDIR are written relative (cwd = $SCRATCHDIR when the run file runs).
# Required: HV_RUN_FILE, HV_RADAR1, HV_RADAR2, HV_REF_LAT, HV_REF_LON, HV_OUTDIR
# Optional: HV_CACHE_HIT=0|1, HV_GEOCODE_ARGS, HV_PY_SUFFIX, HV_COMPUTE_PARALLEL=1|0,
#           HV_INGEST_PARALLEL=0|1, HV_INGEST_INSARMAPS=1|0, HV_INGEST_LOS=1|0,
#           HV_INGEST_WORKERS_OPTS (string), HV_GEOM_FILE_ARGS, HV_DATASET_OPT1, HV_DATASET_OPT2,
#           HV_SAVE_QGIS=off|geo|all  (geo: vert/horz + geo asc/desc; all: + radar asc/desc),
#           HV_UPLOAD=1|0, HV_GEOCODE_LAT_STEP, HV_GEOCODE_LON_STEP, HV_FORCE=0|1
hv_write_run_horzvert2timeseries() {
    local run_file="${HV_RUN_FILE:?}"
    local radar1="${HV_RADAR1:?}"
    local radar2="${HV_RADAR2:?}"
    local ref_lat="${HV_REF_LAT:?}"
    local ref_lon="${HV_REF_LON:?}"
    local outdir="${HV_OUTDIR:?}"
    local cache_hit="${HV_CACHE_HIT:-0}"
    local geocode_args="${HV_GEOCODE_ARGS:-}"
    local py_suffix="${HV_PY_SUFFIX:-}"
    local compute_parallel="${HV_COMPUTE_PARALLEL:-1}"
    local ingest_parallel="${HV_INGEST_PARALLEL:-0}"
    local ingest_insarmaps="${HV_INGEST_INSARMAPS:-1}"
    local ingest_los="${HV_INGEST_LOS:-1}"
    local save_qgis="${HV_SAVE_QGIS:-off}"
    local do_upload="${HV_UPLOAD:-1}"
    local lat_step="${HV_GEOCODE_LAT_STEP:-}"
    local lon_step="${HV_GEOCODE_LON_STEP:-}"
    local force="${HV_FORCE:-0}"
    local workers_opts="${HV_INGEST_WORKERS_OPTS:-}"
    local geom_args="${HV_GEOM_FILE_ARGS:-}"
    local ds1="${HV_DATASET_OPT1:-}"
    local ds2="${HV_DATASET_OPT2:-}"
    local geo1 geo2 r_radar1 r_radar2 r_geo1 r_geo2 r_outdir
    local q_radar1 q_radar2 q_geo1 q_geo2 q_outdir amp=""
    local utils_sh abs_outdir abs_radar1 abs_radar2 abs_geo1 abs_geo2 abs_scratch_log
    local q_abs_outdir q_abs_radar1 q_abs_radar2 q_abs_geo1 q_abs_geo2 q_scratch_log

    utils_sh="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/horzvert_timeseries_utils.sh"

    mkdir -p "$(dirname "$run_file")" "$outdir"
    [[ "$ingest_parallel" == "1" ]] && amp=" &"

    geo1="$(dirname "$radar1")/geo_$(basename "$radar1")"
    geo2="$(dirname "$radar2")/geo_$(basename "$radar2")"
    r_radar1=$(hv_runfile_path "$radar1")
    r_radar2=$(hv_runfile_path "$radar2")
    r_geo1=$(hv_runfile_path "$geo1")
    r_geo2=$(hv_runfile_path "$geo2")
    r_outdir=$(hv_runfile_path "$outdir")
    q_radar1=$(printf '%q' "$r_radar1")
    q_radar2=$(printf '%q' "$r_radar2")
    q_geo1=$(printf '%q' "$r_geo1")
    q_geo2=$(printf '%q' "$r_geo2")
    q_outdir=$(printf '%q' "$r_outdir")

    # Absolute paths for ingest after cd into the product dir.
    abs_outdir=$(realpath "$outdir" 2>/dev/null || echo "$outdir")
    abs_radar1=$(realpath "$radar1" 2>/dev/null || echo "$radar1")
    abs_radar2=$(realpath "$radar2" 2>/dev/null || echo "$radar2")
    abs_geo1=$(realpath "$geo1" 2>/dev/null || echo "$geo1")
    abs_geo2=$(realpath "$geo2" 2>/dev/null || echo "$geo2")
    q_abs_outdir=$(printf '%q' "$abs_outdir")
    q_abs_radar1=$(printf '%q' "$abs_radar1")
    q_abs_radar2=$(printf '%q' "$abs_radar2")
    q_abs_geo1=$(printf '%q' "$abs_geo1")
    q_abs_geo2=$(printf '%q' "$abs_geo2")
    abs_scratch_log=""
    if [[ -n "${SCRATCHDIR:-}" ]]; then
        abs_scratch_log="$(realpath "$SCRATCHDIR" 2>/dev/null || echo "$SCRATCHDIR")/log"
    fi
    q_scratch_log=$(printf '%q' "$abs_scratch_log")

    {
        echo '#!/usr/bin/env bash'
        echo 'set -euo pipefail'
        echo "source $(printf '%q' "$utils_sh")"
        if [[ -n "${SCRATCHDIR:-}" ]]; then
            echo "cd $(printf '%q' "$(realpath "$SCRATCHDIR" 2>/dev/null || echo "$SCRATCHDIR")")"
        fi
        echo ""

        if [[ "$cache_hit" != "1" ]]; then
            if [[ "$compute_parallel" == "1" ]]; then
                echo "pids=()"
                echo "reference_point_hdfeos5.bash ${q_radar1} --ref-lalo $(printf '%q' "$ref_lat") $(printf '%q' "$ref_lon") &"
                echo "pids+=(\"\$!\")"
                if [[ "$radar1" != "$radar2" ]]; then
                    echo "reference_point_hdfeos5.bash ${q_radar2} --ref-lalo $(printf '%q' "$ref_lat") $(printf '%q' "$ref_lon") &"
                    echo "pids+=(\"\$!\")"
                fi
                echo "hv_wait_pids \"\${pids[@]}\" || exit 1"
            else
                echo "reference_point_hdfeos5.bash ${q_radar1} --ref-lalo $(printf '%q' "$ref_lat") $(printf '%q' "$ref_lon")"
                if [[ "$radar1" != "$radar2" ]]; then
                    echo "reference_point_hdfeos5.bash ${q_radar2} --ref-lalo $(printf '%q' "$ref_lat") $(printf '%q' "$ref_lon")"
                fi
            fi
            echo ""
            if [[ "$force" == "1" ]]; then
                echo "need_geocode1=1"
                echo "need_geocode2=1"
            else
                echo "need_geocode1=0"
                echo "need_geocode2=0"
                echo "need_geocode ${q_radar1} ${q_geo1} $(printf '%q' "$lat_step") $(printf '%q' "$lon_step") && need_geocode1=1"
                echo "need_geocode ${q_radar2} ${q_geo2} $(printf '%q' "$lat_step") $(printf '%q' "$lon_step") && need_geocode2=1"
            fi
            echo ""
            if [[ "$compute_parallel" == "1" ]]; then
                echo "pids=()"
                echo "if [[ \$need_geocode1 -eq 1 ]]; then"
                echo "  geocode.py ${q_radar1} ${geocode_args} &"
                echo "  pids+=(\"\$!\")"
                echo "fi"
                echo "if [[ \$need_geocode2 -eq 1 ]]; then"
                echo "  geocode.py ${q_radar2} ${geocode_args} &"
                echo "  pids+=(\"\$!\")"
                echo "fi"
                echo "if [[ \${#pids[@]} -gt 0 ]]; then"
                echo "  hv_wait_pids \"\${pids[@]}\" || exit 1"
                echo "fi"
            else
                echo "if [[ \$need_geocode1 -eq 1 ]]; then"
                echo "  geocode.py ${q_radar1} ${geocode_args}"
                echo "fi"
                echo "if [[ \$need_geocode2 -eq 1 ]]; then"
                echo "  geocode.py ${q_radar2} ${geocode_args}"
                echo "fi"
            fi
            echo ""
            echo "horzvert_timeseries.py ${q_geo1} ${q_geo2}${py_suffix}${geom_args}"
            echo "wait"
            echo ""
        fi

        if [[ "$save_qgis" != "off" || "$ingest_insarmaps" == "1" ]]; then
            echo "VERT=\$(ls -t ${q_outdir}/*vert*.he5 2>/dev/null | head -1)"
            echo "HORZ=\$(ls -t ${q_outdir}/*horz*.he5 2>/dev/null | head -1)"
            echo "if [[ -z \"\$VERT\" || -z \"\$HORZ\" || ! -f \"\$VERT\" || ! -f \"\$HORZ\" ]]; then"
            echo "  echo \"Error: missing *vert*/*horz*.he5 under ${q_outdir}\" >&2"
            echo "  exit 1"
            echo "fi"
            echo "VERT=\$(realpath \"\$VERT\")"
            echo "HORZ=\$(realpath \"\$HORZ\")"
        fi

        if [[ "$save_qgis" != "off" ]]; then
            echo 'hv_save_qgis_he5 "$VERT"'
            echo 'hv_save_qgis_he5 "$HORZ"'
            echo "hv_save_qgis_he5 ${q_abs_geo1}"
            echo "hv_save_qgis_he5 ${q_abs_geo2}"
            if [[ "$save_qgis" == "all" ]]; then
                echo "hv_save_qgis_he5 ${q_abs_radar1}"
                echo "hv_save_qgis_he5 ${q_abs_radar2}"
            fi
            echo ""
        fi

        if [[ "$ingest_insarmaps" == "1" ]]; then
            # Cd into product dir so ingest writes insarmaps.log next to overlay.html.
            # Truncate first so this run's four URLs are the only entries.
            # Also append command lines to SCRATCHDIR/log via hv_ingest_insarmaps_logged.
            echo "cd ${q_abs_outdir}"
            echo "rm -f insarmaps.log"
            echo "hv_ingest_insarmaps_logged ${q_scratch_log} \"\$VERT\" ${workers_opts}${amp}"
            echo "hv_ingest_insarmaps_logged ${q_scratch_log} \"\$HORZ\" ${workers_opts}${amp}"
            if [[ "$ingest_los" == "1" ]]; then
                if [[ -n "$ds1" ]]; then
                    echo "hv_ingest_insarmaps_logged ${q_scratch_log} ${q_abs_radar1} --dataset $(printf '%q' "$ds1") ${workers_opts}${amp}"
                else
                    echo "hv_ingest_insarmaps_logged ${q_scratch_log} ${q_abs_radar1} ${workers_opts}${amp}"
                fi
                if [[ -n "$ds2" ]]; then
                    echo "hv_ingest_insarmaps_logged ${q_scratch_log} ${q_abs_radar2} --dataset $(printf '%q' "$ds2") ${workers_opts}${amp}"
                else
                    echo "hv_ingest_insarmaps_logged ${q_scratch_log} ${q_abs_radar2} ${workers_opts}${amp}"
                fi
            fi
            if [[ "$ingest_parallel" == "1" ]]; then
                echo "wait"
            fi
        fi

        echo ""
        echo "hv_finish_horzvert_run ${q_abs_outdir} $(printf '%q' "$lat_step") $(printf '%q' "$lon_step") \\"
        echo "  ${q_abs_radar1} ${q_abs_radar2} \\"
        echo "  $(printf '%q' "$ingest_insarmaps") $(printf '%q' "$ingest_los") $(printf '%q' "$save_qgis") \\"
        echo "  $(printf '%q' "$do_upload") ${q_outdir}"
    } > "$run_file"

    chmod +x "$run_file"
}

# Write horzvert_timeseries.job next to the run file via job_submission.py.
hv_write_horzvert_jobfile() {
    local run_file="$1"
    local job_name="${2:-horzvert_timeseries}"
    local work_dir

    [[ -f "$run_file" ]] || {
        echo "hv_write_horzvert_jobfile: missing $run_file" >&2
        return 1
    }
    work_dir=$(dirname "$run_file")
    (
        cd "$work_dir"
        create_horzvert_runfile_job.py --from-file "$(basename "$run_file")" --job-name "$job_name"
    )
}

# Print overlay.html URL after horzvert run (urls.log or latest job stdout).
hv_print_horzvert_overlay_url() {
    local product_dir="$1"
    local urls_log url f

    [[ -n "$product_dir" && -d "$product_dir" ]] || return 0
    product_dir=$(realpath "$product_dir" 2>/dev/null || echo "$product_dir")

    urls_log="${product_dir}/urls.log"
    if [[ -f "$urls_log" ]]; then
        url=$(grep -E 'overlay\.html' "$urls_log" | tail -1)
        if [[ -n "$url" ]]; then
            echo ""
            echo "Data at:"
            echo "$url"
            return 0
        fi
    fi

    for f in \
        "${product_dir}/horzvert_timeseries_"*.o \
        "${product_dir}/stdout_horzvert_timeseries/horzvert_timeseries_"*.o; do
        [[ -f "$f" ]] || continue
        url=$(grep -E '^https?://' "$f" | grep 'overlay\.html' | tail -1)
        if [[ -n "$url" ]]; then
            echo ""
            echo "Data at:"
            echo "$url"
            return 0
        fi
    done
    return 0
}

# Execute script-style run file: bash locally, or JOB_SUBMIT .job + run_workflow --jobfile on SLURM login.
hv_run_or_submit_script() {
    local run_file="$1"
    local job_name="${2:-horzvert_timeseries}"
    local job_file work_dir

    [[ -f "$run_file" ]] || {
        echo "hv_run_or_submit_script: missing $run_file" >&2
        return 1
    }
    work_dir=$(dirname "$run_file")

    if hv_should_use_slurm_jobfile; then
        hv_write_horzvert_jobfile "$run_file" "$job_name"
        job_file="${work_dir}/${job_name}.job"
        [[ -f "$job_file" ]] || {
            echo "hv_run_or_submit_script: jobfile not created: $job_file" >&2
            return 1
        }
        echo "Submitting via run_workflow.bash --jobfile $job_file"
        run_workflow.bash --jobfile "$job_file"
        hv_print_horzvert_overlay_url "$work_dir"
    else
        echo "Running: bash $run_file"
        bash "$run_file"
    fi
}
