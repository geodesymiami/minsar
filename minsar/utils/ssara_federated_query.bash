#!/usr/bin/env bash

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
helptext="                                                                                                           \n\
   Downloads data.  It first run ssara_federated_query.py to create ssara_listing.txt and ssara_search*.kml files.   \n\
   Then it reads file URLs from ssara_listing.txt  and downloads using wget                                          \n\
                                                                                                                     \n\
   Example:                                                                                                         \n\
      ssara_federated_quey.bash --relativeOrbit=15 --intersectsWith='Polygon((4 49, 4 51, 10 51, 10 49, 4 49))' --platform=SENTINEL-1A,SENTINEL-1B --parallel=6 --maxResults=20000 \n\
                                                                                                                     \n\
"
   printf "$helptext"
   exit 0;
fi

cmd=""
parallel=5  # Set default value for parallel
for arg in "$@"; do
  if [[ "$arg" == --intersectsWith=* ]]; then
    # Extract the value right after '=' and wrap it with single quotes
    value="${arg#--intersectsWith=}"
    arg="--intersectsWith='$value'"
  elif [[ "$arg" == --collectionName=* ]]; then
    # Extract the value right after '=' and wrap it with double quotes
    value="${arg#--collectionName=}"
    arg="--collectionName=\"$value\""
  fi
  if [[ "$arg" == --parallel* ]]; then
    parallel="${arg#--parallel=}"
  fi
  # Append each argument to the command
  # echo "QQ: <$arg> <$cmd>"
  cmd+=" $arg"
done

# writing command to logfile including '' for intersectsWith
echo "$(date +"%Y%m%d-%H:%m") * `basename "$0"` $cmd " >> log

asfResponseTimeout_opt="--asfResponseTimeout=300"
for arg in "$@"; do
    if [[ "$arg" == *"TSX"* ]] || [[ $arg == *COSMO* ]]; then
        asfResponseTimeout_opt=""
    fi
done

############################################################
# run ssara_federated_query.py to create ssara_listing.txt #
############################################################
rm -f ssara_listing.txt
cmd="ssara_federated_query.py $cmd $asfResponseTimeout_opt --kml --print > ssara_listing.txt 2> ssara.e"

# Try for 2 days if error 502 occurs
elapsed=0
duration=$((2 * 24 * 60 * 60)) # 2 days in seconds
wait_time=300
#duration=30
wait_time=10

while [ $elapsed -lt $duration ]; do
    # Log and run the command
    echo "$(date +"%Y%m%d-%H:%M") * $cmd " >> log
    echo "Running.... $cmd"
    eval "$cmd"

    # Check for error 502
    if grep -q "urllib.error.HTTPError: HTTP Error 502: Proxy Error" ssara.e; then
        echo -e "Download problem: urllib.error.HTTPError: HTTP Error 502: Proxy Error. Retrying in $wait_time seconds...\n"
        sleep $wait_time                  # Wait for 300 seconds before retrying
        elapsed=$((elapsed + $wait_time)) # Increment the elapsed time
    # Check for error 500
    elif grep -q "urllib.error.HTTPError: HTTP Error 500: Internal Server Error" ssara.e; then
        echo -e  "Download problem: urllib.error.HTTPError: HTTP Error 500: Internal Server Error. Retrying in $wait_time seconds...\n"
        sleep $wait_time     # Wait for 300 seconds before retrying
        elapsed=$((elapsed + $wait_time)) # Increment the elapsed time
#    elif grep -q "ERROR 404: Not Found" wget.e; then
#        # FA 12/2024:  I did not check whether this works, in particular whether removing wget.e is the right thing to do
#        echo -e  "wget download problem: ERROR 404: Not Found. Retrying in $wait_time seconds...\n"
#        rm wget.e
#        sleep $wait_time     # Wait for 300 seconds before retrying
#        elapsed=$((elapsed + $wait_time)) # Increment the elapsed time
#    elif grep -q "ERROR 403: Forbidden" wget.e; then
#        # FA 5/2025:  addded as MiamitestTsxSMDT36 gave HTTP Error 403: Forbidden
#        echo -e  "wget download problem: QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ"
#        echo -e  "wget download problem: HTTP Error 403: Forbidden. Retrying in $wait_time seconds...\n"
#        rm wget.e
#        sleep $wait_time     # Wait for 300 seconds before retrying
#        elapsed=$((elapsed + $wait_time)) # Increment the elapsed time
#        echo "QQQQQQQ: Elapsed time $elapsed"
    else
        echo "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
        echo "Successfully downloaded ssara_listing.txt (no 500 or 502 error detected.)"
        echo "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
        break # Exit the loop if no 502 error is detected
    fi
