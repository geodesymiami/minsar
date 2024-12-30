#!/usr/bin/env bash
########################################################################
set -euo pipefail

show_help() {
    cat <<EOF
Usage: ${0##*/} [--dir <directory>] <template_file>

Runs smallbaselineApp.py. Before, running removes incomplete timeseries*h5 files and after the run create pic/index.html

Positional argument:
  template_file                 Path to the template file (required)

Options:
  --dir <mintpy_test>      directory for mintpy processing (default: mintpy)
  -h, --help               Show this help message and exit

Examples:
  ${0##*/} \$SAMPLESDIR/slc_unitGalapagosSenD128.template
  ${0##*/} \$SAMPLESDIR/slc_unitGalapagosSenD128.template --dir mintpy_202001-20241201
EOF
}

# Now log the entire command
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils/minsar_functions.bash"

# Default values
dir="mintpy"          

# Parse command-line arguments
TEMP=$(getopt \
  -o h \
  --long help,dir: \
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
        --dir)
            dir="$2"
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

# ----------------------------------------------------------------------
PROJECT_DIR="$(basename "${template_file%.template}")"
cd "$SCRATCHDIR/$PROJECT_DIR"

log_command_line "log" "$@"

echo "Running..."
echo "check_timeseries_file.bash --dir $dir"
echo "smallbaselineApp.py $template_file --dir $dir"
echo "create_html.py  $dir/pic"

check_timeseries_file.bash --dir $dir
smallbaselineApp.py $template_file --dir $dir
create_html.py  $dir/pic
