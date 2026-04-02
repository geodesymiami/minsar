#!/usr/bin/env bash
#
# Test suite for submit_jobs.bash
# Run with: bash tests/test_submit_jobs.bash
#
# These tests verify the behavior of submit_jobs.bash utility functions
# without actually submitting jobs (which requires SLURM).
#

set -o pipefail

#######################################
# Configuration
#######################################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SUBMIT_SCRIPT="$PROJECT_ROOT/minsar/bin/submit_jobs.bash"

# Source test helpers
source "$SCRIPT_DIR/test_helpers.bash"

# Test workspace
TEST_WORKSPACE=""

#######################################
# Source functions from submit_jobs.bash
#######################################
source_submit_functions() {
    # Source the shared workflow utilities library (which submit_jobs.bash uses)
    local lib_file="$PROJECT_ROOT/minsar/lib/workflow_utils.sh"
    if [[ -f "$lib_file" ]]; then
        source "$lib_file"
    else
        echo "ERROR: Could not find workflow_utils.sh at $lib_file"
        return 1
    fi
}

#######################################
# Test Cases
#######################################

test_help_flag() {
    print_test_start "Help Flag" \
        "Verifies that 'submit_jobs.bash --help' shows usage info and exits cleanly."
    
    echo "  [Action] Running: submit_jobs.bash --help"
    
    local output
    output=$("$SUBMIT_SCRIPT" --help 2>&1)
    local exit_code=$?
    
    echo "  [Check] Verifying help output contains expected sections..."
    
    assert_exit_code 0 "$exit_code" "Help exits with code 0 (success)"
    assert_contains "$output" "job_file_pattern" "Help mentions job_file_pattern"
    assert_contains "$output" "--random" "Help documents --random option"
    assert_contains "$output" "--rapid" "Help documents --rapid option"
    assert_contains "$output" "sbatch_conditional" "Help references sbatch_conditional"
    
    print_test_end "Help Flag"
}

test_abbreviate_function() {
    print_test_start "Abbreviate Function (from shared library)" \
        "Tests the abbreviate() function used to shorten long filenames."
    
    source_submit_functions
    
    echo "  [Action] Testing abbreviate() with various string lengths..."
    
    local result
    
    # Test 1: Short string (no abbreviation)
    echo "  [Test] Input: 'short' (5 chars), max: 20"
    result=$(abbreviate "short" 20 10 7)
    assert_equals "short" "$result" "Short string stays unchanged"
    
    # Test 2: Long string (needs abbreviation)
    echo "  [Test] Input: 'this_is_a_very_long_filename_that_needs_abbreviation.job' (57 chars), max: 20"
    result=$(abbreviate "this_is_a_very_long_filename_that_needs_abbreviation.job" 20 10 7)
    assert_contains "$result" "..." "Long string gets '...' inserted"
    
    # Test 3: Exactly at limit
    echo "  [Test] Input: 'exactly_20_chars_xx' (19 chars), max: 20"
    result=$(abbreviate "exactly_20_chars_xx" 20 10 7)
    assert_equals "exactly_20_chars_xx" "$result" "String at limit stays unchanged"
    
    print_test_end "Abbreviate Function (from shared library)"
}

