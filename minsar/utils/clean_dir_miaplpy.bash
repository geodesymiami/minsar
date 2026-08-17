#!/usr/bin/env bash
# Legacy name: delegate to minsar/bin/clean_miaplpy_from_step.bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/../bin/clean_miaplpy_from_step.bash" "$@"
