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
    local status
    status=$(hv_are_we_on_slurm_system 2>/dev/null || echo "False")
    [[ "$status" == "login_node" && -z "${SLURM_JOB_ID:-}" ]]
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

# Exit 0 if radar must be geocoded (no geo file, or radar newer than geo).
need_geocode() {
    local radar="$1"
    local geo="$2"
    [[ ! -f "$geo" || "$radar" -nt "$geo" ]]
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
# Optional: HV_CACHE_HIT=0|1, HV_GEOCODE_ARGS, HV_PY_SUFFIX, HV_INGEST_PARALLEL=0|1,
#           HV_INGEST_INSARMAPS=1|0, HV_INGEST_LOS=1|0, HV_INGEST_WORKERS_OPTS (string),
#           HV_GEOM_FILE_ARGS, HV_DATASET_OPT1, HV_DATASET_OPT2
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
    local ingest_parallel="${HV_INGEST_PARALLEL:-0}"
    local ingest_insarmaps="${HV_INGEST_INSARMAPS:-1}"
    local ingest_los="${HV_INGEST_LOS:-1}"
    local workers_opts="${HV_INGEST_WORKERS_OPTS:-}"
    local geom_args="${HV_GEOM_FILE_ARGS:-}"
    local ds1="${HV_DATASET_OPT1:-}"
    local ds2="${HV_DATASET_OPT2:-}"
    local geo1 geo2 r_radar1 r_radar2 r_geo1 r_geo2 r_outdir
    local q_radar1 q_radar2 q_geo1 q_geo2 q_outdir amp=""
    local utils_sh abs_outdir abs_radar1 abs_radar2 abs_scratch_log
    local q_abs_outdir q_abs_radar1 q_abs_radar2 q_scratch_log

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
    q_abs_outdir=$(printf '%q' "$abs_outdir")
    q_abs_radar1=$(printf '%q' "$abs_radar1")
    q_abs_radar2=$(printf '%q' "$abs_radar2")
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
            echo "pids=()"
            echo "reference_point_hdfeos5.bash ${q_radar1} --ref-lalo $(printf '%q' "$ref_lat") $(printf '%q' "$ref_lon") &"
            echo "pids+=(\"\$!\")"
            if [[ "$radar1" != "$radar2" ]]; then
                echo "reference_point_hdfeos5.bash ${q_radar2} --ref-lalo $(printf '%q' "$ref_lat") $(printf '%q' "$ref_lon") &"
                echo "pids+=(\"\$!\")"
            fi
            echo "hv_wait_pids \"\${pids[@]}\" || exit 1"
            echo ""
            echo "need_geocode1=0"
            echo "need_geocode2=0"
            echo "need_geocode ${q_radar1} ${q_geo1} && need_geocode1=1"
            echo "need_geocode ${q_radar2} ${q_geo2} && need_geocode2=1"
            echo ""
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
            echo ""
            echo "horzvert_timeseries.py ${q_geo1} ${q_geo2}${py_suffix}${geom_args}"
            echo "wait"
            echo ""
        fi

        if [[ "$ingest_insarmaps" == "1" ]]; then
            # Resolve products under SCRATCHDIR cwd, then cd into product dir so
            # ingest writes insarmaps.log next to overlay.html (all four URLs).
            # Also append command lines to SCRATCHDIR/log via hv_ingest_insarmaps_logged.
            echo "VERT=\$(ls -t ${q_outdir}/*vert*.he5 2>/dev/null | head -1)"
            echo "HORZ=\$(ls -t ${q_outdir}/*horz*.he5 2>/dev/null | head -1)"
            echo "if [[ -z \"\$VERT\" || -z \"\$HORZ\" || ! -f \"\$VERT\" || ! -f \"\$HORZ\" ]]; then"
            echo "  echo \"Error: missing *vert*/*horz*.he5 under ${q_outdir} (needed for ingest)\" >&2"
            echo "  exit 1"
            echo "fi"
            echo "VERT=\$(realpath \"\$VERT\")"
            echo "HORZ=\$(realpath \"\$HORZ\")"
            echo "cd ${q_abs_outdir}"
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
    } > "$run_file"

    chmod +x "$run_file"
}

# Execute script-style run file: bash locally, or create .job + run_workflow --jobfile on SLURM login.
hv_run_or_submit_script() {
    local run_file="$1"
    local job_name="${2:-horzvert2timeseries}"
    local job_file work_dir

    [[ -f "$run_file" ]] || {
        echo "hv_run_or_submit_script: missing $run_file" >&2
        return 1
    }
    work_dir=$(dirname "$run_file")

    if hv_should_use_slurm_jobfile; then
        (
            cd "$work_dir"
            create_slurm_jobfile.sh --job-name "$job_name" --from-file "$(basename "$run_file")"
        )
        job_file="${work_dir}/${job_name}.job"
        [[ -f "$job_file" ]] || job_file="${work_dir}/$(basename "$run_file" | sed 's/^run_//').job"
        echo "Submitting via run_workflow.bash --jobfile $job_file"
        run_workflow.bash --jobfile "$job_file"
    else
        echo "Running: bash $run_file"
        bash "$run_file"
    fi
}
