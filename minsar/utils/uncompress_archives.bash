#!/usr/bin/env bash
set -eo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    helptext="
usage: ${SCRIPT_NAME} [--jobs N] COMMANDS

Run each line of COMMANDS, at most N at a time.

Options:
    --jobs N    simultaneous archives (default: 5)

Examples:
    ${SCRIPT_NAME} --jobs 5 SLC_ORIG/run_01_uncompress_commands
    ${SCRIPT_NAME} SLC_ORIG/run_01_uncompress_commands
"
    printf '%s\n' "$helptext"
    exit 0
fi

jobs=5
positional=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --jobs)
            if [[ $# -lt 2 || ! "$2" =~ ^[1-9][0-9]*$ ]]; then
                echo "Error: --jobs requires a positive integer" >&2
                exit 1
            fi
            jobs="$2"
            shift 2
            ;;
        -?*|--*)
            echo "Error: Unknown option: $1" >&2
            echo "Use ${SCRIPT_NAME} --help for available options" >&2
            exit 1
            ;;
        *)
            positional+=("$1")
            shift
            ;;
    esac
done

if [[ ${#positional[@]} -ne 1 ]]; then
    echo "Error: COMMANDS file required" >&2
    echo "Use ${SCRIPT_NAME} --help for available options" >&2
    exit 1
fi

commands="${positional[0]}"
if [[ ! -f "$commands" ]]; then
    echo "Error: command list not found: $commands" >&2
    exit 1
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

count=0
while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "${line//[[:space:]]/}" ]] && continue
    printf '%s\0' "$line" >> "$tmp"
    count=$((count + 1))
done < "$commands"

if [[ "$count" -eq 0 ]]; then
    exit 0
fi

xargs -0 -n 1 -P "$jobs" bash -c 'eval "$1"' _ < "$tmp"
