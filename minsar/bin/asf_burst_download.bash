#!/usr/bin/env bash
#
# ASF burst download: create listing, download with retry loop, check burst sizes.
# Run from the burst/SLC directory (same pattern as ssara_federated_query.bash).
# Reads ../download_asf_burst.cmd:
#   Line 1: this script's invocation command (used by minsarApp.bash)
#   Line 2: listing command  (creates asf_burst_listing.txt in cwd)
#   Line 3: download command (downloads bursts into cwd)
# Burst2safe is run later in the unpack step.
#

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    echo "Usage: asf_burst_download.bash"
    echo "  Run from the SLC (download) directory."
    echo "  Reads ../download_asf_burst.cmd for listing (line 2) and download (line 3) commands."
    echo "  Retries download for up to 1 hour (configurable). Removes dates with undersized bursts."
    exit 0
fi

# Retry duration: 1 hour (change to 12*3600 = 43200 for 12 hours)
duration=$((1 * 60 * 60))
wait_time=300

MIN_BURST_BYTES=$((100 * 1024 * 1024))   # 100 MB

CMD_FILE="../download_asf_burst.cmd"

if [[ ! -f "$CMD_FILE" ]]; then
    echo "ERROR: $CMD_FILE not found. Run generate_download_command.py first." >&2
    exit 1
fi

# Line 2: listing command; line 3: download command
listing_cmd=$(sed -n '2p' "$CMD_FILE")
download_cmd=$(sed -n '3p' "$CMD_FILE")

if [[ -z "$listing_cmd" || -z "$download_cmd" ]]; then
    echo "ERROR: $CMD_FILE must have at least 3 lines (invocation, listing, download)." >&2
    exit 1
fi

####################################
# Create burst listing
####################################
echo "$(date +"%Y%m%d-%H:%M") * asf_burst_download.bash: creating listing" | tee -a ../log
echo "Running.... $listing_cmd"
eval "$listing_cmd"

if [[ ! -s asf_burst_listing.txt ]]; then
    echo "ERROR: asf_burst_listing.txt missing or empty after listing command." >&2
    exit 1
fi

# Expected number of bursts (non-empty lines in listing)
num_expected=$(wc -l < asf_burst_listing.txt 2>/dev/null | tr -d ' \n')
[[ -z "$num_expected" ]] && num_expected=0
echo "Expected bursts from listing: $num_expected"

####################################
# Download with retry loop
####################################
elapsed=0
download_ok=0

while [[ $elapsed -lt $duration ]]; do
    echo "$(date +"%Y%m%d-%H:%M") * asf_burst_download.bash: running download (elapsed=${elapsed}s)" | tee -a ../log
    echo "Running.... $download_cmd"
    eval "$download_cmd" || true

    # Count burst tiffs in current directory
    num_actual=0
    for f in *BURST.tiff; do
        [[ -f "$f" ]] && num_actual=$((num_actual + 1))
    done

    echo "Downloaded bursts: $num_actual / $num_expected"

    if [[ $num_actual -ge $num_expected && $num_expected -gt 0 ]]; then
        download_ok=1
        break
    fi
    if [[ $num_expected -eq 0 && $num_actual -eq 0 ]]; then
        download_ok=1
        break
    fi

    echo "Retrying in $wait_time seconds..."
    sleep "$wait_time"
    elapsed=$((elapsed + wait_time))
done

if [[ $download_ok -ne 1 ]]; then
    echo "ERROR: Download did not complete after ${duration}s. Have $num_actual bursts, expected $num_expected." | tee -a ../log
    exit 1
fi

echo "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
echo "Download successful ($num_actual bursts). Checking burst sizes (threshold: 100 MB)..."
echo "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"

####################################
# Size check: remove dates with any burst below MIN_BURST_BYTES
####################################
dates_removed_file="DATES_REMOVED.txt"
dates_to_remove=()

for f in *BURST.tiff; do
    [[ -f "$f" ]] || continue
    size=$(wc -c < "$f" 2>/dev/null | tr -d ' \n')
    [[ -z "$size" ]] && size=0
    if [[ $size -lt $MIN_BURST_BYTES ]]; then
        # Extract date: S1_185680_IW1_20170116T161603_VV_6CBF-BURST.tiff -> 20170116
        date=$(echo "$f" | sed -E 's/.*([0-9]{4})([0-9]{2})([0-9]{2})T.*/\1\2\3/')
        if [[ -n "$date" && "$date" =~ ^[0-9]{8}$ ]]; then
            dates_to_remove+=("$date")
            echo "Will remove date $date (incomplete burst: $f size $size bytes)"
        fi
    fi
done

# Remove each bad date once (deduplicate)
for date in $(printf '%s\n' "${dates_to_remove[@]}" | sort -u); do
    echo "${date}  Burst file below size threshold (100 MB)" >> "$dates_removed_file"
    for g in *"$date"*; do
        [[ -e "$g" ]] || continue
        rm -rf "$g"
    done
done

[[ ${#dates_to_remove[@]} -gt 0 ]] && echo "Dates removed due to size check appended to $dates_removed_file"

echo "asf_burst_download.bash finished successfully."
exit 0
