#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

echo "sourcing ${SCRIPT_DIR}/../lib/minsarApp_specifics.sh ..."
echo "sourcing ${SCRIPT_DIR}/../lib/utils.sh ..."
source ${SCRIPT_DIR}/../lib/minsarApp_specifics.sh
source ${SCRIPT_DIR}/../lib/utils.sh

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
helptext="                                                                       \n\
  Examples:                                                                      \n\
      minsarApp.bash  $TE/GalapagosSenDT128.template                             \n\
      minsarApp.bash  $TE/GalapagosSenDT128.template --dostep dem                \n\
      minsarApp.bash  $TE/GalapagosSenDT128.template --start  ifgram            \n\
      minsarApp.bash  $TE/GalapagosSenDT128.template --start jobfiles --mintpy --miaplpy\n\
      minsarApp.bash  $TE/GalapagosSenDT128.template --no-insarmaps                             \n\
                                                                                 \n\
  Processing steps (start/end/dostep): \n\
   Command line options for steps processing with names are chosen from the following list: \n\
                                                                                 \n\
   ['download', 'dem', 'jobfiles', 'ifgram', 'mintpy', 'miaplpy']                \n\
                                                                                 \n\
   --upload    [--no-upload]    upload data products to jetstream (default)      \n\
   --insarmaps [--no-insarmaps] ingest into insarmaps (default is yes for mintpy no for miaplpy)  \n\
                                                                                 \n\
   In order to use either --start or --dostep, it is necessary that a            \n\
   previous run was done using one of the steps options to process at least      \n\
   through the step immediately preceding the starting step of the current run.  \n\
                                                                                 \n\
   --start STEP          start processing at the named step [default: download]. \n\
   --end STEP, --stop STEP                                                       \n\
   --dostep STEP         run processing at the named step only                   \n\
                                                                                 \n\
   --mintpy              use smallbaselineApp.py for time series [default]       \n\
   --miaplpy             use miaplpyApp.py                                       \n\
   --mintpy --miaplpy    use smallbaselineApp.py and miaplpyApp.py               \n\
   --no-mintpy --miaplpy use only miaplpyApp.py                                  \n\
                                                                                 \n\
   --asf-download        download using asf_search (Default: ssara)              \n\
   --burst-download      download burst instead of frames                        \n\
   --no-orbit-download   don't download prior to jobfile creation                \n\
                                                                                 \n\
   --sleep SECS           sleep seconds before running                           \n\
   --select_reference     select reference date [default].                       \n\
   --no_select_reference  don't select reference date.                           \n\
   --chunks         process in form of multiple chunks.                          \n\
   --debug
                                                                                 \n\
   Coding To Do:                                                                 \n\
       - clean up run_workflow (remove smallbaseline.job insarmaps.job)          \n\
       - move bash functions into minsarApp_functions.bash                       \n\
       - change flags from 0/1 to False/True for reading from template file      \n\
       - create a command execution function (cmd_exec)                          \n\
       - create .minsarrc for defaults                                           \n
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
mkdir -p $WORK_DIR
cd $WORK_DIR

# create name including $TE for concise log file
template_file_dir=$(dirname "$template_file")          # create name including $TE for concise log file
if   [[ $template_file_dir == $TEMPLATES ]]; then
    template_print_name="\$TE/$(basename $template_file)"
elif [[ $template_file_dir == $SAMPLESDIR ]]; then
    template_print_name="\$SAMPLESDIR/$(basename $template_file)"
else
    template_print_name="$template_file"
fi
echo "$(date +"%Y%m%d:%H-%M") * $SCRIPT_NAME $template_print_name ${@:2}" | tee -a "${WORK_DIR}"/log
cli_command=$(echo "$SCRIPT_NAME $template_print_name ${@:2}")

#Switches
chunks_flag=0
jobfiles_flag=1
orbit_download_flag=1
select_reference_flag=1
new_reference_flag=0
debug_flag=0
download_ECMWF_flag=1
download_ECMWgF_before_mintpy_flag=0

runfiles_dir="run_files_tmp"
configs_dir="configs_tmp"

args=( "$@" )    # copy of command line arguments

##################################
# set defaults steps (insarmaps_flag and upload_flag are set to 0 if not given on command line or in template file )
download_flag=1
dem_flag=1
ifgram_flag=1
mintpy_flag=1
miaplpy_flag=0
finishup_flag=1

