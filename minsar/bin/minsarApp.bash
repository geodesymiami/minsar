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
      minsarApp.bash  $TE/GalapagosSenDT128.template --no-insarmaps              \n\
      minsarApp.bash  $TE/GalapagosSenDT128.template --start ifgram --isce-start 5  \n\
      minsarApp.bash  $TE/GalapagosSenDT128.template --start ifgram --isce-start 5 --isce-stop 6  \n\
      minsarApp.bash  $TE/GalapagosSenDT128.template --start ifgram --isce-step 5 \n\
      minsarApp.bash  $TE/GalapagosSenDT128.template --start miaplpy --miaplpy-start 6         \n\
      minsarApp.bash  $TE/GalapagosSenDT128.template --start miaplpy --miaplpy-start 6 --miaplpy-stop 6 \n\
      minsarApp.bash  $TE/GalapagosSenDT128.template --start miaplpy --miaplpy-step 6     \n\
      minsarApp.bash  $TE/GalapagosSenDT128.template --miaplpy-stop 1     \n\
                                                                                 \n\
  Processing steps (start/end/dostep): \n\
   Command line options for steps processing with names are chosen from the following list: \n\
                                                                                 \n\
   ['download', 'preprocess', 'dem', 'jobfiles', 'ifgram', 'mintpy', 'miaplpy']      \n\
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
   --download-method {slc, burst2safe, burst2stack, ssara-slc, ssara-bash, ssara-python} (default: burst2stack) \n\
                                                                                 \n\
   --mintpy              use smallbaselineApp.py for time series [default]       \n\
   --miaplpy             use miaplpyApp.py                                       \n\
   --mintpy --miaplpy    use smallbaselineApp.py and miaplpyApp.py               \n\
   --no-mintpy --miaplpy use only miaplpyApp.py                                  \n\
                                                                                 \n\
   --no-orbit-download   don't download orbits prior to jobfile creation         \n\
   --opposite-orbit [--no-opposite-orbit]  run opposite-orbit step (default: off)       \n\
   --horzvert [--no-horzvert]       run horzvert post-step after MiaplPy (default: off) \n\
                                                                                 \n\
   --sleep SECS           sleep seconds before running                           \n\
   --chunks               process in form of multiple chunks.                    \n\
                                                                                 \n\
For sarvey:                                                                      \n\
   --miaplpy-stop 1      to only run step 1 (load_slc_geometry.py) of miaplpy    \n\
                                                                                 \n\
Debug options:                                                                   \n\
   --debug           sets set -x                                                 \n\
   --skip-mintpy     skip mintpy processing (but runs everything else)           \n\
   --skip-miaplpy    skip miaplpy processing (but runs everything else)          \n\
   --start miaplpy --miaplpy-step 5
                                                                                 \n\
Using AOI and name as postional arguments (for options run: create_template.py --help):\n\
      minsarApp.bash 36.331:36.486,25.318:25.492 Santorini --no-mintpy --miaplpy  \n\
      minsarApp.bash 36.331:36.486,25.318:25.492 Santorini --quick-run 2026 --no-mintpy --miaplpy  \n\
      minsarApp.bash 36.331:36.486,25.318:25.492 Santorini --last-year --no-mintpy --miaplpy  \n\
      minsarApp.bash 36.331:36.486,25.318:25.492 Santorini --start-date 2020-01-01 --end-date 2024-12-31 --no-mintpy --miaplpy  \n\
      minsarApp.bash 36.331:36.486,25.318:25.492 Santorini --period 20210101:20221231 --miaplpy  \n\
      minsarApp.bash 36.331:36.486,25.318:25.492 Santorini --exclude-season 1101-0430 --no-mintpy --miaplpy  \n\
      minsarApp.bash 36.331:36.486,25.318:25.492 Santorini --flight-dir asc --miaplpy  \n\
                                                                                 \n\
   Coding To Do:                                                                 \n\
       - create .minsarrc for defaults                                           \n
     "
    printf "$helptext"
    exit 0
fi

