#!/usr/bin/env bash
#
# Unit tests for print_summary upload/insarmaps log tail behavior.
#

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

source "$SCRIPT_DIR/test_helpers.bash"
eval "$(declare -f print_summary | sed '1s/^print_summary/_tests_print_summary/')"
source "$PROJECT_ROOT/minsar/lib/minsarApp_specifics.sh"
source "$PROJECT_ROOT/minsar/lib/utils.sh"
set +e

test_print_summary_tail_one_when_miaplpy_only() {
    print_test_start "print_summary tail -1 (MiaplPy only)" \
        "Single pipeline flag yields one URL line per log."
    setup_test_workspace

    local wd="$TEST_WORKSPACE/proj"
    mkdir -p "$wd"
    export SCRATCHDIR="$TEST_WORKSPACE"
    export MINSAR_RUN_START_EPOCH=$(( $(date +%s) - 3600 ))

    {
        echo "http://old-upload"
        echo "http://new-upload"
    } > "$wd/upload.log"
    {
        echo "http://old-insarmaps"
        echo "http://new-insarmaps"
    } > "$wd/insarmaps.log"
    touch "$wd/upload.log" "$wd/insarmaps.log"

    local output
    output="$(print_summary "$wd" 0 1)"

    assert_contains "$output" "http://new-upload" \
        "Includes latest upload URL"
    assert_not_contains "$output" "http://old-upload" \
        "Omits older upload URL when tail -1"
    assert_contains "$output" "http://new-insarmaps" \
        "Includes latest insarmaps URL"

    teardown_test_workspace
    print_test_end "print_summary tail -1 (MiaplPy only)"
}

test_print_summary_tail_two_when_both_pipelines() {
    print_test_start "print_summary tail -2 (MintPy + MiaplPy)" \
        "Both pipeline flags yield two URL lines per log."
    setup_test_workspace

    local wd="$TEST_WORKSPACE/proj"
    mkdir -p "$wd"
    export SCRATCHDIR="$TEST_WORKSPACE"
    export MINSAR_RUN_START_EPOCH=$(( $(date +%s) - 3600 ))

    {
        echo "http://mintpy-upload"
        echo "http://miaplpy-upload"
    } > "$wd/upload.log"
    {
        echo "http://mintpy-insarmaps"
        echo "http://miaplpy-insarmaps"
    } > "$wd/insarmaps.log"
    touch "$wd/upload.log" "$wd/insarmaps.log"

    local output
    output="$(print_summary "$wd" 1 1)"

    assert_contains "$output" "http://mintpy-upload" \
        "Includes MintPy upload URL"
    assert_contains "$output" "http://miaplpy-upload" \
        "Includes MiaplPy upload URL"
    assert_contains "$output" "http://mintpy-insarmaps" \
        "Includes MintPy insarmaps URL"
    assert_contains "$output" "http://miaplpy-insarmaps" \
        "Includes MiaplPy insarmaps URL"

    teardown_test_workspace
    print_test_end "print_summary tail -2 (MintPy + MiaplPy)"
}

test_print_summary_skips_stale_logs() {
    print_test_start "print_summary skips stale logs" \
        "Logs older than MINSAR_RUN_START_EPOCH are not printed."
    setup_test_workspace

    local wd="$TEST_WORKSPACE/proj"
    mkdir -p "$wd"
    export SCRATCHDIR="$TEST_WORKSPACE"
    export MINSAR_RUN_START_EPOCH=$(date +%s)

    echo "http://stale-upload" > "$wd/upload.log"
    echo "http://stale-insarmaps" > "$wd/insarmaps.log"
    touch -d '1 hour ago' "$wd/upload.log" "$wd/insarmaps.log"

    local output
    output="$(print_summary "$wd" 0 1)"

    assert_not_contains "$output" "upload.log:" \
        "Stale upload.log is omitted"
    assert_not_contains "$output" "insarmaps.log:" \
        "Stale insarmaps.log is omitted"

    teardown_test_workspace
    print_test_end "print_summary skips stale logs"
}

print_header "PRINT_SUMMARY LOG TAIL TEST SUITE"

test_print_summary_tail_one_when_miaplpy_only
test_print_summary_tail_two_when_both_pipelines
test_print_summary_skips_stale_logs

_tests_print_summary
exit $?
