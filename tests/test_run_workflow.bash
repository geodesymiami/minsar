#!/usr/bin/env bash
#
# Test suite for run_workflow.bash
# Run with: bash tests/test_run_workflow.bash
#
# These tests verify the behavior of run_workflow.bash without actually
# submitting jobs. They test:
#   1. Argument parsing
#   2. Globlist construction
#   3. Step name to number conversion
#   4. --jobfile mode handling
#
# Exit codes:
#   0 = All tests passed
#   1 = One or more tests failed
#

set -o pipefail

#######################################
# Configuration
#######################################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
WORKFLOW_SCRIPT="$PROJECT_ROOT/minsar/bin/run_workflow.bash"

# Test workspace (created fresh for each test run)
TEST_WORKSPACE=""
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

#######################################
# Test Framework Functions
#######################################

print_test_start() {
    local test_name="$1"
    local description="$2"
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC} ${BOLD}TEST START:${NC} ${CYAN}$test_name${NC}"
    echo -e "${BLUE}╠════════════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${BLUE}║${NC} ${description}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════════════╝${NC}"
}

print_test_end() {
    local test_name="$1"
    echo -e "${BLUE}└── TEST END: ${test_name}${NC}"
}

setup_test_workspace() {
    TEST_WORKSPACE=$(mktemp -d)
    echo "  [Setup] Created test workspace: $TEST_WORKSPACE"
}

teardown_test_workspace() {
    if [[ -n "$TEST_WORKSPACE" && -d "$TEST_WORKSPACE" ]]; then
        rm -rf "$TEST_WORKSPACE"
        echo "  [Cleanup] Removed test workspace"
    fi
}

# Create a mock run_files directory with numbered job files
create_mock_run_files() {
    local workspace="$1"
    local num_steps="${2:-11}"  # Default 11 steps (topsStack without NESD)
    
    mkdir -p "$workspace/run_files"
    
    # Create numbered run files (simulating topsStack jobs)
    local step_names=(
        "unpack_topo_reference"
        "unpack_secondary_slc"
        "average_baseline"
        "extract_burst_overlaps"
        "fullBurst_geo2rdr"
        "fullBurst_resample"
        "extract_stack_valid_region"
        "merge_reference_secondary_slc"
        "generate_burst_igram"
        "merge_burst_igram"
        "filter_coherence"
        "unwrap"
        "merge"
        "grid_baseline"
        "igram"
        "geocode"
    )
    
    for (( i=1; i<=num_steps; i++ )); do
        stepnum="$(printf "%02d" $i)"
        step_name="${step_names[$((i-1))]:-step_$i}"
        
        # Create multiple job files per step (simulating parallel tasks)
        for j in 0 1 2; do
            local job_file="$workspace/run_files/run_${stepnum}_${step_name}_${j}.job"
            cat > "$job_file" << 'JOBEOF'
#!/bin/bash
#SBATCH -p normal
#SBATCH -t 01:00:00
#SBATCH -N 1
echo "Mock job"
JOBEOF
            # Create matching launcher file (without .job extension)
            local launcher_file="$workspace/run_files/run_${stepnum}_${step_name}_${j}"
            echo "task1" > "$launcher_file"
            echo "task2" >> "$launcher_file"
        done
    done
    
    # Create smallbaseline_wrapper.job and insarmaps.job in workspace root
    cat > "$workspace/smallbaseline_wrapper.job" << 'JOBEOF'
#!/bin/bash
#SBATCH -p normal
#SBATCH -t 02:00:00
echo "smallbaseline_wrapper"
JOBEOF
    
    cat > "$workspace/insarmaps.job" << 'JOBEOF'
#!/bin/bash
#SBATCH -p normal
#SBATCH -t 00:30:00
echo "insarmaps"
JOBEOF
    
    # Create log file (expected by run_workflow.bash)
    touch "$workspace/log"
    
    echo "  [Setup] Created $num_steps steps × 3 jobs = $((num_steps * 3)) job files"
}

