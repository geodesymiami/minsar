##! /bin/bash
#set -x

# Source shared utility functions (Task 4 refactor)
# Determine script directory for relative sourcing
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MINSAR_LIB_DIR="${SCRIPT_DIR}/../lib"
if [[ -f "${MINSAR_LIB_DIR}/workflow_utils.sh" ]]; then
    source "${MINSAR_LIB_DIR}/workflow_utils.sh"
elif [[ -n "${RSMASINSAR_HOME}" && -f "${RSMASINSAR_HOME}/minsar/lib/workflow_utils.sh" ]]; then
    source "${RSMASINSAR_HOME}/minsar/lib/workflow_utils.sh"
fi
###########################################

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
helptext="                                                                         \n\
Job submission script
usage: run_workflow.bash [custom_template_file] [OPTIONS]\n\
                                                                                    \n\
  The template file is OPTIONAL for most use cases.                               \n\
  It is REQUIRED only when using --miaplpy or --dir options.                      \n\
                                                                                    \n\
  Examples (without template file):                                               \n\
      run_workflow.bash --start 2                                                 \n\
      run_workflow.bash --dostep 4                                                \n\
      run_workflow.bash --stop 8                                                  \n\
      run_workflow.bash --start 2 --stop 5                                        \n\
      run_workflow.bash --start mintpy                                            \n\
      run_workflow.bash --dostep insarmaps                                        \n\
      run_workflow.bash --jobfile insarmaps.job                                   \n\
      run_workflow.bash --append                                                  \n\
                                                                                    \n\
  Examples (with template file - REQUIRED for miaplpy):                           \n\
      run_workflow.bash \$SAMPLESDIR/unittestGalapagosSenDT128.template --miaplpy    \n\
      run_workflow.bash \$SAMPLESDIR/unittestGalapagosSenDT128.template --miaplpy --start 2    \n\
      run_workflow.bash \$SAMPLESDIR/unittestGalapagosSenDT128.template --miaplpy --dostep generate_ifgram    \n\
      run_workflow.bash \$SAMPLESDIR/unittestGalapagosSenDT128.template --miaplpy --start load_ifgram    \n\
      run_workflow.bash \$SAMPLESDIR/unittestGalapagosSenDT128.template --dir miaplpy_2015_2021  \n\
      run_workflow.bash \$SAMPLESDIR/unittestGalapagosSenDT128.template --dir miaplpy_2015_2021 --start 9 \n\
      run_workflow.bash \$SAMPLESDIR/unittestGalapagosSenDT128.template --dir miaplpy_2015_2021 --start timeseries_correction \n\
                                                                                   \n\
| Processing steps (start/end/dostep): \n\
                                                                                 \n\
   ['1-16', 'mintpy', 'miaplpy', 'insarmaps' ]                                          \n\
                                                                                 \n\
   In order to use either --start or --dostep, it is necessary that a            \n\
   previous run was done using one of the steps options to process at least      \n\
   through the step immediately preceding the starting step of the current run.  \n\
                                                                                 \n\
   --start STEP          start processing at the named step [default: load_data].\n\
   --end STEP, --stop STEP                                                       \n\
                         end processing at the named step [default: upload]      \n\
   --dostep STEP         run processing at the named step only                   \n\
                                                                                 \n\
   --miaplpy:  requires template file; the run_files directory is determined by the *template file       \n\
   --dir:      for --miaplpy only (see  miaplpyApp.py --help)                    \n\
   --miaplpy --start --end options:                                               \n\
              'load_data', 'phase_linking', 'concatenate_patches', 'generate_ifgram', 'unwrap_ifgram'       \n\
              'load_ifgram', 'ifgram_correction', 'invert_network', 'timeseries_correction'  [1-9] \n\
   --jobfile filename.job: run individual job and wait for completion            \n
   --no-check-job-outputs skip running check_job_outputs.py after completion       \n
   "
    printf "$helptext"
    exit 0;
fi

# Parse optional template file (if first argument doesn't start with --)
template_file=""
if [[ -n "$1" && "$1" != --* ]]; then
    template_file=$1
    shift  # Remove template file from arguments
fi

# Set WORKDIR to current directory
WORKDIR=$(pwd)
cd $WORKDIR

# Set PROJECT_NAME from current directory if no template provided
if [[ -n "$template_file" ]]; then
    PROJECT_NAME=$(basename "$template_file" | awk -F ".template" '{print $1}')