ssara_download_flag=1

##################################

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
        --mintpy)
            mintpy_flag=1
            shift
            ;;
        --no-mintpy)
            mintpy_flag=0
            shift
            ;;
        --miaplpy)
            miaplpy_flag=1
            shift
            ;;
        --insarmaps)
            insarmaps_flag=1
            shift
            ;;
        --no-insarmaps)
            insarmaps_flag=0
            shift
            ;;
        --upload)
            upload_flag=1
            shift
            ;;
        --no-upload)
            upload_flag=0
            shift
            ;;
        --no-orbit-download)
            orbit_download_flag=0
            shift
            ;;
         --sleep)
            sleep_time="$2"
            shift
            shift
            ;;
        --select_reference)
            select_reference_flag=1
            shift
            ;;
        --no_select_reference)
            select_reference_flag=0
            shift
            ;;
        --chunks)
            chunks_flag=1
            shift
            ;;
        --debug)
            debug_flag=1
            shift
            ;;
        --burst-download)
            burst_download_flag=1
            ssara_download_flag=0
            shift
            ;;
        --asf-download)
            ssara_download_flag=0
            shift
            ;;
        *)
            POSITIONAL+=("$1") # save it in an array for later
            shift # past argument
            ;;
esac
done
set -- "${POSITIONAL[@]}" # restore positional parameters

