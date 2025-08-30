###########################################
cpus_per_node_skx_dev=48
cpus_per_node_skx=48
cpus_per_node_icx=80
max_walltime_skx_dev="02:00:00"   # HH:MM:SS

###########################################
hms_to_sec() {
  local t="$1"
  awk -F: '{
    if (NF==3) {print ($1*3600)+($2*60)+$3}
    else if (NF==2) {print ($1*60)+$2}
    else {print $1}
  }' <<<"$t"
}
###########################################
function changequeuenormal() {
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
   echo "  Usage: changequeuenormal run_10*.job"; return
fi
if [[ $PLATFORM_NAME == "frontera" ]] ; then
          sed -i "s|flex|normal|g" "$@" ;
          sed -i "s|small|normal|g" "$@" ;
          sed -i "s|development|normal|g" "$@" ;
elif [[ $PLATFORM_NAME == "stampede3" ]] ; then
          sed -i "s|skx-dev|skx|g" "$@" ;
          sed -i "s|icx|skx|g" "$@" ;
          sed -i "s/^#SBATCH -n \s*[0-9]\+/#SBATCH -n ${cpus_per_node_skx}/" "$f"
fi
}
###########################################
function changequeueicx() {
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
   echo "  Usage: changequeueicx run_10*.job"; return
fi
if [[ $PLATFORM_NAME == "stampede3" ]] ; then
          sed -i "s|skx-dev|icx|g" "$@" ;
          sed -i "s|skx|icx|g" "$@" ;
          sed -i "s/^#SBATCH -n \s*[0-9]\+/#SBATCH -n ${cpus_per_node_icx}/" "$@"
fi
}
###########################################
scancel_jobs() {
    if [ -z "$1" ] || [ "$1" == "--help" ]; then
        echo
        echo "Usage: scancel_jobs <job_name_pattern>"
        echo
        echo "Cancels all SLURM jobs containing the specified pattern in their name."
        echo
        echo "Example: scancel_jobs run_05"
        echo
        return 0
    fi

    job_name_pattern=$1
    for job_id in $(squeue -u $USER -o "%.18i %.100j" | grep "$job_name_pattern" | awk '{print $1}'); do
        scancel $job_id
    done
}

