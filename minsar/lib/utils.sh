echo "sourcing ${BASH_SOURCE[0]#$MINSAR_HOME/} ..."
#############################################################################
# Function: run_command: executes a command and generates stdout and stderr files
# Usage: run_command <command>
# Example: run_command "smallbaselineApp.py $SAMPLESDIR/unittestGalapagosSenD128.template --dir mintpy"
# Example: run_command "smallbaselineApp.py $SAMPLESDIR/unittestGalapagosSenD128.template --dir mintpy --slurm"
function qrun_command() {
    function show_help() {
        echo "Usage: run_command [OPTIONS] COMMAND"
        echo
        echo "Options:"
        echo "  -h, --help           Show this help message and exit."
        echo "      --prefix PREFIX  Specify a prefix for output files (default: 'out')."
        echo "      --verbose        Enable verbose mode (output is displayed on the terminal)."
        echo "      --slurm          Generate and execute a SLURM jobfile."
        echo
        echo "COMMAND:"
        echo "  The command to execute. All arguments after the options will be treated as the command."
        echo
        echo "Examples:"
        echo "  run_command ls -l"
        echo "  run_command \"ls -l\""
        echo "  run_command --verbose --prefix out1 \"ls -l\""
        echo
        echo "Description:"
        echo "  This function executes a specified command and captures output and errors."
        echo "  In verbose mode, command output is also isplayed on the terminal."
    }
    # Initialize variables
    local verbose=0        # Flag to determine if verbose mode is enabled
    local out_prefix="out0" # Default prefix for output files
    local slurm=0        # Flag to determine if verbose mode is enabled
    local cmd=""           # Variable to store the command to execute

    # Parse options using getopt for long options and reorder the command-line arguments
    TEMP=$(getopt -o h --long help,prefix:,slurm,verbose -- "$@")
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
            --slurm)
                slurm=1
                shift
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

    log_command_line "$cmd"
    ## Generate a timestamp for logging
    #local timestamp
    #timestamp="$(date +"%Y%m%d:%H-%M")"

    ## Log the command being run
    #echo "Running.... $cmd"
    #echo "${timestamp} * $cmd" | tee -a log

    # Define output and error file names with the specified prefix
    local out_file="${out_prefix}_${base_cmd}.o"
    local err_file="${out_prefix}_${base_cmd}.e"

    if [ "$slurm" -eq 1 ]; then
        create_slurm_jobfile.sh "$cmd"

        app_cmd_str="$cmd"
        read -r -a cmd_array <<< "$app_cmd_str"
        app_cmd="${cmd_array[0]}"
        base_cmd="$(basename "$app_cmd")"
        base_cmd="${base_cmd%.py}"
        base_cmd="${base_cmd%.sh}"
        base_cmd="${base_cmd%.bash}"
        job_file="${base_cmd}.job"

        echo "Running....   sbatch $job_file"
        sleep 100
        local exit_status="${PIPESTATUS[0]}"
    elif [ "$verbose" -eq 1 ]; then
        # In verbose mode, pipe stdout to both the out_file and the terminal, stderr is still redirected to the err_file
        eval "$cmd" 2>"$err_file" | tee "$out_file"
        # Capture the exit status of the command (not tee)
        local exit_status="${PIPESTATUS[0]}"
    else
        # In non-verbose mode, redirect stdout tbasho out_file and stderr to err_file
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
# Function: log_command_line: logs command in log file
# Usage: log_command_line <command>
function log_command_line() {
    #set -x
    local log_file="$1"
    shift  # shift off the log file path, leaving only the command args

    local timestamp
    #timestamp="$(date '+%Y%m%d:%H-%M')"
    #timestamp="$(date '+%Y%m%d:%H-%M')"
    timestamp="$(date +"%Y%m%d:%H-%M")"
    #echo QQ "$(date +"%Y%m%d:%H-%M")
    #echo QQQ $timestamp
    # echo "$(date +"%Y%m%d:%H-%M") * minsarApp.bash $template_print_name ${@:2}" | tee -a "${WORK_DIR}"/log



    local transformed_args=()
    for arg in "$@"; do

        # Only transform if the arg ends in ".template".
        if [[ "$arg" == *.template ]]; then
            local arg_dir  arg_basename
            arg_dir="$(dirname "$arg")"
            arg_basename="$(basename "$arg")"

            # Replace directory with $TE or $SAMPLESDIR
            if [[ "$arg_dir" == "$TEMPLATES" ]]; then
                transformed_args+=( "\$TE/$arg_basename" )
            elif [[ "$arg_dir" == "$SAMPLESDIR" ]]; then
                transformed_args+=( "\$SAMPLESDIR/$arg_basename" )
            else
                transformed_args+=( "$arg" )
            fi
        else
            transformed_args+=( "$arg" )
        fi
    done

    echo "${timestamp} * ${0##*/} ${transformed_args[*]}" | tee -a "$log_file"
}

