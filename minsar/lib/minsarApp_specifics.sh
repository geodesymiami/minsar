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
# Reference lat/lon for horzvert (and similar): prefer minsar.reference.lalo, else
# mintpy.reference.lalo, else empty minsar key. Uses global associative array
# `template` (populate with create_template_array first).
function get_ref_lalo_from_template_file() {
    if [[ -n "${template[minsar.reference.lalo]:-}" ]]; then
        printf '%s' "${template[minsar.reference.lalo]}"
    elif [[ -n "${template[mintpy.reference.lalo]:-}" ]]; then
        printf '%s' "${template[mintpy.reference.lalo]}"
    else
        printf '%s' "${template[minsar.reference.lalo]:-}"
    fi
}

###########################################
# Args for recursive minsarApp after opposite-orbit: copy of CLI args from global array
# `args` (see minsarApp.bash), excluding --opposite-orbit / --no-opposite-orbit.
# Does not include the template (args[0]); join with spaces for use in run_command.
function get_modified_command_line_for_opposite_orbit() {
    local -a out=()
    local a
    for a in "${args[@]:1}"; do
        [[ "$a" == "--opposite-orbit" ]] && continue
        [[ "$a" == "--no-opposite-orbit" ]] && continue
        [[ "$a" == "--file-size" ]] && continue
        [[ "$a" == "--footer-logs-only" ]] && continue
        out+=("$a")
    done
    local saved_ifs="$IFS"
    IFS=' '
    printf '%s' "${out[*]}"
    IFS="$saved_ifs"
}

###########################################
# Human-readable file size as "448 MB" / "16 GB" (logical size: GNU --apparent-size, else du -h fallback).
function _minsar_he5_filesize_readable() {
    local f="$1"
    local line sz num suf
    [[ -f "$f" ]] || { printf '%s\n' "?"; return 0; }
    if ! line=$(du -h --apparent-size "$f" 2>/dev/null); then
        line=$(LC_ALL=C du -h "$f" 2>/dev/null) || { printf '%s\n' "?"; return 0; }
    fi
    sz=$(printf '%s' "$line" | awk '{ print $1 }')
    num="${sz%%[KkMmGgTtPp]*}"
    suf="${sz#"$num"}"
    suf=$(printf '%s' "$suf" | LC_ALL=C tr '[:lower:]' '[:upper:]')
    suf="${suf%I*}"
    case "${suf}" in
        K|KB) printf '%s KB' "${num}" ;;
        M|MB) printf '%s MB' "${num}" ;;
        G|GB) printf '%s GB' "${num}" ;;
        T|TB) printf '%s TB' "${num}" ;;
        P|PB) printf '%s PB' "${num}" ;;
        *)    printf '%s' "${sz}" ;;
    esac
}

###########################################
function _minsar_print_he5_path_colon_size() {
    local f
    for f in "$@"; do
        [[ -f "$f" ]] || continue
        printf '%s : %s\n' "$f" "$(_minsar_he5_filesize_readable "$f")"
    done
}

