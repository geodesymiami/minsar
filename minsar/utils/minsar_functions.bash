#set -eo pipefail
###################################################################################
function create_template_array() {
mapfile -t array < <(grep -e ^ssaraopt -e ^minsar -e ^mintpy -e ^miaplpy -e ^topsStack $1)
declare -gA template
for item in "${array[@]}"; do
  #echo "item: <$item>"
  IFS='=' ; read -a arr1 <<< "$item"
  item="${arr1[1]}"
  IFS='#' ; read -a arr2 <<< "$item"
  key="${arr1[0]}"
  key=$(echo $key | tr -d ' ')
  value="${arr2[0]}"
  shopt -s extglob
  value="${value##*( )}"          # Trim leading whitespaces
  value="${value%%*( )}"          # Trim trailing whitespaces
  shopt -u extglob
  #echo "key, value: <$key> <$value>"
  if [ ! -z "$key"  ]; then
     template[$key]="$value"
  fi
unset IFS
done
}

###########################################
function run_command() {
    local cmd="$1"
    echo "Running.... $cmd"
    echo "$(date +"%Y%m%d:%H-%M") * $cmd" | tee -a log
    eval "$cmd"
    local exit_status="$?"
    if [[ $exit_status -ne 0 ]]; then
        echo "$cmd exited with a non-zero exit code ($exit_status). Exiting."
        exit 1;
    fi
}

function run_command2() {
    local cmd="$1"

    # 1) Extract the *first token* of the command.
    #    e.g., "dem_rsmas.py" from "dem_rsmas.py mytemplate.template"
    local base_cmd
    base_cmd="$(echo "$cmd" | awk '{print $1}')"

    # 2) Strip off any leading path (only if the command includes slashes).
    #    e.g., from "/usr/bin/dem_rsmas.py" to "dem_rsmas.py"
    base_cmd="$(basename "$base_cmd")"

    # 3) Remove known extensions: .bash, .sh, .py
    base_cmd="${base_cmd%.bash}"
    base_cmd="${base_cmd%.sh}"
    base_cmd="${base_cmd%.py}"

    # 4) Replace any non-alphanumeric or non-standard characters with "_"
    base_cmd="$(echo "$base_cmd" | sed 's/[^A-Za-z0-9._-]/_/g')"

    # 5) Generate the out_*.o and out_*.e filenames
    local out_file="out_${base_cmd}.o"
    local err_file="out_${base_cmd}.e"

    # 6) Log the command to the main log file
    local timestamp
    timestamp="$(date +"%Y%m%d:%H-%M")"
    echo "Running.... $cmd"
    echo "${timestamp} * $cmd" | tee -a log

    # 7) Execute the command, capturing stdout and stderr
    eval "$cmd" >"$out_file" 2>"$err_file"
    local exit_status="$?"

    # 8) Exit if the command fails
    if [[ $exit_status -ne 0 ]]; then
        echo "$cmd exited with a non-zero exit code ($exit_status). Exiting."
        exit 1
    fi
}

###############################################################################
function log_command_line() {
    local log_file="$1"
    shift  # shift off the log file path, leaving only the command args

    local timestamp
    timestamp="$(date +"%Y%m%d:%H-%M")"

    local transformed_args=()
    for arg in "$@"; do

        # Only transform if the arg ends in ".template".
        if [[ "$arg" == *.template ]]; then
            local arg_dir  arg_basename
            arg_dir="$(dirname "$arg")"
            arg_basename="$(basename "$arg")"

            if [[ "$arg_dir" == "$TEMPLATES" ]]; then
                # Replace directory with $TE
                transformed_args+=( "\$TE/$arg_basename" )
            elif [[ "$arg_dir" == "$SAMPLESDIR" ]]; then
                # Replace directory with $SAMPLESDIR
                transformed_args+=( "\$SAMPLESDIR/$arg_basename" )
            else
                # Directory doesn't match TEMPLATES or SAMPLESDIR
                transformed_args+=( "$arg" )
            fi
        else
            # Not a .template file, just keep it as-is
            transformed_args+=( "$arg" )
        fi
    done

    # Print out timestamp, script name, and transformed arguments
    echo "${timestamp} * ${0##*/} ${transformed_args[*]}" | tee -a "$log_file"
}

