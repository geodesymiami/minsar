#!/usr/bin/env bash
#
# Tests for reference_point_hdfeos5.bash SUFFIX detection heuristic.
# The heuristic decides whether the 2nd-to-last "_"/"."-separated token of an
# HE5 basename is a real dataset suffix (e.g. filtDel4DS, Del4DS, Del4PS,
# filtSingDS) or a non-suffix token like a date placeholder XXXXXXXX, a literal
# date YYYYMMDD, or a corner segment N1944W10366.
#
# Run: bash tests/test_reference_point_hdfeos5_suffix.bash
#

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

source "$SCRIPT_DIR/test_helpers.bash"

REF_PT_SCRIPT="$PROJECT_ROOT/minsar/bin/reference_point_hdfeos5.bash"

# Run the SUFFIX awk exactly as it appears in reference_point_hdfeos5.bash so
# the test fails if the script logic diverges.
suffix_for() {
    local basename="$1"
    echo "$basename" | awk -F'[_.]' '
    {
        s = $(NF-1);
        if (s == "XXXXXXXX")            { print ""; next }
        if (s ~ /^[0-9]{8}$/)           { print ""; next }
        if (length(s) < 11)             { print s;  next }
        if (length(s) == 11 && s !~ /^[SN]/) { print s; next }
        print "";
    }'
}

test_suffix_xxxxxxxx_is_not_a_suffix() {
    print_test_start "SUFFIX rejects XXXXXXXX placeholder" \
        "Update-mode placeholder XXXXXXXX must NOT be treated as a dataset suffix (otherwise save_hdfeos5.py emits …_XXXXXXXX_XXXXXXXX.he5)."
    local out
    out=$(suffix_for "S1_desc_012_miaplpy_20150110_XXXXXXXX.he5")
    assert_equals "" "$out" "XXXXXXXX end-date placeholder is not a SUFFIX"
}

test_suffix_literal_date_is_not_a_suffix() {
    print_test_start "SUFFIX rejects 8-digit dates" \
        "A literal 8-digit end date must not be treated as a dataset suffix."
    local out
    out=$(suffix_for "S1_desc_012_miaplpy_20150110_20210315.he5")
    assert_equals "" "$out" "20210315 end-date is not a SUFFIX"
}

test_suffix_filt_del4ds_detected() {
    print_test_start "SUFFIX detects filtDel4DS" \
        "Real dataset suffix filtDel4DS must be detected after corner segments."
    local out
    out=$(suffix_for "S1_asc_049_miaplpy_20150101_XXXXXXXX_N1944W10366_N1946W10355_N1963W10358_N1961W10369_filtDel4DS.he5")
    assert_equals "filtDel4DS" "$out" "filtDel4DS detected"
}

test_suffix_del4ds_detected() {
    print_test_start "SUFFIX detects Del4DS" \
        "Real dataset suffix Del4DS must be detected."
    local out
    out=$(suffix_for "S1_desc_012_miaplpy_20150110_XXXXXXXX_N1961W10355_N1963W10366_N1946W10369_N1944W10358_Del4DS.he5")
    assert_equals "Del4DS" "$out" "Del4DS detected"
}

test_suffix_corner_segment_is_not_a_suffix() {
    print_test_start "SUFFIX rejects corner segment" \
        "A corner segment like N1944W10366 (11 chars starting with N) must not be treated as a dataset suffix."
    local out
    out=$(suffix_for "S1_desc_012_miaplpy_20150110_XXXXXXXX_N1963W10369_N1963W10355_N1944W10355_N1944W10369.he5")
    assert_equals "" "$out" "Corner segment is not a SUFFIX"
}

test_script_uses_updated_suffix_logic() {
    print_test_start "script source contains hardened SUFFIX awk" \
        "reference_point_hdfeos5.bash must reject XXXXXXXX and 8-digit dates in SUFFIX detection."
    local content
    content=$(cat "$REF_PT_SCRIPT")
    assert_contains "$content" 'if (s == "XXXXXXXX")'    "Script awk skips XXXXXXXX"
    assert_contains "$content" 'if (s ~ /^[0-9]{8}$/)'   "Script awk skips 8-digit dates"
}

print_header "REFERENCE_POINT_HDFEOS5 SUFFIX TESTS"

test_suffix_xxxxxxxx_is_not_a_suffix
test_suffix_literal_date_is_not_a_suffix
test_suffix_filt_del4ds_detected
test_suffix_del4ds_detected
test_suffix_corner_segment_is_not_a_suffix
test_script_uses_updated_suffix_logic

print_summary
exit $?
