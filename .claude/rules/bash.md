---
paths:
  - "**/*.bash"
  - "**/*.sh"
  - "tests/**"
---

# Bash scripts

- Start with `#!/usr/bin/env bash` and `set -eo pipefail`.
- `[[ ]]` not `[ ]`; quote variables; `$(command)` not backticks.
- Source shared libs: `SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"`, then `source "${SCRIPT_DIR}/../lib/workflow_utils.sh"` (provides `abbreviate`, `convert_array_to_comma_separated_string`, `remove_from_list`, `clean_array`).
- Log important commands to `$WORKDIR/log`.
- Reject unknown options immediately, with a branch before the positional default, and validate the type of named arguments (e.g. `--ref-lalo` must be numeric lat,lon):

```bash
        -?*|--*)
            echo "Error: Unknown option: $1"
            echo "Use $SCRIPT_NAME --help for available options"
            exit 1
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
```

## Mac and Linux portability

All bash scripts and tests must run on both macOS (BSD tools) and Linux (GNU tools).

| Avoid | Use instead |
|---|---|
| `grep -P`, `grep -oP` | `sed -E` or `awk` |
| `sed -r` | `sed -E` |
| `ls -1v` | `ls … \| sort -V` |
| `shuf` | `awk 'BEGIN{srand()}{print rand()"\t"$0}' \| sort -n \| cut -f2-` |
| `date -d` | Python for date parsing |
| `head -n -1` | `sed '$d'` |
| bare `wc -l` in comparisons | `wc -l \| tr -d ' \n'` (BSD pads with spaces) |

Portable patterns:

- Version-sorted file list: `ls run_files/run_*.job 2>/dev/null | sort -V`
- Extract `run_XX` from a path: `echo "$path" | sed -E 's/.*(run_[0-9][0-9]).*/\1/'`
- Strip trailing `_N.job` or `.job`: `sed -E 's/_[0-9]+\.job$//; s/\.job$//'`