# AOI + project name: first create templates under TEMPLATES, then continue as template mode.
# Accept AOI as first positional even when it starts with '-' (negative latitude).
# Exclude long-option invocations and template-file mode.
if [[ -n "${1-}" && -n "${2-}" && "$1" != --* && "$1" != *".template" && "$2" != -* ]]; then
  export MINSAR_APP_BASH="${BASH_SOURCE[0]}"
  exec python3 "${SCRIPT_DIR}/../scripts/minsarapp_aoi_entry.py" "$@"
fi

PROJECT_NAME=$(basename -- "$1" | awk -F ".template" '{print $1}')
exit_status="$?"
if [[ $PROJECT_NAME == "" ]]; then
   echo "Could not compute basename for that file. Exiting. Make sure you have specified an input file as the first argument."
   exit 1
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
echo "#############################################################################################" | tee -a "${WORK_DIR}"/log
echo "$(date +"%Y%m%d:%H-%M") * $SCRIPT_NAME $template_print_name ${@:2}" | tee -a "${WORK_DIR}"/log
cli_command=$(echo "$SCRIPT_NAME $template_print_name ${@:2}")

#Switches
chunks_flag=0
jobfiles_flag=1
orbit_download_flag=1

debug_flag=0
download_ECMWF_flag=1
download_ECMWgF_before_mintpy_flag=0

args=( "$@" )    # copy of command line arguments
POSITIONAL=()

##################################
create_template_array $template_file
##################################
# set defaults steps (insarmaps_flag and upload_flag are set to 0 if not given on command line or in template file )
download_flag=1
preprocess_flag=1
dem_flag=1
ifgram_flag=1
mintpy_flag=1
miaplpy_flag=0
opposite_orbit_flag=0
horzvert_flag=0

download_method="burst2stack"
miaplpy_startstep=1
miaplpy_stopstep=9

# Track whether options were explicitly set on CLI
startstep_cli_flag=0
stopstep_cli_flag=0
isce_start_cli_flag=0
isce_stop_cli_flag=0
miaplpy_start_cli_flag=0
no_mintpy_cli_flag=0

skip_mintpy_flag=0
skip_miaplpy_flag=0

srun_cmd="srun -n1 -N1 -A $JOBSHEDULER_PROJECTNAME -p $QUEUENAME  -t 00:25:00 "
##################################

while [[ $# -gt 0 ]]
do
    key="$1"

    case $key in
        --start)
            startstep="$2"
            startstep_cli_flag=1
            shift # past argument
            shift # past value
            ;;
	--stop)
            stopstep="$2"
            stopstep_cli_flag=1
            shift
            shift
            ;;
	--dostep)
            startstep="$2"
            stopstep="$2"
            startstep_cli_flag=1
            stopstep_cli_flag=1
            shift
            shift
            ;;
        --mintpy)
            mintpy_flag=1
            shift
            ;;
        --no-mintpy)
            mintpy_flag=0
            no_mintpy_cli_flag=1
            shift
            ;;
        --isce-start)
            isce_start_cli="$2"
            isce_start_cli_flag=1
            shift
            shift
            ;;
        --isce-stop)
            ifgram_flag=1
            isce_stop_cli="$2"
            isce_stop_cli_flag=1
            shift
            shift
            ;;
        --isce-step)
            isce_start_cli="$2"
            isce_stop_cli="$2"
            isce_start_cli_flag=1
            isce_stop_cli_flag=1
            shift
            shift
            ;;
        --miaplpy)
            miaplpy_flag=1
            shift
            ;;
        --miaplpy-start)
            miaplpy_flag=1
            miaplpy_start_cli_flag=1
            miaplpy_startstep="$2"
            shift
            shift
            ;;
        --miaplpy-stop)
            miaplpy_flag=1
            miaplpy_stopstep="$2"
            shift
            shift
            ;;
        --miaplpy-step)
            miaplpy_startstep="$2"
            miaplpy_stopstep="$2"
            shift
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
        --opposite-orbit)
            opposite_orbit_flag=1
            shift
            ;;
        --no-opposite-orbit)
            opposite_orbit_flag=0
            shift
            ;;
        --horzvert)
            horzvert_flag=1
            shift
            ;;
        --no-horzvert)
            horzvert_flag=0
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
        --chunks)
            chunks_flag=1
            shift
            ;;
        --debug)
            debug_flag=1
            shift
            ;;
        --skip-mintpy)
            skip_mintpy_flag=1
            shift
            ;;
        --skip-miaplpy)
            skip_miaplpy_flag=1
            shift
            ;;
        --download-method)
            download_method=$2
            shift 2
            ;;

        *)
            POSITIONAL+=("$1") # save it in an array for later
            shift # past argument
            ;;