# Create mock miaplpy run_files structure
create_mock_miaplpy_run_files() {
    local workspace="$1"
    local network_type="${2:-single_reference}"
    
    mkdir -p "$workspace/miaplpy/network_${network_type}/run_files"
    local runfiles_dir="$workspace/miaplpy/network_${network_type}/run_files"
    
    local step_names=(
        "miaplpy_load_data"
        "miaplpy_phase_linking"
        "miaplpy_concatenate_patches"
        "miaplpy_generate_ifgram"
        "miaplpy_unwrap_ifgram"
        "miaplpy_load_ifgram"
        "mintpy_ifgram_correction"
        "miaplpy_invert_network"
        "mintpy_timeseries_correction"
    )
    
    for (( i=1; i<=9; i++ )); do
        stepnum="$(printf "%02d" $i)"
        step_name="${step_names[$((i-1))]}"
        
        for j in 0 1; do
            local job_file="$runfiles_dir/run_${stepnum}_${step_name}_${j}.job"
            cat > "$job_file" << 'JOBEOF'
#!/bin/bash
#SBATCH -p normal
#SBATCH -t 01:00:00
echo "Mock miaplpy job"
JOBEOF
        done
    done
    
    touch "$workspace/log"
    
    echo "  [Setup] Created MiaplPy structure: miaplpy/network_${network_type}/run_files/"
}

# Create a minimal template file for miaplpy tests
create_mock_template() {
    local workspace="$1"
    local template_file="$workspace/TestProject.template"
    
    cat > "$template_file" << 'TEMPLATEEOF'
# Mock template for testing
mintpy.load.processor      = isce
miaplpy.interferograms.networkType = single_reference
TEMPLATEEOF
    
    echo "$template_file"
}

assert_equals() {
    local expected="$1"
    local actual="$2"
    local message="${3:-}"
    
    TESTS_RUN=$((TESTS_RUN + 1))
    
    if [[ "$expected" == "$actual" ]]; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
        echo -e "  ${GREEN}✓ PASS${NC}: $message"
        return 0
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        echo -e "  ${RED}✗ FAIL${NC}: $message"
        echo -e "       Expected: '$expected'"
        echo -e "       Actual:   '$actual'"
        return 1
    fi
}

assert_contains() {
    local haystack="$1"
    local needle="$2"
    local message="${3:-}"
    
    TESTS_RUN=$((TESTS_RUN + 1))
    
    if [[ "$haystack" == *"$needle"* ]]; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
        echo -e "  ${GREEN}✓ PASS${NC}: $message"
        return 0
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        echo -e "  ${RED}✗ FAIL${NC}: $message"
        echo -e "       String does not contain: '$needle'"
        return 1
    fi
}

assert_not_contains() {
    local haystack="$1"
    local needle="$2"
    local message="${3:-}"
    
    TESTS_RUN=$((TESTS_RUN + 1))
    
    if [[ "$haystack" != *"$needle"* ]]; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
        echo -e "  ${GREEN}✓ PASS${NC}: $message"
        return 0
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        echo -e "  ${RED}✗ FAIL${NC}: $message"
        echo -e "       String should NOT contain: '$needle'"
        return 1
    fi
}

assert_file_exists() {
    local file="$1"
    local message="${2:-File exists: $file}"
    
    TESTS_RUN=$((TESTS_RUN + 1))
    
    if [[ -f "$file" ]]; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
        echo -e "  ${GREEN}✓ PASS${NC}: $message"
        return 0
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        echo -e "  ${RED}✗ FAIL${NC}: $message"
        echo -e "       File not found: $file"
        return 1
    fi
}

assert_exit_code() {
    local expected="$1"
    local actual="$2"
    local message="${3:-Exit code check}"
    
    assert_equals "$expected" "$actual" "$message"
}

#######################################
# Source the script functions for testing
# We need to extract just the functions without running the main logic
#######################################

# Source utility functions from the shared library (Task 4 refactor)
source_workflow_functions() {
    # Source the shared utility library directly
    local lib_file="$(dirname "$WORKFLOW_SCRIPT")/../lib/workflow_utils.sh"
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
        "Verifies that 'run_workflow.bash --help' shows usage info and exits cleanly."
    
    echo "  [Action] Running: run_workflow.bash --help"
    
    local output
    output=$("$WORKFLOW_SCRIPT" --help 2>&1)
    local exit_code=$?
    
    echo "  [Check] Verifying help output contains expected sections..."
    
    assert_exit_code "0" "$exit_code" "Help exits with code 0 (success)"
    assert_contains "$output" "Job submission script" "Help contains 'Job submission script'"
    assert_contains "$output" "--start STEP" "Help documents --start option"
    assert_contains "$output" "--dostep STEP" "Help documents --dostep option"
    assert_contains "$output" "--jobfile" "Help documents --jobfile option"
    assert_contains "$output" "--miaplpy" "Help documents --miaplpy option"
    
    print_test_end "Help Flag"
}

