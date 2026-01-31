#!/usr/bin/env bash
# workflow_utils.sh - Shared utility functions for workflow scripts

###########################################
# abbreviate - Truncate long strings with ellipsis in the middle
# Usage: abbreviate STRING MAX_LENGTH PREFIX_LEN SUFFIX_LEN
# Example: abbreviate "this_is_a_very_long_filename.job" 20 10 7
#          Returns: "this_is_a_...name.job"
###########################################
function abbreviate {
    local abb=$1
    if [[ "${#abb}" -gt $2 ]]; then
        abb=$(echo "$(echo $(basename $abb) | cut -c -$3)...$(echo $(basename $abb) | rev | cut -c -$4 | rev)")
    fi
    echo $abb
}

###########################################
# convert_array_to_comma_separated_string - Convert array to comma-separated string
# Usage: convert_array_to_comma_separated_string "${array[@]}"
# Example: convert_array_to_comma_separated_string "12345" "67890" "11111"
#          Returns: "12345,67890,11111"
###########################################
function convert_array_to_comma_separated_string() {
    local joined_string=""
    for item in "$@"; do
        joined_string+="${item},"
    done
    # Remove the trailing comma at the end
    joined_string="${joined_string%,}"
    echo $joined_string
}

###########################################
# remove_from_list - Remove an item from an array
# Usage: new_array=($(remove_from_list ITEM_TO_REMOVE "${array[@]}"))
# Example: remove_from_list "b" "a" "b" "c" "d"
#          Returns: "a c d"
###########################################
function remove_from_list {
    local var=$1
    shift
    local list=("$@")
    local new_list=()
    
    for item in ${list[@]}; do
        if [ "$item" != "$var" ]; then
            new_list+=("$item")
        fi
    done
    echo "${new_list[@]}"
}

###########################################
# clean_array - Remove empty and whitespace-only elements from an array in-place
# Usage: clean_array ARRAY_NAME (note: pass the name, not the array itself)
# Example: 
#   arr=("a" "" "b" "   " "c")
#   clean_array arr
#   # arr is now ("a" "b" "c")
###########################################
function clean_array() {
    local arr_name="$1"
    local original=()
    local cleaned=()

    # copy array into 'original'
    eval "original=(\"\${${arr_name}[@]}\")"

    # iterate and keep only non-empty, non-whitespace entries
    for item in "${original[@]}"; do
        # Trim whitespace
        local trimmed="$(echo "$item" | xargs)"
        if [[ -n "$trimmed" ]]; then
            cleaned+=("$item")
        fi
    done

    # overwrite original array with cleaned one
    eval "$arr_name=(\"\${cleaned[@]}\")"
}
