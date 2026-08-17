#!/usr/bin/env bash
#
# Tests for list_merged_slc_yyyymmdd_dates / list_slcstack_load_dates / get_date_str
# / exclude-season dir naming in minsarApp_specifics.sh
#

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

source "$PROJECT_ROOT/minsar/lib/minsarApp_specifics.sh"
source "$SCRIPT_DIR/test_helpers.bash"

LOAD_DATES_SCRIPT="$PROJECT_ROOT/minsar/bin/get_slcstack_load_dates.bash"

test_list_ignores_exclude_season() {
    setup_test_workspace
    local slc="$TEST_WORKSPACE/merged/SLC"
    mkdir -p "$slc/20141123" "$slc/20260630" "$slc/ex0101-0630/20240101" "$slc/notadate"
    local dates
    dates=$(list_merged_slc_yyyymmdd_dates "$slc")
    assert_equals "20141123
20260630" "$dates" "Only YYYYMMDD dirs listed"
}

test_get_date_str_auto_uses_first_last_slc() {
    setup_test_workspace
    cd "$TEST_WORKSPACE" || return 1
    mkdir -p merged/SLC/20141123 merged/SLC/20260630 merged/SLC/ex0101-0630
    declare -gA template=()
    template[miaplpy.load.startDate]="auto"
    template[miaplpy.load.endDate]="auto"
    local out
    out=$(get_date_str)
    assert_equals "201411_202606" "$out" "auto/auto uses first/last YYYYMMDD in merged/SLC"
}

test_get_date_str_clips_to_slcs_in_window() {
    setup_test_workspace
    cd "$TEST_WORKSPACE" || return 1
    mkdir -p merged/SLC/20141123 merged/SLC/20200315 merged/SLC/20210630
    declare -gA template=()
    template[miaplpy.load.startDate]="20200101"
    template[miaplpy.load.endDate]="20201231"
    local out dates
    dates=$(list_slcstack_load_dates)
    assert_equals "20200315" "$dates" "Only SLCs inside load window"
    out=$(get_date_str)
    assert_equals "202003_202003" "$out" "Dir dates are first/last SLC in window, not template bounds"
}

test_get_date_str_start_only() {
    setup_test_workspace
    cd "$TEST_WORKSPACE" || return 1
    mkdir -p merged/SLC/20141123 merged/SLC/20200315 merged/SLC/20210630
    declare -gA template=()
    template[miaplpy.load.startDate]="20200101"
    template[miaplpy.load.endDate]="auto"
    local out
    out=$(get_date_str)
    assert_equals "202003_202106" "$out" "startDate clips first SLC; endDate auto keeps last SLC"
}

test_exclude_season_suffix_empty() {
    declare -gA template=()
    local out
    out=$(get_exclude_season_suffix)
    assert_equals "" "$out" "No excludeSeason -> empty suffix"
}

test_exclude_season_suffix_set() {
    declare -gA template=()
    template[ssaraopt.excludeSeason]="0101-0630"
    local out
    out=$(get_exclude_season_suffix)
    assert_equals "_ex0101-0630" "$out" "Valid excludeSeason -> _exMMDD-MMDD"
}

test_exclude_season_suffix_invalid() {
    declare -gA template=()
    template[ssaraopt.excludeSeason]="bad"
    local out
    out=$(get_exclude_season_suffix)
    assert_equals "" "$out" "Invalid excludeSeason -> empty suffix"
}

test_miaplpy_dir_name_auto_with_season() {
    setup_test_workspace
    cd "$TEST_WORKSPACE" || return 1
    mkdir -p merged/SLC/20141123 merged/SLC/20260630
    declare -gA template=()
    template[minsar.miaplpyDir.addition]="auto"
    template[miaplpy.load.startDate]="auto"
    template[miaplpy.load.endDate]="auto"
    template[ssaraopt.excludeSeason]="0101-0630"
    local out
    out=$(get_miaplpy_dir_name)
    assert_equals "miaplpy_ex0101-0630" "$out" "auto + season"
}

test_miaplpy_dir_name_date_with_season() {
    setup_test_workspace
    cd "$TEST_WORKSPACE" || return 1
    mkdir -p merged/SLC/20141123 merged/SLC/20260630
    declare -gA template=()
    template[minsar.miaplpyDir.addition]="date"
    template[miaplpy.load.startDate]="auto"
    template[miaplpy.load.endDate]="auto"
    template[ssaraopt.excludeSeason]="0101-0630"
    local out
    out=$(get_miaplpy_dir_name)
    assert_equals "miaplpy_201411_202606_ex0101-0630" "$out" "date + season"
}

test_miaplpy_dir_name_custom_without_season() {
    setup_test_workspace
    cd "$TEST_WORKSPACE" || return 1
    mkdir -p merged/SLC/20141123 merged/SLC/20260630
    declare -gA template=()
    template[minsar.miaplpyDir.addition]="SN"
    template[miaplpy.load.startDate]="auto"
    template[miaplpy.load.endDate]="auto"
    local out
    out=$(get_miaplpy_dir_name)
    assert_equals "miaplpy_SN_201411_202606" "$out" "custom without season"
}

test_mintpy_dir_name_date_with_season() {
    setup_test_workspace
    cd "$TEST_WORKSPACE" || return 1
    mkdir -p merged/SLC/20141123 merged/SLC/20260630
    declare -gA template=()
    template[minsar.mintpyDir.addition]="date"
    template[miaplpy.load.startDate]="auto"
    template[miaplpy.load.endDate]="auto"
    template[ssaraopt.excludeSeason]="0101-0630"
    local out
    out=$(get_mintpy_dir_name)
    assert_equals "mintpy_201411_202606_ex0101-0630" "$out" "mintpy date + season"
}

test_get_slcstack_load_dates_script() {
    setup_test_workspace
    mkdir -p "$TEST_WORKSPACE/merged/SLC/20141123" "$TEST_WORKSPACE/merged/SLC/20200315" "$TEST_WORKSPACE/merged/SLC/20210630"
    cat > "$TEST_WORKSPACE/proj.template" <<'EOF'
miaplpy.load.startDate               = 20200101
miaplpy.load.endDate                 = 20201231
EOF
    local out
    out=$("$LOAD_DATES_SCRIPT" "$TEST_WORKSPACE/proj.template" --slc-dir "$TEST_WORKSPACE/merged/SLC")
    assert_equals "20200315 20200315" "$out" "CLI prints first last load dates"
    out=$("$LOAD_DATES_SCRIPT" "$TEST_WORKSPACE/proj.template" --slc-dir "$TEST_WORKSPACE/merged/SLC" --date-str)
    assert_equals "202003_202003" "$out" "CLI --date-str"
}

print_header "minsarApp_specifics get_date_str / exclude-season naming tests"
test_list_ignores_exclude_season
test_get_date_str_auto_uses_first_last_slc
test_get_date_str_clips_to_slcs_in_window
test_get_date_str_start_only
test_exclude_season_suffix_empty
test_exclude_season_suffix_set
test_exclude_season_suffix_invalid
test_miaplpy_dir_name_auto_with_season
test_miaplpy_dir_name_date_with_season
test_miaplpy_dir_name_custom_without_season
test_mintpy_dir_name_date_with_season
test_get_slcstack_load_dates_script
print_summary