if [[ ${#POSITIONAL[@]} -gt 1 ]]; then
    echo "Unknown parameters provided: ${POSITIONAL[-1]}"
    exit 1;
fi

if [[ $debug_flag == "1" ]]; then
   set -x
fi

create_template_array $template_file

# adjust switches according to template options if insarmaps_flag is not set
# first test if insarmaps_flag is set
if [[ ! -v insarmaps_flag ]]; then
   ## test if minsar.insarmaps_flag is set
   if [[ -n ${template[minsar.insarmaps_flag]+_} ]]; then
       if [[ ${template[minsar.insarmaps_flag]} == "True" ]]; then
           insarmaps_flag=1
       else
           insarmaps_flag=0
       fi
   else
       insarmaps_flag=0
   fi
fi

# adjust switches according to template options if upload_flag is not given on command line
if [[ ! -v upload_flag ]]; then
   if [[ -n ${template[minsar.upload_flag]+_} ]]; then
       if [[ ${template[minsar.upload_flag]} == "True" ]]; then
           upload_flag=1
       else
           upload_flag=0
       fi
   else
       upload_flag=0
   fi
fi

# adjust switches according to template options if burst_download_flag is not given on command line
if [[ ! -v burst_download_flag ]]; then
   if [[ -n ${template[minsar.burst_download_flag]+_} ]]; then
       if [[ ${template[minsar.burst_download_flag]} == "True" ]]; then
           burst_download_flag=1
       else
           burst_download_flag=0
       fi
   else
       burst_download_flag=0
   fi
fi

if [ ! -z ${sleep_time+x} ]; then
  echo "sleeping $sleep_time secs before starting ..."
  sleep $sleep_time
fi

### get minsar variables from *template
if [[ -n ${template[minsar.insarmaps_dataset]} ]]; then
   insarmaps_dataset=${template[minsar.insarmaps_dataset]}
else
   insarmaps_dataset=geo
fi

if [[ $startstep == "download" ]]; then
    download_flag=1
elif [[ $startstep == "dem" ]]; then
    download_flag=0
    dem_flag=1
elif [[ $startstep == "jobfiles" ]]; then
    download_flag=0
    dem_flag=0
elif [[ $startstep == "ifgram" ]]; then
    download_flag=0
    dem_flag=0
    jobfiles_flag=0
elif [[ $startstep == "mintpy" ]]; then
    download_flag=0
    dem_flag=0
    jobfiles_flag=0
    ifgram_flag=0
elif [[ $startstep == "miaplpy" ]]; then
    download_flag=0
    dem_flag=0
    jobfiles_flag=0
    ifgram_flag=0
    mintpy_flag=0
    miaplpy_flag=1
elif [[ $startstep == "upload" ]]; then
    download_flag=0
    dem_flag=0
    jobfiles_flag=0
    ifgram_flag=0
    mintpy_flag=0
    miaplpy_flag=0
elif [[ $startstep == "insarmaps" ]]; then
    download_flag=0
    dem_flag=0
    jobfiles_flag=0
    ifgram_flag=0
    mintpy_flag=0
    miaplpy_flag=0
    upload_flag=0
elif [[ $startstep == "finishup" ]]; then
    download_flag=0
    dem_flag=0
    jobfiles_flag=0
    ifgram_flag=0
    mintpy_flag=0
    miaplpy_flag=0
    upload_flag=0
    insarmaps_flag=0
elif [[ $startstep != "" ]]; then
    echo "USER ERROR: startstep received value of "${startstep}". Exiting."
    exit 1
fi

if [[ $stopstep == "download" ]]; then
    dem_flag=0
    jobfiles_flag=0
    ifgram_flag=0
    mintpy_flag=0
    minooy_flag=0
    upload_flag=0
    insarmaps_flag=0
    finishup_flag=0
elif [[ $stopstep == "dem" ]]; then
    jobfiles_flag=0
    ifgram_flag=0
    mintpy_flag=0
    miaplpy_flag=0
    upload_flag=0
    insarmaps_flag=0
    finishup_flag=0
elif [[ $stopstep == "jobfiles" ]]; then
    ifgram_flag=0
    mintpy_flag=0
    miaplpy_flag=0
    upload_flag=0
    insarmaps_flag=0
    finishup_flag=0
elif [[ $stopstep == "ifgram" ]]; then
    mintpy_flag=0
    miaplpy_flag=0
    upload_flag=0
    insarmaps_flag=0
    finishup_flag=0
elif [[ $stopstep == "mintpy" ]]; then
    miaplpy_flag=0
    upload_flag=0
    insarmaps_flag=0
    finishup_flag=0
elif [[ $stopstep == "miaplpy" ]]; then
    upload_flag=0
    insarmaps_flag=0
    finishup_flag=0
elif [[ $stopstep == "upload" ]]; then
    insarmaps_flag=0
    finishup_flag=0
elif [[ $stopstep == "insarmaps" ]]; then
    finishup_flag=0
elif [[ $stopstep != "" ]]; then
    echo "stopstep received value of "${stopstep}". Exiting."
    exit 1
fi

# switch mintpy off for slc workflow
if [[ ${template[topsStack.workflow]} == "slc" ]]; then
   mintpy_flag=0
fi

echo "Switches: select_reference: $select_reference_flag   ssara_download_flag: $ssara_download_flag burst_download: $burst_download_flag  chunks: $chunks_flag"
echo "Flags for processing steps:"
echo "download dem jobfiles ifgram mintpy miaplpy upload insarmaps finishup"
echo "    $download_flag     $dem_flag      $jobfiles_flag       $ifgram_flag       $mintpy_flag      $miaplpy_flag      $upload_flag       $insarmaps_flag        $finishup_flag"

sleep 1

#############################################################

platform_str=$( (grep platform "$template_file" || echo "") | cut -d'=' -f2 )
if [[ -z $platform_str ]]; then
   # assume TERRASAR-X if no platform is given (ssara_federated_query.py does not seem to work with --platform-TERRASAR-X)
   collectionName_str=$(grep collectionName $template_file || True | cut -d'=' -f2)
   echo "$collectionName_str"
   platform_str="TERRASAR-X"
fi

if [[ $platform_str == *"COSMO-SKYMED"* ]]; then
    download_dir="$WORK_DIR/RAW_data"
elif [[ $platform_str == *"TERRASAR-X"* ]]; then
    download_dir="$WORK_DIR/SLC_ORIG"
else
    download_dir="$WORK_DIR/SLC"
fi

####################################
srun_cmd="srun -n1 -N1 -A $JOBSHEDULER_PROJECTNAME -p $QUEUENAME  -t 00:07:00 "
srun_cmd="srun -n1 -N1 -A $JOBSHEDULER_PROJECTNAME -p $QUEUENAME  -t 00:25:00 "
####################################
###       Processing Steps       ###
####################################
if [[ $download_flag == "1" ]]; then

    echo "Running.... generate_download_command.py $template_file"
    run_command "generate_download_command.py $template_file"

    mkdir -p $download_dir
    cd $download_dir

    if [[ $ssara_download_flag == "1" ]]; then
       cmd=$(cat ../download_ssara_bash.cmd)
       run_command "$cmd"
    elif [[ $burst_download_flag == "1" ]]; then
       cmd=$(cat ../download_asf_search_burst.cmd)
       run_command "$cmd"
    else
       cmd=$(cat ../download_asf_search.cmd)
       run_command "$cmd"
    fi

    cd ..

    # remove excluded dates
    if [[ ! -z $(grep "^minsar.excludeDates" $template_file) ]];  then
      date_string=$(grep ^minsar.excludeDates $template_file | awk -F = '{printf "%s\n",$2}')
      date_array=($(echo $date_string | tr ',' "\n"))
      echo "${date_array[@]}"

       for date in "${date_array[@]}"; do
           echo "Remove $date if exist"
           files="RAW_data/*$date*"
           echo "Removing: $files"
           rm $files
       done
    fi
fi

if [[ $dem_flag == "1" ]]; then
    if [[ ! -z $(grep -E "^stripmapStack.demDir|^topsStack.demDir" $template_file) ]];  then
       # copy DEM if given
       demDir=$(grep -E "^stripmapStack.demDir|^topsStack.demDir" $template_file | awk -F = '{printf "%s\n",$2}' | sed 's/ //')
       rm -rf DEM; eval "cp -r $demDir DEM"
    else
       # download DEM
       run_command "dem_rsmas.py $template_file --ssara_kml 2>out_dem_rsmas.e 1>out_dem_rsmas.o"
    fi
fi

if [[ $chunks_flag == "1" ]]; then
    # create string with minsar command options (could save options at beginning)
    set -- "${args[@]}"
    options=""
    while [[ $# -gt 0 ]]
    do
        key="$1"

        case $key in
            --start)
                options="$options --start $2"
                shift # past argument
                shift # past value
                ;;
            --stop)
                options="$options --stop $2"
                shift
                shift
                ;;
            --dostep)
                options="$options --dostep $2"
                shift
                shift
                ;;
            --mintpy)
                options="$options --mintpy"
                shift
                ;;
            --miaplpy)
                options="$options --miaplpy"
                shift
                ;;
            *)
                #POSITIONAL+=("$1") # save it in an array for later
                shift # past argument
                ;;
    esac
    done

    # generate chunk template files
    run_command "generate_chunk_template_files.py $template_file $options 2>out_generate_chunk_template_files.e 1>out_generate_chunk_template_files.o"

    echo "Submitting chunk minsar jobs:" | tee -a log
    cat $WORK_DIR/minsar_commands.txt | tee -a log
    bash $WORK_DIR/minsar_commands.txt
    exit_status="$?"
    if [[ $exit_status -ne 0 ]]; then
       echo "bash $WORK_DIR/minsar_commands.txt exited with a non-zero exit code ($exit_status). Exiting."
       exit 1;
    fi
    echo "Successfully submitted minsarApp.bash chunk jobs"
    exit 0
