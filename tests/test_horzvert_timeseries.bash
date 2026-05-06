#!/usr/bin/env bash
#
# Tests for horzvert_timeseries.bash helpers and ingest wiring.
# Run: bash tests/test_horzvert_timeseries.bash
#

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

source "$SCRIPT_DIR/test_helpers.bash"
source "$PROJECT_ROOT/minsar/lib/horzvert_timeseries_utils.sh"

HV_SCRIPT="$PROJECT_ROOT/minsar/bin/horzvert_timeseries.bash"

test_hv_he5_radar_los_path_non_geo_unchanged() {
    print_test_start "hv_he5_radar_los_path non-geo" "Radar path is echoed unchanged."
    local tmp out
    tmp=$(mktemp -d)
    touch "$tmp/S1_foo.he5"
    out=$(hv_he5_radar_los_path "$tmp/S1_foo.he5")
    assert_equals "$tmp/S1_foo.he5" "$out" "Non-geo basename unchanged"
    rm -rf "$tmp"
    print_test_end "hv_he5_radar_los_path non-geo"
}

test_hv_he5_radar_los_path_geo_maps_to_sibling() {
    print_test_start "hv_he5_radar_los_path geo→radar" "geo_*.he5 maps to sibling S1*.he5 when present."
    local tmp out
    tmp=$(mktemp -d)
    touch "$tmp/S1_foo.he5"
    touch "$tmp/geo_S1_foo.he5"
    out=$(hv_he5_radar_los_path "$tmp/geo_S1_foo.he5")
    assert_equals "$tmp/S1_foo.he5" "$out" "geo_ prefix stripped to radar sibling"
    rm -rf "$tmp"
    print_test_end "hv_he5_radar_los_path geo→radar"
}

test_hv_he5_radar_los_path_geo_missing_sibling_fails() {
    print_test_start "hv_he5_radar_los_path missing sibling" "geo_*.he5 without radar sibling exits non-zero."
    local tmp ec out
    tmp=$(mktemp -d)
    touch "$tmp/geo_S1_only.he5"
    ec=0
    out=$(hv_he5_radar_los_path "$tmp/geo_S1_only.he5" 2>&1) || ec=$?
    assert_equals "1" "$ec" "Expect exit code 1"
    assert_contains "$out" "sibling" "Error mentions sibling"
    rm -rf "$tmp"
    print_test_end "hv_he5_radar_los_path missing sibling"
}

test_hv_promote_short_he5_to_corner_name() {
    print_test_start "hv_promote short→corner" "Moves updated short HE5 over stale long-name sibling."
    local tmp short long out
    tmp=$(mktemp -d)
    short="$tmp/S1_asc_069_miaplpy_20141010_20180104_filtDel4DS.he5"
    long="$tmp/S1_asc_069_miaplpy_20141010_20180104_N1314E12362_N1317E12378_N1333E12375_N1330E12360_filtDel4DS.he5"
    printf x >"$short"
    printf y >"$long"
    out=$(hv_promote_miaplpy_short_he5_to_corner_filename "$short" 2>/dev/null)
    assert_equals "$long" "$out" "Returns long path"
    assert_file_exists "$long" "Long path exists"
    assert_equals "x" "$(cat "$long")" "Long path receives content from updated short"
    _gone=""
    [[ ! -f "$short" ]] && _gone="yes"
    assert_equals "yes" "$_gone" "Short basename removed after mv onto long"
    rm -rf "$tmp"
    print_test_end "hv_promote short→corner"
}

test_hv_promote_short_he5_update_placeholder_to_corner_name() {
    print_test_start "hv_promote short→corner (XXXXXXXX)" \
        "Update-mode miaplpy filename (YYYYMMDD_XXXXXXXX) promotes over corner sibling."
    local tmp short long out
    tmp=$(mktemp -d)
    short="$tmp/S1_asc_142_miaplpy_20250414_XXXXXXXX_filtDel4DS.he5"
    long="$tmp/S1_asc_142_miaplpy_20250414_XXXXXXXX_N1397E12097_N1398E12103_N1405E12102_N1404E12096_filtDel4DS.he5"
    printf newref >"$short"
    printf oldref >"$long"
    out=$(hv_promote_miaplpy_short_he5_to_corner_filename "$short" 2>/dev/null)
    assert_equals "$long" "$out" "Returns long path"
    assert_equals "newref" "$(cat "$long")" "Long receives content from updated short"
    rm -rf "$tmp"
    print_test_end "hv_promote short→corner (XXXXXXXX)"
}

test_hv_promote_corner_file_unchanged() {
    print_test_start "hv_promote long unchanged" "Corner-suffix basename is not replaced."
    local tmp long out
    tmp=$(mktemp -d)
    long="$tmp/S1_asc_069_miaplpy_20141010_20180104_N1314E12362_N1317E12378_N1333E12375_N1330E12360_filtDel4DS.he5"
    printf z >"$long"
    out=$(hv_promote_miaplpy_short_he5_to_corner_filename "$long")
    assert_equals "$long" "$out" "Same path when already long form"
    rm -rf "$tmp"
    print_test_end "hv_promote long unchanged"
}

test_hv_promote_corner_update_placeholder_unchanged() {
    print_test_start "hv_promote long XXXXXXXX unchanged" \
        "Corner form with miaplpy_…_YYYYMMDD_XXXXXXXX stays as-is when passed directly."
    local tmp long out
    tmp=$(mktemp -d)
    long="$tmp/S1_asc_142_miaplpy_20250414_XXXXXXXX_N1397E12097_N1398E12103_N1405E12102_N1404E12096_filtDel4DS.he5"
    printf z >"$long"
    out=$(hv_promote_miaplpy_short_he5_to_corner_filename "$long")
    assert_equals "$long" "$out" "Same path when already corner form (update naming)"
    rm -rf "$tmp"
    print_test_end "hv_promote long XXXXXXXX unchanged"
}

test_horzvert_script_syntax_and_los_ingest_no_ref_lalo() {
    print_test_start "horzvert_timeseries.bash wiring" "bash -n passes; LOS ingest does not use --ref-lalo."
    local content _n
    bash -n "$HV_SCRIPT"
    _n=$?
    assert_equals "0" "$_n" "bash -n horzvert_timeseries.bash"
    content=$(cat "$HV_SCRIPT")
    assert_contains "$content" "Step 0c: Re-reference radar LOS" "Documents re-reference step"
    assert_contains "$content" "Step 0d: Unify short-name vs corner-suffix" "Documents HE5 rename step"
    assert_contains "$content" "reference_point_hdfeos5.bash" "Calls reference_point_hdfeos5.bash"
    assert_not_contains "$content" 'ingest_insarmaps.bash "$ORIGINAL_RESOLVED_FILE1" --ref-lalo' "LOS ingest file1 without --ref-lalo"
    assert_not_contains "$content" 'ingest_insarmaps.bash "$ORIGINAL_RESOLVED_FILE2" --ref-lalo' "LOS ingest file2 without --ref-lalo"
    print_test_end "horzvert_timeseries.bash wiring"
}

print_header "HORZVERT_TIMESERIES TESTS"

test_hv_he5_radar_los_path_non_geo_unchanged
test_hv_he5_radar_los_path_geo_maps_to_sibling
test_hv_he5_radar_los_path_geo_missing_sibling_fails
test_hv_promote_short_he5_to_corner_name
test_hv_promote_short_he5_update_placeholder_to_corner_name
test_hv_promote_corner_file_unchanged
test_hv_promote_corner_update_placeholder_unchanged
test_horzvert_script_syntax_and_los_ingest_no_ref_lalo

print_summary
exit $?
