#!/usr/bin/env bash
#
# Tests for horzvert HE5 path resolution: files are used as-is (trailing
# slashes ignored); directories select by --dataset or the default newest HE5.
#
# Run: bash tests/test_horzvert_resolve_he5.bash
#

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

source "$SCRIPT_DIR/test_helpers.bash"
source "$PROJECT_ROOT/minsar/lib/horzvert_timeseries_utils.sh"

# Load resolve helpers from horzvert_timeseries.bash without running the script.
eval "$(awk '
  /^resolve_he5\(\)/ {p=1}
  /^is_geocoded\(\)/ {p=0}
  p
' "$PROJECT_ROOT/minsar/bin/horzvert_timeseries.bash")"

test_strip_trailing_slashes() {
    print_test_start "hv_strip_trailing_slashes" \
        "Trailing slashes are removed from file and directory paths."
    assert_equals "foo.he5" "$(hv_strip_trailing_slashes 'foo.he5/')" \
        "single trailing slash on file"
    assert_equals "foo.he5" "$(hv_strip_trailing_slashes 'foo.he5///')" \
        "multiple trailing slashes on file"
    assert_equals "network_delaunay_4" "$(hv_strip_trailing_slashes 'network_delaunay_4/')" \
        "trailing slash on directory"
    assert_equals "/" "$(hv_strip_trailing_slashes '/')" \
        "root path is unchanged"
}

test_file_with_trailing_slash_is_used() {
    print_test_start "resolve_he5_or_dataset uses a file even with a trailing slash" \
        "A .he5 path with a trailing slash must not be searched as a directory."
    local tmp file out
    tmp=$(mktemp -d)
    file="$tmp/S1_desc_009_miaplpy_20200501_20260630_Del4DS_coh075.he5"
    touch "$file"
    out=$(resolve_he5_or_dataset "$file/" "")
    assert_equals "$file" "$out" "stripped file path is returned"
    out=$(resolve_he5_or_dataset "$file/" "DS")
    assert_equals "$file" "$out" "explicit file is used even when --dataset is set"
    rm -rf "$tmp"
}

test_append_youngest_network_dir() {
    print_test_start "hv_append_youngest_network_dir" \
        "A miaplpy dir without a trailing network_* gets the youngest network_* child."
    local tmp miaplpy out
    tmp=$(mktemp -d)
    miaplpy="$tmp/LengaiSenA130/miaplpy_202504_202610"
    mkdir -p "$miaplpy/network_single_reference" "$miaplpy/network_delaunay_4"
    touch -t 202001010000 "$miaplpy/network_single_reference"
    touch -t 202401010000 "$miaplpy/network_delaunay_4"
    out=$(hv_append_youngest_network_dir "$miaplpy")
    assert_equals "$miaplpy/network_delaunay_4" "$out" \
        "youngest network_* is the newest by mtime"
    out=$(hv_append_youngest_network_dir "$miaplpy/")
    assert_equals "$miaplpy/network_delaunay_4" "$out" \
        "trailing slash still resolves to youngest network_*"
    out=$(hv_append_youngest_network_dir "$miaplpy/network_single_reference/")
    assert_equals "$miaplpy/network_single_reference" "$out" \
        "path that already ends in network_* is kept"
    mkdir -p "$tmp/ChilesSenD142/mintpy"
    out=$(hv_append_youngest_network_dir "$tmp/ChilesSenD142/mintpy")
    assert_equals "$tmp/ChilesSenD142/mintpy" "$out" \
        "mintpy dir without network_* is unchanged"
    touch "$tmp/S1_asc.he5"
    out=$(hv_append_youngest_network_dir "$tmp/S1_asc.he5")
    assert_equals "$tmp/S1_asc.he5" "$out" \
        "a .he5 file path is unchanged"
    mkdir -p "$tmp/EtnaSenA44/miaplpy_empty"
    out=$(hv_append_youngest_network_dir "$tmp/EtnaSenA44/miaplpy_empty" 2>/dev/null || true)
    assert_equals "" "$out" \
        "miaplpy dir with no network_* child is an error"
    rm -rf "$tmp"
}

test_directory_selects_by_dataset() {
    print_test_start "resolve_he5_or_dataset selects HE5 by --dataset in a directory" \
        "Youngest matching .he5 in a directory is chosen according to --dataset."
    local tmp net out
    tmp=$(mktemp -d)
    net="$tmp/network_delaunay_4"
    mkdir -p "$net"
    touch -t 202001010000 "$net/S1_filtDel4DS.he5"
    touch -t 202001020000 "$net/S1_Del4DS.he5"
    out=$(resolve_he5_or_dataset "$net/" "DS")
    assert_equals "$net/S1_Del4DS.he5" "$out" "--dataset DS skips filt files"
    out=$(resolve_he5_or_dataset "$net/" "filtDS")
    assert_equals "$net/S1_filtDel4DS.he5" "$out" "--dataset filtDS picks filt file"
    rm -rf "$tmp"
}

