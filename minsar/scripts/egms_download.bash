#!/usr/bin/env bash
# Search EGMS products (minimal API filters), filter locally, print and/or download via curl.
#
# First-layer egms_search.py gets AOI + level + releases only (avoids API hangs from
# relativeOrbit+swath). Local filters: --relativeOrbit, --swath, --direction.
#
# Usage / Examples:
#   egms_download.bash --aoi='37.51:37.88,15.15:15.16' --releases=2020-2024 --swath=IW2 --relativeOrbit=44 --print
#   egms_download.bash --intersectsWith='Polygon((14.75 37.51, 15.25 37.51, 15.25 37.88, 14.75 37.88, 14.75 37.51))' --releases=2020-2024 --swath=IW2 --relativeOrbit=44 --download --dir=./egms
#   egms_download.bash --aoi='37.51:37.88,15.15:15.16' --releases=2020-2024 --download --parallel=1

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<EOF
Search EGMS products via egms_search.py (AOI/level/releases), filter locally, then
print and/or download with curl (retries + resume). Requires CLMS service key.

Options:
  --aoi AOI | --intersectsWith AOI   Required. S:N,W:E or WKT POLYGON
  --level LEVEL                      First-layer search (default: L2A)
  --releases REL                     First-layer search (default: 2020-2024; skips flaky GET /releases)
  --relativeOrbit N                  Local filter only
  --swath SWATH                      Local filter only (e.g. IW2)
  --direction DIR                    Local filter only (ascending|descending)
  --print                            Print filtered listing (default if no --download)
  --download                         Write and run curl downloads
  --dir FOLDER                       Download directory (default: ./egms)
  --parallel N                       Concurrent curl jobs (default: 1)
  --unzip                            Unzip downloaded .zip files into --dir (default: yes)
  --no-unzip                         Skip unzip after download
  --reuse-search                     Skip egms_search.py if egms_hits_raw.json already exists
  --service-key PATH                 CLMS service key JSON
  --help, -h                         This help

Examples:
  egms_download.bash --aoi='37.51:37.88,15.15:15.16' --releases=2020-2024 --swath=IW2 --relativeOrbit=44 --print
  egms_download.bash --intersectsWith='Polygon((14.75 37.51, 15.25 37.51, 15.25 37.88, 14.75 37.88, 14.75 37.51))' --releases=2020-2024 --swath=IW2 --relativeOrbit=44 --download --dir=./egms
  egms_download.bash --aoi='37.51:37.88,15.15:15.16' --releases=2020-2024 --download --parallel=1 --no-unzip

Concatenate (after download):
  egms_concat_csv.py --dir ./egms --pattern 'EGMS_L2a_044_*_IW2_*.zip'
  egms_concat_csv.py ./egms/EGMS_L2a_044_022*_IW2_*.zip

Insarmaps ingest:
  egms2insarmaps.py ./egms/EGMS_L2a_044_IW2_VV_2020_2024_concat.csv --xml ./egms/EGMS_L2a_044_0221_IW2_VV_2020_2024_1.xml --flight-direction A --relative-orbit 44 --num-workers 1
  egms2insarmaps.py ./egms/EGMS_L2a_044_IW2_VV_2020_2024_concat.csv --step 1 --flight-direction A --relative-orbit 44 --num-workers 1
  egms2insarmaps.py ./egms/EGMS_L2a_044_IW2_VV_2020_2024_concat.csv --step 2
EOF
    exit 0
fi

aoi=""
intersects_with=""
level="L2A"
releases="2020-2024"
relative_orbit=""
swath=""
direction=""
do_print=0
do_download=0
outdir="./egms"
parallel=1
do_unzip=1
reuse_search=0
service_key=""

