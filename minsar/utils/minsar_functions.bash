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
function run_command0() {
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

###########################################
function run_command2() {
#############################################################################

    local cmd="$1"

    #  Extract the *first token* of the command, strip off any leading path and extension, replace any non-standard characters with "_"
    local base_cmd
    base_cmd="$(echo "$cmd" | awk '{print $1}')"
    base_cmd="$(basename "$base_cmd")"
    base_cmd="${base_cmd%.bash}"
    base_cmd="${base_cmd%.sh}"
    base_cmd="${base_cmd%.py}"
    base_cmd="$(echo "$base_cmd" | sed 's/[^A-Za-z0-9._-]/_/g')"

    local timestamp
    timestamp="$(date +"%Y%m%d:%H-%M")"
    echo "Running.... $cmd"
    echo "${timestamp} * $cmd" | tee -a log

    # Execute the command, capturing stdout and stderr
    local out_file="out_${base_cmd}.o"
    local err_file="out_${base_cmd}.e"

    eval "$cmd" >"$out_file" 2>"$err_file"
    local exit_status="$?"
    if [[ $exit_status -ne 0 ]]; then
        echo "$cmd exited with a non-zero exit code ($exit_status). Exiting."
        exit 1
    fi
}


#############################################################################
# Function to run a command with logging and optional verbosity
function run_command() {
    # Local function to display help for run_command2
    function show_help() {
        echo "Usage: run_command [OPTIONS] COMMAND"
        echo
        echo "Options:"
        echo "  -h, --help           Show this help message and exit."
        echo "      --prefix PREFIX  Specify a prefix for output files (default: 'out')."
        echo "      --verbose        Enable verbose mode (output is displayed on the terminal)."
        echo
        echo "COMMAND:"
        echo "  The command to execute. All arguments after the options will be treated as the command."
        echo
        echo "Examples:"
        echo "  run_command ls -l"
        echo "  run_command \"ls -l\""
        echo "  run_command --verbose --prefix out1 \"ls -l\""
        echo "  run_command --dir /path/to/dir --data-type csv process_data.sh"
        echo
        echo "Description:"
        echo "  This function executes a specified command, captures output and errors into separate files with an optional prefix."
        echo "  In verbose mode, command output is displayed on the terminal as well as logged."
    }
    # Initialize variables
    local verbose=0        # Flag to determine if verbose mode is enabled
    local out_prefix="out0" # Default prefix for output files
    local cmd=""           # Variable to store the command to execute

    # Parse options using getopt for long options and reorder the command-line arguments
    TEMP=$(getopt -o h --long help,prefix:,verbose -- "$@")
    if [ $? -ne 0 ]; then
        echo "Error: Failed to parse options." >&2
        return 1
    fi
    eval set -- "$TEMP"

    # Process parsed options
    while true; do
        case "$1" in
            --prefix)
                out_prefix="$2"
                shift 2
                ;;
            --verbose)
                verbose=1
                shift
                ;;
            --dir)
                processing_dir="$2"
                shift 2
                ;;
            -h|--help)
                show_help
                return 0
                ;;
            --)
                shift
                break
                ;;
            *)
                # This should never happen
                echo "Error: Unexpected option '$1'." >&2
                return 1
                ;;
        esac
    done

    # Check if the command is provided
    if [ $# -lt 1 ]; then
        echo "Error: Missing command to execute." >&2
        echo "Use --help for usage information." >&2
        return 1
    fi

    # Combine all remaining arguments into the command string
    cmd="$*"

    # Extract the first token of the command for naming output files
    local base_cmd
    base_cmd="$(echo "$cmd" | awk '{print $1}')"
    base_cmd="$(basename "$base_cmd")"
    base_cmd="${base_cmd%.bash}"
    base_cmd="${base_cmd%.sh}"
    base_cmd="${base_cmd%.py}"
    base_cmd="$(echo "$base_cmd" | sed 's/[^A-Za-z0-9._-]/_/g')"

    # Generate a timestamp for logging
    local timestamp
    timestamp="$(date +"%Y%m%d:%H-%M")"

    # Log the command being run
    echo "Running.... $cmd"
    echo "${timestamp} * $cmd" | tee -a log

    # Define output and error file names with the specified prefix
    local out_file="${out_prefix}_${base_cmd}.o"
    local err_file="${out_prefix}_${base_cmd}.e"

    # Execute the command with appropriate redirection based on verbosity
    if [ "$verbose" -eq 1 ]; then
        # In verbose mode, pipe stdout to both the out_file and the terminal
        # stderr is still redirected to the err_file
        eval "$cmd" 2>"$err_file" | tee "$out_file"
        # Capture the exit status of the command (not tee)
        local exit_status="${PIPESTATUS[0]}"
    else
        # In non-verbose mode, redirect stdout to out_file and stderr to err_file
        eval "$cmd" >"$out_file" 2>"$err_file"
        local exit_status="$?"
    fi

    # Check the exit status of the command
    if [[ $exit_status -ne 0 ]]; then
        echo "Error: Command '$cmd' exited with a non-zero status ($exit_status)." >&2
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
  --platform-name           Platform name (default: \$PLATFORM_NAME)
  --queuename               Queue name (default: \$QUEUENAME)

Positional Argument:
  <param_name>              e.g. CPUS_PER_NODE, THREADS_PER_CORE, etc.

Description:
  Looks up <param_name> in minsar/defaults/queues.cfg and prints to stdout

Examples:
  get_queue_parameter --platform-name stampede3 --queuename skx CPUS_PER_NODE
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
function get_job_parameter() {

    # Local function to show usage
    function _show_help_get_job_parameter() {
        cat << EOF
Usage: get_job_parameter [--help] [--jobname <JOBNAME>] <param_name>

Options:
  --help                Show usage information and exit
  --jobname <JOBNAME>   Name of the job (required)

Positional Argument:
  <param_name>          e.g. c_walltime, s_walltime, c_memory, s_memory, etc.

Description:
  Reads \$MINSAR_HOME/minsar/defaults/job_defaults.cfg, which contains lines of
  the form:
    jobname c_walltime s_walltime seconds_factor c_memory s_memory ...
  Looks for a row whose first column is <JOBNAME>, then extracts the column
  named <param_name>.

Examples:
  get_job_parameter --jobname create_runfiles c_walltime
  get_job_parameter --jobname create_runfiles c_memory
EOF
    }

    # We'll store the jobname in a local variable. No default is assumed here;
    # we require the user to provide --jobname or we error out.
    local _jobname=""

    local TEMP
    TEMP="$(getopt \
        -o '' \
        --long help,jobname: \
        -n 'get_job_parameter' -- "$@")"

    if [[ $? -ne 0 ]]; then
        echo "Error: Invalid options to get_job_parameter." >&2
        return 1
    fi

    eval set -- "$TEMP"

    while true; do
        case "$1" in
            --help)
                _show_help_get_job_parameter
                return 0
                ;;
            --jobname)
                _jobname="$2"
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

    # After parsing, we expect exactly 1 leftover: <param_name>
    if [[ $# -ne 1 ]]; then
        echo "Error: Must supply exactly 1 <param_name> argument." >&2
        _show_help_get_job_parameter
        return 1
    fi
    local param_name="$1"

    ###########################################################################
    # Ensure we have a jobname
    ###########################################################################
    if [[ -z "$_jobname" ]]; then
        echo "Error: No jobname provided. Use --jobname <JOBNAME>." >&2
        _show_help_get_job_parameter
        return 1
    fi

    ###########################################################################
    # Config file location
    ###########################################################################
    local cfg_file="$MINSAR_HOME/minsar/defaults/job_defaults.cfg"
    if [[ ! -f "$cfg_file" ]]; then
        echo "Error: job_defaults.cfg not found at $cfg_file" >&2
        return 1
    fi

    # 1) Read header line
    local header
    header="$(grep -v '^#' "$cfg_file" | grep -v '^-*$' | head -1)"

    # 2) Convert header into an array
    local -a header_array
    read -ra header_array <<< "$header"

    # 3) Find the zero-based index of param_name
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

    # 4) Find the line whose first column == _jobname
    #    (We skip header line with NR>1)
    local line
    line="$(
      awk -v jname="$_jobname" '
        NR>1 && $1==jname {print $0}
      ' "$cfg_file"
    )"

    if [[ -z "$line" ]]; then
        echo "Error: No matching line found for jobname '$_jobname' in $cfg_file." >&2
        return 1
    fi

    # 5) Extract the value from the found line
    #    Because AWK uses 1-based indexing, we do param_index+1
    local value
    value="$(echo "$line" | awk -v col=$((param_index+1)) '{print $col}')"

    # 6) Print the result
    echo "$value"
}

#cfalk
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

