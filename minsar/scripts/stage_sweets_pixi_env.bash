#!/usr/bin/env bash
# Scratch staging of the SWEETS pixi env is disabled.
# Batch jobs use $MINSAR_HOME/tools/sweets/.pixi/envs/default (or $SWEETS_ENV if set).

set -euo pipefail

print_help() {
    cat <<EOF
usage: stage_sweets_pixi_env.bash [-h] [--force]

No-op: scratch staging of SWEETS pixi is disabled.
Jobs use \$MINSAR_HOME/tools/sweets/.pixi/envs/default (override with \$SWEETS_ENV).

options:
  -h, --help   show this help
  --force      ignored (kept for old callers)

Examples:
  stage_sweets_pixi_env.bash
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            print_help
            exit 0
            ;;
        --force)
            shift
            ;;
        -*)
            echo "Error: unknown option: $1" >&2
            exit 1
            ;;
        *)
            echo "Error: unexpected argument: $1" >&2
            exit 1
            ;;
    esac
done

echo "SWEETS pixi scratch staging is disabled; using in-tree env under \$MINSAR_HOME/tools/sweets."
exit 0
