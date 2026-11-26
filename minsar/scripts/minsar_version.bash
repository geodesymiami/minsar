#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TOOLS_DIR="${REPO_ROOT}/tools"
CONDA_ENV_DIR="${TOOLS_DIR}/miniforge3/envs/minsar"
TESTED_VERSIONS_FILE="${REPO_ROOT}/setup/tested_versions.cfg"

# name:kind:arg  (git: directory under tools/, conda: package, pip: distribution, dir: tools/ glob prefix)
# Every git clone in tools/ is listed, so a newly installed tool needs no change here.
COMPONENTS=("isce2-conda:conda:isce2")
while IFS= read -r tool_name; do
    COMPONENTS+=("${tool_name}:git:${tool_name}")
done < <(for git_entry in "${TOOLS_DIR}"/*/.git; do [[ -e "$git_entry" ]] && basename "$(dirname "$git_entry")"; done | LC_ALL=C sort -f)
COMPONENTS+=(
    "burst2safe:pip:burst2safe"
    "asf_search:pip:asf_search"
    "snaphu:dir:snaphu-v"
    "gdal:conda:gdal"
    "python:conda:python"
)
ONE_LINE_COMPONENTS=(isce2-conda MintPy MiaplPy)

show_help() {
    cat <<EOF
usage: $SCRIPT_NAME [-h] [--short | --one-line | --components]

Prints the MinSAR version (from git tags) and the installed dependency versions.
A dependency that differs from setup/tested_versions.cfg is marked with *.

options:
  -h, --help     show this help
  --short        MinSAR version only
  --one-line     MinSAR, isce2 (conda), MintPy and MiaplPy on one line
  --components   dependencies as name=version lines

Examples:
  $SCRIPT_NAME
  $SCRIPT_NAME --short
  $SCRIPT_NAME --one-line
EOF
}

get_minsar_version() {
    local describe hash dirty=""
    if ! git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
        echo "unknown"
        return
    fi
    describe=$(git -C "$REPO_ROOT" describe --tags --long --dirty --match 'v[0-9]*' 2>/dev/null || true)
    if [[ -n "$describe" ]]; then
        # v0.5.0-14-g3b9984c7-dirty -> 0.5.0+14.g3b9984c7.dirty ; exactly on a clean tag -> 0.5.0
        echo "$describe" | sed -E 's/^v(.*)-([0-9]+)-g([0-9a-f]+)(-dirty)?$/\1+\2.g\3\4/; s/-dirty$/.dirty/; s/\+0\.g[0-9a-f]+$//'
        return
    fi
    hash=$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || true)
    if [[ -z "$hash" ]]; then
        echo "unknown"
        return
    fi
    [[ -n "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=no 2>/dev/null)" ]] && dirty=".dirty"
    echo "0.0.0+g${hash}${dirty}"
}

get_component_version() {
    local kind="$1" arg="$2" match version=""
    case "$kind" in
        git)
            version=$(git -C "${TOOLS_DIR}/${arg}" describe --tags --always 2>/dev/null || true)
            ;;
        conda)
            match=$(ls "${CONDA_ENV_DIR}/conda-meta/${arg}"-[0-9]*.json 2>/dev/null | head -1)
            [[ -n "$match" ]] && version=$(basename "$match" .json) && version="${version#"${arg}"-}"
            ;;
        pip)
            match=$(ls -d "${CONDA_ENV_DIR}"/lib/python3*/site-packages/"${arg}"-[0-9]*.dist-info 2>/dev/null | head -1)
            [[ -n "$match" ]] && version=$(basename "$match" .dist-info) && version="${version#"${arg}"-}"
            ;;
        dir)
            match=$(ls -d "${TOOLS_DIR}/${arg}"*/ 2>/dev/null | head -1)
            [[ -n "$match" ]] && version=$(basename "$match") && version="${version#"${arg}"}"
            ;;
    esac
    echo "${version:-not installed}"
}

get_tested_version() {
    [[ -f "$TESTED_VERSIONS_FILE" ]] || return 0
    awk -F= -v name="$1" '$1 == name {print substr($0, length(name) + 2); exit}' "$TESTED_VERSIONS_FILE"
}

print_components() {
    local entry name kind arg
    for entry in "${COMPONENTS[@]}"; do
        IFS=: read -r name kind arg <<< "$entry"
        echo "${name}=$(get_component_version "$kind" "$arg")"
    done
}

print_one_line() {
    local wanted entry name kind arg parts=()
    for wanted in "${ONE_LINE_COMPONENTS[@]}"; do
        for entry in "${COMPONENTS[@]}"; do
            IFS=: read -r name kind arg <<< "$entry"
            [[ "$name" == "$wanted" ]] && parts+=("$name $(get_component_version "$kind" "$arg")")
        done
    done
    local joined
    joined=$(printf '%s, ' "${parts[@]}")
    echo "minsar $(get_minsar_version) (${joined%, })"
}

print_report() {
    local entry name kind arg version tested
    printf '%-24s %s\n' "minsar" "$(get_minsar_version)"
    for entry in "${COMPONENTS[@]}"; do
        IFS=: read -r name kind arg <<< "$entry"
        version=$(get_component_version "$kind" "$arg")
        tested=$(get_tested_version "$name")
        if [[ -n "$tested" && "$tested" != "$version" ]]; then
            printf '%-24s %-28s * tested with %s\n' "$name" "$version" "$tested"
        else
            printf '%-24s %s\n' "$name" "$version"
        fi
    done
}

mode="report"
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)    show_help; exit 0 ;;
        --short)      mode="short"; shift ;;
        --one-line)   mode="one-line"; shift ;;
        --components) mode="components"; shift ;;
        *)
            echo "Error: Unknown option: $1"
            echo "Use $SCRIPT_NAME --help for available options"
            exit 1
            ;;
    esac
done

case "$mode" in
    short)      get_minsar_version ;;
    one-line)   print_one_line ;;
    components) print_components ;;
    report)     print_report ;;
esac
