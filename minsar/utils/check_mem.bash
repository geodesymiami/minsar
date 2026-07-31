#!/usr/bin/env bash
# check_mem.bash — report RAM / /dev/shm use relevant to InsarMaps ingest,
# and print copy-paste commands to free orphan shared memory and stuck jobs.
#
# Does NOT kill or delete anything unless --apply / --apply-all is passed
# (then runs immediately, no confirmation).
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
# APPLY_MODE: off | memory | all
APPLY_MODE=off
MIN_SHM_MB=100   # only report /dev/shm files at least this large
MIN_RSS_KB=$((500 * 1024))  # suggest kill only if RSS >= 500 MB (unless holds shm / is hdfeos5)

usage() {
    cat <<EOF
Usage: $SCRIPT_NAME [--apply [all]] [--min-shm-mb N]

Report memory occupied by:
  - large POSIX shared-memory files under /dev/shm (e.g. psm_* from
    hdfeos5_2json_mbtiles.py)
  - related ingest / stuck processes (stopped Tl, high RSS)

By default only prints suggested commands. With --apply / --apply all,
runs the free commands immediately (no confirmation prompt).

Options:
  --apply           Run memory kill/rm suggestions immediately
  --apply all       Also kill all listed stopped/zombie jobs (low-RSS optional set)
  --apply-all       Same as --apply all
  --min-shm-mb N    Ignore /dev/shm files smaller than N MB (default: $MIN_SHM_MB)
  -h, --help        Show this help

Examples:
  $SCRIPT_NAME
  $SCRIPT_NAME --min-shm-mb 50
  $SCRIPT_NAME --apply
  $SCRIPT_NAME --apply all
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --apply)
            APPLY_MODE=memory
            if [[ "${2:-}" == "all" ]]; then
                APPLY_MODE=all
                shift
            fi
            shift
            ;;
        --apply-all)
            APPLY_MODE=all
            shift
            ;;
        --min-shm-mb)
            [[ $# -ge 2 ]] || { echo "Error: --min-shm-mb needs a value" >&2; exit 1; }
            MIN_SHM_MB="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -?*|--*)
            echo "Error: unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
        *)
            echo "Error: unexpected argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

bytes_to_human() {
    local b="$1"
    if [[ "$b" -ge $((1024**3)) ]]; then
        awk -v b="$b" 'BEGIN { printf "%.1fG", b/1024/1024/1024 }'
    elif [[ "$b" -ge $((1024**2)) ]]; then
        awk -v b="$b" 'BEGIN { printf "%.0fM", b/1024/1024 }'
    else
        awk -v b="$b" 'BEGIN { printf "%.0fK", b/1024 }'
    fi
}

# Redact secrets and normalize whitespace in command lines shown to the user.
redact_cmd() {
    tr '\t' ' ' | tr -s ' ' | sed -E \
        -e 's/(Authorization:[[:space:]]*Bearer[[:space:]]+)[^[:space:]]+/\1<REDACTED>/gi' \
        -e 's/(--password[=[:space:]]+)[^[:space:]]+/\1<REDACTED>/gi' \
        -e 's/(TOKEN|SECRET|PASSWORD|API_KEY)=[^[:space:]]+/\1=<REDACTED>/gi'
}

# True for services we should not suggest killing (even if RSS is large).
is_protected_process() {
    local cmd="$1"
    [[ "$cmd" == *org.apache.catalina.startup.Bootstrap* ]] && return 0
    [[ "$cmd" == */tomcat/* ]] && return 0
    [[ "$cmd" == *cursor-server* ]] && return 0
    [[ "$cmd" == *dockerd* ]] && return 0
    [[ "$cmd" == */systemd* ]] && return 0
    [[ "$cmd" == *multipathd* ]] && return 0
    return 1
}

is_scanner_noise() {
    local cmd="$1"
    [[ "$cmd" =~ ^awk[[:space:]] ]] && return 0
    [[ "$cmd" =~ ^grep[[:space:]] ]] && return 0
    [[ "$cmd" == *"$SCRIPT_NAME"* || "$cmd" == *"check_mem.bash"* ]] && return 0
    return 1
}

# PIDs that have any mapping under /dev/shm/<name>
pids_mapping_shm() {
    local name="$1"
    local pid maps
    for maps in /proc/[0-9]*/maps; do
        pid="${maps#/proc/}"
        pid="${pid%/maps}"
        if grep -Fq "/dev/shm/${name}" "$maps" 2>/dev/null; then
            echo "$pid"
        fi
    done
}

echo "========== System memory =========="
free -h
echo ""
echo "========== /dev/shm (POSIX shared memory) =========="
df -h /dev/shm 2>/dev/null || echo "(no /dev/shm)"
echo ""

declare -a SUGGESTED_CMDS=()
declare -a OPTIONAL_CMDS=()   # low-RSS stopped jobs (--apply all)
declare -a ORPHAN_SHM=()
declare -a LIVE_SHM=()
declare -A SHM_HOLDER_PIDS=()

min_bytes=$((MIN_SHM_MB * 1024 * 1024))

if [[ -d /dev/shm ]]; then
    shopt -s nullglob
    shm_files=(/dev/shm/*)
    shopt -u nullglob

    if [[ ${#shm_files[@]} -eq 0 ]]; then
        echo "No files in /dev/shm."
    else
        printf "%-12s %10s  %s\n" "SIZE" "STATUS" "FILE"
        for f in "${shm_files[@]}"; do
            [[ -f "$f" ]] || continue
            sz=$(stat -c '%s' "$f" 2>/dev/null || echo 0)
            [[ "$sz" -ge "$min_bytes" ]] || continue
            name="$(basename "$f")"
            map_pids=$(pids_mapping_shm "$name" | tr '\n' ' ' | sed 's/[[:space:]]*$//')
            human=$(bytes_to_human "$sz")
            if [[ -z "$map_pids" ]]; then
                printf "%-12s %10s  %s\n" "$human" "ORPHAN" "$f"
                ORPHAN_SHM+=("$f")
                SUGGESTED_CMDS+=("rm -f $(printf '%q' "$f")")
            else
                printf "%-12s %10s  %s  (PIDs: %s)\n" "$human" "IN-USE" "$f" "$map_pids"
                LIVE_SHM+=("$f|$map_pids")
                for pid in $map_pids; do
                    SHM_HOLDER_PIDS[$pid]=1
                done
            fi
        done
        if [[ ${#ORPHAN_SHM[@]} -eq 0 && ${#LIVE_SHM[@]} -eq 0 ]]; then
            echo "(no /dev/shm files >= ${MIN_SHM_MB} MB)"
        fi
    fi
fi

echo ""
echo "========== Related / high-memory processes =========="
printf "%-8s %6s %6s %-6s %s\n" "PID" "%MEM" "RSS" "STAT" "COMMAND"
found_proc=0

while IFS=$'\t' read -r pid pmem rss_kb stat cmd; do
    [[ -z "${pid:-}" ]] && continue
    [[ "$pid" == "$$" ]] && continue
    safe_cmd=$(printf '%s' "$cmd" | redact_cmd)
    is_scanner_noise "$safe_cmd" && continue

    rss_h=$(bytes_to_human $((rss_kb * 1024)))
    printf "%-8s %6s %6s %-6s %s\n" "$pid" "$pmem" "$rss_h" "$stat" "$safe_cmd"
    found_proc=1

    is_protected_process "$safe_cmd" && continue

    is_ingest=0
    [[ "$safe_cmd" == *hdfeos5_2json* || "$safe_cmd" == *tippecanoe* ]] && is_ingest=1
    holds_shm=0
    [[ -n "${SHM_HOLDER_PIDS[$pid]:-}" ]] && holds_shm=1
    high_rss=0
    [[ "$rss_kb" -ge "$MIN_RSS_KB" ]] && high_rss=1
    stopped=0
    [[ "$stat" == *T* ]] && stopped=1

    # Suggest kill only when it frees meaningful memory or clears ingest/shm holders
    if [[ "$holds_shm" -eq 1 || "$is_ingest" -eq 1 || "$high_rss" -eq 1 ]]; then
        note=""
        [[ "$stopped" -eq 1 ]] && note="stopped "
        [[ "$holds_shm" -eq 1 ]] && note+="holds-shm "
        [[ "$is_ingest" -eq 1 ]] && note+="ingest "
        SUGGESTED_CMDS+=("kill $pid   # ${note}RSS=$rss_h $safe_cmd")
        SUGGESTED_CMDS+=("# if still alive: kill -9 $pid")
    fi
done < <(
    ps -eo pid=,pmem=,rss=,stat=,args= --sort=-rss \
        | awk -v OFS='\t' -v minrss="$MIN_RSS_KB" '
            {
              pid=$1; pmem=$2; rss=$3; stat=$4
              $1=$2=$3=$4=""; sub(/^ +/,"");
              cmd=$0
              # exclude scanner awk (may contain hdfeos5_2json in the pattern text)
              if (cmd ~ /^awk([[:space:]]|$)/) next
              if (rss >= minrss || stat ~ /T/ || cmd ~ /(^|\/)hdfeos5_2json/ || cmd ~ /(^|[[:space:]])tippecanoe([[:space:]]|$)/)
                  print pid, pmem, rss, stat, cmd
            }' \
        | head -40
)

# Also list other stopped jobs that we intentionally did not suggest killing
echo ""
echo "========== Other stopped jobs (low RSS; optional cleanup) =========="
stopped_note=0
while IFS=$'\t' read -r pid pmem rss_kb stat cmd; do
    [[ -z "${pid:-}" ]] && continue
    [[ "$pid" == "$$" ]] && continue
    safe_cmd=$(printf '%s' "$cmd" | redact_cmd)
    is_scanner_noise "$safe_cmd" && continue
    [[ "$rss_kb" -ge "$MIN_RSS_KB" ]] && continue
    [[ "$safe_cmd" == *hdfeos5_2json* || "$safe_cmd" == *tippecanoe* ]] && continue
    [[ -n "${SHM_HOLDER_PIDS[$pid]:-}" ]] && continue
    printf "%-8s %6s %6s %-6s %s\n" "$pid" "$pmem" "$(bytes_to_human $((rss_kb * 1024)))" "$stat" "$safe_cmd"
    echo "  # optional: kill $pid"
    OPTIONAL_CMDS+=("kill $pid   # stopped low-RSS $safe_cmd")
    OPTIONAL_CMDS+=("# if still alive: kill -9 $pid")
    stopped_note=1
done < <(
    ps -eo pid=,pmem=,rss=,stat=,args= --sort=-rss \
        | awk -v OFS='\t' '
            {
              pid=$1; pmem=$2; rss=$3; stat=$4
              $1=$2=$3=$4=""; sub(/^ +/,"");
              if (stat ~ /T/ && $0 !~ /^awk([[:space:]]|$)/)
                  print pid, pmem, rss, stat, $0
            }' \
        | head -30
)
if [[ "$stopped_note" -eq 0 ]]; then
    echo "(none)"
fi

if [[ "$found_proc" -eq 0 ]]; then
    echo "(none matching: RSS>=500M, stopped, hdfeos5_2json*, or tippecanoe)"
fi

if [[ ${#LIVE_SHM[@]} -gt 0 ]]; then
    echo ""
    echo "========== Processes holding large /dev/shm =========="
    for entry in "${LIVE_SHM[@]}"; do
        f="${entry%%|*}"
        pids="${entry#*|}"
        echo "File: $f"
        for pid in $pids; do
            if [[ -r "/proc/$pid/cmdline" ]]; then
                cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" | sed 's/[[:space:]]*$//' | redact_cmd)
                rss_kb=$(awk '/VmRSS:/ {print $2}' "/proc/$pid/status" 2>/dev/null || echo 0)
                echo "  PID $pid  RSS=$(bytes_to_human $((rss_kb * 1024)))  $cmd"
                SUGGESTED_CMDS+=("kill $pid   # holds $(basename "$f")")
                SUGGESTED_CMDS+=("# if still alive: kill -9 $pid")
                SUGGESTED_CMDS+=("rm -f $(printf '%q' "$f")   # after process exits")
            fi
        done
    done
fi

echo ""
echo "========== InsarMaps peak rule of thumb =========="
echo "hdfeos5_2json_mbtiles.py peaks at ~2x displacement cube size"
echo "(numpy load + SharedMemory copy), needs that much MemAvailable,"
echo "plus ~1x cube free in /dev/shm. Swap is often 0 on Jetstream."
avail_kb=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
shm_avail=$(df -B1 --output=avail /dev/shm 2>/dev/null | tail -1 | tr -d ' ' || echo 0)
echo "MemAvailable now: $(bytes_to_human $((avail_kb * 1024)))"
echo "/dev/shm avail:   $(bytes_to_human "${shm_avail:-0}")"

echo ""
echo "========== Suggested commands to free memory =========="

declare -A seen=()
unique_cmds=()
for c in "${SUGGESTED_CMDS[@]}"; do
    [[ -n "${seen[$c]:-}" ]] && continue
    seen[$c]=1
    unique_cmds+=("$c")
done

if [[ ${#unique_cmds[@]} -eq 0 ]]; then
    echo "(nothing obvious to free)"
else
    for c in "${unique_cmds[@]}"; do
        echo "$c"
    done
fi

if [[ ${#OPTIONAL_CMDS[@]} -gt 0 ]]; then
    echo ""
    echo "========== Optional stopped/zombie kills (--apply all) =========="
    for c in "${OPTIONAL_CMDS[@]}"; do
        echo "$c"
    done
fi

apply_kill_or_rm() {
    local c="$1"
    local run_cmd pid
    [[ "$c" == \#* ]] && return 0
    if [[ "$c" =~ ^kill\ ([0-9]+) ]]; then
        pid="${BASH_REMATCH[1]}"
        if [[ ! -e "/proc/$pid" ]]; then
            echo "+ (pid $pid already gone)"
            return 0
        fi
        echo "+ kill $pid"
        kill "$pid" 2>/dev/null || true
        sleep 0.2
        if [[ -e "/proc/$pid" ]]; then
            echo "+ kill -9 $pid"
            kill -9 "$pid" 2>/dev/null || true
        fi
        return 0
    fi
    if [[ "$c" =~ ^rm\ -f\  ]]; then
        run_cmd="${c%%   #*}"
        echo "+ $run_cmd"
        eval "$run_cmd" || true
    fi
}

if [[ "$APPLY_MODE" != "off" ]]; then
    apply_list=("${unique_cmds[@]}")
    if [[ "$APPLY_MODE" == "all" ]]; then
        for c in "${OPTIONAL_CMDS[@]}"; do
            [[ -n "${seen[$c]:-}" ]] && continue
            seen[$c]=1
            apply_list+=("$c")
        done
    fi

    if [[ ${#apply_list[@]} -eq 0 ]]; then
        echo ""
        echo "Nothing to apply."
        exit 0
    fi

    echo ""
    if [[ "$APPLY_MODE" == "all" ]]; then
        echo "Applying memory suggestions AND all stopped/zombie kills..."
    else
        echo "Applying memory kill/rm suggestions..."
    fi
    for c in "${apply_list[@]}"; do
        apply_kill_or_rm "$c"
    done
    echo ""
    echo "After apply:"
    free -h
    ls -lah /dev/shm/ 2>/dev/null || true
fi