# Accept --key=value and --key value
while [[ $# -gt 0 ]]; do
    case "$1" in
        --aoi=*)
            aoi="${1#--aoi=}"
            shift
            ;;
        --aoi)
            [[ $# -lt 2 ]] && { echo "Error: --aoi requires an argument" >&2; exit 1; }
            aoi="$2"
            shift 2
            ;;
        --intersectsWith=*)
            intersects_with="${1#--intersectsWith=}"
            shift
            ;;
        --intersectsWith)
            [[ $# -lt 2 ]] && { echo "Error: --intersectsWith requires an argument" >&2; exit 1; }
            intersects_with="$2"
            shift 2
            ;;
        --level=*)
            level="${1#--level=}"
            shift
            ;;
        --level)
            [[ $# -lt 2 ]] && { echo "Error: --level requires an argument" >&2; exit 1; }
            level="$2"
            shift 2
            ;;
        --releases=*)
            releases="${1#--releases=}"
            shift
            ;;
        --releases)
            [[ $# -lt 2 ]] && { echo "Error: --releases requires an argument" >&2; exit 1; }
            releases="$2"
            shift 2
            ;;
        --relativeOrbit=*)
            relative_orbit="${1#--relativeOrbit=}"
            shift
            ;;
        --relativeOrbit)
            [[ $# -lt 2 ]] && { echo "Error: --relativeOrbit requires an argument" >&2; exit 1; }
            relative_orbit="$2"
            shift 2
            ;;
        --swath=*)
            swath="${1#--swath=}"
            shift
            ;;
        --swath)
            [[ $# -lt 2 ]] && { echo "Error: --swath requires an argument" >&2; exit 1; }
            swath="$2"
            shift 2
            ;;
        --direction=*)
            direction="${1#--direction=}"
            shift
            ;;
        --direction)
            [[ $# -lt 2 ]] && { echo "Error: --direction requires an argument" >&2; exit 1; }
            direction="$2"
            shift 2
            ;;
        --dir=*)
            outdir="${1#--dir=}"
            shift
            ;;
        --dir)
            [[ $# -lt 2 ]] && { echo "Error: --dir requires an argument" >&2; exit 1; }
            outdir="$2"
            shift 2
            ;;
        --parallel=*)
            parallel="${1#--parallel=}"
            shift
            ;;
        --parallel)
            [[ $# -lt 2 ]] && { echo "Error: --parallel requires an argument" >&2; exit 1; }
            parallel="$2"
            shift 2
            ;;
        --unzip)
            # bare --unzip enables; --unzip yes|no also accepted
            if [[ $# -ge 2 && "$2" != -* ]]; then
                case "$2" in
                    yes|YES|y|Y|1|true|TRUE) do_unzip=1 ;;
                    no|NO|n|N|0|false|FALSE) do_unzip=0 ;;
                    *)
                        echo "Error: --unzip must be yes or no (got: $2)" >&2
                        exit 1
                        ;;
                esac
                shift 2
            else
                do_unzip=1
                shift
            fi
            ;;
        --unzip=*)
            case "${1#--unzip=}" in
                yes|YES|y|Y|1|true|TRUE) do_unzip=1 ;;
                no|NO|n|N|0|false|FALSE) do_unzip=0 ;;
                *)
                    echo "Error: --unzip must be yes or no (got: ${1#--unzip=})" >&2
                    exit 1
                    ;;
            esac
            shift
            ;;
        --no-unzip)
            do_unzip=0
            shift
            ;;
        --reuse-search)
            reuse_search=1
            shift
            ;;
        --service-key=*)
            service_key="${1#--service-key=}"
            shift
            ;;
        --service-key|-k)
            [[ $# -lt 2 ]] && { echo "Error: --service-key requires an argument" >&2; exit 1; }
            service_key="$2"
            shift 2
            ;;
        --print)
            do_print=1
            shift
            ;;
        --download)
            do_download=1
            shift
            ;;
        -?*|--*)
            echo "Error: unknown option: $1" >&2
            exit 1
            ;;
        *)
            echo "Error: unexpected argument: $1" >&2
            exit 1
            ;;
    esac
done

if [[ -z "$aoi" && -z "$intersects_with" ]]; then
    echo "Error: provide --aoi or --intersectsWith" >&2
    exit 1
fi

if [[ "$do_print" -eq 0 && "$do_download" -eq 0 ]]; then
    do_print=1
fi

if ! [[ "$parallel" =~ ^[1-9][0-9]*$ ]]; then
    echo "Error: --parallel must be a positive integer (got: $parallel)" >&2
    exit 1
fi

# Log (ssara-style)
log_cmd="$SCRIPT_NAME"
[[ -n "$aoi" ]] && log_cmd+=" --aoi='$aoi'"
[[ -n "$intersects_with" ]] && log_cmd+=" --intersectsWith='$intersects_with'"
log_cmd+=" --level=$level"
[[ -n "$releases" ]] && log_cmd+=" --releases=$releases"
[[ -n "$relative_orbit" ]] && log_cmd+=" --relativeOrbit=$relative_orbit"
[[ -n "$swath" ]] && log_cmd+=" --swath=$swath"
[[ -n "$direction" ]] && log_cmd+=" --direction=$direction"
[[ "$do_print" -eq 1 ]] && log_cmd+=" --print"
[[ "$do_download" -eq 1 ]] && log_cmd+=" --download"
log_cmd+=" --dir=$outdir --parallel=$parallel"
if [[ "$do_unzip" -eq 1 ]]; then
    log_cmd+=" --unzip=yes"
