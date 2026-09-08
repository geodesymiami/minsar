#!/usr/bin/env bash
# Stage SWEETS pixi env to SCRATCH for SLURM compute nodes (work2 is often noexec/unreadable).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MINSAR_HOME="${MINSAR_HOME:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"

print_help() {
    cat <<EOF
usage: stage_sweets_pixi_env.bash [-h] [--force]

Copy SWEETS pixi default env to SCRATCH for batch jobs.

options:
  -h, --help   show this help
  --force      rsync even when staged python already runs

Examples:
  stage_sweets_pixi_env.bash
  stage_sweets_pixi_env.bash --force
EOF
}

force=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            print_help
            exit 0
            ;;
        --force)
            force=true
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

: "${SCRATCHDIR:?ERROR: SCRATCHDIR is required; source setup/environment.bash}"

src="${MINSAR_HOME}/tools/sweets/.pixi/envs/default"
stage="${SCRATCHDIR}/minsar_sweets_pixi_default"

src_python=""
if [[ -x "$src/bin/python" ]]; then
    src_python="$src/bin/python"
elif [[ -x "$src/bin/python3" ]]; then
    src_python="$src/bin/python3"
fi
[[ -n "$src_python" ]] || {
    echo "Error: SWEETS pixi env incomplete (no python): $src" >&2
    echo "Re-run: setup/install_isce3.bash" >&2
    exit 1
}
"$src_python" -c "import opera_utils" >/dev/null 2>&1 || {
    echo "Error: SWEETS pixi env cannot import opera_utils: $src" >&2
    echo "Re-run: setup/install_isce3.bash" >&2
    exit 1
}

if [[ "$force" != "true" ]] && [[ -x "$stage/bin/python3" ]] && "$stage/bin/python3" -c "import opera_utils" >/dev/null 2>&1; then
    echo "SWEETS pixi env already staged: $stage"
    exit 0
fi

echo "Staging SWEETS pixi env: $src -> $stage"
mkdir -p "$stage"
rsync -a "$src/" "$stage/"
"$stage/bin/python" -c "import opera_utils" >/dev/null 2>&1 || {
    echo "Error: staged SWEETS env cannot import opera_utils: $stage" >&2
    exit 1
}
echo "Done. Batch jobs should use SWEETS_ENV=$stage"
