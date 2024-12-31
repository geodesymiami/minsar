#!/usr/bin/env bash
########################################################################
# download SAR data (SLCs, bursts or CSLCs)
set -euo pipefail

# Help message
show_help() {
    cat <<EOF
Usage: ${0##*/} [--data-type <SLC|burst|CSLC>] [--download-tool <ssara|asf_search>] <template_file>

Downloads SAR data.

Positional argument:
  template_file                 Path to the template file (required)

Options:
  --data-type <SLC|burst|CSLC>       Data type to download (default: SLC)
  --download-tool <ssara|asf_search> Download tool to use (default: ssara)
  -h, --help                         Show this help message and exit

Examples:
  ${0##*/} \$SAMPLESDIR/slc_unitGalapagosSenD128.template
  ${0##*/} \$SAMPLESDIR/slc_unitGalapagosSenD128.template --data-type SLC --download-tool ssara
  ${0##*/} \$SAMPLESDIR/burst_unitGalapagosSenD128.template --data-type burst --download-tool ssara
  ${0##*/} \$SAMPLESDIR/cslc_unitGalapagosSenD128.template --data-type CSLC 
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils/minsar_functions.bash"

# Default values
data_type="SLC"          # one of: SLC, burst, CSLC
download_tool="ssara"    # one of: ssara, asf_search

# Parse command-line arguments
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

case "$data_type" in
    SLC|burst|CSLC)
        ;;
    *)
        echo "Error: Invalid --data-type '$data_type'. Valid choices: SLC, burst, CSLC" >&2
        exit 1
        ;;
esac

case "$download_tool" in
    ssara|asf_search)
        ;;
    *)
        echo "Error: Invalid --download-tool '$download_tool'. Valid choices: ssara, asf_search" >&2
        exit 1
        ;;
esac

# ----------------------------------------------------------------------
#echo "Data type:       $data_type"
#echo "Download tool:   $download_tool"
#echo "Template file:   $template_file"

PROJECT_DIR="$(basename "${template_file%.template}")"
mkdir -p "$SCRATCHDIR/$PROJECT_DIR"
cd "$SCRATCHDIR/$PROJECT_DIR"

log_command_line "log" "$@"

if [ "$download_tool" = "ssara" ]; then
  echo "Downloading SLCs using $download_tool..."
  generate_download_command.py $template_file
  mkdir -p SLC
  cd SLC
  bash ../download_ssara.cmd
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