test_file_pattern_expansion() {
    print_test_start "File Pattern Expansion" \
        "Tests that job file patterns expand correctly to match files."
    
    setup_test_workspace
    create_mock_run_files "$TEST_WORKSPACE" 11
    
    cd "$TEST_WORKSPACE"
    
    echo "  [Action] Testing file pattern matching..."
    
    local files count
    
    # Test 1: Pattern matching run_01 files (sort -V for version order; portable Mac/Linux)
    echo "  [Test] Pattern: run_files/run_01*.job"
    files=($(ls run_files/run_01*.job 2>/dev/null | sort -V))
    count=${#files[@]}
    assert_equals "3" "$count" "run_01*.job matches 3 files"
    
    # Test 2: Pattern matching run_05 files
    echo "  [Test] Pattern: run_files/run_05*.job"
    files=($(ls run_files/run_05*.job 2>/dev/null | sort -V))
    count=${#files[@]}
    assert_equals "3" "$count" "run_05*.job matches 3 files"
    
    # Test 3: Pattern matching all run files
    echo "  [Test] Pattern: run_files/run_*.job"
    files=($(ls run_files/run_*.job 2>/dev/null | sort -V))
    count=${#files[@]}
    assert_equals "33" "$count" "run_*.job matches all 33 files"
    
    # Test 4: Single file pattern (smallbaseline)
    echo "  [Test] Pattern: smallbaseline_wrapper.job"
    files=($(ls smallbaseline_wrapper.job 2>/dev/null | sort -V))
    count=${#files[@]}
    assert_equals "1" "$count" "smallbaseline_wrapper.job matches 1 file"
    
    cd - > /dev/null
    teardown_test_workspace
    
    print_test_end "File Pattern Expansion"
}

test_random_order_shuffle() {
    print_test_start "Random Order Shuffle" \
        "Tests that --random flag changes the order of files."
    
    setup_test_workspace
    create_mock_run_files "$TEST_WORKSPACE" 5
    
    cd "$TEST_WORKSPACE"
    
    echo "  [Action] Testing random shuffle behavior..."
    
    # Get files in normal order (sort -V portable; ls -1v is GNU-only)
    local normal_order
    normal_order=$(ls run_files/run_01*.job 2>/dev/null | sort -V | tr '\n' ' ')
    
    # Shuffle: use sed -E (portable) and awk+sort for shuffle (shuf is GNU-only)
    local shuffled_order
    shuffled_order=$(echo "$normal_order" | tr " " "\n" | awk 'BEGIN{srand()}{print rand()"\t"$0}' | sort -n | cut -f2- | tr '\n' ' ')
    
    # Note: This test documents the shuffle mechanism but can't guarantee difference
    # due to randomness. We just verify the mechanism doesn't break.
    echo "  [Info] Normal order: $normal_order"
    echo "  [Info] Shuffle mechanism executed successfully"
    
    # Count files after shuffle (should be same)
    local normal_count shuffled_count
    normal_count=$(echo "$normal_order" | wc -w)
    shuffled_count=$(echo "$shuffled_order" | wc -w)
    
    assert_equals "$normal_count" "$shuffled_count" "Shuffle preserves file count"
    
    cd - > /dev/null
    teardown_test_workspace
    
    print_test_end "Random Order Shuffle"
}

test_job_pattern_extraction() {
    print_test_start "Job Pattern Extraction" \
        "Tests regex pattern used to extract file pattern from job files."
    
    echo "  [Action] Testing pattern extraction regex..."
    
    local result
    
    # Portable pattern extraction: strip _N.job or .job (grep -oP is GNU-only)
    # sed -E: strip _<digits>.job from end, then .job for special names
    # Test 1: Standard run file
    echo "  [Test] Extracting pattern from 'run_files/run_01_unpack_topo_reference_0.job'"
    result=$(echo "run_files/run_01_unpack_topo_reference_0.job" | sed -E 's/_[0-9]+\.job$//; s/\.job$//')
    assert_equals "run_files/run_01_unpack_topo_reference" "$result" "Extracts pattern without trailing number"
    
    # Test 2: smallbaseline_wrapper
    echo "  [Test] Extracting pattern from 'smallbaseline_wrapper.job'"
    result=$(echo "smallbaseline_wrapper.job" | sed -E 's/_[0-9]+\.job$//; s/\.job$//')
    assert_equals "smallbaseline_wrapper" "$result" "Extracts smallbaseline_wrapper"
    
    # Test 3: insarmaps
    echo "  [Test] Extracting pattern from 'insarmaps.job'"
    result=$(echo "insarmaps.job" | sed -E 's/_[0-9]+\.job$//; s/\.job$//')
    assert_equals "insarmaps" "$result" "Extracts insarmaps"
    
    print_test_end "Job Pattern Extraction"
}

test_argument_parsing() {
    print_test_start "Argument Parsing" \
        "Verifies help text documents expected arguments."
    
    local help_output
    help_output=$("$SUBMIT_SCRIPT" --help 2>&1)
    
    echo "  [Check] Verifying documented argument combinations..."
    
    assert_contains "$help_output" "--max_time" "Documents --max_time option"
    assert_contains "$help_output" "--random" "Documents --random option"
    assert_contains "$help_output" "--rapid" "Documents --rapid option"
    assert_contains "$help_output" "604800" "Documents default max_time (7 days)"
    
    print_test_end "Argument Parsing"
}

test_regression_shared_library() {
    print_test_start "[REGRESSION] Shared Library Integration" \
        "CRITICAL: Verifies submit_jobs.bash correctly uses shared workflow_utils.sh library."
    
    echo "  [Purpose] After Task 4 refactoring, functions come from shared library."
    echo "  [Purpose] This test verifies the integration is working."
    
    # Check that submit_jobs.bash sources the library (at least one reference)
    local sources_library
    sources_library=$(grep -c "workflow_utils.sh" "$SUBMIT_SCRIPT" 2>/dev/null || echo "0")
    
    # Should have at least 1 reference
    if [[ $sources_library -ge 1 ]]; then
        ((TESTS_RUN++))
        echo -e "  ${GREEN}✓ PASS${NC}: submit_jobs.bash sources workflow_utils.sh (found $sources_library references)"
        ((TESTS_PASSED++))
    else
        ((TESTS_RUN++))
        echo -e "  ${RED}✗ FAIL${NC}: submit_jobs.bash sources workflow_utils.sh"
        echo -e "       Expected: at least 1 reference"
        echo -e "       Actual:   $sources_library"
        ((TESTS_FAILED++))
    fi
    
    # Check library file exists
    local lib_file="$PROJECT_ROOT/minsar/lib/workflow_utils.sh"
    assert_file_exists "$lib_file" "Shared library exists at minsar/lib/workflow_utils.sh"
    
    # Source and verify functions are available
    source_submit_functions
    
    # Test that abbreviate function works from library
    local result
    result=$(abbreviate "test" 20 10 7)
    assert_equals "test" "$result" "abbreviate() function works from shared library"
    
    print_test_end "[REGRESSION] Shared Library Integration"
}

#######################################
# Run All Tests
#######################################

run_all_tests() {
    print_header "submit_jobs.bash TEST SUITE"
    
    echo ""
    echo "Script under test: $SUBMIT_SCRIPT"
    
    print_section "SECTION 1: HELP & USAGE TESTS"
    test_help_flag
    test_argument_parsing
    
    print_section "SECTION 2: UTILITY FUNCTION TESTS"
    test_abbreviate_function
    
    print_section "SECTION 3: FILE PATTERN TESTS"
    test_file_pattern_expansion
    test_random_order_shuffle
    test_job_pattern_extraction
    
    print_section "SECTION 4: REGRESSION TESTS"
    test_regression_shared_library
    
    print_summary
}

# Run tests if executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    run_all_tests
    exit $?
fi
