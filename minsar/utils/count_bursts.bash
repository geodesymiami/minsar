#!/usr/bin/env bash
set -euo pipefail

usage() {
cat <<EOF
Usage: count_bursts.bash

Counts number of BURST files in each line of run_01_burst2safe.

Search order:
  1) ./run_01_burst2safe
  2) SLC/run_01_burst2safe

Outputs:
  - For each line: line_number date subswath burst_count
  - Writes results to number_bursts.txt
  - Summary: distribution of counts and total bursts

Options:
  -h, --help    Show this help and exit
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

# locate input file
if [[ -f "./run_01_burst2safe" ]]; then
    infile="./run_01_burst2safe"
elif [[ -f "SLC/run_01_burst2safe" ]]; then
    infile="SLC/run_01_burst2safe"
else
    echo "ERROR: run_01_burst2safe not found in . or SLC/"
    exit 1
fi

outfile="number_bursts.txt"
> "$outfile"

awk '
/burst2safe/ {
    n = 0
    date = ""
    iw = ""
    for (i=1; i<=NF; i++) {
        if ($i ~ /BURST/) {
            n++
            if (date == "" || iw == "") {
                pos = index($i, "T")
                if (pos > 8) {
                    date = substr($i, pos-8, 8)
                }
                if ($i ~ /_IW[123]_/) {
                    match($i, /_IW[123]_/)
                    iw = substr($i, RSTART+1, RLENGTH-2)   # IW1, IW2, or IW3
                }
            }
        }
    }
    if (n > 0) {
        print NR, date, iw, n
    }
}
' "$infile" > "$outfile"

# print per-line counts (line_number date subswath count)
cat "$outfile"

echo ""
echo "Summary:"

awk '
NR > 0 {
    count = $4
    freq[count]++
    total += count
}
END {
    for (n in freq) {
        printf "%d bursts: %d line(s)\n", n, freq[n]
    }
    printf "Total: %d bursts in %d line(s)\n", total, NR
}
' "$outfile"
