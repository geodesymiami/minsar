#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/minsarApp_specifics.sh
source "${SCRIPT_DIR}/../lib/minsarApp_specifics.sh"

# No-args, --help, and -h are handled inside abbrev_path.
abbrev_path "$@"