else
    log_cmd+=" --no-unzip"
fi
[[ "$reuse_search" -eq 1 ]] && log_cmd+=" --reuse-search"
echo "$(date +"%Y%m%d-%H:%M") * $log_cmd" >> log

raw_json="egms_hits_raw.json"
filt_json="egms_hits.json"
curl_script="download_egms.sh"
urls_tsv="egms_urls.tsv"

########################################
# Layer 1: minimal egms_search.py call #
########################################
if [[ "$reuse_search" -eq 1 && -f "$raw_json" ]]; then
    echo "Reusing existing $raw_json (--reuse-search)"
else
    search_cmd=(egms_search.py --level "$level" --releases "$releases" --json-out "$raw_json")
    if [[ -n "$aoi" ]]; then
        search_cmd+=(--aoi "$aoi")
    else
        search_cmd+=(--intersectsWith "$intersects_with")
    fi
    [[ -n "$service_key" ]] && search_cmd+=(--service-key "$service_key")

    echo "Running: ${search_cmd[*]}"
    search_ok=0
    for attempt in 1 2 3; do
        if "${search_cmd[@]}"; then
            search_ok=1
            break
        fi
        echo "Warning: egms_search.py failed (attempt $attempt/3); waiting $((attempt * 20))s..." >&2
        sleep $((attempt * 20))
    done
    if [[ "$search_ok" -ne 1 ]]; then
        echo "Error: egms_search.py failed after 3 attempts. If $raw_json exists from a prior run, retry with --reuse-search." >&2
        exit 1
    fi
fi

########################################
# Layer 2: local filter                #
########################################
filter_cmd=(filter_egms_hits.py --json-in "$raw_json" --json-out "$filt_json")
[[ -n "$relative_orbit" ]] && filter_cmd+=(--relativeOrbit "$relative_orbit")
[[ -n "$swath" ]] && filter_cmd+=(--swath "$swath")
[[ -n "$direction" ]] && filter_cmd+=(--direction "$direction")
[[ -n "$releases" ]] && filter_cmd+=(--releases "$releases")
filter_cmd+=(--level "$level")

if [[ "$do_print" -eq 1 ]]; then
    filter_cmd+=(--print)
fi
if [[ "$do_download" -eq 1 ]]; then
    filter_cmd+=(--write-curl "$curl_script" --write-urls "$urls_tsv" --dir "$outdir")
fi

echo "Running: ${filter_cmd[*]}"
"${filter_cmd[@]}"

if [[ "$do_download" -eq 0 ]]; then
    exit 0
fi

n_urls=$(wc -l < "$urls_tsv" | tr -d ' ')
if [[ "$n_urls" -eq 0 ]]; then
    echo "No granules to download after filtering. Exiting."
    exit 0
fi

mkdir -p "$outdir"
echo "Downloading $n_urls file(s) to $outdir (parallel=$parallel)"

download_one() {
    local filename="$1"
    local url="$2"
    local dest="$outdir/$filename"
    echo "Downloading $filename → $dest"
    local token
    token="$(clms_get_access_token.py)"
    curl -fL --http1.1 --connect-timeout 120 --retry 20 --retry-delay 30 --retry-all-errors -C - \
        -H "Authorization: Bearer ${token}" \
        -o "$dest" \
        "$url"
    sleep 2
}
export -f download_one
export outdir

if [[ "$parallel" -eq 1 ]]; then
    bash "$curl_script" "$outdir"
else
    # Parallel: one curl per line from TSV (filename<TAB>url)
    while IFS=$'\t' read -r filename url; do
        [[ -z "${filename:-}" || -z "${url:-}" ]] && continue
        printf '%s\0%s\0' "$filename" "$url"
    done < "$urls_tsv" | xargs -0 -n 2 -P "$parallel" bash -c 'download_one "$1" "$2"' _
fi

if [[ "$do_unzip" -eq 1 ]]; then
    echo "Unzipping archives in $outdir"
    while IFS=$'\t' read -r filename _url; do
        [[ -z "${filename:-}" ]] && continue
        zip_path="$outdir/$filename"
        if [[ ! -f "$zip_path" ]]; then
            echo "Warning: missing zip, skip unzip: $zip_path" >&2
            continue
        fi
        echo "Unzipping $filename → $outdir"
        # -n: never overwrite existing CSV/XML (safe for re-runs)
        unzip -n -q "$zip_path" -d "$outdir"
    done < "$urls_tsv"
fi

echo "Done. Downloaded to $outdir"
exit 0
