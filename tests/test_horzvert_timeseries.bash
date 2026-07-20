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
    print_test_start "horzvert_timeseries.bash wiring" "bash -n passes; run-file dispatch and LOS ingest wiring."
    local content _n
    bash -n "$HV_SCRIPT"
    _n=$?
    assert_equals "0" "$_n" "bash -n horzvert_timeseries.bash"
    content=$(cat "$HV_SCRIPT")
    assert_contains "$content" "run_horzvert2timeseries" "Writes run_horzvert2timeseries"
    assert_contains "$content" "hv_write_run_horzvert2timeseries" "Uses run-file writer"
    assert_contains "$content" "hv_run_or_submit_script" "Uses bash/SLURM dispatch helper"
    assert_contains "$content" "reference_point_hdfeos5.bash" "References reference_point_hdfeos5.bash"
    assert_contains "$content" "hv_promote_short_he5_to_corner_filename" "Uses MintPy/MiaplPy HE5 rename helper"
    assert_contains "$content" "--check-cache-only" "Forwards cache check to horzvert_timeseries.py"
    assert_contains "$content" "--submit" "Documents --submit option"
    assert_contains "$content" "--ingest-parallel" "Documents --ingest-parallel option"
    assert_contains "$content" "--force" "Documents --force option"
    assert_contains "$content" "--clean" "Documents --clean option"
    assert_contains "$content" "hv_clean_cached_products" "Defines clean helper for cached products"
    assert_contains "$content" "Write InsarMaps HTML" "HTML written outside LOS-only gate"
    assert_not_contains "$content" 'ingest_insarmaps.bash "$ORIGINAL_RESOLVED_FILE1" --ref-lalo' "LOS ingest file1 without --ref-lalo"
    assert_not_contains "$content" 'ingest_insarmaps.bash "$ORIGINAL_RESOLVED_FILE2" --ref-lalo' "LOS ingest file2 without --ref-lalo"
    print_test_end "horzvert_timeseries.bash wiring"
}

test_horzvert_help_lists_cache_options() {
    print_test_start "horzvert_timeseries.bash --help" "Help documents --force, --clean, --submit, --sleep."
    local content
    content=$("$HV_SCRIPT" --help 2>&1)
    assert_contains "$content" "--force" "Help lists --force"
    assert_contains "$content" "--clean" "Help lists --clean"
    assert_contains "$content" "--submit" "Help lists --submit"
    assert_contains "$content" "--sleep" "Help lists --sleep"
    assert_not_contains "$content" "Re-reference:" "No long prose after options"
    print_test_end "horzvert_timeseries.bash --help"
}

test_horzvert_sleep_rejects_non_integer() {
    print_test_start "horzvert_timeseries.bash --sleep" "Rejects non-integer --sleep."
    local rc=0
    "$HV_SCRIPT" a b --ref-lalo 1 2 --sleep abc >/dev/null 2>&1 || rc=$?
    assert_equals "1" "$rc" "Non-integer --sleep exits 1"
    print_test_end "horzvert_timeseries.bash --sleep"
}

test_hv_longest_processing_method_dir() {
    print_test_start "hv_longest_processing_method_dir" "Keeps mintpy/miaplpy dir with longer period."
    local out
    out=$(hv_longest_processing_method_dir \
        "EtnaSenA44/miaplpy_202001_202412/network_delaunay_4/" \
        "EtnaSenD124/miaplpy_202001_202410/network_delaunay_4/")
    assert_equals "miaplpy_202001_202412" "$out" "Longer end date wins"
    out=$(hv_longest_processing_method_dir \
        "EtnaSenD124/miaplpy_202001_202410/network_delaunay_4/" \
        "EtnaSenA44/miaplpy_202001_202412/network_delaunay_4/")
    assert_equals "miaplpy_202001_202412" "$out" "Order-independent longer period"
    out=$(hv_longest_processing_method_dir \
        "ChilesSenD142/mintpy" \
        "ChilesSenA120/mintpy")
    assert_equals "mintpy" "$out" "Bare mintpy unchanged"
    out=$(hv_longest_processing_method_dir \
        "A/miaplpy/network_delaunay_4" \
        "B/miaplpy/network_delaunay_4")
    assert_equals "miaplpy" "$out" "Bare miaplpy unchanged"
    out=$(hv_extract_processing_method_dir "EtnaSenA44/miaplpy_202001_202412/network_delaunay_4/file.he5")
    assert_equals "miaplpy_202001_202412" "$out" "Extract from file path"
    print_test_end "hv_longest_processing_method_dir"
}

