#!/usr/bin/env bash
# Convert WKT POLYGON to extent (lon_min lat_min lon_max lat_max)
# Usage: polygon2extent.bash "POLYGON((...))"
# Example: polygon2extent.bash "POLYGON((-86.6062 12.3516,-86.44 12.3516,-86.44 12.5019,-86.6062 12.5019,-86.6062 12.3516))"
# Output: -86.6062 12.3516 -86.44 12.5019

usage() {
    echo "Usage: $0 \"POLYGON((lon1 lat1,lon2 lat2,...))\""
    echo "  Input: WKT POLYGON string"
    echo "  Output: lon_min lat_min lon_max lat_max"
    exit 1
}

if [[ $# -lt 1 ]] || [[ -z "$1" ]]; then
    usage
fi

polygon="$1"

# Extract coordinates and compute min/max with awk
result=$(echo "$polygon" | awk '{
    gsub(/^POLYGON\(\(/, "", $0)
    gsub(/\)\)$/, "", $0)
    gsub(/^ +| +$/, "", $0)
    n = split($0, pairs, ",")
    lon_min = lon_max = lat_min = lat_max = ""
    for (i = 1; i <= n; i++) {
        gsub(/^ +/, "", pairs[i])
        m = split(pairs[i], xy, / +/)
        if (m >= 2) {
            lon = xy[1] + 0
            lat = xy[2] + 0
            if (lon_min == "" || lon < lon_min) lon_min = lon
            if (lon_max == "" || lon > lon_max) lon_max = lon
            if (lat_min == "" || lat < lat_min) lat_min = lat
            if (lat_max == "" || lat > lat_max) lat_max = lat
        }
    }
    if (lon_min != "")
        print lon_min, lat_min, lon_max, lat_max
}')

if [[ -z "$result" ]]; then
    echo "$0: invalid POLYGON format or no coordinates" >&2
    exit 1
fi

echo "$result"
