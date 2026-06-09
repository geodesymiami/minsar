#!/usr/bin/env bash
# Wrapper for apply_debug_table.py
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/apply_debug_table.py" "$@"
