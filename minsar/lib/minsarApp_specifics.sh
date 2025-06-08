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
