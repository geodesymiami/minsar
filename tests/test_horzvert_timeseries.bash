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

test_hv_promote_long_with_newer_short_sibling_promotes() {
    print_test_start "hv_promote long←newer short" \
        "Long-form input with a freshly-written short sibling: short content overwrites long path."
    local tmp short long out gone
    tmp=$(mktemp -d)
    long="$tmp/S1_desc_156_miaplpy_20210705_XXXXXXXX_N1336W06113_N1337W06120_N1331W06122_N1329W06115_filtDel4DS.he5"
    short="$tmp/S1_desc_156_miaplpy_20210705_XXXXXXXX_filtDel4DS.he5"
    printf staleref >"$long"
    # Make sure short is strictly newer than long (mtime resolution can be 1s on some FS).
    sleep 1
    printf newref >"$short"
    out=$(hv_promote_miaplpy_short_he5_to_corner_filename "$long" 2>/dev/null)
    assert_equals "$long" "$out" "Returns long path"
    assert_equals "newref" "$(cat "$long")" "Long path now contains short's freshly-written bytes"
    gone=""
    [[ ! -f "$short" ]] && gone="yes"
    assert_equals "yes" "$gone" "Short sibling removed after mv onto long"
    rm -rf "$tmp"
    print_test_end "hv_promote long←newer short"
}

test_hv_promote_mintpy_short_to_corner_name() {
    print_test_start "hv_promote mintpy short→corner" \
        "MintPy short basename promotes over corner-suffix sibling."
    local tmp short long out
    tmp=$(mktemp -d)
    short="$tmp/S1_desc_142_mintpy_20240904_XXXXXXXX.he5"
    long="$tmp/S1_desc_142_mintpy_20240904_XXXXXXXX_N0151W07849_N0151W07756_N0034W07756_N0034W07849.he5"
    printf newref >"$short"
    printf oldref >"$long"
    out=$(hv_promote_short_he5_to_corner_filename "$short" 2>/dev/null)
    assert_equals "$long" "$out" "Returns long path"
    assert_equals "newref" "$(cat "$long")" "Long receives content from updated short"
    rm -rf "$tmp"
    print_test_end "hv_promote mintpy short→corner"
}

test_hv_promote_mintpy_long_with_newer_short_sibling() {
    print_test_start "hv_promote mintpy long←newer short" \
        "MintPy corner file with newer short sibling gets updated REF from short."
    local tmp short long out
    tmp=$(mktemp -d)
    long="$tmp/S1_desc_142_mintpy_20240904_XXXXXXXX_N0151W07849_N0151W07756_N0034W07756_N0034W07849.he5"
    short="$tmp/S1_desc_142_mintpy_20240904_XXXXXXXX.he5"
    printf staleref >"$long"
    sleep 1
    printf newref >"$short"
    out=$(hv_promote_short_he5_to_corner_filename "$long" 2>/dev/null)
    assert_equals "$long" "$out" "Returns long path"
    assert_equals "newref" "$(cat "$long")" "Long path updated from short"
    rm -rf "$tmp"
    print_test_end "hv_promote mintpy long←newer short"
}

test_hv_promote_mintpy_double_placeholder_short_to_corner() {
    print_test_start "hv_promote mintpy XXXXXXXX_XXXXXXXX" \
        "save_hdfeos5 update-mode double placeholder short promotes to corner sibling."
    local tmp short long out
    tmp=$(mktemp -d)
    short="$tmp/S1_asc_120_mintpy_20240902_XXXXXXXX_XXXXXXXX.he5"
    long="$tmp/S1_asc_120_mintpy_20240902_XXXXXXXX_N0161W07905_N0161W07720_N0020W07720_N0020W07905.he5"
    printf newref >"$short"
    printf oldref >"$long"
    out=$(hv_promote_short_he5_to_corner_filename "$short" 2>/dev/null)
    assert_equals "$long" "$out" "Returns long path"
    assert_equals "newref" "$(cat "$long")" "Long receives content from double-placeholder short"
    rm -rf "$tmp"
    print_test_end "hv_promote mintpy XXXXXXXX_XXXXXXXX"
}

test_hv_promote_long_with_older_short_sibling_keeps_long() {
    print_test_start "hv_promote long keeps when short older" \
        "Long-form input with an older short sibling: leave both files untouched."
    local tmp short long out
    tmp=$(mktemp -d)
    short="$tmp/S1_desc_156_miaplpy_20210705_XXXXXXXX_filtDel4DS.he5"
    long="$tmp/S1_desc_156_miaplpy_20210705_XXXXXXXX_N1336W06113_N1337W06120_N1331W06122_N1329W06115_filtDel4DS.he5"
    printf oldshort >"$short"
    sleep 1
    printf currentlong >"$long"
    out=$(hv_promote_miaplpy_short_he5_to_corner_filename "$long")
    assert_equals "$long" "$out" "Returns long path"
    assert_equals "currentlong" "$(cat "$long")" "Long file untouched"
    assert_equals "oldshort" "$(cat "$short")" "Short file untouched"
    rm -rf "$tmp"
    print_test_end "hv_promote long keeps when short older"
}

