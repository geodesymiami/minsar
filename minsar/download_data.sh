#!/usr/bin/env bash
########################################################################
# download SAR data (SLCs, bursts or CSLCs)
set -euo pipefail

# ----------------------------------------------------------------------
# Default values
# ----------------------------------------------------------------------
data_type="SLC"          # one of: SLC, burst, CSLC
download_tool="ssara"    # one of: ssara, asf_search

# ----------------------------------------------------------------------
# Help message
# ----------------------------------------------------------------------
show_help() {
    cat <<EOF
Usage: ${0##*/} [OPTIONS] <template_file>

Downloads SAR data.

Positional argument:
  template_file                 Path to the template file (required)

Options:
  --data-type <SLC|burst|CSLC>      Data type to download (default: SLC)
  --download-tool <ssara|asf_search>  Download tool to use (default: ssara)
  -h, --help                        Show this help message and exit

Examples:
  ${0##*/} --data-type SLC --download-tool ssara my_template.txt
  ${0##*/} --data-type CSLC cslc_template.txt
EOF
}

# ----------------------------------------------------------------------
# Parse command-line arguments
# ----------------------------------------------------------------------
# Use GNU getopt to parse long options (and -h for help).
TEMP=$(getopt \
  -o h \
  --long help,download-tool:,data-type: \
  -n "${0##*/}" -- "$@"
)

# If the getopt parsing failed, exit
if [ $? -ne 0 ]; then
    echo "Error: Invalid command line arguments" >&2
    exit 1
fi

# Reorganize the command-line arguments
eval set -- "$TEMP"

# Parse the recognized options
while true; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        --download-tool)
            download_tool="$2"
            shift 2
            ;;
        --data-type)
            data_type="$2"
            shift 2
            ;;
        --)
            # End of recognized options
            shift
            break
            ;;
        *)
            # Should never reach here
            echo "Error: Unexpected option '$1'" >&2
            exit 1
            ;;
    esac
done

# ----------------------------------------------------------------------
# Handle positional argument (template_file)
# ----------------------------------------------------------------------
# After shifting out recognized options, $1 should be the template_file.
if [ $# -lt 1 ]; then
    echo "Error: Missing positional argument <template_file>"
    show_help
    exit 1
fi

template_file="$1"

# If there are extra args, bail out:
if [ $# -gt 1 ]; then
    echo "Error: Too many positional arguments. Only <template_file> is required."
    show_help
    exit 1
fi

# ----------------------------------------------------------------------
# Validate data_type
# ----------------------------------------------------------------------
case "$data_type" in
    SLC|burst|CSLC)
        ;;
    *)
        echo "Error: Invalid --data-type '$data_type'. Valid choices: SLC, burst, CSLC" >&2
        exit 1
        ;;
esac

# ----------------------------------------------------------------------
# Validate download_tool
# ----------------------------------------------------------------------
case "$download_tool" in
    ssara|asf_search)
        ;;
    *)
        echo "Error: Invalid --download-tool '$download_tool'. Valid choices: ssara, asf_search" >&2
        exit 1
        ;;
esac

# ----------------------------------------------------------------------
# Main script logic
# ----------------------------------------------------------------------
echo "Data type:       $data_type"
echo "Download tool:   $download_tool"
echo "Template file:   $template_file"

if [ "$download_tool" = "ssara" ]; then
  echo "Downloading SLCs using $download_tool..."
  generate_download_command.py $template_file
  mkdir -p SLC
  cd SLC
  bash ../download_ssara.txt
  cd ..
fi

# Example logic:
# if [ "$data_type" = "SLC" ]; then
#   echo "Downloading SLCs using $download_tool..."
#   # ...
# elif [ "$data_type" = "burst" ]; then
#   echo "Downloading bursts using $download_tool..."
#   # ...
# else
#   echo "Downloading CSLCs using $download_tool..."
#   # ...
# fi