###########################################
function get_queue_parameter() {

    ###########################################################################
    # Local function to show usage
    ###########################################################################
    function _show_help_get_queue_parameter() {
        cat << EOF
Usage: get_queue_parameter [--help] [--platform-name <PLATFORM>] [--queuename <QUEUE>] <param_name>

Options:
  --help                    Show usage information and exit
  --platform-name <PLATFORM>Platform name (default: \$PLATFORM_NAME)
  --queuename <QUEUE>       Queue name (default: \$QUEUENAME)

Positional Argument:
  <param_name>              e.g. CPUS_PER_NODE, THREADS_PER_CORE, etc.

Description:
  Looks up <param_name> in \$MINSAR_HOME/minsar/defaults/queues.cfg for the row
  matching <platform_name> <queue_name>. Prints the parameter’s value to stdout.

Examples:
  # 1) Explicit flags
  get_queue_parameter --platform-name stampede3 --queuename skx CPUS_PER_NODE

  # 2) Let it default to the environment:
  export PLATFORM_NAME=stampede3
  export QUEUENAME=skx
  get_queue_parameter CPUS_PER_NODE

EOF
    }

    ###########################################################################
    # Default platform_name / queue_name from environment
    ###########################################################################
    local _platform_name="${PLATFORM_NAME:-}"
    local _queuename="${QUEUENAME:-}"

    ###########################################################################
    # Parse command-line options using GNU getopt
    ###########################################################################
    local TEMP
    TEMP="$(getopt \
        -o '' \
        --long help,platform-name:,queuename: \
        -n 'get_queue_parameter' -- "$@")"

    if [[ $? -ne 0 ]]; then
        echo "Error: Invalid options to get_queue_parameter." >&2
        return 1
    fi

    eval set -- "$TEMP"

    while true; do
        case "$1" in
            --help)
                _show_help_get_queue_parameter
                return 0
                ;;
            --platform-name)
                _platform_name="$2"
                shift 2
                ;;
            --queuename)
                _queuename="$2"
                shift 2
                ;;
            --)
                shift
                break
                ;;
            *)
                echo "Error: Unexpected option '$1'." >&2
                return 1
                ;;
        esac
    done

    ###########################################################################
    # We expect exactly 1 leftover: <param_name>
    ###########################################################################
    if [[ $# -ne 1 ]]; then
        echo "Error: Must supply exactly 1 <param_name> argument." >&2
        _show_help_get_queue_parameter
        return 1
    fi
    local param_name="$1"

    ###########################################################################
    # Ensure we have platform_name / queue_name
    ###########################################################################
    if [[ -z "$_platform_name" ]]; then
        echo "Error: No platform name provided, and \$PLATFORM_NAME is empty." >&2
        return 1
    fi
    if [[ -z "$_queuename" ]]; then
        echo "Error: No queue name provided, and \$QUEUENAME is empty." >&2
        return 1
    fi

    ###########################################################################
    # Read from MINSAR_HOME/minsar/defaults/queues.cfg
    ###########################################################################
    local cfg_file="$MINSAR_HOME/minsar/defaults/queues.cfg"
    if [[ ! -f "$cfg_file" ]]; then
        echo "Error: queues.cfg not found at $cfg_file" >&2
        return 1
    fi

    # Read the header line
    local header
    header="$(head -1 "$cfg_file")"

    local -a header_array
    read -ra header_array <<< "$header"

    # Find the column index of param_name
    local param_index=-1
    for i in "${!header_array[@]}"; do
        if [[ "${header_array[$i]}" == "$param_name" ]]; then
            param_index=$i
            break
        fi
    done

    if [[ $param_index -lt 0 ]]; then
        echo "Error: Parameter '$param_name' not found in header of $cfg_file." >&2
        return 1
    fi

    # Find the line matching <_platform_name> <_queuename>
    local line
    line="$(
      awk -v plat="$_platform_name" -v que="$_queuename" '
        NR>1 && $1==plat && $2==que {print $0}
      ' "$cfg_file"
    )"

    if [[ -z "$line" ]]; then
        echo "Error: No matching line found for '$_platform_name' '$_queuename' in $cfg_file." >&2
        return 1
    fi

    # Extract the value from the found line
    local value
    value="$(echo "$line" | awk -v col=$((param_index+1)) '{print $col}')"

    # Print the result
    echo "$value"
}

###########################################
function get_date_str() {
# get string with start and end date
if  [ ! -z ${template[miaplpy.load.startDate]} ] && [ ! ${template[miaplpy.load.startDate]} == "auto" ]; then
    start_date=${template[miaplpy.load.startDate]}
else
    start_date=$(ls merged/SLC | head -1)
fi
if  [ ! -z ${template[miaplpy.load.endDate]} ] && [ ! ${template[miaplpy.load.endDate]} == "auto" ]; then
    end_date=${template[miaplpy.load.endDate]}
else
    end_date=$(ls merged/SLC | tail -1)
fi
date_str="${start_date:0:6}_${end_date:0:6}"
echo $date_str
}