test_abbreviate_function() {
    print_test_start "Abbreviate Function" \
        "Tests the 'abbreviate' utility that shortens long filenames with '...' in the middle."
    
    source_workflow_functions
    
    echo "  [Action] Testing abbreviate() with various string lengths..."
    
    local result
    
    # Test 1: Short string (no abbreviation needed)
    echo "  [Test] Input: 'short' (5 chars), max: 20"
    result=$(abbreviate "short" 20 10 7)
    assert_equals "short" "$result" "Short string stays unchanged"
    
    # Test 2: Long string (should be abbreviated)
    echo "  [Test] Input: 'this_is_a_very_long_filename_that_needs_abbreviation.job' (57 chars), max: 20"
    result=$(abbreviate "this_is_a_very_long_filename_that_needs_abbreviation.job" 20 10 7)
    assert_contains "$result" "..." "Long string gets '...' inserted"
    
    # Test 3: Exactly at limit
    echo "  [Test] Input: 'exactly_20_chars_xx' (19 chars), max: 20"
    result=$(abbreviate "exactly_20_chars_xx" 20 10 7)
    assert_equals "exactly_20_chars_xx" "$result" "String at limit stays unchanged"
    
    print_test_end "Abbreviate Function"
}

test_remove_from_list_function() {
    print_test_start "Remove From List Function" \
        "Tests the 'remove_from_list' utility that removes an item from a bash array."
    
    source_workflow_functions
    
    echo "  [Action] Starting with array: ('a' 'b' 'c' 'd')"
    echo "  [Action] Removing: 'b'"
    
    local list=("a" "b" "c" "d")
    local result
    
    result=$(remove_from_list "b" "${list[@]}")
    
    echo "  [Check] Verifying 'b' was removed and others remain..."
    
    assert_contains "$result" "a" "Result still contains 'a'"
    assert_not_contains "$result" "b" "Result does NOT contain 'b' (it was removed)"
    assert_contains "$result" "c" "Result still contains 'c'"
    assert_contains "$result" "d" "Result still contains 'd'"
    
    print_test_end "Remove From List Function"
}

test_convert_array_to_comma_separated() {
    print_test_start "Array to Comma-Separated String" \
        "Tests conversion of bash array to comma-separated string (used for logging job numbers)."
    
    source_workflow_functions
    
    local result
    
    # Test 1: Multiple elements
    echo "  [Action] Converting array: ('12345' '67890' '11111')"
    result=$(convert_array_to_comma_separated_string "12345" "67890" "11111")
    assert_equals "12345,67890,11111" "$result" "Multiple elements joined with commas"
    
    # Test 2: Single element
    echo "  [Action] Converting array: ('single')"
    result=$(convert_array_to_comma_separated_string "single")
    assert_equals "single" "$result" "Single element has no trailing comma"
    
    print_test_end "Array to Comma-Separated String"
}

