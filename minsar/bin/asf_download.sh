#!/usr/bin/env bash

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
helptext="                                                                                                           \n\
   Downloads data using asf_search_args.py which uses asf_search                                                     \n\
                                                                                                                     \n\
   Example:                                                                                                         \n\
      asf_download.sh --product=SLC --relativeOrbit=163 --intersectsWith='Polygon((125.3 2.1, 125.5 2.1, 125.5 2.4, 125.3 2.4, 125.3 2.1))' --platform=SENTINEL-1A,SENTINEL-1B --start=2025-04-01 --end=2020-05-31 --parallel=6 --dir=SLC\n\
      asf_download.sh --product=SLC --relativeOrbit=163 --intersectsWith='Polygon((125.3 2.1, 125.5 2.1, 125.5 2.4, 125.3 2.4, 125.3 2.1))' --platform=SENTINEL-1A,SENTINEL-1B\n\
                                                                                                   \n\
"
   printf "$helptext"
   exit 0;
fi

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
echo "$(date +"%Y%m%d:%H-%M") + $SCRIPT_NAME $*" | tee -a log

cmd="asf_search_args.py"
for arg in "$@"; do
  if [[ "$arg" == --intersectsWith=* ]]; then
    # Extract the value right after '=' and wrap it with single quotes
    value="${arg#--intersectsWith=}"
    arg="--intersectsWith='$value'"
  fi
  # Append each argument to the command
  cmd+=" $arg"
done

waittime=10           # seconds to wait between retries
timeout=86400          # total seconds before giving up

start_time=$(date +%s)
logfile="download_retry.log"
> "$logfile"

# Retry loop
while true; do
    echo "Starting download at $(date)" | tee -a "$logfile"
    #set -x
    echo "running ... $cmd"
    eval "$cmd"
    exit_status="$?"
    if [ $exit_status -eq 0 ]; then
        echo "Download completed successfully." | tee -a "$logfile"
        break
    fi

    # Check for HTTP 50x errors in the log
    if grep -E "HTTP Error 50[0-9]|502 Server Error|50[0-9]: Proxy Error|50[0-9]: Internal Server Error" "$logfile"; then
        echo "Encountered server error (HTTP 50x). Retrying in $waittime seconds..." | tee -a "$logfile"
        sleep "$waittime"

        now=$(date +%s)
        elapsed=$((now - start_time))

        if [ $elapsed -ge $timeout ]; then
            echo "Repeated 50x errors. Exiting after $timeout seconds." | tee -a "$logfile"
            exit 1
        fi
    else
        echo "Download failed with non-retryable error. Exiting." | tee -a "$logfile"
        exit $exit_code
    fi
done

# removing files https://github.com/isce-framework/isce2/issues/956#issuecomment-3062201116
rm -f SLC/*20250429*
rm -f SLC/*20250430*
rm -f SLC/*20250501*