test_hv_scratchdir_display_path_under_scratch() {
    print_test_start "hv_scratchdir_display_path" "Paths under SCRATCHDIR show \$SCRATCHDIR/ prefix."
    local tmp out
    tmp=$(mktemp -d)
    export SCRATCHDIR="$tmp/scratch"
    mkdir -p "$SCRATCHDIR/NisyrosSenA29/miaplpy_201410_202606/network_delaunay_4"
    out=$(hv_scratchdir_display_path "$SCRATCHDIR/NisyrosSenA29/miaplpy_201410_202606/network_delaunay_4")
    assert_equals '$SCRATCHDIR/NisyrosSenA29/miaplpy_201410_202606/network_delaunay_4/' "$out" "SCRATCHDIR-relative display"
    unset SCRATCHDIR
    rm -rf "$tmp"
    print_test_end "hv_scratchdir_display_path"
}

test_hv_announce_command_logs_to_dir() {
    print_test_start "hv_announce_command logging" "Announces In/Running and appends to directory log."
    local tmp logfile out
    tmp=$(mktemp -d)
    export SCRATCHDIR="$tmp/scratch"
    mkdir -p "$SCRATCHDIR/proj/subdir"
    out=$(hv_announce_command "$SCRATCHDIR/proj/subdir" 'extract_hdfeos5.py "foo.he5" --all' 2>&1)
    assert_contains "$out" 'In $SCRATCHDIR/proj/subdir/' "Stdout shows In line"
    assert_contains "$out" 'Running: extract_hdfeos5.py "foo.he5" --all' "Stdout shows Running line"
    logfile="$SCRATCHDIR/proj/subdir/log"
    assert_file_exists "$logfile" "Directory log created"
    assert_contains "$(cat "$logfile")" 'extract_hdfeos5.py "foo.he5" --all' "Command logged in directory log"
    unset SCRATCHDIR
    rm -rf "$tmp"
    print_test_end "hv_announce_command logging"
}

test_horzvert_script_syntax_and_los_ingest_no_ref_lalo() {
    print_test_start "horzvert_timeseries.bash wiring" "bash -n passes; LOS ingest does not use --ref-lalo."
    local content _n
    bash -n "$HV_SCRIPT"
    _n=$?
    assert_equals "0" "$_n" "bash -n horzvert_timeseries.bash"
    content=$(cat "$HV_SCRIPT")
    assert_contains "$content" "Step 0c: Re-reference radar LOS" "Documents re-reference step"
    assert_contains "$content" "Step 0d: Unify short-name vs corner-suffix HE5" "Documents HE5 rename step"
    assert_contains "$content" "hv_promote_short_he5_to_corner_filename" "Uses MintPy/MiaplPy HE5 rename helper"
    assert_contains "$content" "reference_point_hdfeos5.bash" "Calls reference_point_hdfeos5.bash"
    assert_contains "$content" "hv_announce_command" "Uses hv_announce_command before subprocesses"
    assert_contains "$content" "--check-cache-only" "Forwards cache check to horzvert_timeseries.py"
    assert_contains "$content" "--force" "Documents --force option"
    assert_contains "$content" "--clean" "Documents --clean option"
    assert_contains "$content" "hv_clean_cached_products" "Defines clean helper for cached products"
    assert_not_contains "$content" 'ingest_insarmaps.bash "$ORIGINAL_RESOLVED_FILE1" --ref-lalo' "LOS ingest file1 without --ref-lalo"
    assert_not_contains "$content" 'ingest_insarmaps.bash "$ORIGINAL_RESOLVED_FILE2" --ref-lalo' "LOS ingest file2 without --ref-lalo"
    print_test_end "horzvert_timeseries.bash wiring"
}

test_horzvert_help_lists_cache_options() {
    print_test_start "horzvert_timeseries.bash --help" "Help documents --force and --clean."
    local content
    content=$(cat "$HV_SCRIPT")
    assert_contains "$content" "--force" "Help lists --force"
    assert_contains "$content" "--clean" "Help lists --clean"
    assert_contains "$content" ".hvparams" "Help mentions hvparams sidecar"
    print_test_end "horzvert_timeseries.bash --help"
}

print_header "HORZVERT_TIMESERIES TESTS"

test_hv_he5_radar_los_path_non_geo_unchanged
test_hv_he5_radar_los_path_geo_maps_to_sibling
test_hv_he5_radar_los_path_geo_missing_sibling_fails
test_hv_promote_short_he5_to_corner_name
test_hv_promote_short_he5_update_placeholder_to_corner_name
test_hv_promote_corner_file_unchanged
test_hv_promote_corner_update_placeholder_unchanged
test_hv_promote_long_with_newer_short_sibling_promotes
test_hv_promote_long_with_older_short_sibling_keeps_long
test_hv_promote_mintpy_short_to_corner_name
test_hv_promote_mintpy_long_with_newer_short_sibling
test_hv_promote_mintpy_double_placeholder_short_to_corner
test_hv_scratchdir_display_path_under_scratch
test_hv_announce_command_logs_to_dir
test_horzvert_script_syntax_and_los_ingest_no_ref_lalo
test_horzvert_help_lists_cache_options

print_summary
exit $?
