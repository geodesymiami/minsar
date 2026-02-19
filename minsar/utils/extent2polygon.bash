#!/usr/bin/env bash
# Convert extent (lon_min lat_min lon_max lat_max) to WKT POLYGON
# Usage: extent2polygon.bash lon_min lat_min lon_max lat_max
# Example: extent2polygon.bash -156.1 18.9 -154.5 19.9
# Output: POLYGON((-156.1 18.9,-154.5 18.9,-154.5 19.9,-156.1 19.9,-156.1 18.9))

usage() {
    echo "Usage: $0 lon_min lat_min lon_max lat_max"
    echo "  Extent format: west south east north (or lon_min lat_min lon_max lat_max)"
    echo "  Output: WKT POLYGON"
    exit 1
}

if [[ $# -ne 4 ]]; then
    usage
fi

lon_min="$1"
lat_min="$2"
lon_max="$3"
lat_max="$4"

# Validate numeric
for val in "$lon_min" "$lat_min" "$lon_max" "$lat_max"; do
    if ! [[ "$val" =~ ^-?[0-9]+\.?[0-9]*$ ]]; then
        echo "$0: invalid numeric value: $val" >&2
        exit 1
    fi
done

# Build polygon: SW -> SE -> NE -> NW -> SW (clockwise)
printf 'POLYGON((%s %s,%s %s,%s %s,%s %s,%s %s))\n' \
    "$lon_min" "$lat_min" \
    "$lon_max" "$lat_min" \
    "$lon_max" "$lat_max" \
    "$lon_min" "$lat_max" \
    "$lon_min" "$lat_min"