###########################################
# Under WORK_DIR with cwd set there: MiaplPy network_* directory (basename), or empty.
function _minsar_footer_guess_network_dir() {
    local nd_saved
    nd_saved=$(shopt -p nullglob)
    shopt -s nullglob
    local -a m=( miaplpy_*/network_* )
    eval "${nd_saved}"
    if [[ ${#m[@]} -eq 0 ]]; then
        printf ''
        return 0
    fi
    LC_ALL=C printf '%s\n' "${m[@]}" | LC_ALL=C sort | head -n1
}

###########################################
# Resolve PROJECT WORK_DIR from print_summary argv: directory path, or *.template → $SCRATCHDIR/<basename-project>.
function _print_summary_work_dir_from_arg() {
    local arg="$1"
    if [[ -z "$arg" ]]; then
        printf 'print_summary: missing WORK_DIR or *.template path.\n' >&2
        return 2
    fi
    if [[ -d "$arg" ]]; then
        cd "$arg" && pwd || return 2
        return 0
    fi
    if [[ "$arg" == *.template ]]; then
        if [[ -z "${SCRATCHDIR:-}" ]]; then
            printf 'print_summary: SCRATCHDIR must be set to resolve a *.template path.\n' >&2
            return 2
        fi
        local pn
        pn=$(basename -- "$arg" | awk -F ".template" '{print $1}')
        if [[ -z "$pn" ]]; then
            printf 'print_summary: could not derive project name from template path.\n' >&2
            return 2
        fi
        printf '%s/%s\n' "$(cd "${SCRATCHDIR}" && pwd)" "$pn"
        return 0
    fi
    printf 'print_summary: not a directory and not *.template path: %q\n' "$arg" >&2
    return 2
}

###########################################
# Summary for one stack: pass a MinSAR *.template file or explicit PROJECT WORK_DIR.
# Nested minsarApp (opposite orbit) must set MINSAR_SKIP_PRINT_SUMMARY=1 so the parent prints both stacks.
#
# Usage:
#   print_summary [--help|-h]
#   print_summary [--filesize] TEMPLATE_OR_WORK_DIR
function print_summary() {
    case "${1:-}" in
        --help|-h)
            printf '%s\n' \
                "Usage: print_summary [--filesize] TEMPLATE_OR_WORK_DIR" \
                "       print_summary [--help|-h]" \
                "" \
                "Summarize ONE MinSAR project tree, identified by either:" \
                "  • WORK_DIR directory path, or" \
                "  • path ending in .template → WORK_DIR is \"\$SCRATCHDIR/<name before .template>\" (same as minsarApp.bash)." \
                "" \
                "  --filesize   HDF-EOS *.he5 paths and sizes (mintpy/ and inferred miaplpy_*/network_*/)." \
                "  (no flag)    Full upload.log and insarmaps.log when each exists in that WORK_DIR." \
                "" \
                "Example:" \
                '  print_summary --filesize "$TE/myproject087.template"' \
                '  print_summary          "$TE/myproject087.template"' \
                ""
            return 0
            ;;
    esac

    local want_filesize=0
    if [[ "${1:-}" == "--filesize" ]]; then
        want_filesize=1
        shift
    fi

    if [[ $# -lt 1 ]]; then
        printf 'print_summary: expected WORK_DIR or *.template argument (see --help).\n' >&2
        return 2
    fi
    local target="$1"
    if [[ "$target" == --* ]]; then
        printf 'print_summary: unknown option %q (see --help).\n' "$target" >&2
        return 2
    fi
    shift
    if [[ $# -gt 0 ]]; then
        printf 'print_summary: unexpected extra arguments: %q\n' "$*" >&2
        return 2
    fi

    local wd
    wd=$(_print_summary_work_dir_from_arg "$target") || return 2

    local network_dir nd_saved_nullglob
    local -a mintpy_he5 net_he5 all_he5

    (
        cd "$wd" || {
            printf 'print_summary: cannot cd to %q\n' "$wd" >&2
            exit 2
        }

        network_dir="$(_minsar_footer_guess_network_dir)"

        if [[ -d mintpy ]]; then
            mapfile -t mintpy_he5 < <(find mintpy -maxdepth 1 -type f \( -iname '*.he5' \) -print 2>/dev/null | LC_ALL=C sort)
        else
            mintpy_he5=()
        fi
        if [[ -n "${network_dir}" && -d "${network_dir}" ]]; then
            mapfile -t net_he5 < <(find "${network_dir}" -maxdepth 1 -type f \( -iname '*.he5' \) -print 2>/dev/null | LC_ALL=C sort)
        else
            net_he5=()
        fi
        if [[ -n "${network_dir}" && -d "${network_dir}" && ${#net_he5[@]} -eq 0 ]]; then
            nd_saved_nullglob=$(shopt -p nullglob)
            shopt -s nullglob
            net_he5=( "${network_dir}"/*.he5 "${network_dir}"/*.HE5 )
            eval "${nd_saved_nullglob}"
        fi

        if [[ ${#mintpy_he5[@]} -gt 0 || ${#net_he5[@]} -gt 0 ]]; then
            mapfile -t all_he5 < <(printf '%s\n' "${mintpy_he5[@]}" "${net_he5[@]}" | LC_ALL=C sort -u)
        else
            all_he5=()
        fi

        if [[ "$want_filesize" -eq 1 ]]; then
            if [[ ${#all_he5[@]} -gt 0 ]]; then
                echo "Products:"
                _minsar_print_he5_path_colon_size "${all_he5[@]}"
                echo
            fi
        else
            if [[ -f upload.log ]]; then
                echo "upload.log:"
                cat upload.log
                echo
            fi
            if [[ -f insarmaps.log ]]; then
                echo "insarmaps.log:"
                cat insarmaps.log
                echo
            fi
        fi
    )
}

###########################################
function run_command() {
    local cmd="$*"

    # Replace long paths with shorter variable references for logging
    local log_cmd="$cmd"
    if [[ -n "$SCRATCHDIR" ]]; then
        log_cmd="${log_cmd//$SCRATCHDIR/\$SCRATCHDIR}"
    fi
    if [[ -n "$TE" ]]; then
        log_cmd="${log_cmd//$TE/\$TE}"
    fi
    if [[ -n "$SAMPLESDIR" ]]; then
        log_cmd="${log_cmd//$SAMPLESDIR/\$SAMPLESDIR}"
    fi

    echo "Running.... $cmd"
    echo "$(date +"%Y%m%d:%H-%M") * $log_cmd" | tee -a log
    eval "$cmd"
    local exit_status="$?"
    if [[ $exit_status -ne 0 ]]; then
        echo "$cmd exited with a non-zero exit code (exit code: $exit_status). Exiting."
        exit 1;
    fi
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
# Burst count for one topsStack IW* directory (geom_reference, coreg_secondarys, or overlap).
# Same priority everywhere: geometry rasters first, then burst products/metadata.
function _minsar_count_bursts_one_iw_dir() {
    local d="$1"
    local c
    [[ -d "$d" ]] || { printf '%s\n' 0; return; }
    c=$(ls "$d"/hgt*rdr 2>/dev/null | wc -l | tr -d '[:space:]')
    [[ "${c:-0}" -gt 0 ]] && { printf '%s\n' "$c"; return; }
    c=$(ls "$d"/lat_*.rdr 2>/dev/null | wc -l | tr -d '[:space:]')
    [[ "${c:-0}" -gt 0 ]] && { printf '%s\n' "$c"; return; }
    c=$(ls "$d"/burst*xml 2>/dev/null | wc -l | tr -d '[:space:]')
    [[ "${c:-0}" -gt 0 ]] && { printf '%s\n' "$c"; return; }
    c=$(ls "$d"/range_*.off.xml 2>/dev/null | wc -l | tr -d '[:space:]')
    [[ "${c:-0}" -gt 0 ]] && { printf '%s\n' "$c"; return; }
    c=$(ls "$d"/burst_*.slc 2>/dev/null | wc -l | tr -d '[:space:]')
    [[ "${c:-0}" -gt 0 ]] && { printf '%s\n' "$c"; return; }
    printf '%s\n' 0
}

#####################################################################
function countbursts(){
                   local subswath date total icount reference_date total_geom
                   local -a array iwdirs

                   # geom_reference and coreg_secondarys: identical per-IW* counting (see _minsar_count_bursts_one_iw_dir)
                   array=()
                   total_geom=0
                   while IFS= read -r subswath; do
                       [[ -d "$subswath" ]] || continue
                       icount=$(_minsar_count_bursts_one_iw_dir "$subswath")
                       array+=("$icount")
                       total_geom=$((total_geom + icount))
                   done < <(ls -d geom_reference/IW* 2>/dev/null | sort -V)

                   reference_date=$(get_reference_date)
                   echo "geom_reference/$reference_date   #of_bursts: $total_geom   ${array[*]}"

                   for date in coreg_secondarys/*; do
                       [[ -d "$date" ]] || continue
                       iwdirs=()
                       while IFS= read -r subswath; do
                           iwdirs+=("$subswath")
                       done < <(ls -d "$date"/IW* 2>/dev/null | sort -V)
                       if [[ ${#iwdirs[@]} -eq 0 ]] || [[ ! -d "${iwdirs[0]:-}" ]]; then
                           iwdirs=()
                           while IFS= read -r subswath; do
                               iwdirs+=("$subswath")
                           done < <(ls -d "$date"/overlap/IW* 2>/dev/null | sort -V)
                       fi
                       array=()
                       total=0
                       for subswath in "${iwdirs[@]}"; do
                           [[ -d "$subswath" ]] || continue
                           icount=$(_minsar_count_bursts_one_iw_dir "$subswath")
                           array+=("$icount")
                           total=$((total + icount))
                       done
                       # 1-burst: ISCE may write only overlap (IW1_top.xml, IW1_bottom.xml), no burst_01.slc.xml
                       if [[ "$total" -eq 0 ]] && [[ -d "$date/overlap" ]]; then
                           if [[ -d "$date/overlap/IW1" ]] || [[ -f "$date/overlap/IW1_top.xml" ]] || [[ -f "$date/overlap/IW1_bottom.xml" ]]; then
                               total=1
                               array=(1)
                           fi
                       fi
                       echo "$date #of_bursts: $total   ${array[*]}"
                   done
                   }
#####################################################################
function check_bursts(){
   # FA 8/2025: This  function does not properly calculate number_of_dates_with_less_or_equal_bursts_than_reference and number_of_dates_with_less_bursts_than_reference for example when reference has most bursts
   # determine whether to select new reference date
   #countbursts | tr '/' ' ' | sort -k 1 | sort -k 2 | sort -k 4 -s | sed 's/ /\//' > number_of_bursts_sorted.txt
   #countbursts | tr '/' ' ' | sort -k4,4nr | sed 's/ /\//' > number_of_bursts_sorted.txt
   countbursts | awk '{$1=$1}1' OFS='\t' | sort -k4,4r -k1,1r > number_of_bursts_sorted.txt
   number_of_dates_with_less_or_equal_bursts_than_reference=$(grep -n reference number_of_bursts_sorted.txt | cut -f1 -d:)
      echo "Number of dates with less or equal bursts than reference: $number_of_dates_with_less_or_equal_bursts_than_reference"
   number_of_dates_with_less_bursts_than_reference=$(( $number_of_dates_with_less_or_equal_bursts_than_reference - 1 ))
      echo "Number of dates with less bursts than reference: $number_of_dates_with_less_bursts_than_reference"
   number_of_dates=$(wc -l < number_of_bursts_sorted.txt)
       echo "Total number of dates: $number_of_dates"
   percentage_of_dates_with_less_bursts_than_reference=$(echo "scale=2; $number_of_dates_with_less_bursts_than_reference / $number_of_dates * 100"  | bc)
       echo "Percentage of dates with less bursts than reference: $percentage_of_dates_with_less_bursts_than_reference"
   percentage_of_dates_allowed_to_exclude=1
   percentage_of_dates_allowed_to_exclude=3  # FA 12 Mar 2022: changed to 1 %
   tmp=$(echo "$percentage_of_dates_allowed_to_exclude $number_of_dates" | awk '{printf "%f", $1 / 100 * $2}')
   number_of_dates_allowed_to_exclude="${tmp%.*}"

   new_reference_date=$(head -$((number_of_dates_allowed_to_exclude+1))  number_of_bursts_sorted.txt | tail -1 | awk '{print $1}' | cut -d'/' -f2)

   if [[ $(echo "$percentage_of_dates_with_less_bursts_than_reference > $percentage_of_dates_allowed_to_exclude"  | bc -l ) -eq 1 ]] && [[ $new_reference_date != $reference_date ]] ; then
      new_reference_flag=1
   else
      new_reference_flag=0
   fi

   echo "#########################################">> log 
   echo "Number of dates with less bursts than reference: $number_of_dates_with_less_bursts_than_reference">> log
   echo "Total number of dates: $number_of_dates">> log
   echo "Percentage of dates with less bursts than reference: $percentage_of_dates_with_less_bursts_than_reference">> log
   echo "# head -$number_of_dates_with_less_or_equal_bursts_than_reference  number_of_bursts_sorted.txt:">> log
   head -"$number_of_dates_with_less_or_equal_bursts_than_reference" number_of_bursts_sorted.txt>> log
   echo "new_reference_flag, new_reference_date: $new_reference_flag $new_reference_date">> log

   echo "$new_reference_flag $new_reference_date"
}
# Function: shorten_path
# Usage: shorten_path <template_file>
# Description:
#   Replaces the full directory path of a given template file with
#   a variable reference ($TE or $SAMPLESDIR) if the file resides
#   in one of those directories. Otherwise, returns the full path.
shorten_path() {
    local template_file="$1"
    local template_file_dir
    template_file_dir=$(dirname "$template_file")

    if [[ "$template_file_dir" == "$TEMPLATES" ]]; then
        echo "\$TE/$(basename "$template_file")"
    elif [[ "$template_file_dir" == "$SAMPLESDIR" ]]; then
        echo "\$SAMPLESDIR/$(basename "$template_file")"
    else
        echo "$template_file"
    fi
}
###########################################
###########################################
###########################################

generate_create_isce_jobfiles_script() {
    # Call: generate_prepare_isce_script <template_file>
    local template_file="$1"
    local output_script="run_create_isce_jobfiles.bash"

    template_file=$(shorten_path "$template_file")

    printf "#!/usr/bin/env bash\n" > "$output_script"

    printf "\n# ORIGINAL COMMAND:  BUFOPT in last line ommitted\n" >> "$output_script"
    printf "# if [[ \$template_file == *\"Tsx\"* ]] || [[ \$template_file == *\"Csk\"* ]]; then\n" >> "$output_script"
    printf "#     BUFFOPT=\"PYTHONUNBUFFERED=1\"\n" >> "$output_script"
    printf "# fi\n" >> "$output_script"
    printf "# ( run_command \"\$BUFFOPT create_runfiles.py \$template_file --jobfiles --queue \$QUEUENAME\" ) 2>out_create_jobfiles.e | tee out_create_jobfiles.o\n" >> "$output_script"

    echo "create_runfiles.py $template_file --jobfiles --queue \$QUEUENAME 2>out_create_jobfiles.e >out_create_jobfiles.o" >> "$output_script"

    chmod +x "$output_script"
}

generate_mintpy_script() {
    # Call: generate_mintpy_script <template_file> <processing_dir>
    local template_file="$1"
    local processing_dir="$2"
    local output_script="run_mintpy.bash"
    
    template_file=$(shorten_path "$template_file")

    printf "#!/usr/bin/env bash\n" > "$output_script"
    printf "\n# create and run smallbasline_wrapper.job\n" >> "$output_script"
    printf "create_mintpy_jobfile.py $template_file $processing_dir\n" >> "$output_script"
    printf "run_workflow.bash $template_file --jobfile ${PWD}/smallbaseline_wrapper.job\n\n" >> "$output_script"

    chmod +x "$output_script"
}

generate_miaplpy_script() {
    # Call: generate_miaplpy_script <template_file>
    local template_file="$1"
    local output_script="run_miaplpy.bash"

    template_file=$(shorten_path "$template_file")

    printf "#!/usr/bin/env bash\n" > "$output_script"
    
    
    printf "\n# create and run miaplpyApp.job\n" >> "$output_script"
    printf "create_miaplpyApp_jobfile.py $template_file $miaplpy_dir_name --queue $QUEUENAME\n" >> "$output_script"
    printf "run_workflow.bash $template_file --jobfile ${PWD}/miaplpyApp.job\n" >> "$output_script"
    
    printf "\n# run miaplpy jobfiles\n" >> "$output_script"
    printf "run_workflow.bash $template_file --dostep miaplpy --dir $miaplpy_dir_name\n" >> "$output_script"
    
    printf "\n# create and run run_10_save_hdfeos5_radar.job\n" >> "$output_script"
    printf "create_save_hdfeos5_jobfile.py  $template_file $network_dir --outdir $network_dir/run_files --outfile run_10_save_hdfeos5_radar_0 --queue $QUEUENAME\n" >> "$output_script"
    printf "run_workflow.bash $template_file --dir $miaplpy_dir_name --start 10\n" >> "$output_script"
    
    printf "\n# create index.html containing images\n" >> "$output_script"
    printf "create_html.py ${network_dir}/pic\n\n" >> "$output_script"

    chmod +x "$output_script"
}

generate_insarmaps_script() {
    # Call: generate_insarmaps_script <template_file> <data_dir> <dataset>
    local template_file="$1"
    local data_dir="$2"
    local dataset="$3"
    local output_script="run_insarmaps.bash"

    template_file=$(shorten_path "$template_file")

    printf "#!/usr/bin/env bash\n" > "$output_script"
    printf "\n# create and run insarmaps.job\n" >> "$output_script"
    printf "create_insarmaps_jobfile.py $data_dir --dataset $dataset\n" >> "$output_script"
    printf "run_workflow.bash $template_file --jobfile ${PWD}/insarmaps.job\n\n" >> "$output_script"

    chmod +x "$output_script"
}

generate_upload_script() {
    # Call: generate_upload_script <data_dir> [<option>]
    local dir="$1"
    local option="${2:-}"
    local output_script="run_upload.bash"
    
    printf "#!/usr/bin/env bash" > "$output_script"
    printf "\n# run upload_data_products.py\n" >> "$output_script"
    printf "upload_data_products.py $dir $option\n\n" >> "$output_script"

    chmod +x "$output_script"
}
