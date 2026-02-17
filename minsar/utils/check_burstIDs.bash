#!/usr/bin/env bash
set -euo pipefail

usage() {
cat <<EOF
Usage: check_burstIDs.bash

Extracts burst ID numbers from each line of run_01_burst2safe and prints
date and IDs with "consecutive" or "non-consecutive". Ends with a summary.

Search order:
  1) ./run_01_burst2safe
  2) SLC/run_01_burst2safe

Output format per line: DATE ID1 ID2 ... consecutive|non-consecutive
Summary: N bursts2safe calls, M non-consecutive.

Options:
  -h, --help    Show this help and exit
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

# locate input file (same as count_bursts.bash)
if [[ -f "./run_01_burst2safe" ]]; then
    infile="./run_01_burst2safe"
elif [[ -f "SLC/run_01_burst2safe" ]]; then
    infile="SLC/run_01_burst2safe"
else
    echo "ERROR: run_01_burst2safe not found in . or SLC/"
    exit 1
fi

echo "$infile"

# Use awk: for each burst2safe line, collect burst IDs (numeric part before -BURST),
# sort them, check if consecutive, print date and IDs and consecutive|non-consecutive.
# Summary: total lines (bursts2safe calls) and count of non-consecutive.
awk '
/burst2safe/ {
    date = ""
    n = 0
    delete ids
    for (i = 1; i <= NF; i++) {
        if ($i ~ /-BURST$/) {
            # Burst ID is 2nd field: S1_060358_IW1_20250903T..._VV_A38D-BURST -> 060358
            split($i, a, "_")
            if (a[2] != "" && a[2] ~ /^[0-9]+$/) {
                id = a[2] + 0
                ids[++n] = id
            }
            if (date == "" && match($i, /[0-9]{8}T/)) {
                date = substr($i, RSTART, 8)
            }
        }
    }
    if (n == 0) next

    # sort numerically (simple bubble sort for small n)
    for (i = 1; i <= n; i++)
        for (j = i + 1; j <= n; j++)
            if (ids[j] < ids[i]) { t = ids[i]; ids[i] = ids[j]; ids[j] = t }

    consec = 1
    for (i = 2; i <= n; i++)
        if (ids[i] != ids[i-1] + 1) { consec = 0; break }

    line = date
    for (i = 1; i <= n; i++)
        line = line " " sprintf("%06d", ids[i])
    print line, (consec ? "consecutive" : "non-consecutive")

    total++
    if (!consec) nonconsec++
}
END {
    print ""
    print "Summary:"
    if (total > 0) {
        print total " bursts2safe calls"
        print nonconsec + 0 " non-consecutive."
    }
}
' "$infile"