fi

if [[ $jobfiles_flag == "1" ]]; then
#############################################################
    if [[ $orbit_download_flag == "1" && $template_file == *"Sen"*  ]]; then
       # download new Sentinel-1 orbits from the ASF
       run_command "run_download_orbits_asf.bash"
    fi

    # clean directory for processing and create jobfiles
    pwd=`pwd`; echo "DIR: $pwd"
    run_command "run_clean_dir.bash $PWD --runfiles --ifgram --mintpy --miaplpy"

    if [[ $template_file == *"Tsx"*  ]] || [[ $template_file == *"Csk"*  ]]; then
       BUFFOPT="PYTHONUNBUFFERED=1"
    fi
    ( run_command "$BUFFOPT create_runfiles.py $template_file --jobfiles --queue $QUEUENAME" ) 2>out_create_jobfiles.e | tee out_create_jobfiles.o
fi

if [[ $ifgram_flag == "1" ]]; then

    if [[ $template_file != *"Sen"* || $select_reference_flag == "0" ]]; then
       run_command "run_workflow.bash $template_file --dostep ifgram"
    else

       echo "topsStack.workflow: <${template[topsStack.workflow]}>"
       ifgram_stopstep=11              # default for interferogram workflow
       if [[ ${template[topsStack.workflow]} == "slc" ]] || [[ $mintpy_flag == 0 ]]; then
          ifgram_stopstep=7
       fi

       # run with checking and selecting of reference date
       echo "### Running step 1 to 5 to check whether reference date has enough bursts"
       run_command "run_workflow.bash $template_file --start 1 --stop 5"

       reference_date=$(get_reference_date)
       echo "Reference date: $reference_date" | tee reference_date_isce.txt

       # determine whether to select new reference date
       countbursts | tr '/' ' ' | sort -k 1 | sort -k 2 | sort -k 4 -s | sed 's/ /\//' > number_of_bursts_sorted.txt
       number_of_dates_with_less_or_equal_bursts_than_reference=$(grep -n reference number_of_bursts_sorted.txt | cut -f1 -d:)
       number_of_dates_with_less_bursts_than_reference=$(( $number_of_dates_with_less_or_equal_bursts_than_reference - 1 ))
       number_of_dates=$(wc -l < number_of_bursts_sorted.txt)
       percentage_of_dates_with_less_bursts_than_reference=$(echo "scale=2; $number_of_dates_with_less_bursts_than_reference / $number_of_dates * 100"  | bc)
       echo "#########################################" | tee -a log | tee -a `ls wor* | tail -1`
       echo "Number of dates with less bursts than reference: $number_of_dates_with_less_bursts_than_reference" | tee -a log | tee -a  `ls wor* | tail -1`
       echo "Total number of dates: $number_of_dates" | tee -a log | tee -a  `ls wor* | tail -1`
       echo "Percentage of dates with less bursts than reference: $percentage_of_dates_with_less_bursts_than_reference" | tee -a log | tee -a  `ls wor* | tail -1`
       echo "# head -$number_of_dates_with_less_or_equal_bursts_than_reference  number_of_bursts_sorted.txt:" | tee -a log | tee -a `ls wor* | tail -1`
       head -"$number_of_dates_with_less_or_equal_bursts_than_reference" number_of_bursts_sorted.txt | tee -a log | tee -a `ls wor* | tail -1`
       percentage_of_dates_allowed_to_exclude=3  # FA 12 Mar 2022: changed to 1 %
       percentage_of_dates_allowed_to_exclude=1
       tmp=$(echo "$percentage_of_dates_allowed_to_exclude $number_of_dates" | awk '{printf "%f", $1 / 100 * $2}')
       number_of_dates_allowed_to_exclude="${tmp%.*}"
       new_reference_date=$(head -$((number_of_dates_allowed_to_exclude+1))  number_of_bursts_sorted.txt | tail -1 | awk '{print $1}' | cut -d'/' -f2)

       if [[ $(echo "$percentage_of_dates_with_less_bursts_than_reference > $percentage_of_dates_allowed_to_exclude"  | bc -l ) -eq 1 ]] && [[ $new_reference_date != $reference_date ]] ; then
          # insert new reference date into templatefile and rerun from beginning
          new_reference_flag=1
          echo "Original reference date:  $reference_date" | tee -a log | tee -a `ls wor* | tail -1` | tee reference_date_isce.txt
          echo "Selected reference date (image $((number_of_dates_allowed_to_exclude+1)) after sorting): $new_reference_date" | tee -a log | tee -a `ls wor* | tail -1` | tee -a tee reference_date_isce.txt
          echo "#########################################" | tee -a log | tee -a `ls wor* | tail -1`

          rm -rf modified_template
          mkdir modified_template
          cp $template_file modified_template
          template_file=$PWD/modified_template/$(basename $template_file)
          sed -i  "s|topsStack.subswath.*|&\ntopsStack.referenceDate              = $new_reference_date|" $template_file

          mv $runfiles_dir modified_template
          mv $configs_dir modified_template
          rm -rf run_files configs

          # clean directory for processing and create jobfiles
          run_command "run_clean_dir.bash $PWD --runfiles --ifgram"
          run_command "create_runfiles.py $template_file --jobfiles --queue $QUEUENAME 2>create_jobfiles.e 1>out_create_jobfiles.o"

          # rerun steps 1 to 5  with new reference
	      echo "### Re-running step 1 to 5 with reference $new_reference_date"
          run_command "run_workflow.bash $template_file --start 1 --stop 5 --append"
       else
          echo "No new reference date selected. Continue with original date: $reference_date" | tee -a log | tee -a `ls wor* | tail -1`
          echo "#########################################" | tee -a log | tee -a `ls wor* | tail -1`
       fi

       # continue running starting step 6
       run_command "run_workflow.bash $template_file --start 6 --stop $ifgram_stopstep --append"

    fi