done

# Check if the loop exited because the duration was exceeded
if [ $elapsed -ge $duration ]; then
    echo "Download problem persists after $duration seconds. Exiting."
    exit 1
fi

# select password according to satellite
if [[ $cmd == *SENTINEL* ]]; then
   user=`grep asfuser $SSARAHOME/password_config.py | sed 's/\"//g''' | cut -d '=' -f 2`
   passwd=`grep asfpass $SSARAHOME/password_config.py | sed 's/\"//g''' | cut -d '=' -f 2`
elif [[ $cmd == *COSMO-SKYMED* ]] || [[ $cmd == *ALOS-2* ]] || [[ $cmd == *TSX* ]]; then
   user=`grep unavuser $SSARAHOME/password_config.py | sed 's/\"//g''' | cut -d '=' -f 2`
   passwd=`grep unavpass $SSARAHOME/password_config.py | sed 's/\"//g''' | cut -d '=' -f 2`
   regex="https:\/\/imaging\.unavco\.\.org\/[a-zA-Z\/0-9\_]+\.tar\.gz"
   regex="https:\/\/imaging\.unavco\.\.org\/*\.gz"
fi

downloads_num=$(grep Found ssara_listing.txt | cut -d " " -f 2)
echo "Number of granules in ssara_listing.txt : $downloads_num"

urls_list=$(cut -s -d ',' -f 14 ssara_listing.txt)
unset IFS
urls=($urls_list)

num_urls=${#urls[@]}

echo "URLs to download: ${urls[@]}"
echo "$(date +"%Y%m%d:%H-%m") * Datafiles to download: $num_urls" | tee -a log

timeout=500

echo "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
echo "XXX  Download with wget through xargs XXXX"
echo "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"

runs=1
new_timeout=$timeout
elapsed=0
exit_code=1    # set exit_code to 1 so that it does not think it was already successful
while [[ "$exit_code" -ne 0 ]] && [[ "$elapsed" -lt "$duration" ]]; do
    rm -f wget.e
    echo "Run $runs of wget downloads using xargs. elapsed, wait_time, duration, timeout:  $elapsed, $wait_time, $duration, $new_timeout"
    ######################## Actual data download command using wget  ######################################################
    echo "Downloading using command: echo $URLs | xargs -n 1 -P $parallel timeout $new_timeout wget --continue --user $user --password $passwd --quiet" | tee -a log
    echo ${urls[@]} | xargs -n 1 -P $parallel timeout $new_timeout wget --continue --user $user --password $passwd --quiet 2>> wget.e
    exit_code=$?
    if [[ $exit_code -ne 0 ]]; then 
       new_timeout=$(echo "$timeout * 5" | bc)
       echo "$(date +"%Y%m%d:%H-%m") * Something went wrong. Exit code was ${exit_code}. Trying again with $new_timeout second timeout" | tee -a log
    fi

    echo "$(date +"%Y%m%d:%H-%m") check_download: `check_download.py $PWD --delete`"  | tee -a log
    granules_num=$(ls *.{zip,tar.gz} 2> /dev/null | wc -l)
    echo "$(date +"%Y%m%d:%H-%m") * Downloaded scenes after check_download: $granules_num" | tee -a log

    runs=$((runs+1))
    elapsed=$((elapsed + $wait_time)) # Increment the elapsed time
    sleep 1
done

if [[ $granules_num -ge $num_urls ]]; then
   echo "Download was successful, downloaded scenes: $granules_num" | tee -a log
   exit 0;
else
  echo "ERROR: Only $granules_num of $num_urls scenes downloaded."  | tee -a log
  exit 1;
fi