test_hv_write_run_file_has_wait_and_amp() {
    print_test_start "hv_write_run_horzvert2timeseries" "Run file has need_geocode flags, &/wait, and ingest."
    local tmp runf content
    tmp=$(mktemp -d)
    mkdir -p "$tmp/out" "$tmp/scratch/SenA/net" "$tmp/scratch/SenD/net"
    touch "$tmp/scratch/SenA/net/a.he5" "$tmp/scratch/SenD/net/b.he5"
    export SCRATCHDIR="$tmp/scratch"
    HV_RUN_FILE="$tmp/run_horzvert2timeseries" \
    HV_RADAR1="$tmp/scratch/SenA/net/a.he5" \
    HV_RADAR2="$tmp/scratch/SenD/net/b.he5" \
    HV_REF_LAT="1.0" \
    HV_REF_LON="2.0" \
    HV_OUTDIR="$tmp/scratch/out" \
    HV_CACHE_HIT=0 \
    HV_GEOCODE_ARGS="--lalo-step 0.00014 0.00014" \
    HV_PY_SUFFIX=" --ref-lalo 1.0 2.0" \
    HV_INGEST_PARALLEL=1 \
    HV_INGEST_INSARMAPS=1 \
    HV_INGEST_LOS=1 \
    HV_INGEST_WORKERS_OPTS="--num-workers 1" \
    hv_write_run_horzvert2timeseries
    runf="$tmp/run_horzvert2timeseries"
    assert_file_exists "$runf" "Run file created"
    content=$(cat "$runf")
    assert_contains "$content" "reference_point_hdfeos5.bash" "Has ref-point commands"
    assert_contains "$content" "SenA/net/a.he5" "SCRATCHDIR-relative radar path"
    assert_contains "$content" "source " "Sources horzvert utils lib"
    assert_contains "$content" "need_geocode1" "Has need_geocode1 flag"
    assert_contains "$content" "need_geocode2" "Has need_geocode2 flag"
    assert_not_contains "$content" "need_geocode() {" "need_geocode defined in lib, not run file"
    assert_not_contains "$content" "_p1=" "No _p1 variable"
    assert_not_contains "$content" "radar1=" "No radar1 variable"
    assert_contains "$content" " &" "Has background ampersands"
    assert_contains "$content" "hv_wait_pids" "Waits on background PIDs with failure propagation"
    assert_contains "$content" "wait" "Has wait barriers"
    assert_contains "$content" "horzvert_timeseries.py" "Has HV python"
    assert_contains "$content" "hv_ingest_insarmaps_logged" "Ingest via logged helper"
    assert_contains "$content" "missing *vert*/*horz*.he5" "Fails clearly if vert/horz missing before ingest"
    assert_contains "$content" "cd " "Cds into product dir before ingest"
    assert_contains "$content" "realpath" "Resolves vert/horz to absolute paths before cd"
    assert_contains "$content" "/log" "Appends ingest lines to SCRATCHDIR log"
    assert_contains "$(type hv_ingest_insarmaps_logged)" "ingest_insarmaps.bash" "Helper invokes ingest_insarmaps.bash"
    bash -n "$runf"
    assert_equals "0" "$?" "bash -n run file"
    unset SCRATCHDIR
    rm -rf "$tmp"
    print_test_end "hv_write_run_horzvert2timeseries"
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
test_horzvert_sleep_rejects_non_integer
test_hv_longest_processing_method_dir
test_hv_write_run_file_has_wait_and_amp

print_summary
exit $?
