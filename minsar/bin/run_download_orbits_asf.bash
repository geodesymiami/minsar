#!/usr/bin/env bash
#############################################################
# download latest orbits from ASF mirror
set -uo pipefail

show_help() {
    echo "Usage: ${0##*/}"
    echo
    echo "Downloads the latest orbits from ASF."
    echo
    echo "Options:"
    echo "  --help    Show this help message and exit"
    echo
    echo "Examples:"
    echo "  ${0##*/}"
}

# ---------------------------------------------
# Handle command-line arguments (if any)
# ---------------------------------------------
if [[ $# -gt 0 ]]; then
  case "$1" in
    --help|-h)
      show_help
      exit 0
      ;;
    *)
      echo "Error: Unknown argument '$1'" >&2
      show_help
      exit 1
      ;;
  esac
fi

echo "Preparing to download latest poe and res orbits from ASF..."
cd $SENTINEL_ORBITS
rm -f failed_poe.txt failed_res.txt ASF_poeorb_latest.txt ASF_resorb_latest.txt

year=$(date +%Y)
current_month=$(date +%Y%m)
previous_month=$(date -d'-1 month' +%Y%m)

MAX_RETRIES=$((24*60))  # retry 1 day every 60 seconds
#MAX_RETRIES=5  # retry 5 minutes very 60 seconds
SLEEP_SECONDS=60
attempt=0

while (( attempt < MAX_RETRIES )); do
    echo "=== Attempt $((attempt+1)) at $(date) ==="

    #############################################################
    # Step 1: download listings
    #############################################################
    curl --ftp-ssl-reqd --silent --use-ascii --ftp-method nocwd --list-only https://s1qc.asf.alaska.edu/aux_poeorb/ > ASF_poeorb.txt
    curl_status1=$?

    curl --ftp-ssl-reqd --silent --use-ascii --ftp-method nocwd --list-only https://s1qc.asf.alaska.edu/aux_resorb/ > ASF_resorb.txt
    #curl --connect-timeout 1 --max-time 2 https://10.255.255.1/  # test-only call (can be removed)
    curl_status2=$?

    if [[ $curl_status1 -eq 0 && $curl_status2 -eq 0 ]]; then
        break
    fi
    echo "curl command failed (status $curl_status1 / $curl_status2), retrying in $SLEEP_SECONDS secs..."
    sleep "$SLEEP_SECONDS"
    ((attempt++))
done

############################################################
# Step 2: generate download script that uses wget
#############################################################
cat ASF_poeorb.txt | awk '{printf "if ! test -f %s; then wget -c https://s1qc.asf.alaska.edu/aux_poeorb/%s || echo %s >> failed_poe.txt; fi\n", substr($0,10,77), substr($0,10,77), substr($0,10,77)}' | grep "$year" > ASF_poeorb_latest.txt
cat ASF_resorb.txt | awk '{printf "if ! test -f %s; then wget -c https://s1qc.asf.alaska.edu/aux_resorb/%s || echo %s >> failed_res.txt; fi\n", substr($0,10,77), substr($0,10,77), substr($0,10,77)}' | grep "$current_month"  > ASF_resorb_latest.txt
cat ASF_resorb.txt | awk '{printf "if ! test -f %s; then wget -c https://s1qc.asf.alaska.edu/aux_resorb/%s || echo %s >> failed_res.txt; fi\n", substr($0,10,77), substr($0,10,77), substr($0,10,77)}' | grep "$previous_month" >> ASF_resorb_latest.txt

############################################################
# Step 3: Start wget download 
#############################################################
echo "Downloading poe and res orbits: running bash ASF_poeorb_latest.txt, ASF_resorb_latest.txt in orbit directory  $SENTINEL_ORBITS  ..."
while (( attempt < MAX_RETRIES )); do
    bash ASF_poeorb_latest.txt
    bash ASF_resorb_latest.txt

    #############################################################
    # Step 4: Check if downloads failed
    #############################################################
    if [[ ! -s failed_poe.txt && ! -s failed_res.txt ]]; then
        echo "All orbit files downloaded successfully."
        break
    else
        echo "Some downloads failed. Retrying in $SLEEP_SECONDS seconds..."
        # Rebuild download scripts only with failed files
        if [[ -s failed_poe.txt ]]; then
            awk '{printf "wget -c https://s1qc.asf.alaska.edu/aux_poeorb/%s || echo %s >> failed_poe.txt\n", $1, $1}' failed_poe.txt > ASF_poeorb_latest.txt
        fi
        if [[ -s failed_res.txt ]]; then
            awk '{printf "wget -c https://s1qc.asf.alaska.edu/aux_resorb/%s || echo %s >> failed_res.txt\n", $1, $1}' failed_res.txt > ASF_resorb_latest.txt
        fi
        rm -f failed_poe.txt failed_res.txt
        sleep "$SLEEP_SECONDS"
        ((attempt++))
    fi
done

if (( attempt == MAX_RETRIES )); then
    echo "ERROR: Orbit download failed after 1 day of retries." >&2
    exit 28
fi
cd -