else
    PROJECT_NAME=$(basename "$WORKDIR")
fi

randomorder=false
rapid=false
append=false
dir_miaplpy="miaplpy"
wait_time=30

run_files_name="run_files"

startstep=1
stopstep=11

# FA 4/23: need function to get  stopstep depending on ToPS verus stripmap
dir_flag=false
miaplpy_flag=false

jobfile_flag=0
check_job_outputs_flag=true
jobfiles=()

# Parse command line arguments
while [[ $# -gt 0 ]]
do
    key="$1"

    case $key in
        --start)
            startstep="$2"
            shift # past argument
            shift # past value
            ;;
        --stop)
            stopstep="$2"
            shift
            shift
            ;;
        --dostep)
            startstep="$2"
            stopstep="$2"
            shift
            shift
            ;;
        --random)
            randomorder=true
            shift
            ;;
        --rapid)
            rapid=true
            wait_time=10
            shift
            ;;
        --append)
            append=true
            shift
            ;;
        --miaplpy)
            miaplpy_flag=true
            shift
            ;;
        --no-check-job-outputs)
            check_job_outputs_flag=false
            shift
            ;;
        --jobfile)
            jobfile_flag=true
            jobfile="$2"
            # Handle relative jobfile paths - check if file exists in current directory
            if [[ "$jobfile" != /* ]]; then
                # It's a relative path
                if [[ -f "$PWD/$jobfile" ]]; then
                    jobfile="$PWD/$jobfile"
                elif [[ ! -f "$jobfile" ]]; then
                    echo "ERROR: jobfile '$jobfile' not found in current directory ($PWD) or as absolute path. Exiting."
                    exit 1
                fi
            fi
            shift
            shift
            ;;
        --dir)
            miaplpy_flag=true
            dir_flag=true
            dir_miaplpy="$2"
            shift
            shift
            ;;
        *)
            POSITIONAL+=("$1") # save it in an array for later
            shift # past argument
            ;;
esac
done
set -- "${POSITIONAL[@]}" # restore positional parameters

if [[ $startstep == "miaplpy" ]]; then
   miaplpy_flag=true
fi

# Check if miaplpy requires template file
if [[ $miaplpy_flag == "true" && -z "$template_file" ]]; then
    echo "ERROR: --miaplpy option requires a template file argument. Exiting."
    exit 1
fi

# Log the command invocation with full command line
if [[ -n "$template_file" ]]; then
    # Create a nice print name for the template file
    template_file_dir=$(dirname "$template_file")
    if  [[ $template_file_dir == $TE ]]; then
        template_print_name="\$TE/$(basename $template_file)"
    elif [[ $template_file_dir == $SAMPLESDIR ]]; then
        template_print_name="\$SAMPLESDIR/$(basename $template_file)"
    else
        template_print_name="$template_file"
    fi
    echo "$(date +"%Y%m%d:%H-%M") + run_workflow.bash $template_print_name $@" >> "${WORKDIR}"/log
else
    # Log without template file
    echo "$(date +"%Y%m%d:%H-%M") + run_workflow.bash $@" >> "${WORKDIR}"/log
fi

# Print the collected job files for confirmation
#echo "Job files: ${jobfiles[@]}"
#for jobfile in "${jobfiles[@]}"; do
#    echo "Processing job file: $jobfile"
#done
echo "job from --jobfile: <${jobfile}>"
sleep 1

# MiaplPy step name to number mapping (Task 3 refactor)
declare -A MIAPLPY_STEPS=(
    [load_data]=1 [phase_linking]=2 [concatenate_patches]=3
    [generate_ifgram]=4 [unwrap_ifgram]=5 [load_ifgram]=6
    [ifgram_correction]=7 [invert_network]=8 [timeseries_correction]=9
)

# set startstep, stopstep if miaplpy options are given
echo "startstep, stopstep:<$startstep> <$stopstep>"
if [[ $miaplpy_flag == "true" ]]; then
    # Convert step names to numbers using associative array
    if [[ -n "${MIAPLPY_STEPS[$startstep]}" ]]; then
        startstep="${MIAPLPY_STEPS[$startstep]}"
    elif [[ $startstep != *[1-9]* ]] && [[ $startstep != "mintpy" ]] && [[ $startstep != "miaplpy" ]]; then
        echo "ERROR: $startstep -- not a valid startstep. Exiting."
        exit 1
    fi

    if [[ -n "${MIAPLPY_STEPS[$stopstep]}" ]]; then
        stopstep="${MIAPLPY_STEPS[$stopstep]}"
    elif [[ $stopstep != *[1-9]* ]] && [[ $stopstep != "mintpy" ]] && [[ $stopstep != "miaplpy" ]]; then
        echo "ERROR: $stopstep -- not a valid stopstep. Exiting."
        exit 1
    fi
fi
#echo "startstep, stopstep:<$startstep> <$stopstep>"

# IO load for each step. For step_io_load=1 the maximum tasks allowed is step_max_tasks_unit
# for step_io_load=2 the maximum tasks allowed is step_max_tasks_unit/2

# declare -A  step_io_load_list
# step_io_load_list=(
#     [unpack_topo_reference]=1
#     [unpack_secondary_slc]=1
#     [average_baseline]=1
#     [extract_burst_overlaps]=1
#     [overlap_geo2rdr]=1
#     [overlap_resample]=1
#     [pairs_misreg]=1
#     [timeseries_misreg]=1
#     [fullBurst_geo2rdr]=1
#     [fullBurst_resample]=1
#     [extract_stack_valid_region]=1
#     [merge_reference_secondary_slc]=1
#     [generate_burst_igram]=1
#     [merge_burst_igram]=1
#     [filter_coherence]=1
#     [unwrap]=1

#     [smallbaseline_wrapper]=1
#     [insarmaps]=1

#     [miaplpy_crop]=1
#     [miaplpy_inversion]=1
#     [miaplpy_ifgram]=1
#     [miaplpy_unwrap]=1
#     [miaplpy_un-wrap]=1
#     [miaplpy_mintpy_corrections]=1

    
# )

##### For proper logging to both file and stdout #####
num_logfiles=$(ls $WORKDIR/workflow.*.log 2>/dev/null | wc -l)
test -f $WORKDIR/workflow.0.log  || touch workflow.0.log
if $append; then num_logfiles=$(($num_logfiles-1)); fi
logfile_name="${WORKDIR}/workflow.${num_logfiles}.log"
#printf '' > $logfile_name
#tail -f $logfile_name & 
#trap "pkill -P $$" EXIT
#exec 1>>$logfile_name 2>>$logfile_name
# FA 12/22  for debugging comment previous line out so that STDOUT goes to STDOUT
######################################################

RUNFILES_DIR=$WORKDIR"/"$run_files_name

if [[ $miaplpy_flag == "true" ]]; then
   # get miaplpy run_files directory name
   # This requires the template file
   if [[ ! -z $(grep "^miaplpy.interferograms.networkType" $template_file) ]];  then
      network_type=$(grep -E "^miaplpy.interferograms.networkType" $template_file | awk -F= '{print $2}' |  awk -F# '{print $1}' | tail -1 | xargs  )
      if [[ $network_type == "auto" ]];  then
         network_type=single_reference                  # default of MiaplPy
      fi
   else
      network_type=single_reference                     # default of MiaplPy
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

   RUNFILES_DIR=$WORKDIR"/${dir_miaplpy}/network_${network_type}/run_files"
   echo "RUNFILES_DIR: $RUNFILES_DIR"

   if [ ! -d $RUNFILES_DIR ]; then
       echo "run_files directory $RUNFILES_DIR does not exist -- exiting."
       exit 1;
   fi
      
   echo "Running miaplpy jobs in ${RUNFILES_DIR}"
fi

# Single job file mode - skip all globlist construction (Task 1 refactor)
if [[ $jobfile_flag == "true" ]]; then
    echo "Single job file mode: $jobfile"
    globlist=("$jobfile")
else
    # Normal mode: construct globlist from steps

    #find the last job (11 for 'geometry' and 16 for 'NESD', 9 for stripmap) and remove leading zero
    #jobfile_arr=(ls $RUNFILES_DIR/run_*_0.job)   # before FA 8/2025 change
    jobfile_arr=(ls $RUNFILES_DIR/run_*_*.job)    # FA 8/2025   (not 
    last_jobfile=${jobfile_arr[-1]}
    last_jobfile=${last_jobfile##*/}
    last_jobfile_number=${last_jobfile:4:2}
    last_jobfile_number=$(echo $((10#${last_jobfile_number})))        # FA 10/2025. This probably related to leading zeros (01, 02) etc, but chat suggests to change to last_jobfile_number=$((10#${last_jobfile_number})). That may remove the error
    echo "last jobfile number: <$last_jobfile_number>"

    # Convert named steps (mintpy, insarmaps) to step numbers
    if [[ $startstep == "ifgram" || $startstep == "miaplpy" ]]; then
        startstep=1
    elif [[ $startstep == "mintpy" ]]; then
        # Convert to jobfile mode for mintpy
        jobfile_flag=true
        jobfile="$WORKDIR/smallbaseline_wrapper.job"
        globlist=("$jobfile")
        echo "Converting --start mintpy to single job file mode: $jobfile"
    elif [[ $startstep == "insarmaps" ]]; then
        # Convert to jobfile mode for insarmaps
        jobfile_flag=true
        jobfile="$WORKDIR/insarmaps.job"
        globlist=("$jobfile")
        echo "Converting --start insarmaps to single job file mode: $jobfile"
    fi

    # Only continue with globlist construction if not converted to jobfile mode
    if [[ $jobfile_flag != "true" ]]; then
        if [[ $stopstep == "ifgram" || $stopstep == "miaplpy" || -z ${stopstep+x}  ]]; then
            stopstep=$last_jobfile_number
        elif [[ $stopstep == "mintpy" ]]; then
            stopstep=$((last_jobfile_number+1))
        elif [[ $stopstep == "insarmaps" ]]; then
            stopstep=$((last_jobfile_number+2))
        fi

        echo "last jobfile number: <$last_jobfile_number>, startstep: <$startstep>, stopstep: <$stopstep>"
        
        # Build globlist from numbered steps only (no special handling for smallbaseline/insarmaps)
        for (( i=$startstep; i<=$stopstep; i++ )) do
            stepnum="$(printf "%02d" ${i})"
            if [[ $i -le $last_jobfile_number ]]; then
                fname="$RUNFILES_DIR/run_${stepnum}_*.job"
                globlist+=("$fname")
            fi
        done

        echo "Full list of jobfiles to submit: ${globlist[@]}"
    fi
fi

defaults_file="${RSMASINSAR_HOME}/minsar/defaults/job_defaults.cfg"

echo "Started at: $(date +"%Y-%m-%d %H:%M:%S")"

#echo "QQQ globlist (shown with declare -p):"
#declare -p globlist
clean_array globlist
#echo "QQQ globlist after stripping off empty elements (FA 10/25):"   # FA: 10/25: Simplift to one echo command if there no problems
declare -p globlist

#FA 10/25: This also worked
#original_globlist=("${globlist[@]}")
#globlist=()
#for item in "${original_globlist[@]}"; do
#    [[ -n $item ]] && globlist+=("$item")
#done

for g in "${globlist[@]}"; do
    if [[ -n $g ]]; then
        files=($(ls -1v $g))
    fi

    if $randomorder; then
        files=( $(echo "${files[@]}" | sed -r 's/(.[^;]*;)/ \1 /g' | tr " " "\n" | shuf | tr -d " " ) )
    fi

    echo "Jobfiles to submit:"
    printf "%s\n" "${files[@]}"

    jobnumbers=()
    file_pattern=$(echo "${files[0]}" | grep -oP "(.*)(?=_\d{1,}.job)|insarmaps|smallbaseline_wrapper")
    
    sbc_command="submit_jobs.bash $file_pattern"
    
    if [[ $jobfile_flag == "true" ]]; then
        sbc_command="submit_jobs.bash $jobfile"
    fi

    if $randomorder; then
        sbc_command="$sbc_command --random"
        echo "Jobs are being submitted in random order. Submission order is likely different from the order above."
    fi
    if $rapid; then
        sbc_command="$sbc_command --rapid"
        echo "Rapid job submission enabled."
    fi

    ###############################
    # Here the jobs are submitted #
    ###############################
    echo "Job submission command:"
    echo "$sbc_command"

    jns=$($sbc_command)
    exit_status="$?"
    if [[ $exit_status -eq 0 ]]; then
        jobnumbers=($jns)
    fi

    #echo "Jobs submitted: ${jobnumbers[@]}"      #       FA 8/23 : switch to print comma-separated
    echo "Jobs submitted: $(convert_array_to_comma_separated_string "${jobnumbers[@]}")"
    sleep 5

    # Wait for each job to complete
    num_jobs=${#jobnumbers[@]}
    num_complete=0
    num_running=0
    num_pending=0
    num_timeout=0
    num_waiting=0

    while [[ $num_complete -lt $num_jobs ]]; do
        num_complete=0
        num_running=0
        num_pending=0
        num_waiting=0
        
        sleep $wait_time

        for (( j=0; j < "${#jobnumbers[@]}"; j++)); do
            file=${files[$j]}
            file_pattern="${file%.*}"
            step_name=$(echo $file_pattern | grep -oP "(?<=run_\d{2}_)(.*)(?=_\d{1,})|insarmaps|smallbaseline_wrapper")
            step_name_long=$(echo $file_pattern | grep -oP "(?<=$run_files_name\/)(.*)(?=_\d{1,})|insarmaps|smallbaseline_wrapper")
            jobnumber=${jobnumbers[$j]}
            state=$(sacct --format="State" -j $jobnumber | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | head -3 | tail -1 )
            if [[ $state == *"COMPLETED"* ]]; then
                num_complete=$(($num_complete+1))
            elif [[ $state == *"RUNNING"* ]]; then
                num_running=$(($num_running+1))
            elif [[ $state == *"PENDING"* ]]; then
                num_pending=$(($num_pending+1))
            elif [[ $state == *"TIMEOUT"* || $state == *"NODE_FAIL"* ]]; then
                num_timeout=$(($num_timeout+1))
                #step_max_tasks=$(echo "$SJOBS_STEP_MAX_TASKS/${step_io_load_list[$step_name]}" | bc | awk '{print int($1)}')
        
                if [[ $state == *"TIMEOUT"* ]]; then
                    init_walltime=$(grep -oP '(?<=#SBATCH -t )[0-9]+:[0-9]+:[0-9]+' $file)
                    echo "Job file ${file} timed out with walltime of ${init_walltime}."
                                    
                    # Compute a new walltime and update the job file
                    update_walltime_queuename.py "$file" &> /dev/null
                    updated_walltime=$(grep -oP '(?<=#SBATCH -t )[0-9]+:[0-9]+:[0-9]+' $file)

                    datetime=$(date +"%Y-%m-%d:%H-%M")
                    echo "${datetime}: re-running: ${file}: ${init_walltime} --> ${updated_walltime}" >> "${RUNFILES_DIR}"/rerun.log
                    echo "Resubmitting file (${file}) with new walltime of ${updated_walltime}"
                fi

                jobnumbers=($(remove_from_list $jobnumber "${jobnumbers[@]}"))
                files=($(remove_from_list $file "${files[@]}"))

                # Resubmit as a new job number
                #jobnumber=$(submit_jobs.bash $file_pattern --step_name $step_name --step_max_tasks $step_max_tasks --total_max_tasks $SJOBS_TOTAL_MAX_TASKS 2> /dev/null) 
                jobnumber=$(submit_jobs.bash $file_pattern 2> /dev/null)
                exit_status="$?"
                if [[ $exit_status -eq 0 ]]; then
                    jobnumbers+=("$jobnumber")
                    files+=("$file")
                    j=$(($j-1))
                    echo "Resubmitted as jobumber: ${jobnumber}."
                else
                    echo "Error on resubmit for $jobnumber. Exiting."
                    exit 1
                fi
            elif [[ ( $state == *"FAILED"* || $state ==  *"CANCELLED"* ) ]]; then
                echo "Job $file, $j: state FAILED or CANCELLED. Exiting."
                echo "There could be other problem jobs. Need to change  run_workflow so that it exits after loop over all jobs completed"
                echo "Need to modify code  to resubmit cancelled, failed jobs once (unclear how to count)"
                exit 1; 
            else
                echo "Strange job state: $state, encountered."
                continue;
            fi

        done

        num_waiting=$(($num_jobs-$num_complete-$num_running-$num_pending))

        printf "%s, %s, %-7s: %-12s, %-10s, %-10s, %-12s.\n" "$PROJECT_NAME" "$step_name_long" "$num_jobs jobs" "$num_complete COMPLETED" "$num_running RUNNING" "$num_pending PENDING" "$num_waiting WAITING"
    done

    if [[ "$check_job_outputs_flag" == "true" ]]; then
       # Run check_job_outputs.py on all files
       cmd="check_job_outputs.py  ${files[@]}"
       echo "$cmd"
       $cmd
       exit_status="$?"
       if [[ $exit_status -ne 0 ]]; then
           echo "Error in run_workflow.bash: check_job_outputs.py exited with code ($exit_status)."
           exit 1
       fi
       echo
    fi
done
