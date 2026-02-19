#!/usr/bin/env bash
# Convert burst2stack-style command args to ASF Vertex search URL for rapid burst visualization.
# Usage: burstcmd2asf.bash [burst2stack] [options]
#   burst2stack - optional, ignored
#   --rel-orbit N       relative orbit number
#   --start-date DATE   YYYY-MM-DD
#   --end-date DATE     YYYY-MM-DD
#   --extent lomin latmin lomax latmax   bounding box (4 numbers)
# Output: ASF Vertex URL (print to stdout)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<'EOF'
Usage: burstcmd2asf.bash [burst2stack] --rel-orbit N --start-date DATE --end-date DATE --extent lon_min lat_min lon_max lat_max

  Convert burst2stack command arguments to an ASF Vertex search URL for rapid burst visualization.

Options:
  burst2stack          Optional first argument, ignored (for compatibility with burst2stack command)
  --rel-orbit N        Relative orbit number
  --start-date DATE    Start date (YYYY-MM-DD)
  --end-date DATE      End date (YYYY-MM-DD)
  --extent a b c d     Bounding box: lon_min lat_min lon_max lat_max (4 numbers)

Output:
  Full ASF Vertex URL to stdout. Open in a browser to view bursts.

Examples:
  burstcmd2asf.bash --rel-orbit 87 --start-date 2025-06-01 --end-date 2099-12-31 --extent -156.1 18.9 -154.5 19.9

  burstcmd2asf.bash burst2stack --rel-orbit 87 --start-date 2025-01-01 --end-date 2025-12-31 --extent -86.6062 12.3516 -86.44 12.5019

Reference URLs:
  https://search.asf.alaska.edu/#/?zoom=6.717&center=-81.496,9.263&polygon=POLYGON((-86.6062%2012.3516,-86.44%2012.3516,-86.44%2012.5019,-86.6062%2012.5019,-86.6062%2012.3516))&dataset=SENTINEL-1%20BURSTS&maxResults=250&resultsLoaded=true
  https://search.asf.alaska.edu/#/?zoom=7.270&center=-154.965,17.512&polygon=POLYGON((-155.7503%2019.2782,-155.0419%2019.2782,-155.0419%2019.7544,-155.7503%2019.7544,-155.7503%2019.2782))&dataset=SENTINEL-1%20BURSTS&maxResults=250&resultsLoaded=true&relativeOrbit=87&start=2025-01-01T00:00:00Z&end=2025-12-31T23:59:59Z
EOF
    exit 0
}

for a in "$@"; do
    [[ "$a" == "-h" ]] || [[ "$a" == "--help" ]] && usage
done

rel_orbit=""
start_date=""
end_date=""
extent=()

args=("$@")
i=0
# Optional leading "burst2stack"
if [[ $# -gt 0 && "${args[0]}" == "burst2stack" ]]; then
    i=1
fi

while [[ $i -lt $# ]]; do
    a="${args[$i]}"
    case "$a" in
        --rel-orbit)
            (( i++ ))
            rel_orbit="${args[$i]:?--rel-orbit requires a value}"
            ;;
        --start-date)
            (( i++ ))
            start_date="${args[$i]:?--start-date requires a value}"
            ;;
        --end-date)
            (( i++ ))
            end_date="${args[$i]:?--end-date requires a value}"
            ;;
        --extent)
            (( i++ ))
            for _ in 1 2 3 4; do
                [[ $i -lt $# ]] || { echo "$0: --extent requires 4 numbers" >&2; exit 1; }
                extent+=("${args[$i]}")
                (( i++ ))
            done
            (( i-- ))  # back up one, outer loop will advance
            ;;
        *)
            echo "$0: unknown option: $a" >&2
            exit 1
            ;;
    esac
    (( i++ ))
done

if [[ ${#extent[@]} -ne 4 ]]; then
    echo "$0: --extent is required with 4 numbers (lon_min lat_min lon_max lat_max)" >&2
    exit 1
fi

# Convert extent to polygon
polygon=$("$SCRIPT_DIR/extent2polygon.bash" "${extent[0]}" "${extent[1]}" "${extent[2]}" "${extent[3]}")
polygon_enc=$(echo "$polygon" | sed 's/ /%20/g')

# Center of extent
lon_min="${extent[0]}"
lat_min="${extent[1]}"
lon_max="${extent[2]}"
lat_max="${extent[3]}"
lon_center=$(awk -v a="$lon_min" -v b="$lon_max" 'BEGIN { printf "%.3f", (a+b)/2 }')
lat_center=$(awk -v a="$lat_min" -v b="$lat_max" 'BEGIN { printf "%.3f", (a+b)/2 }')

# Base URL and fixed params
base="https://search.asf.alaska.edu/#/"
params="zoom=7&center=${lon_center},${lat_center}&polygon=${polygon_enc}&dataset=SENTINEL-1%20BURSTS&maxResults=250&resultsLoaded=true"

if [[ -n "$rel_orbit" ]]; then
    params="${params}&relativeOrbit=${rel_orbit}&path=${rel_orbit}-"
fi
if [[ -n "$start_date" ]]; then
    params="${params}&start=${start_date}T00:00:00Z"
fi
if [[ -n "$end_date" ]]; then
    params="${params}&end=${end_date}T23:59:59Z"
fi

echo "${base}?${params}"