fi

########################
#       MintPy         #
########################
if [[ $mintpy_flag == "1" ]]; then

    # run MintPy
    run_command "run_workflow.bash $template_file --append --dostep mintpy"

    # upload mintpy directory
    if [[ $upload_flag == "1" ]]; then
        run_command "upload_data_products.py mintpy ${template[minsar.upload_option]}"
    fi

    ## insarmaps
    if [[ $insarmaps_flag == "1" ]]; then
        run_command "create_insarmaps_jobfile.py mintpy --dataset geo"

        insarmaps_jobfile=$(ls -t insar*job | head -n 1)
        run_command "run_workflow.bash $template_file --jobfile $PWD/$insarmaps_jobfile"
    fi
fi

########################
#       MiaplPy        #
########################
if [[ $miaplpy_flag == "1" ]]; then

    # remove directory with reference data which should not be here ( https://github.com/geodesymiami/rsmas_insar/issues/568)
    if [[ $template_file == *"Tsx"*  ]] || [[ $template_file == *"Csk"*  ]]; then
       dir=$(find merged/SLC/ -type f -path '*/referenceShelve/data.rsc' -printf '%h\n' | sed 's|/referenceShelve$||')
       [ -n "$dir" ] && rm -r "$dir"
    fi

    miaplpy_dir_name=$(get_miaplpy_dir_name)
    network_type=$(get_network_type)
    network_dir=${miaplpy_dir_name}/network_${network_type}

    # create miaplpy jobfiles
    run_command "$srun_cmd miaplpyApp.py $template_file --dir $miaplpy_dir_name --jobfiles --queue $QUEUENAME"

    # run miaplpy jobfiles ( after create_save_hdfeos5_jobfile.py to include run_10_save_hdfeos5_radar_0.job )
    run_command "run_workflow.bash $template_file --append --dostep miaplpy --dir $miaplpy_dir_name"

    # create save_hdf5 jobfile
    run_command "create_save_hdfeos5_jobfile.py  $template_file $network_dir --outdir $network_dir/run_files --outfile run_10_save_hdfeos5_radar_0 --queue $QUEUENAME --walltime 0:30"

    # run save_hdfeos5_radar jobfile
    run_command "run_workflow.bash $template_file --dir $miaplpy_dir_name --start 10"

    # create index.html with all images
    run_command "create_html.py ${network_dir}/pic"

    ## insarmaps
    if [[ $insarmaps_flag == "1" ]]; then
        run_command "create_insarmaps_jobfile.py $network_dir --dataset $insarmaps_dataset"

        # run jobfile
        insarmaps_jobfile=$(ls -t insar*job | head -n 1)
        run_command "run_workflow.bash $template_file --jobfile $PWD/$insarmaps_jobfile"

    fi

    # upload data products
    run_command "upload_data_products.py $network_dir ${template[minsar.upload_option]}"