###############################################################################
# Function: get_queue_parameter: gets parameters from defaults/queue.cfg
# Usage: get_queue_parameter <command>
# Example: get_queue_parameter --help
# Example: get_queue_parameter CPUS_PER_NODE
function get_queue_parameter() {

    # Local function to show usage
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

    # Default platform_name / queue_name from environment
    local _platform_name="${PLATFORM_NAME:-}"
    local _queuename="${QUEUENAME:-}"

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

    # We expect exactly 1 leftover: <param_name>
    if [[ $# -ne 1 ]]; then
        echo "Error: Must supply exactly 1 <param_name> argument." >&2
        _show_help_get_queue_parameter
        return 1
    fi
    local param_name="$1"

    # Ensure we have platform_name / queue_name
    if [[ -z "$_platform_name" ]]; then
        echo "Error: No platform name provided, and \$PLATFORM_NAME is empty." >&2
        return 1
    fi
    if [[ -z "$_queuename" ]]; then
        echo "Error: No queue name provided, and \$QUEUENAME is empty." >&2
        return 1
    fi

    # Read from MINSAR_HOME/minsar/defaults/queues.cfg
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

###############################################################################
# Function: get_slurm_job_parameter: gets parameters from defaults/job_defaults.cfg
# Usage: get_slurm_job_parameter <command>
# Example: get_slurm_job_parameter --jobname create_runfiles c_walltime
# Example: get_slurm_job_parameter --help
function get_slurm_job_parameter() {

    # Local function to show usage
    function show_help() {
        cat << EOF
Usage: get_slurm_job_parameter [--help] [--jobname <JOBNAME>] <param_name>

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
  get_slurm_job_parameter --jobname create_runfiles c_walltime
  get_slurm_job_parameter --jobname create_runfiles c_memory
EOF
    }

    local _jobname=""

    local TEMP
    TEMP="$(getopt \
        -o '' \
        --long help,jobname: \
        -n 'get_slurm_job_parameter' -- "$@")"

    if [[ $? -ne 0 ]]; then
        echo "Error: Invalid options to get_slurm_job_parameter." >&2
        return 1
    fi

    eval set -- "$TEMP"

    while true; do
        case "$1" in
            --help)
                show_help
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
        show_help
        return 1
    fi
    local param_name="$1"

    ###########################################################################
    # Ensure we have a jobname
    ###########################################################################
    if [[ -z "$_jobname" ]]; then
        echo "Error: No jobname provided. Use --jobname <JOBNAME>." >&2
        show_help
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

#####################################################################
# Function: get_reference_date:  prints the reference date for a processed dataset
# Usage: get_reference_date
function get_reference_date(){
   reference_date=( $(xmllint --xpath 'string(/productmanager_name/component[@name="instance"]/component[@name="bursts"]/component[@name="burst1"]/property[@name="burststartutc"]/value)' \
                    reference/IW*.xml | cut -d ' ' -f 1 | sed "s|-||g") )
   echo $reference_date
}

#####################################################################
# Function: countbursts: Counts the number of bursts in a dataset.
# Usage: countbursts <dataset>
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