###########################################
function changequeuedev() {
  if [[ "$1" == "--help" || "$1" == "-h" || "$#" -lt 1 ]]; then
    echo "Usage: changequeuedev run_10*.job [more .job files]"
    echo "  * frontera: set queue to development and ~2h walltime"
    echo "  * stampede3: set partition to skx-dev, -n=${cpus_per_node_skx_dev},"
    echo "               and cap walltime at ${max_walltime_skx_dev}"
    return
  fi

  if [[ "${PLATFORM_NAME}" == "frontera" ]]; then

    sed -i 's/^#SBATCH -p \s*flex/#SBATCH -p development/'   "$@"
    sed -i 's/^#SBATCH -p \s*small/#SBATCH -p development/'  "$@"
    sed -i 's/^#SBATCH -p \s*normal/#SBATCH -p development/' "$@"

    sed -i 's/^#SBATCH -t \s*[0-9]\{1,2\}:[0-9]\{2\}:[0-9]\{2\}/#SBATCH -t 01:59:00/' "$@"

  elif [[ "${PLATFORM_NAME}" == "stampede3" ]]; then
    for f in "$@"; do

      if grep -q '^#SBATCH -p icx' "$f"; then
         sed -i 's/^#SBATCH -p \s*icx/#SBATCH -p skx-dev/' "$f"
      elif grep -q '^#SBATCH -p skx ' "$f"; then
         sed -i 's/^#SBATCH -p \s*skx/#SBATCH -p skx-dev/' "$f"
      fi

      sed -i "s/^#SBATCH -n \s*[0-9]\+/#SBATCH -n ${cpus_per_node_skx_dev}/" "$f"

      # Cap walltime at max_walltime_skx_dev if current > max
      if grep -q '^#SBATCH -t ' "$f"; then
        current=$(grep '^#SBATCH -t ' "$f" | head -n1 | awk '{print $3}')
        current_secs=$(hms_to_sec "$current")
        max_secs=$(hms_to_sec "$max_walltime_skx_dev")
        if (( current_secs > max_secs )); then
          # replace only the first occurrence to be safe
          awk -v newt="$max_walltime_skx_dev" '
            BEGIN{done=0}
            {
              if (!done && $0 ~ /^#SBATCH -t /) {
                sub(/^#SBATCH -t[ \t]+[0-9:]+/, "#SBATCH -t " newt)
                done=1
              }
              print
            }' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
        fi
      fi
    done
  else
    echo "PLATFORM_NAME='${PLATFORM_NAME}' not recognized. No changes made."
  fi
}

###########################################
function changequeueflex() {
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
   echo "  Usage: changequeueflex run_10*.job"; return
fi
if [[ $PLATFORM_NAME == "frontera" ]] ; then
          sed -i "s|normal|flex|g" "$@" ;
          sed -i "s|small|flex|g" "$@" ;
          sed -i "s|development|flex|g" "$@" ;
fi
}

#function changequeuedev() { sed -i "s|skx-normal|$QUEUE_DEV|g"  "$@" ; sed -i "s|flex|$QUEUE_DEV|g"  "$@" ; sed -i "s|normal|$QUEUE_DEV|g"  "$@" ; }
function changequeuesmall() { sed -i "s|flex|small|g" "$@" ; sed -i "s|development|small|g" "$@" ; sed -i "s|normal|small|g" "$@" ; }
#function changequeueflex()  { sed -i "s|small|flex|g" "$@" ; sed -i "s|development|flex|g"  "$@" ; }

###########################################
function check_matplotlib_pyplot(){
   #set -x
   #Check if 'timeout' command is available
   if command -v timeout &> /dev/null; then
      timeout 120 python -c "import matplotlib.pyplot"
   else
      gtimeout 120 python -c "import matplotlib.pyplot"
   fi
   exit_status=$?
   if [[ $exit_status -ne 0 ]]; then
      echo "Can't import. Reason unknown. Try a new shell (exit_status: $exit_status)"
      return 1;
   fi
   #echo Continue ... python -c \"import matplotlib.pyplot\" was successful within 6 secs
   echo "        ... successful, continue ... "
   return 0
}
###########################################
function listc() {
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
helptext="                                       \n\
  Examples:                                      \n\
      listc ChamanChunk24SenAT144                \n\
      listc ChamanBigSenAT144                    \n\
      listc ChamanChunksSenAT144                 \n\
      listc SenAT144                             \n\
      listc C*SenAT144                           \n\
                                                 \n\
  List progress of chunk-wise processing.        \n\n\
  Lists S1* files (if exist) or out_* files. Unnecessary string  \n\
  (e.g. Chunk24, Big, Chunks) are stripped from argument. \n\
  Run in \$SCRATCHDIR.  \n
    "
    printf "$helptext"
    return
fi

not_finished=()
arg=$1
arg_mod=*$arg
# modify argument if it contains Chunk or Big
[[ $arg == *"Chunk"* ]] && arg_mod=$(echo $arg | sed -e s/Chunk.\*Sen/\*Sen/)
[[ $arg == *"Big"* ]] && arg_mod=$(echo $arg | sed -e s/Big.\*Sen/\*Sen/)
[[ $arg == *"Chunks"* ]] && arg_mod=$(echo $arg | sed -e s/Chunks.\*Sen/\*Sen/)
#echo Original_argument: $arg
#echo Modified_argument: ${arg_mod}

dir_list=$(ls -d $arg_mod)
for dir in $dir_list; do
   S1_files=( $dir/mintpy/S1* )
   if [[  ${#S1_files[@]} -ne 1 ]]; then
      echo "Too many S1* files: ${S1_files[@]}"
      return
   fi

   if  test -f $dir/mintpy/S1*  ; then
      ls -lh $dir/mintpy/S1* | awk  '{printf "%5s %s %2s %s %s\n", $5,$6,$7,$8,$9}'
   else
      not_finished+=($dir)
   fi
done;
for dir in ${not_finished[@]}; do
    if [[ $dir != *Big* ]] && [[ $dir != *ChunksS* ]]; then
       #ls -lvd $dir/{,out_run*.e}  | awk  '{print $5,$6,$7,$8,$9}'
       ls -lvd $dir/{,out_run*.e}  | awk  '{printf "%5s %s %2s %s %s\n", $5,$6,$7,$8,$9}'
    fi
done
}

###########################################
function add_ref_lalo_to_file() {
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
helptext="                                       \n\
  Examples:                                      \n\
      add_ref_lalo_to_file  S1_IW1_128_0596_0597_20160605_XXXXXXXX_S00860_S00810_W091190_W091130_Del4PS.he5                \n\
                                                 \n\
  adds REF_LAT, REF_LON to file (read from geo_velocity.h5)  \n
    "
    printf "$helptext"
    return
fi

file=$1

echo adding to $file
REF_LAT=$(info.py geo/geo_velocity.h5 | grep REF_LAT | awk '{print $2}')
REF_LON=$(info.py geo/geo_velocity.h5 | grep REF_LON | awk '{print $2}')

$MINTPY_HOME/src/mintpy/legacy/add_attribute.py $file REF_LAT=${REF_LAT}
$MINTPY_HOME/src/mintpy/legacy/add_attribute.py $file REF_LON=${REF_LON}
}

###########################################
function rsyncFJ() {
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
helptext="            \n\
  rsyncFJ:  rsync directory From Jetstream (FJ) server to local \$SCRATCHDIR \n\
                            requires local \$SCRATCHDIR environment variable\n\
                                                 \n\
  Examples:                                      \n\
     rsyncFJ MaunLoaSenAT124                     \n\
     rsyncFJ MaunLoaSenAT124/mintpy_5_20         \n\
     rsyncFJ unittestGalapagosSenDT128/miaplpy/network_single_reference \n\
     rsyncFJ unittestGalapagosSenDT128/miaplpy_SN_201606_201608/inputs \n\
     rsyncFJ unittestGalapagosSenDT128/miaplpy_SN_201606_201608/inverted \n\
"
    printf "$helptext"
    return
fi

if [[ $# -eq 0 && $(basename $(dirname $PWD)) == "scratch" ]]; then
  dir=$(basename $PWD)
else
  dir=$1
fi

set -v
echo "test:"
if [ ! -d "$SCRATCHDIR/$dir" ]; then
  echo "dir $SCRATCHDIR/$dir does not exist, making it"
  mkdir -p $SCRATCHDIR/$dir
fi

echo "Syncing directory $dir from jetstream:"
cmd="rsync -avzh --progress exouser@149.165.154.65:/data/HDF5EOS/$dir/ $SCRATCHDIR/$dir"
echo running ... $cmd
$cmd

if [[ $dir == *"network"* ]]; then
  cmd="rsync -avzh --progress exouser@149.165.154.65:/data/HDF5EOS/${dir%/*}/maskPS.h5 $SCRATCHDIR/${dir%/*}/maskPS.h5"
  echo running ... $cmd
  $cmd
  cmd="rsync -avzh --progress exouser@149.165.154.65:/data/HDF5EOS/$dir/inputs/geometryRadar.h5 $SCRATCHDIR/$dir/inputs"
  echo running ... $cmd
  $cmd
fi

}

###########################################
function rsyncTJ() {
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
helptext="            \n\
  rsyncTJ:  rsync directory TO JETSTREAM server from local $SCRATCHDIR \n\
                                                 \n\
  Examples:                                      \n\
            (from $SCRATCHDIR:)                  \n\
     rsyncTJ MaunLoaSenAT124                     \n\
                                                 \n\
            (from /scratch/MaunaLoaSenAT124:)     \n\
     rsyncTJ                                     \n\
    "
    printf "$helptext"
    return
fi

if [[ $# -eq 0 && $(basename $(dirname $PWD)) == "scratch" ]]; then
  dir=$(basename $PWD)
else
  dir=$1
fi

echo "Syncing directory $dir from jetstream:"
cmd="rsync -avzh --progress $SCRATCHDIR/$dir/ exouser@149.165.154.65:/data/HDF5EOS/$dir "
echo running ... $cmd
$cmd
}