fi

if [[ $finishup_flag == "1" ]]; then
    if [[ $miaplpy_flag == "1" ]]; then
        miaplpy_opt="--miaplpyDir $miaplpy_dir_name"
    else
        miaplpy_opt=""
    fi
    run_command "summarize_job_run_times.py $template_file $miaplpy_opt"
fi

echo
if ls mintpy/*he5 1> /dev/null 2>&1; then
   echo "hdfeos5 files produced:"
   ls -sh mintpy/*he5
fi
if ls $network_dir/*he5 1> /dev/null 2>&1; then
   echo " hdf5files in network_dir: <$network_dir>"
   ls -sh $network_dir/*he5
fi

# Summarize results
echo
echo "Done:  $cli_command"
echo

echo
echo "Yup! That's all from minsarApp.bash."
echo

echo "Data products uploaded to:"
if [ -f "upload.log" ]; then
    tail -n -1 upload.log
fi

lines=1
if [[ "$insarmaps_dataset" == "PSDS" ]]; then
    lines=2
fi
if [[ "$insarmaps_dataset" == "all" ]]; then
   lines=4
fi

lines=$((lines * 2))  # multiply as long as we ingestinto two servers
if [ -f "insarmaps.log" ]; then
    tail -n $lines insarmaps.log
fi

