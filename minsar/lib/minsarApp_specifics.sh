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
    printf "run_workflow.bash $template_file --append --dostep miaplpy --dir $miaplpy_dir_name\n" >> "$output_script"
    
    printf "\n# create and run run_10_save_hdfeos5_radar.job\n" >> "$output_script"
    printf "create_save_hdfeos5_jobfile.py  $template_file $network_dir --outdir $network_dir/run_files --outfile run_10_save_hdfeos5_radar_0 --queue $QUEUENAME --walltime 0:30\n" >> "$output_script"
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
