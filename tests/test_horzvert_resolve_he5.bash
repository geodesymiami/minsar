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

print_header "HORZVERT RESOLVE HE5 TESTS"

test_strip_trailing_slashes
test_file_with_trailing_slash_is_used
test_directory_selects_by_dataset

print_summary
exit $?
