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
function changequeuepvc() {
  local walltime="7:00:00"
  local -a positionals=()
  local -a jobfile_globs=()
  local -a job_files=()
  local jobfiles_set=0
  local dir=""
  local g f
  local -a matches

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h)
        echo "Usage: changequeuepvc [--walltime HH:MM:SS] [--jobfiles GLOB ...] FILE.job|DIR"
        echo "  stampede3: set partition to pvc, -n=${cpus_per_node_icx}, walltime (default 7:00:00)"
        echo "  DIR mode: select .job files via --jobfiles (default: run_06*.job run_07*.job run_08*.job run_09*.job)"
        echo
        echo "Examples:"
        echo "changequeuepvc run_09*.job"
        echo "changequeuepvc --walltime 2:00:00 run_09*.job"
        echo "changequeuepvc miaplpy/network_delaunay_4/run_files"
        echo "changequeuepvc miaplpy/network_delaunay_4/run_files --jobfiles run_08*.job run_09*.job"
        echo "changequeuepvc --walltime 2:00:00 miaplpy/network_delaunay_4/run_files"
        return 0
        ;;
      --walltime|-t)
        if [[ -z "${2:-}" ]]; then
          echo "Error: --walltime requires HH:MM:SS" >&2
          return 1
        fi
        walltime="$2"
        shift 2
        ;;
      --jobfiles)
        jobfiles_set=1
        shift
        while [[ $# -gt 0 ]]; do
          case "$1" in
            -?*|--*) break ;;
            *)
              jobfile_globs+=("$1")
              shift
              ;;
          esac
        done
        if [[ ${#jobfile_globs[@]} -lt 1 ]]; then
          echo "Error: --jobfiles requires at least one GLOB" >&2
          return 1
        fi
        ;;
      -?*|--*)
        echo "Error: Unknown option: $1" >&2
        echo "Use changequeuepvc --help for available options" >&2
        return 1
        ;;
      *)
        positionals+=("$1")
        shift
        ;;
    esac
  done

  if [[ ${#positionals[@]} -lt 1 ]]; then
    echo "Usage: changequeuepvc [--walltime HH:MM:SS] [--jobfiles GLOB ...] FILE.job|DIR"
    echo "Use changequeuepvc --help for more information"
    return 1
  fi

  if [[ ! "$walltime" =~ ^[0-9]{1,2}:[0-9]{2}(:[0-9]{2})?$ ]]; then
    echo "Error: --walltime must be HH:MM or HH:MM:SS, got: $walltime" >&2
    return 1
  fi

  # Directory mode: exactly one positional that is a directory
  if [[ ${#positionals[@]} -eq 1 && -d "${positionals[0]}" ]]; then
    dir="${positionals[0]}"
    dir="${dir%/}"
    if [[ $jobfiles_set -eq 0 ]]; then
      # Quote patterns so cwd pathname expansion does not rewrite them
      jobfile_globs=('run_06*.job' 'run_07*.job' 'run_08*.job' 'run_09*.job')
    fi
    job_files=()
    shopt -s nullglob
    for g in "${jobfile_globs[@]}"; do
      matches=( "${dir}"/${g} )
      for f in "${matches[@]}"; do
        [[ -f "$f" ]] || continue
        job_files+=("$f")
      done
    done
    shopt -u nullglob
    if [[ ${#job_files[@]} -lt 1 ]]; then
      echo "Error: no job files matched in ${dir}/ with pattern(s): ${jobfile_globs[*]}" >&2
      return 1
    fi
  else
    if [[ $jobfiles_set -eq 1 ]]; then
      echo "Error: --jobfiles is only valid with a directory argument" >&2
      return 1
    fi
    # One positional that is a directory but -d failed earlier is impossible here;
    # still reject directories so we never pass them to sed.
    job_files=()
    for f in "${positionals[@]}"; do
      if [[ -d "$f" ]]; then
        echo "Error: directory given but job files were not resolved: $f" >&2
        echo "Hint: re-source helpers: source \"\${MINSAR_HOME}/minsar/lib/common_helpers.sh\"" >&2
        return 1
      fi
      if [[ ! -f "$f" ]]; then
        echo "Error: not a file or directory: $f" >&2
        return 1
      fi
      job_files+=("$f")
    done
  fi

  if [[ ${#job_files[@]} -lt 1 ]]; then
    echo "Error: no job files to update" >&2
    return 1
  fi
  for f in "${job_files[@]}"; do
    if [[ ! -f "$f" ]]; then
      echo "Error: refusing to edit non-file: $f" >&2
      return 1
    fi
  done

  if [[ "${PLATFORM_NAME}" == "stampede3" ]]; then
    sed -i "s|skx-dev|pvc|g" "${job_files[@]}"
    sed -i "s|skx|pvc|g" "${job_files[@]}"
    sed -i "s/^#SBATCH -n \s*[0-9]\+/#SBATCH -n ${cpus_per_node_icx}/" "${job_files[@]}"
    sed -i "s/^#SBATCH -t .*/#SBATCH -t ${walltime}/" "${job_files[@]}"
    echo "Modified ${#job_files[@]} jobfile(s):"
    printf '  %s\n' "${job_files[@]}"
  fi
}
###########################################
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
# Look up one column from minsar/defaults/queues.cfg for PLATFORM_NAME + queue.
_queue_cfg_value() {
  local platform="$1" queue="$2" param="$3"
  local cfg="${MINSAR_HOME}/minsar/defaults/queues.cfg"
  if [[ ! -f "$cfg" ]]; then
    echo "Error: queues.cfg not found: $cfg" >&2
    return 1
  fi
  awk -v plat="$platform" -v que="$queue" -v param="$param" '
    NR == 1 {
      for (i = 1; i <= NF; i++) if ($i == param) col = i
      next
    }
    $1 == plat && $2 == que {
      if (col) print $col
      exit
    }
  ' "$cfg"
}

###########################################
function changequeuedev() {
  if [[ "$1" == "--help" || "$1" == "-h" || "$#" -lt 1 ]]; then
    echo "Usage: changequeuedev run_10*.job [more .job files]"
    echo "  Set partition to \$QUEUE_DEV (or platform default), -n from queues.cfg"
    echo "  CPUS_PER_NODE, and cap -t at queues.cfg MAX_WALLTIME when longer."
    return
  fi

  local target_queue cpus max_walltime f current current_secs max_secs
  if [[ "${PLATFORM_NAME}" == "frontera" ]]; then
    target_queue="${QUEUE_DEV:-development}"
  elif [[ "${PLATFORM_NAME}" == "stampede3" ]]; then
    target_queue="${QUEUE_DEV:-skx-dev}"
  else
    echo "PLATFORM_NAME='${PLATFORM_NAME}' not recognized. No changes made." >&2
    return 1
  fi

  cpus="$(_queue_cfg_value "${PLATFORM_NAME}" "${target_queue}" CPUS_PER_NODE)" || return 1
  max_walltime="$(_queue_cfg_value "${PLATFORM_NAME}" "${target_queue}" MAX_WALLTIME)" || return 1
  if [[ -z "$cpus" || -z "$max_walltime" ]]; then
    echo "Error: no queues.cfg row for ${PLATFORM_NAME} ${target_queue}" >&2
    return 1
  fi
  max_secs=$(hms_to_sec "$max_walltime")

  for f in "$@"; do
    if [[ ! -f "$f" ]]; then
      echo "Error: not a file: $f" >&2
      return 1
    fi
    sed -i -E "s/^(#SBATCH[[:space:]]+-p[[:space:]]+)[^[:space:]]+/\1${target_queue}/" "$f"
    sed -i -E "s/^(#SBATCH[[:space:]]+-n[[:space:]]+)[0-9]+/\1${cpus}/" "$f"
    if grep -q '^#SBATCH -t ' "$f"; then
      current=$(grep '^#SBATCH -t ' "$f" | head -n1 | awk '{print $3}')
      current_secs=$(hms_to_sec "$current")
      if (( current_secs > max_secs )); then
        sed -i -E "s/^(#SBATCH[[:space:]]+-t[[:space:]]+)[0-9:]+/\1${max_walltime}/" "$f"
      fi
    fi
  done
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
# Show YAML keys/values only (no comments or blank lines).
showy() {
if [[ "$1" == "--help" || "$1" == "-h" || $# -eq 0 ]]; then
    echo "usage: showy FILE.yaml"
    echo
    echo "Print YAML without comment or blank lines."
    echo
    echo "Examples:"
    echo "  showy dolphin_config.yaml"
    echo "  showy /scratch/\$USER/proj/sweets_config.yaml"
    return 0
fi
if [[ ! -f "$1" ]]; then
    echo "Error: file not found: $1" >&2
    return 1
fi
grep -vE '^[[:space:]]*(#|$)' "$1"
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
      add_ref_lalo_to_file  S1_IW1_128_0596_0597_20160605_XXXXXXXX_S00860_S00810_W091190_W091130_Del4PS.he5                            \n\
      add_ref_lalo_to_file  S1_IW1_128_0596_0597_20160605_XXXXXXXX_S00860_S00810_W091190_W091130_Del4PS.he5  --ref-lalo -0.81 -91.190  \n\
                                                 \n\
  adds REF_LAT, REF_LON to file. If --ref-lalo is provided, uses those values;  \n\
  otherwise reads from geo_velocity.h5  \n
    "
    printf "$helptext"
    return
fi

# Parse arguments
ref_lat=""
ref_lon=""
file=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --ref-lalo)
            if [[ $# -lt 3 ]]; then
                echo "Error: --ref-lalo requires two arguments (LAT LON)"
                return 1
            fi
            ref_lat="$2"
            ref_lon="$3"
            shift 3
            ;;
        *)
            if [[ -z "$file" ]]; then
                file="$1"
            else
                echo "Error: Multiple files specified or unknown argument: $1"
                return 1
            fi
            shift
            ;;
    esac
done

# Check if file was provided
if [[ -z "$file" ]]; then
    echo "Error: File argument is required"
    return 1
fi

echo adding to $file

# If ref_lat and ref_lon were not provided, extract from geo_velocity.h5
if [[ -z "$ref_lat" ]] || [[ -z "$ref_lon" ]]; then
    REF_LAT=$(info.py geo/geo_velocity.h5 | grep REF_LAT | awk '{print $2}')
    REF_LON=$(info.py geo/geo_velocity.h5 | grep REF_LON | awk '{print $2}')
else
    REF_LAT="$ref_lat"
    REF_LON="$ref_lon"
fi

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
  rsyncTJ:  rsync directory or file TO JETSTREAM under /data/HDF5EOS/<path-relative-to-\$SCRATCHDIR> \n\
                                                 \n\
  Works from \$SCRATCHDIR or any subdirectory.   \n\
                                                 \n\
  Examples:                                      \n\
     (from \$SCRATCHDIR:)                        \n\
       rsyncTJ q1EtnaSenD128                     \n\
       rsyncTJ q1EtnaSenD128/miaplpy_*/network_*/file.he5 \n\
                                                 \n\
     (from project dir:)                         \n\
       rsyncTJ                                   \n\
       rsyncTJ miaplpy_*/network_*/file.he5      \n\
                                                 \n\
     (from a deep subdir:)                       \n\
       rsyncTJ file.he5                          \n\
    "
    printf "$helptext"
    return
fi

if [[ -z "$SCRATCHDIR" ]]; then
  echo "ERROR: SCRATCHDIR is not set"
  return 1
fi

# Resolve local source: cwd-relative first, then \$SCRATCHDIR-relative; no-arg = current dir
if [[ $# -eq 0 ]]; then
  local_src="$PWD"
else
  arg="$1"
  if [[ -e "$PWD/$arg" ]]; then
    if [[ -d "$PWD/$arg" ]]; then
      local_src="$(cd "$PWD/$arg" && pwd)"
    else
      local_src="$(cd "$(dirname "$PWD/$arg")" && pwd)/$(basename "$arg")"
    fi
  elif [[ -e "$SCRATCHDIR/$arg" ]]; then
    if [[ -d "$SCRATCHDIR/$arg" ]]; then
      local_src="$(cd "$SCRATCHDIR/$arg" && pwd)"
    else
      local_src="$(cd "$(dirname "$SCRATCHDIR/$arg")" && pwd)/$(basename "$arg")"
    fi
  else
    echo "ERROR: $arg not found under \$PWD ($PWD) or \$SCRATCHDIR ($SCRATCHDIR)"
    return 1
  fi
fi

if [[ "$local_src" != "$SCRATCHDIR" && "$local_src" != "$SCRATCHDIR"/* ]]; then
  echo "ERROR: $local_src is not under \$SCRATCHDIR ($SCRATCHDIR)"
  return 1
fi

remote_rel="${local_src#"$SCRATCHDIR"/}"

if [[ -f "$local_src" ]]; then
  echo "Syncing file $remote_rel to jetstream:"
  cmd="rsync -avzh --progress $local_src exouser@149.165.154.65:/data/HDF5EOS/$remote_rel"
elif [[ -d "$local_src" ]]; then
  echo "Syncing directory $remote_rel to jetstream:"
  cmd="rsync -avzh --progress $local_src/ exouser@149.165.154.65:/data/HDF5EOS/$remote_rel "
else
  echo "ERROR: $local_src is neither a file nor a directory"
  return 1
fi
echo running ... $cmd
$cmd
}