esac
done
set -- "${POSITIONAL[@]}" # restore positional parameters

if [[ ${#POSITIONAL[@]} -gt 1 ]]; then
    if [[ "$2" == -* ]]; then
        echo "Unknown option: $2"
    else
        echo "Unknown parameters provided: $2"
    fi
    exit 1
fi

# Validate incompatible option combinations before deriving defaults.
if [[ "$miaplpy_start_cli_flag" == "1" && "$startstep_cli_flag" == "1" && "$startstep" != "miaplpy" ]]; then
    echo "USER ERROR: Inconsistent options: --miaplpy-start requires --start miaplpy (or omit --start)." >&2
    exit 1
fi

if [[ "$isce_start_cli_flag" == "1" && "$startstep_cli_flag" == "1" && ( "$startstep" == "mintpy" || "$startstep" == "miaplpy" ) ]]; then
    echo "USER ERROR: Inconsistent options: --isce-start cannot be combined with --start $startstep." >&2
    exit 1
fi

# Normalize start mode from explicit CLI ranges
if [[ "$miaplpy_start_cli_flag" == "1" && "$startstep_cli_flag" == "0" ]]; then
    startstep="miaplpy"
elif [[ "$isce_start_cli_flag" == "1" && "$startstep_cli_flag" == "0" ]]; then
    startstep="ifgram"
fi

if [[ $debug_flag == "1" ]]; then
   set -x
fi

# FA 8/2025: this should go into a function that adjusts defaults
if [[ -v template[minsar.upload_option] && "${template[minsar.upload_option]}" == "None" ]]; then
  unset 'template[minsar.upload_option]'
fi

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
       if [[ ${template[minsar.upload_flag]} == "False" ]]; then
           upload_flag=0
       else
           upload_flag=1
       fi
   else
       upload_flag=1
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

if [[ -n "${template[minsar.remoteDataDir]:-}" ]]; then
    download_method="remote_data_dir"
fi

if [[ $startstep == "download" ]]; then
    download_flag=1
elif [[ $startstep == "preprocess" ]]; then
    download_flag=0
    preprocess_flag=1
elif [[ $startstep == "dem" ]]; then
    download_flag=0
    preprocess_flag=0
    dem_flag=1
elif [[ $startstep == "jobfiles" ]]; then
    download_flag=0
    preprocess_flag=0
    dem_flag=0
elif [[ $startstep == "ifgram" ]]; then
    download_flag=0
    preprocess_flag=0
    dem_flag=0
    jobfiles_flag=0
elif [[ $startstep == "mintpy" ]]; then
    download_flag=0
    preprocess_flag=0
    dem_flag=0
    jobfiles_flag=0
    ifgram_flag=0
elif [[ $startstep == "miaplpy" ]]; then
    download_flag=0
    preprocess_flag=0
    dem_flag=0
    jobfiles_flag=0
    ifgram_flag=0
    mintpy_flag=0
    miaplpy_flag=1
elif [[ $startstep != "" ]]; then
    echo "USER ERROR: startstep received value of "${startstep}". Exiting."
    exit 1
fi

if [[ $stopstep == "download" ]]; then
    preprocess_flag=0
    dem_flag=0
    jobfiles_flag=0
    ifgram_flag=0
    mintpy_flag=0
    miaplpy_flag=0
    horzvert_flag=0
    opposite_orbit_flag=0
elif [[ $stopstep == "preprocess" ]]; then
    dem_flag=0
    jobfiles_flag=0
    ifgram_flag=0
    mintpy_flag=0
    miaplpy_flag=0
elif [[ $stopstep == "dem" ]]; then
    jobfiles_flag=0
    ifgram_flag=0
    mintpy_flag=0
    miaplpy_flag=0
    horzvert_flag=0
    opposite_orbit_flag=0
elif [[ $stopstep == "jobfiles" ]]; then
    ifgram_flag=0
    mintpy_flag=0
    miaplpy_flag=0
    horzvert_flag=0
    opposite_orbit_flag=0
elif [[ $stopstep == "ifgram" ]]; then
    mintpy_flag=0
    miaplpy_flag=0
    horzvert_flag=0
    opposite_orbit_flag=0
elif [[ $stopstep == "mintpy" ]]; then
    miaplpy_flag=0
    horzvert_flag=0
    opposite_orbit_flag=0
elif [[ $stopstep == "miaplpy" ]]; then
    horzvert_flag=0
    opposite_orbit_flag=0
elif [[ $stopstep != "" ]]; then
    echo "stopstep received value of "${stopstep}". Exiting."
    exit 1
fi

# set isce_stop depending on coregistration method and workflow  (for Sentinel-1, for TSX/CSK/ENV we have --dostep ifgram but can be implemented)
if [[ ${template[topsStack.coregistration]} == "geometry" ]]; then 
    full_isce_run_stop=12
    partial_isce_run_stop=8
    if [[ ${template[topsStack.workflow]} == "slc" ]]; then
         full_isce_run_stop=8
         partial_isce_run_stop=8
    fi
else
    # for coregistration "NESD" or "auto" (default if not given)     
    full_isce_run_stop=16
    partial_isce_run_stop=12
    if [[ ${template[topsStack.workflow]} == "slc" ]]; then
         full_isce_run_stop=12
         partial_isce_run_stop=12
    fi
fi

#############################################################
platform_str=$( (grep platform "$template_file" || echo "") | cut -d'=' -f2 )
if [[ -z $platform_str ]]; then
   # assume TERRASAR-X if no platform is given (ssara_federated_query.py does not seem to work with --platform-TERRASAR-X)
   collectionName_str=$(grep collectionName $template_file || True | cut -d'=' -f2)
   echo "$collectionName_str"
   platform_str="TERRASAR-X"
fi

if [[ $platform_str =~ COSMO-SKYMED|TERRASAR-X|ENVISAT ]]; then
    download_dir="$WORK_DIR/SLC_ORIG"
    [[ $download_method == *burst2safe* ]] && download_method="ssara-bash"
else
    # Sentinel-1
    download_dir="$WORK_DIR/SLC"
fi

# set preprocess_flag for Sentinel-1
if [[ $preprocess_flag == "1" && $platform_str == *"SENTINEL-1"*  ]]; then
    preprocess_flag=0
    if [[ $download_method == "burst2safe" ]]; then
        preprocess_flag=1
    fi # no preprocessing needed for burst2stack and slc
fi

# set isce_start/isce_stop from CLI + defaults
isce_start="${isce_start_cli:-1}"
if [[ "$isce_stop_cli_flag" == "1" ]]; then
    isce_stop="$isce_stop_cli"
elif [[ "$platform_str" == *"SENTINEL-1"* && "$isce_start_cli_flag" == "1" ]]; then
    # For Sentinel: if user provides --isce-start but omits --isce-stop, run ifgram-only range.
    isce_stop="$partial_isce_run_stop"
elif [[ "$platform_str" == *"SENTINEL-1"* && "$no_mintpy_cli_flag" == "1" && ${template[topsStack.coregistration]} != "geometry" ]]; then
    # --no-mintpy (e.g. MiaplPy-only): default to partial ISCE (e.g. 1–12 for NESD burst stack), not full through unwrap (16).
    # Geometry coregistration already uses full_isce_run_stop=12; do not override with partial_isce_run_stop=8 here.
    isce_stop="$partial_isce_run_stop"
else
    isce_stop="$full_isce_run_stop"
fi

# switch off mintpy for slc workflow, or when user explicitly limits ISCE range via --isce-stop
if [[ ${template[topsStack.workflow]} == "slc" || "$isce_stop_cli_flag" == "1" ]]; then
   mintpy_flag=0
fi

# Starting at ifgram or later does not need orbit download.
if [[ "$startstep" == "ifgram" || "$startstep" == "mintpy" || "$startstep" == "miaplpy" ]]; then
    orbit_download_flag=0
fi

# If ssaraopt.endDate is explicitly set to a non-auto value, skip orbit download.
if [[ -v template[ssaraopt.endDate] && "${template[ssaraopt.endDate]}" != "auto" ]]; then
    orbit_download_flag=0
fi

echo "Switches: download_method: <$download_method> burst_download: <$burst_download_flag>  chunks: <$chunks_flag>"
echo "Flags for processing steps:"
echo "download preprocess dem jobfiles ifgram mintpy miaplpy upload insarmaps opposite_orbit horzvert"
echo "    $download_flag        $preprocess_flag       $dem_flag      $jobfiles_flag       $ifgram_flag       $mintpy_flag      $miaplpy_flag      $upload_flag       $insarmaps_flag        $opposite_orbit_flag        $horzvert_flag"

echo ""
[[ "$ifgram_flag" == "1" ]] && echo "ISCE steps to process: $isce_start-$isce_stop"
[[ "$miaplpy_flag" == "1" ]] && echo "MiaplPy steps to process: $miaplpy_startstep-$miaplpy_stopstep"

sleep 5

####################################
###       Processing Steps       ###
####################################

if [[ $download_flag == "1" ]]; then

    echo "Running.... generate_download_command.py $template_file --delta-lat 0.0 --delta-lon 0.0"
    run_command "generate_download_command.py $template_file --delta-lat 0.0 --delta-lon 0.0"

    mkdir -p $download_dir

    if [[ $download_method == "burst2safe" ]]; then
        run_command "./download_burst2safe.sh  2>out_download_burst2safe.e 1>out_download_burst2safe.o"
    elif [[ "$download_method" == "burst2stack" ]]; then
        run_command "cmd2jobfile.py ./download_burst2stack.sh --submit"
    elif [[ "$download_method" == "slc" ]]; then
        run_command "./download_slc.sh 2>out_download_slc.e 1>out_download_slc.o"
    elif [[ $download_method == "ssara-python" ]]; then
        cd $download_dir
        cmd=$(cat ../download_ssara_python.cmd)
        run_command "$cmd"
        cd ..
    elif [[ $download_method == "ssara-bash" || $download_method == "ssara" ]]; then
        cd $download_dir
        cmd=$(cat ../download_ssara_bash.cmd)
        run_command "$cmd"
        cd ..
    elif [[ $download_method == "remote_data_dir" ]]; then
        cd $download_dir
        # FA debug note 1/2026: use -avzn for dry-run
        run_command "rsync -avz --progress --sparse ${template[minsar.remoteDataDir]} ."
        cd ..
    else
        echo "ERROR: Unknown download method <$download_method>, Exiting"
        exit 1
    fi

    # Remove S1 acquisitions affected by degraded burst sync
    if [[ $platform_str == *"SENTINEL-1"* && -d "$download_dir" ]]; then
        run_command "remove_problem_data.py $download_dir"
    fi

    # remove excluded dates
    if [[ ! -z $(grep "^minsar.excludeDates" $template_file) ]];  then
      date_string=$(grep ^minsar.excludeDates $template_file | awk -F = '{printf "%s\n",$2}')
      date_array=($(echo $date_string | tr ',' "\n"))
      echo "${date_array[@]}"

       for date in "${date_array[@]}"; do
           echo "Remove $date if exist"
           files="$download_dir/*$date*"
           echo "Removing: $files"
           rm -rf $files
       done
    fi
fi

# preprocess SLCs for non-Sentinel-1 platforms and burst2safe. No preprocessing needed for slc and burst2stack.
if [[ $preprocess_flag == "1" ]]; then
    if [[ $platform_str == *"SENTINEL-1"*  ]]; then
        if [[ $download_method == "burst2safe" ]]; then
            run_command "./pack_bursts.sh SLC"
        fi
    else
        run_command "unpack_SLCs.py $download_dir --queue $QUEUENAME"
    fi
fi


if [[ $dem_flag == "1" ]]; then
    if [[ ! -z $(grep -E "^stripmapStack.demDir|^topsStack.demDir" $template_file) ]];  then
       # copy DEM if given
       demDir=$(grep -E "^stripmapStack.demDir|^topsStack.demDir" $template_file | awk -F = '{printf "%s\n",$2}' | sed 's/ //')
       rm -rf DEM; eval "cp -r $demDir DEM"
    else
       # makeDEM
       run_command "generate_makedem_command.py $template_file 2>out_generate_makedem_command.e 1>out_generate_makedem_command.o"
       run_command "./makedem_sardem.sh  2>out_makedem.e 1>out_makedem.o"
    fi
    if [[ "${template[minsar.zeroElevationDem]}" == "True" ]]; then
        run_command "make_zero_elevation_dem.py DEM --swap-in-place 2>out_make_zero_elevation_dem.e 1>out_make_zero_elevation_dem.o"
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

    if [[ $template_file =~ (Tsx|Csk|Env) ]]; then
       BUFFOPT="PYTHONUNBUFFERED=1"
    fi
    ( run_command "$BUFFOPT create_runfiles.py $template_file --jobfiles --queue $QUEUENAME" ) 2> >(tee out_create_jobfiles.e >&2) | tee out_create_jobfiles.o
fi

if [[ $ifgram_flag == "1" ]]; then

    if [[ $template_file =~ (Tsx|Csk|Env) ]]; then
        OLD_PATH="$PATH"
        PATH="$ISCE_STACK/stripmapStack:$PATH"
        run_command "run_workflow.bash --dostep ifgram"
        PATH="$OLD_PATH"
    else
       run_command "run_workflow.bash --start $isce_start --stop $isce_stop"
    fi

    reference_date=$(get_reference_date)
    echo "Reference date: $reference_date" | tee reference_date_isce.txt

fi

########################
#       MintPy         #
########################
if [[ $mintpy_flag == "1" ]]; then

    if [[ $skip_mintpy_flag != "1" ]]; then
        # run MintPy
        run_command "run_workflow.bash --dostep mintpy"
    fi

    # summarize profiling logs
    if [[ $PROFILE_FLAG == "True" ]]; then
        run_command "summarize_resource_usage.py $template_file SLC run_files --outdir mintpy/pic"
    fi

    ## insarmaps
    if [[ $insarmaps_flag == "1" ]]; then
        run_command "create_ingest_insarmaps_jobfile.py mintpy --dataset geo"

        ingest_insarmaps_jobfile=$(ls -t ingest_insar*job | head -n 1)
        run_command "run_workflow.bash --jobfile $PWD/$ingest_insarmaps_jobfile"
    fi

    # upload mintpy directory
    if [[ $upload_flag == "1" ]]; then
        run_command "upload_data_products.py mintpy ${template[minsar.upload_option]}"
    fi

fi

########################
#       MiaplPy        #
########################
if [[ $miaplpy_flag == "1" ]]; then

    ## remove directory with reference data which should not be here ( https://github.com/geodesymiami/rsmas_insar/issues/568)
    #if [[ $template_file == *"Tsx"*  ]] || [[ $template_file == *"Csk"*  ]]; then
    #   dir=$(find merged/SLC/ -type f -path '*/referenceShelve/data.rsc' -printf '%h\n' | sed 's|/referenceShelve$||')
    #   [ -n "$dir" ] && rm -r "$dir"
    #fi

    miaplpy_dir_name=$(get_miaplpy_dir_name)
    network_type=$(get_network_type)
    network_dir=${miaplpy_dir_name}/network_${network_type}

    if [[ $skip_miaplpy_flag != "1" ]]; then
       # remove slcStack.h5 if exist and create miaplpy jobfiles  (FA 8/25: we may want to remove entire miaplpy folder)

       [[ "$miaplpy_startstep" == 1 ]] &&  rm -f ${miaplpy_dir_name}/inputs/slcStack.h5 ${miaplpy_dir_name}/inputs/geometryRadar.h5
       run_command "create_jobfile_to_generate_miaplpy_jobfiles.py $template_file $miaplpy_dir_name"
       run_command "run_workflow.bash $template_file --jobfile $PWD/create_miaplpy_jobfiles.job"

       # run miaplpy jobfiles
       run_command "run_workflow.bash $template_file --dir $miaplpy_dir_name --start $miaplpy_startstep --stop $miaplpy_stopstep"
    fi

    # add missing ORBIT_DIRECTION / relative_orbit to inputs H5 (for saarvey / upload)
    run_command "add_missing_attributes.py ${miaplpy_dir_name}/inputs/slcStack.h5 ${miaplpy_dir_name}/inputs/geometryRadar.h5"
    if [[ $platform_str == *"SENTINEL-1"* ]]; then
        run_command "flip_sign_bperp.py ${miaplpy_dir_name}/inputs/slcStack.h5"
    fi

    # create and run save_hdf5 jobfile (only when running full miaplpy through step 9)
    if [[ "$miaplpy_stopstep" == "9" ]]; then
        run_command "create_save_hdfeos5_jobfile.py  $template_file $network_dir --outdir $network_dir/run_files --outfile run_10_save_hdfeos5_radar_0 --queue $QUEUENAME --walltime 0:30"
        run_command "run_workflow.bash $template_file --dir $miaplpy_dir_name --start 10"

        # create index.html with all images
        run_command "create_html.py ${network_dir}/pic"

    fi

    # summarize profiling logs
    if [[ $PROFILE_FLAG == "True" ]]; then
        run_command "summarize_resource_usage.py $template_file SLC run_files ${network_dir}/run_files --outdir ${network_dir}/pic"
    fi

    ## insarmaps
    if [[ $insarmaps_flag == "1" && "$miaplpy_stopstep" == "9" ]]; then
        run_command "create_ingest_insarmaps_jobfile.py $network_dir --dataset $insarmaps_dataset"

        # run jobfile
        ingest_insarmaps_jobfile=$(ls -t ingest_insar*job | head -n 1)
        run_command "run_workflow.bash --jobfile $PWD/$ingest_insarmaps_jobfile"

    fi

    # upload data products
    if [[ $upload_flag == "1" ]]; then
        if [[ "$miaplpy_stopstep" == "1" ]]; then
            run_command "upload_data_products.py ${miaplpy_dir_name}/inputs ${template[minsar.upload_option]}"
        else
            run_command "upload_data_products.py $network_dir ${template[minsar.upload_option]}"
        fi
    fi

fi

########################
#   Opposite orbit (post MiaplPy)
########################
if [[ $opposite_orbit_flag == "1" ]]; then
    echo "Running minsarApp.bash for opposite orbit ..."
    run_command "create_opposite_orbit_template.bash $template_file"
    [[ -f "${WORK_DIR}/opposite_orbit.txt" ]] || { echo "missing ${WORK_DIR}/opposite_orbit.txt"; exit 1; }
    opposite_orbit_template_file=$(tr -d '\r\n' < "${WORK_DIR}/opposite_orbit.txt")
    [[ -f "$opposite_orbit_template_file" ]] || { echo "opposite-orbit template not found: $opposite_orbit_template_file"; exit 1; }
    reduced_args="$(get_modified_command_line_for_opposite_orbit)"
    run_command "${SCRIPT_DIR}/${SCRIPT_NAME} $opposite_orbit_template_file $reduced_args"
fi


########################
#   Horzvert 
########################
if [[ $horzvert_flag == "1" ]]; then
    ref_lalo="$(get_ref_lalo_from_template_file)"
    if [[ mintpy_flag == "1" ]]; then
       cmd="horzvert_timeseries.bash $template_file%.template}/mintpy $opposite_orbit_template_file%.template}/mintpy"
       run_command "$cmd"
    fi
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
echo "Yup! That's all!"
echo

echo "Data products uploaded to:"
if [[ -f "upload.log" ]]; then
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
if [[ -f "insarmaps.log" ]]; then
    tail -n $lines insarmaps.log
fi

