#!/usr/bin/env bash
# Smoke tests for save_miaplpy_hdfeos5.bash CLI / early failures
set -o pipefail

source "$(dirname "$0")/test_helpers.bash"

BASH_SCRIPT="$(cd "$(dirname "$0")/../minsar/scripts" && pwd)/save_miaplpy_hdfeos5.bash"

echo "=== test_save_miaplpy_hdfeos5_bash ==="

[[ -x "$BASH_SCRIPT" ]] || { echo "Missing executable: $BASH_SCRIPT" >&2; exit 1; }

help_out=$("$BASH_SCRIPT" --help)
assert_contains "$help_out" "save_miaplpy_hdfeos5.bash" "Help shows script name"
assert_contains "$help_out" "--prefix" "Help documents --prefix"
assert_contains "$help_out" "--no-filter" "Help documents --no-filter"

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

set +e
err_out=$("$BASH_SCRIPT" --bogus 2>&1)
rc=$?
set -e
assert_equals "1" "$rc" "Unknown option exits 1"
assert_contains "$err_out" "Unknown option" "Unknown option message"

mkdir -p "$tmpdir/network_delaunay_4"
echo "mintpy.networkInversion.minTempCoh = 0.75" > "$tmpdir/network_delaunay_4/smallbaselineApp.cfg"
set +e
err_out=$("$BASH_SCRIPT" --dir "$tmpdir/network_delaunay_4" -t smallbaselineApp.cfg --prefix Del4 2>&1)
rc=$?
set -e
assert_equals "1" "$rc" "Missing timeseries exits 1"
assert_contains "$err_out" "timeseries_*demErr.h5" "Missing timeseries error text"

echo "=== test_save_miaplpy_hdfeos5_bash: PASS ==="
print_summary