###########################################
function get_miaplpy_dir_name() {
# assign miaplpyDir.Addition  lalo,dirname or 'miaplpy' for 'auto'
date_str=$(get_date_str)
if [ -z ${template[minsar.miaplpyDir.addition]} ] || [ ${template[minsar.miaplpyDir.addition]} == "auto" ]; then
   miaplpy_dir_name="miaplpy"
elif [ ${template[minsar.miaplpyDir.addition]} == "date" ]; then
   miaplpy_dir_name=miaplpy_${date_str}
elif [ ${template[minsar.miaplpyDir.addition]} == "lalo" ]; then
   if  [ ! -z ${template[miaplpy.subset.lalo]} ]; then
       subset_lalo="${template[miaplpy.subset.lalo]}"
   elif [ ! -z ${template[mintpy.subset.lalo]} ]; then
       subset_lalo="${template[mintpy.subset.lalo]}"
   else
       echo "ERROR: No subset.lalo given -- Exiting"
   fi
   IFS=',' ; read -a lalo_array <<< "$subset_lalo"
   IFS=':' ; read -a lat_array <<< "${lalo_array[0]}"
   IFS=':' ; read -a lon_array <<< "${lalo_array[1]}"
   lat_min=${lat_array[0]}
   lat_max=${lat_array[1]}
   lon_min=${lon_array[0]}
   lon_max=${lon_array[1]}
   lalo_str=$(printf "%.2f_%.2f_%.2f_%.2f\n" "$lat_min" "$lat_max" "$lon_min" "$lon_max")
   miaplpy_dir_name="miaplpy_${lalo_str}_$date_str"
else
   miaplpy_dir_name=miaplpy_"${template[minsar.miaplpyDir.addition]}"_${date_str}
fi
unset IFS
echo $miaplpy_dir_name
}
###########################################
function get_network_type {
# get single_reference or delaunay_4 ect. from template file
network_type=${template[miaplpy.interferograms.networkType]}
if [[ $network_type == "auto" ]] || [[ -z "$network_type" ]];   then
      network_type=single_reference                  # default of MiaplPy
fi
if [[ $network_type == "sequential" ]];  then
   if [[ ! -z $(grep "^miaplpy.interferograms.connNum" $template_file) ]];  then
      connection_number=$(grep -E "^miaplpy.interferograms.connNum" $template_file | awk -F= '{print $2}' |  awk -F# '{print $1}' | xargs  )
   else
      connection_number=3                            # default of MiaplPy
   fi
   network_type=${network_type}_${connection_number}
fi
if [[ $network_type == "delaunay" ]];  then
   if [ ! -z $(grep "^miaplpy.interferograms.delaunayBaselineRatio" $template_file) ] &&  [ ! ${template[miaplpy.interferograms.delaunayBaselineRatio]} == "auto" ]; then
      delaunay_baseline_ratio=$(grep -E "^miaplpy.interferograms.delaunayBaselineRatio" $template_file | awk -F= '{print $2}' |  awk -F# '{print $1}' | xargs  )
   else
      delaunay_baseline_ratio=4                            # default of MiaplPy
   fi
   network_type=${network_type}_${delaunay_baseline_ratio}
fi
echo $network_type
}

#####################################################################
function get_reference_date(){
   reference_date=( $(xmllint --xpath 'string(/productmanager_name/component[@name="instance"]/component[@name="bursts"]/component[@name="burst1"]/property[@name="burststartutc"]/value)' \
                    reference/IW*.xml | cut -d ' ' -f 1 | sed "s|-||g") )
   echo $reference_date
}

#####################################################################
function countbursts(){
                   #set -xv
                   subswaths=geom_reference/*
                   unset array
                   declare -a array
                   for subswath in $subswaths; do
                       icount=`ls $subswath/hgt*rdr | wc -l`
                       array+=($(basename $icount))
                   done;
                   reference_date=$(get_reference_date)
                   echo "geom_reference/$reference_date   #of_bursts: `ls geom_reference/IW*/hgt*rdr | wc -l`   ${array[@]}"

                   dates="coreg_secondarys/*"
                   for date in $dates; do
                       subswaths=$date/???
                       unset array
                       declare -a array
                       for subswath in $subswaths; do
                           icount=`ls $subswath/burst*xml | wc -l`
                           array+=($(basename $icount))
                       done;
                       echo "$date #of_bursts: `ls $date/IW*/burst*xml | wc -l`   ${array[@]}"
                   done;
                   }
###########################################