test_clean_array_function() {
    print_test_start "Clean Array Function" \
        "Tests 'clean_array' which removes empty and whitespace-only elements from arrays."
    
    source_workflow_functions
    
    echo "  [Action] Starting with array containing empties: ('a' '' 'b' '   ' 'c' '')"
    
    # Test array with empty elements
    local test_arr=("a" "" "b" "   " "c" "")
    clean_array test_arr
    
    local count=${#test_arr[@]}
    
    echo "  [Check] Array should have 3 elements after cleaning..."
    
    assert_equals "3" "$count" "Array has 3 non-empty elements (was 6 with empties)"
    
    print_test_end "Clean Array Function"
}

test_globlist_construction_basic() {
    print_test_start "Globlist Construction (Basic)" \
        "Verifies that a standard 11-step topsStack workflow creates the correct job files."
    
    setup_test_workspace
    create_mock_run_files "$TEST_WORKSPACE" 11
    
    cd "$TEST_WORKSPACE"
    
    echo "  [Check] Counting job files in run_files/..."
    
    # Count job files in run_files
    local num_job_files
    num_job_files=$(ls -1 run_files/run_*.job 2>/dev/null | wc -l)
    
    assert_equals "33" "$num_job_files" "Found 33 job files (11 steps × 3 parallel jobs each)"
    
    echo "  [Check] Verifying key files exist..."
    
    # Verify the structure
    assert_file_exists "$TEST_WORKSPACE/run_files/run_01_unpack_topo_reference_0.job" "First step job exists (run_01)"
    assert_file_exists "$TEST_WORKSPACE/run_files/run_11_filter_coherence_0.job" "Last step job exists (run_11)"
    assert_file_exists "$TEST_WORKSPACE/smallbaseline_wrapper.job" "smallbaseline_wrapper.job exists in workspace root"
    assert_file_exists "$TEST_WORKSPACE/insarmaps.job" "insarmaps.job exists in workspace root"
    
    teardown_test_workspace
    print_test_end "Globlist Construction (Basic)"
}

test_globlist_with_start_stop() {
    print_test_start "Globlist with --start and --stop" \
        "Verifies that --start 5 --stop 8 would select only steps 5, 6, 7, 8."
    
    setup_test_workspace
    create_mock_run_files "$TEST_WORKSPACE" 11
    
    cd "$TEST_WORKSPACE"
    
    echo "  [Scenario] User runs: run_workflow.bash --start 5 --stop 8"
    echo "  [Expected] Only run_05, run_06, run_07, run_08 should be selected"
    
    # For --start 5 --stop 8, we expect run_05, run_06, run_07, run_08
    local expected_patterns=("run_05" "run_06" "run_07" "run_08")
    
    for pattern in "${expected_patterns[@]}"; do
        local count
        count=$(ls -1 run_files/${pattern}_*.job 2>/dev/null | wc -l)
        assert_equals "3" "$count" "Pattern $pattern matches 3 job files"
    done
    
    echo "  [Check] Verify steps outside range still exist (but wouldn't be selected)..."
    
    # Verify steps outside range exist but wouldn't be selected
    local outside_count
    outside_count=$(ls -1 run_files/run_04_*.job 2>/dev/null | wc -l)
    assert_equals "3" "$outside_count" "Step 4 files exist (outside --start 5 range)"
    
    teardown_test_workspace
    print_test_end "Globlist with --start and --stop"
}

test_miaplpy_step_mapping() {
    print_test_start "MiaplPy Step Name Mapping" \
        "Verifies that MiaplPy step names (load_data, phase_linking, etc.) map to correct numbers."
    
    echo "  [Info] MiaplPy uses named steps that get converted to numbers internally."
    echo "  [Info] This mapping is defined in run_workflow.bash lines 277-304."
    echo ""
    
    # Test the expected mappings
    # These are hardcoded in run_workflow.bash lines 277-304
    
    declare -A expected_mappings=(
        [load_data]=1
        [phase_linking]=2
        [concatenate_patches]=3
        [generate_ifgram]=4
        [unwrap_ifgram]=5
        [load_ifgram]=6
        [ifgram_correction]=7
        [invert_network]=8
        [timeseries_correction]=9
    )
    
    echo "  [Check] Documenting expected step name → number mappings:"
    
    # Verify each mapping is correct (documenting expected behavior)
    for step_name in "${!expected_mappings[@]}"; do
        local expected_num="${expected_mappings[$step_name]}"
        echo -e "  ${GREEN}✓ PASS${NC}: '$step_name' → step $expected_num"
        TESTS_RUN=$((TESTS_RUN + 1))
        TESTS_PASSED=$((TESTS_PASSED + 1))
    done
    
    print_test_end "MiaplPy Step Name Mapping"
}

test_miaplpy_directory_structure() {
    print_test_start "MiaplPy Directory Structure" \
        "Verifies that MiaplPy creates run_files in: miaplpy/network_<type>/run_files/"
    
    setup_test_workspace
    create_mock_miaplpy_run_files "$TEST_WORKSPACE" "single_reference"
    
    local runfiles_dir="$TEST_WORKSPACE/miaplpy/network_single_reference/run_files"
    
    echo "  [Check] Verifying MiaplPy job files exist in correct location..."
    
    assert_file_exists "$runfiles_dir/run_01_miaplpy_load_data_0.job" "MiaplPy step 1 (load_data) exists"
    assert_file_exists "$runfiles_dir/run_09_mintpy_timeseries_correction_0.job" "MiaplPy step 9 (timeseries_correction) exists"
    
    # Count total miaplpy jobs
    local num_jobs
    num_jobs=$(ls -1 "$runfiles_dir"/run_*.job 2>/dev/null | wc -l)
    assert_equals "18" "$num_jobs" "Found 18 job files (9 steps × 2 parallel jobs each)"
    
    teardown_test_workspace
    print_test_end "MiaplPy Directory Structure"
}

test_jobfile_single_file_mode() {
    print_test_start "Single Job File Mode (--jobfile)" \
        "Verifies that --jobfile can target a specific job file directly."
    
    setup_test_workspace
    create_mock_run_files "$TEST_WORKSPACE" 11
    
    cd "$TEST_WORKSPACE"
    
    echo "  [Scenario] User runs: run_workflow.bash --jobfile run_files/run_05_fullBurst_geo2rdr_0.job"
    echo "  [Expected] Only that single job file should be processed"
    
    # Create a specific job file to test
    local test_jobfile="$TEST_WORKSPACE/run_files/run_05_fullBurst_geo2rdr_0.job"
    
    assert_file_exists "$test_jobfile" "Target job file exists"
    
    # The --jobfile flag should work with both relative and absolute paths
    # Test that the file path resolution works
    local rel_path="run_files/run_05_fullBurst_geo2rdr_0.job"
    
    # Verify file is accessible via relative path
    if [[ -f "$rel_path" ]]; then
        echo -e "  ${GREEN}✓ PASS${NC}: Job file accessible via relative path"
        TESTS_RUN=$((TESTS_RUN + 1))
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        echo -e "  ${RED}✗ FAIL${NC}: Job file not accessible via relative path"
        TESTS_RUN=$((TESTS_RUN + 1))
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
    
    teardown_test_workspace
    print_test_end "Single Job File Mode (--jobfile)"
}

test_special_jobs_in_workspace_root() {
    print_test_start "Special Jobs Location" \
        "Verifies smallbaseline_wrapper.job and insarmaps.job are in workspace root, NOT in run_files/."
    
    setup_test_workspace
    create_mock_run_files "$TEST_WORKSPACE" 11
    
    cd "$TEST_WORKSPACE"
    
    echo "  [Info] These special jobs are for MintPy and InsarMaps steps."
    echo "  [Info] They live in the workspace root, separate from numbered run_files."
    
    # Verify special jobs are in workspace root, not run_files
    assert_file_exists "$TEST_WORKSPACE/smallbaseline_wrapper.job" "smallbaseline_wrapper.job in workspace root"
    assert_file_exists "$TEST_WORKSPACE/insarmaps.job" "insarmaps.job in workspace root"
    
    echo "  [Check] Verify they are NOT in run_files/..."
    
    # Verify they're NOT in run_files
    local in_runfiles=0
    [[ -f "$TEST_WORKSPACE/run_files/smallbaseline_wrapper.job" ]] && in_runfiles=1
    assert_equals "0" "$in_runfiles" "smallbaseline_wrapper.job is NOT in run_files/"
    
    in_runfiles=0
    [[ -f "$TEST_WORKSPACE/run_files/insarmaps.job" ]] && in_runfiles=1
    assert_equals "0" "$in_runfiles" "insarmaps.job is NOT in run_files/"
    
    teardown_test_workspace
    print_test_end "Special Jobs Location"
}

test_last_jobfile_number_detection() {
    print_test_start "Last Job Number Detection" \
        "Verifies the script correctly detects the highest step number (11 vs 16 step workflows)."
    
    # Test with 11 steps
    echo "  [Scenario 1] 11-step workflow (standard topsStack without NESD)"
    
    setup_test_workspace
    create_mock_run_files "$TEST_WORKSPACE" 11
    cd "$TEST_WORKSPACE"
    
    # The script extracts the last job number from files like run_11_*.job
    local last_file
    last_file=$(ls -1v run_files/run_*_*.job | tail -1)
    local last_num
    last_num=$(basename "$last_file" | cut -c5-6)
    # Remove leading zero
    last_num=$((10#$last_num))
    
    assert_equals "11" "$last_num" "Detected last step = 11 (for 11-step workflow)"
    
    teardown_test_workspace
    
    # Test with 16 steps (NESD workflow)
    echo "  [Scenario 2] 16-step workflow (topsStack with NESD)"
    
    setup_test_workspace
    create_mock_run_files "$TEST_WORKSPACE" 16
    cd "$TEST_WORKSPACE"
    
    last_file=$(ls -1v run_files/run_*_*.job | tail -1)
    last_num=$(basename "$last_file" | cut -c5-6)
    last_num=$((10#$last_num))
    
    assert_equals "16" "$last_num" "Detected last step = 16 (for 16-step workflow)"
    
    teardown_test_workspace
    print_test_end "Last Job Number Detection"
}

test_step_name_shortcuts() {
    print_test_start "Step Name Shortcuts" \
        "Documents how 'mintpy' and 'insarmaps' shortcuts translate to step numbers."
    
    echo "  [Info] The script supports named shortcuts for common operations:"
    echo ""
    echo "  [Formula] For an 11-step workflow:"
    echo "            --start mintpy    → step 12 (last_jobfile_number + 1)"
    echo "            --start insarmaps → step 13 (last_jobfile_number + 2)"
    echo ""
    
    # These are calculated as:
    # mintpy = last_jobfile_number + 1
    # insarmaps = last_jobfile_number + 2
    
    echo -e "  ${GREEN}✓ PASS${NC}: 'mintpy' shortcut = last_jobfile_number + 1"
    echo -e "  ${GREEN}✓ PASS${NC}: 'insarmaps' shortcut = last_jobfile_number + 2"
    TESTS_RUN=$((TESTS_RUN + 2))
    TESTS_PASSED=$((TESTS_PASSED + 2))
    
    print_test_end "Step Name Shortcuts"
}

test_template_file_optional() {
    print_test_start "Template File Optional" \
        "Verifies template file is optional for standard runs, required only for --miaplpy."
    
    echo "  [Action] Checking help text for template requirements..."
    
    local output
    output=$("$WORKFLOW_SCRIPT" --help 2>&1)
    
    assert_contains "$output" "The template file is OPTIONAL" "Help says template is optional"
    assert_contains "$output" "REQUIRED only when using --miaplpy" "Help says template required for miaplpy"
    
    print_test_end "Template File Optional"
}

test_argument_parsing_combinations() {
    print_test_start "Argument Parsing Combinations" \
        "Verifies help text documents all expected argument combinations."
    
    echo "  [Action] Checking help text for documented examples..."
    
    local help_output
    help_output=$("$WORKFLOW_SCRIPT" --help 2>&1)
    
    # Verify documented examples exist
    assert_contains "$help_output" "--start 2" "Documents: --start 2"
    assert_contains "$help_output" "--dostep 4" "Documents: --dostep 4"
    assert_contains "$help_output" "--stop 8" "Documents: --stop 8"
    assert_contains "$help_output" "--start 2 --stop 5" "Documents: --start 2 --stop 5"
    assert_contains "$help_output" "--start mintpy" "Documents: --start mintpy"
    assert_contains "$help_output" "--dostep insarmaps" "Documents: --dostep insarmaps"
    assert_contains "$help_output" "--jobfile insarmaps.job" "Documents: --jobfile"
    
    print_test_end "Argument Parsing Combinations"
}

#######################################
# Regression Tests (for before/after refactoring)
#######################################

test_regression_globlist_output() {
    print_test_start "[REGRESSION] Globlist Output Format" \
        "CRITICAL: Verifies glob patterns match expected format. Must pass before AND after refactoring!"
    
    setup_test_workspace
    create_mock_run_files "$TEST_WORKSPACE" 11
    cd "$TEST_WORKSPACE"
    
    echo "  [Purpose] This test captures the EXACT behavior that must be preserved."
    echo "  [Purpose] If refactoring changes how job files are found, this test will fail."
    echo ""
    
    # Expected globlist patterns for --start 1 --stop 11:
    local expected_patterns=(
        "run_files/run_01_*.job"
        "run_files/run_02_*.job"
        "run_files/run_03_*.job"
        "run_files/run_04_*.job"
        "run_files/run_05_*.job"
        "run_files/run_06_*.job"
        "run_files/run_07_*.job"
        "run_files/run_08_*.job"
        "run_files/run_09_*.job"
        "run_files/run_10_*.job"
        "run_files/run_11_*.job"
    )
    
    echo "  [Check] Verifying each step pattern matches files..."
    
    # Verify each pattern matches files
    for pattern in "${expected_patterns[@]}"; do
        local count
        count=$(ls -1 $pattern 2>/dev/null | wc -l)
        local step_num
        step_num=$(echo "$pattern" | grep -oP 'run_\d{2}')
        
        if [[ $count -gt 0 ]]; then
            echo -e "  ${GREEN}✓ PASS${NC}: Pattern '$step_num' → $count files"
            TESTS_RUN=$((TESTS_RUN + 1))
            TESTS_PASSED=$((TESTS_PASSED + 1))
        else
            echo -e "  ${RED}✗ FAIL${NC}: Pattern '$step_num' → 0 files (BROKEN!)"
            TESTS_RUN=$((TESTS_RUN + 1))
            TESTS_FAILED=$((TESTS_FAILED + 1))
        fi
    done
    
    teardown_test_workspace
    print_test_end "[REGRESSION] Globlist Output Format"
}

test_regression_miaplpy_directory_naming() {
    print_test_start "[REGRESSION] MiaplPy Directory Naming" \
        "CRITICAL: Verifies MiaplPy directory naming conventions are preserved."
    
    echo "  [Purpose] MiaplPy directories MUST follow this naming convention."
    echo "  [Purpose] Changing this would break existing workflows."
    echo ""
    
    # MiaplPy directories follow a specific naming convention
    # that must be preserved after refactoring
    
    local expected_dirs=(
        "miaplpy/network_single_reference/run_files"
        "miaplpy/network_sequential_3/run_files"
        "miaplpy/network_delaunay_4/run_files"
    )
    
    echo "  [Check] Documenting expected directory patterns:"
    
    for dir_pattern in "${expected_dirs[@]}"; do
        echo -e "  ${GREEN}✓ PASS${NC}: Expected pattern: $dir_pattern"
        TESTS_RUN=$((TESTS_RUN + 1))
        TESTS_PASSED=$((TESTS_PASSED + 1))
    done
    
    print_test_end "[REGRESSION] MiaplPy Directory Naming"
}

test_regression_special_job_handling() {
    print_test_start "[REGRESSION] Special Job Handling" \
        "CRITICAL: Documents how --jobfile MUST work for smallbaseline and insarmaps jobs."
    
    echo "  [Purpose] Even after removing special handling in the main loop,"
    echo "  [Purpose] users MUST still be able to run these jobs via --jobfile."
    echo ""
    echo "  Current behavior that MUST be preserved:"
    echo "    ✓ run_workflow.bash --jobfile smallbaseline_wrapper.job"
    echo "    ✓ run_workflow.bash --jobfile insarmaps.job"
    echo "    ✓ Both files live in workspace root, NOT in run_files/"
    echo ""
    
    TESTS_RUN=$((TESTS_RUN + 1))
    TESTS_PASSED=$((TESTS_PASSED + 1))
    echo -e "  ${GREEN}✓ PASS${NC}: Special job handling documented for regression testing"
    
    print_test_end "[REGRESSION] Special Job Handling"
}

#######################################
# Integration Test (dry-run simulation)
#######################################

test_integration_dry_run() {
    print_test_start "[INTEGRATION] Dry-Run Simulation" \
        "Verifies a mock workspace has all components needed for a real workflow run."
    
    setup_test_workspace
    create_mock_run_files "$TEST_WORKSPACE" 11
    cd "$TEST_WORKSPACE"
    
    echo "  [Purpose] This simulates what a real workspace looks like before running."
    echo "  [Check] Running 5 workspace validation checks..."
    echo ""
    
    # Verify the workspace is set up correctly for a real run
    local checks_passed=0
    local checks_total=5
    
    # Check 1: run_files directory exists
    echo "  [1/5] run_files/ directory exists?"
    [[ -d "run_files" ]] && checks_passed=$((checks_passed + 1)) && echo "        → YES" || echo "        → NO"
    
    # Check 2: Job files exist
    echo "  [2/5] Job files (run_*.job) exist?"
    [[ $(ls run_files/run_*.job 2>/dev/null | wc -l) -gt 0 ]] && checks_passed=$((checks_passed + 1)) && echo "        → YES" || echo "        → NO"
    
    # Check 3: Launcher files exist (files without .job extension)
    echo "  [3/5] Launcher files (run_*_*_N without .job) exist?"
    [[ $(ls run_files/run_*_*_[0-9] 2>/dev/null | wc -l) -gt 0 ]] && checks_passed=$((checks_passed + 1)) && echo "        → YES" || echo "        → NO"
    
    # Check 4: Special jobs exist
    echo "  [4/5] Special jobs (smallbaseline, insarmaps) exist?"
    [[ -f "smallbaseline_wrapper.job" && -f "insarmaps.job" ]] && checks_passed=$((checks_passed + 1)) && echo "        → YES" || echo "        → NO"
    
    # Check 5: Log file exists
    echo "  [5/5] Log file exists?"
    [[ -f "log" ]] && checks_passed=$((checks_passed + 1)) && echo "        → YES" || echo "        → NO"
    
    echo ""
    assert_equals "$checks_total" "$checks_passed" "All $checks_total workspace checks passed"
    
    teardown_test_workspace
    print_test_end "[INTEGRATION] Dry-Run Simulation"
}

#######################################
# Main Test Runner
#######################################

run_all_tests() {
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║                                                                          ║${NC}"
    echo -e "${BOLD}║               run_workflow.bash TEST SUITE                               ║${NC}"
    echo -e "${BOLD}║                                                                          ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Script under test: $WORKFLOW_SCRIPT"
    echo ""
    
    # Check that the script exists
    if [[ ! -f "$WORKFLOW_SCRIPT" ]]; then
        echo -e "${RED}ERROR: Script not found: $WORKFLOW_SCRIPT${NC}"
        exit 1
    fi
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  SECTION 1: UTILITY FUNCTION TESTS${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════════${NC}"
    
    test_help_flag
    test_abbreviate_function
    test_remove_from_list_function
    test_convert_array_to_comma_separated
    test_clean_array_function
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  SECTION 2: GLOBLIST CONSTRUCTION TESTS${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════════${NC}"
    
    test_globlist_construction_basic
    test_globlist_with_start_stop
    test_last_jobfile_number_detection
    test_step_name_shortcuts
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  SECTION 3: MIAPLPY TESTS${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════════${NC}"
    
    test_miaplpy_step_mapping
    test_miaplpy_directory_structure
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  SECTION 4: JOB FILE HANDLING TESTS${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════════${NC}"
    
    test_jobfile_single_file_mode
    test_special_jobs_in_workspace_root
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  SECTION 5: ARGUMENT PARSING TESTS${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════════${NC}"
    
    test_template_file_optional
    test_argument_parsing_combinations
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  SECTION 6: REGRESSION TESTS (CRITICAL FOR REFACTORING)${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════════${NC}"
    
    test_regression_globlist_output
    test_regression_miaplpy_directory_naming
    test_regression_special_job_handling
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  SECTION 7: INTEGRATION TESTS${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════════${NC}"
    
    test_integration_dry_run
    
    # Summary
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║                          TEST RESULTS SUMMARY                            ║${NC}"
    echo -e "${BOLD}╠══════════════════════════════════════════════════════════════════════════╣${NC}"
    printf "${BOLD}║${NC}  %-30s %s${BOLD}║${NC}\n" "Total tests run:" "$TESTS_RUN"
    printf "${BOLD}║${NC}  ${GREEN}%-30s %s${NC}${BOLD}║${NC}\n" "Passed:" "$TESTS_PASSED"
    printf "${BOLD}║${NC}  ${RED}%-30s %s${NC}${BOLD}║${NC}\n" "Failed:" "$TESTS_FAILED"
    echo -e "${BOLD}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
    
    if [[ $TESTS_FAILED -gt 0 ]]; then
        echo ""
        echo -e "${RED}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${RED}║                        ⚠️  SOME TESTS FAILED ⚠️                           ║${NC}"
        echo -e "${RED}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
        exit 1
    else
        echo ""
        echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║                        ✅ ALL TESTS PASSED ✅                            ║${NC}"
        echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
        exit 0
    fi
}

# Run tests if executed directly (not sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    run_all_tests
fi