test_dataset_token_and_product_cleanup() {
    print_test_start "hv_dataset_token_from_name" \
        "DS and filtDS tokens stay distinct, and --clean removes only the current token."
    assert_equals "DS" "$(hv_dataset_token_from_name 'S1_asc_106_miaplpy_Del4DS.he5')" \
        "Del4DS is DS"
    assert_equals "filtDS" "$(hv_dataset_token_from_name 'S1_asc_106_miaplpy_filtDel4DS.he5')" \
        "filtDel4DS is filtDS"
    assert_equals "DS" "$(hv_dataset_token_from_name 'S1_vert_106_128_miaplpy_N_DS.he5')" \
        "vert product suffix _DS"
    assert_equals "filtDS" "$(hv_dataset_token_from_name 'S1_vert_106_128_miaplpy_N_filtDS.he5')" \
        "vert product suffix _filtDS is not DS"
    assert_equals "PS" "$(hv_dataset_token_from_name 'S1_asc_106_miaplpy_Del4PS.he5')" \
        "Del4PS is PS"
    assert_equals "" "$(hv_dataset_token_from_name 'S1_desc_124_mintpy_20141031_20151231.he5')" \
        "mintpy name has no token"
    local disagree
    disagree=$(hv_dataset_token_for_inputs a_Del4DS.he5 b_filtDel4DS.he5 2>/dev/null || true)
    assert_equals "" "$disagree" "mismatched inputs are an error"

    local tmp data log
    tmp=$(mktemp -d)
    touch "$tmp/S1_vert_106_128_miaplpy_DS.he5" \
        "$tmp/S1_horz_106_128_miaplpy_DS.he5" \
        "$tmp/S1_vert_106_128_miaplpy_DS.hvparams" \
        "$tmp/S1_vert_106_128_miaplpy_filtDS.he5" \
        "$tmp/S1_horz_106_128_miaplpy_filtDS.he5" \
        "$tmp/S1_vert_106_128_miaplpy_filtDS.hvparams"
    hv_remove_dataset_products "$tmp" DS
    assert_file_exists "$tmp/S1_vert_106_128_miaplpy_filtDS.he5" "filtDS vert survives DS clean"
    assert_file_exists "$tmp/S1_vert_106_128_miaplpy_filtDS.hvparams" "filtDS sidecar survives DS clean"
    [[ ! -e "$tmp/S1_vert_106_128_miaplpy_DS.he5" ]]
    assert_equals "0" "$?" "DS vert is removed"

    data="$tmp/data_files.txt"
    printf '%s\n' '# geocode-lalo-step 0.0002 0.0002' \
        'qq/S1_vert_a_DS.he5' 'qq/S1_horz_a_DS.he5' 'qq/S1_vert_a_filtDS.he5' > "$data"
    hv_merge_data_files "$data" DS '# geocode-lalo-step 0.0008 0.0009' \
        'qq/S1_vert_b_DS.he5' 'qq/S1_horz_b_DS.he5'
    assert_contains "$(cat "$data")" 'qq/S1_vert_a_filtDS.he5' "other dataset path is kept"
    assert_contains "$(cat "$data")" 'qq/S1_vert_b_DS.he5' "new DS path is written"
    assert_not_contains "$(cat "$data")" 'qq/S1_vert_a_DS.he5' "old DS path is replaced"

    log="$tmp/insarmaps.log"
    printf '%s\n' \
        'http://h/start/1/2/3?flyToDatasetCenter=false&startDataset=S1_vert_a_DS' \
        'http://h/start/4/5/6?flyToDatasetCenter=false&startDataset=S1_vert_a_filtDS' > "$log"
    hv_prune_insarmaps_log "$log" DS
    assert_contains "$(cat "$log")" 'startDataset=S1_vert_a_filtDS' "filtDS URL is kept"
    assert_not_contains "$(cat "$log")" 'startDataset=S1_vert_a_DS' "DS URL is removed"
    rm -rf "$tmp"
}

print_header "HORZVERT RESOLVE HE5 TESTS"

test_strip_trailing_slashes
test_file_with_trailing_slash_is_used
test_append_youngest_network_dir
test_dataset_token_and_product_cleanup
test_directory_selects_by_dataset

print_summary
exit $?
