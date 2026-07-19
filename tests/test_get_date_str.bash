#!/usr/bin/env bash
#
# Tests for list_merged_slc_yyyymmdd_dates / get_date_str in minsarApp_specifics.sh
#

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

source "$PROJECT_ROOT/minsar/lib/minsarApp_specifics.sh"
source "$SCRIPT_DIR/test_helpers.bash"

test_list_ignores_exclude_season() {
    setup_test_workspace
    local slc="$TEST_WORKSPACE/merged/SLC"
    mkdir -p "$slc/20141123" "$slc/20260630" "$slc/excludeSeason/20240101" "$slc/notadate"
    local dates
    dates=$(list_merged_slc_yyyymmdd_dates "$slc")
    assert_equals "20141123
20260630" "$dates" "Only YYYYMMDD dirs listed"
}

test_get_date_str_ignores_exclude_season() {
    setup_test_workspace
    cd "$TEST_WORKSPACE" || return 1
    mkdir -p merged/SLC/20141123 merged/SLC/20260630 merged/SLC/excludeSeason
    declare -gA template=()
    template[miaplpy.load.startDate]="auto"
    template[miaplpy.load.endDate]="auto"
    local out
    out=$(get_date_str)
    assert_equals "201411_202606" "$out" "get_date_str uses first/last YYYYMMDD only"
}

test_get_date_str_respects_template_dates() {
    setup_test_workspace
    cd "$TEST_WORKSPACE" || return 1
    mkdir -p merged/SLC/20141123 merged/SLC/excludeSeason
    declare -gA template=()
    template[miaplpy.load.startDate]="20200101"
    template[miaplpy.load.endDate]="20201231"
    local out
    out=$(get_date_str)
    assert_equals "202001_202012" "$out" "Template load dates override SLC listing"
}

print_header "minsarApp_specifics get_date_str tests"
test_list_ignores_exclude_season
test_get_date_str_ignores_exclude_season
test_get_date_str_respects_template_dates
print_summary
