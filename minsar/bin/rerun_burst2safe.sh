#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
helptext="                                                                          \n\
  Example:                                                                          \n\
      rerun_burst2safe.sh  $TE/qVolcanoSenA44.template                           \n\
                                                                                    \n\
   Script checks for non-zero SLC/run_01_burst2safe_timeouts_0 file. If it exists it\n\
   runs run_01_burst2safe_timeouts_0.job followed by check_burst2safe_job_outputs.py.\n\
   It will produce a modified /run_01_burst2safe_timeouts_0 if there were still      \n\
   timeouts, else this will be zero size.                                            \n\
                                                                                     \n\
   It will rerun for 24 hours.                                                       \n\
     "
    printf "$helptext"
    exit 0;
else
    PROJECT_NAME=$(basename "$1" | awk -F ".template" '{print $1}')
    exit_status="$?"
    if [[ $PROJECT_NAME == "" ]]; then
       echo "Could not compute basename for that file. Exiting. Make sure you have specified an input file as the first argument."
       exit 1;
    fi
fi

template_file=$1
if [[ $1 == $PWD ]]; then
   template_file=$TEMPLATES/$PROJECT_NAME.template
fi
export template_file
WORK_DIR=${SCRATCHDIR}/${PROJECT_NAME}
cd $WORK_DIR

# write command to log file. First create concise name for template file
template_file_dir=$(dirname "$template_file")          # create name including $TE for concise log file
if   [[ $template_file_dir == $TEMPLATES ]]; then
    template_print_name="\$TE/$(basename $template_file)"
elif [[ $template_file_dir == $SAMPLESDIR ]]; then
    template_print_name="\$SAMPLESDIR/$(basename $template_file)"
else
    template_print_name="$template_file"
fi
echo "$(date +"%Y%m%d:%H-%M") * $SCRIPT_NAME $template_print_name ${@:2}" | tee -a "${WORK_DIR}"/log


max_runtime_seconds=$((24 * 3600))  # 24 hours
wait_time=10
start_time=$(date +%s)

while true; do
    # Check if file exists and is non-zero size
    if [[ -s SLC/run_01_burst2safe_timeouts_0 ]]; then
        echo "SLC/run_01_burst2safe_timeouts_0 is non-zero size. Re-running workflow."

        run_workflow.bash $templatefile --jobfile SLC/run_01_burst2safe_timeouts_0 --no-check-job-outputs
        check_burst2safe_job_outputs.py SLC --clean

        echo "[INFO] Sleeping $wait_time seconds..."
        sleep $wait_time
    else
        echo "SLC/run_01_burst2safe_timeouts_0 is zero size. All timeouts are resolved. Exiting loop."
        break
    fi

    # Check elapsed time
    current_time=$(date +%s)
    elapsed=$((current_time - start_time))
    if (( elapsed >= max_runtime_seconds )); then
        echo "[INFO] Reached 24-hour limit. Exiting loop."
        break
    fi
done

#if [[ -s SLC/run_01_burst2safe_timeouts_0 ]]; then
#   run_workflow.bash $templatefile --jobfile SLC/run_01_burst2safe_timeouts_0 --no-check-job-outputs
#   check_burst2safe_job_outputs.py SLC
#fi

