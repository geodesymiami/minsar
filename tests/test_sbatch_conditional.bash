#!/usr/bin/env bash
#
# Test suite for sbatch_conditional.bash
# Run with: bash tests/test_sbatch_conditional.bash
#
# These tests verify the behavior of sbatch_conditional.bash utility functions
# without actually submitting jobs (which requires SLURM).
#

set -o pipefail

#######################################
# Configuration
#######################################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SBATCH_SCRIPT="$PROJECT_ROOT/minsar/bin/sbatch_conditional.bash"

# Source test helpers
source "$SCRIPT_DIR/test_helpers.bash"

# Test workspace
TEST_WORKSPACE=""

#######################################
# Source functions from sbatch_conditional.bash
#######################################
source_sbatch_functions() {
    # Extract and source functions from sbatch_conditional.bash
    # We source lines 1 up to (but not including) the help check.
    # Use sed '$d' instead of head -n -1 (BSD head doesn't support negative count).
    local func_file=$(mktemp)
    
    sed -n '1,/^if \[\[ "\$1" == "--help"/p' "$SBATCH_SCRIPT" | sed '$d' > "$func_file"
    
    source "$func_file"
    rm -f "$func_file"
}

#######################################
# Test Cases
#######################################

test_help_flag() {
    print_test_start "Help Flag" \
        "Verifies that 'sbatch_conditional.bash --help' shows usage info and exits cleanly."
    
    echo "  [Action] Running: sbatch_conditional.bash --help"
    
    local output
    output=$("$SBATCH_SCRIPT" --help 2>&1)
    local exit_code=$?
    
    echo "  [Check] Verifying help output contains expected sections..."
    
    assert_exit_code 0 "$exit_code" "Help exits with code 0 (success)"
    assert_contains "$output" "sbatch" "Help mentions sbatch"
    assert_contains "$output" "job_file" "Help mentions job_file argument"
    assert_contains "$output" "--verbose" "Help documents --verbose option"
    assert_contains "$output" "SJOBS_MAX_JOBS_PER_QUEUE" "Help documents resource limits"
    
    print_test_end "Help Flag"
}

test_extract_step_name_run_files() {
    print_test_start "Extract Step Name - Run Files" \
        "Tests extract_step_name() with standard run_XX_stepname_N.job patterns."
    
    source_sbatch_functions
    
    echo "  [Action] Testing extract_step_name() with various job file patterns..."
    
    local result
    
    # Test 1: Standard run file pattern
    echo "  [Test] run_01_unpack_topo_reference_0.job"
    result=$(extract_step_name "run_01_unpack_topo_reference_0.job")
    assert_equals "unpack_topo_reference" "$result" "Extracts step name from run_01"
    
    # Test 2: Different step number
    echo "  [Test] run_11_unwrap_3.job"
    result=$(extract_step_name "run_11_unwrap_3.job")
    assert_equals "unwrap" "$result" "Extracts step name from run_11"
    
    # Test 3: Multi-word step name with underscores
    echo "  [Test] run_05_fullBurst_geo2rdr_2.job"
    result=$(extract_step_name "run_05_fullBurst_geo2rdr_2.job")
    assert_equals "fullBurst_geo2rdr" "$result" "Extracts multi-word step name"
    
    # Test 4: Full path
    echo "  [Test] /path/to/run_files/run_03_average_baseline_1.job"
    result=$(extract_step_name "/path/to/run_files/run_03_average_baseline_1.job")
    assert_equals "average_baseline" "$result" "Extracts step name from full path"
    
    print_test_end "Extract Step Name - Run Files"
}

test_extract_step_name_special_jobs() {
    print_test_start "Extract Step Name - Special Jobs" \
        "Tests extract_step_name() with special job files (no hardcoded list needed)."
    
    source_sbatch_functions
    
    echo "  [Action] Testing extract_step_name() with special job patterns..."
    
    local result
    
    # Test 1: smallbaseline_wrapper.job
    echo "  [Test] smallbaseline_wrapper.job"
    result=$(extract_step_name "smallbaseline_wrapper.job")
    assert_equals "smallbaseline_wrapper" "$result" "Extracts smallbaseline_wrapper"
    
    # Test 2: insarmaps.job
    echo "  [Test] insarmaps.job"
    result=$(extract_step_name "insarmaps.job")
    assert_equals "insarmaps" "$result" "Extracts insarmaps"
    
    # Test 3: ingest_insarmaps.job (no longer needs hardcoded support)
    echo "  [Test] ingest_insarmaps.job"
    result=$(extract_step_name "ingest_insarmaps.job")
    assert_equals "ingest_insarmaps" "$result" "Extracts ingest_insarmaps without hardcoding"
    
    # Test 4: horzvert_timeseries.job
    echo "  [Test] horzvert_timeseries.job"
    result=$(extract_step_name "horzvert_timeseries.job")
    assert_equals "horzvert_timeseries" "$result" "Extracts horzvert_timeseries without hardcoding"
    
    # Test 5: Any future job type (demonstrating no hardcoding needed)
    echo "  [Test] future_processing_step.job"
    result=$(extract_step_name "future_processing_step.job")
    assert_equals "future_processing_step" "$result" "Extracts any future job name without hardcoding"
    
    # Test 6: Full path to special job
    echo "  [Test] /path/to/workspace/insarmaps.job"
    result=$(extract_step_name "/path/to/workspace/insarmaps.job")
    assert_equals "insarmaps" "$result" "Extracts step name from full path to special job"
    
    print_test_end "Extract Step Name - Special Jobs"
}

test_extract_step_name_edge_cases() {
    print_test_start "Extract Step Name - Edge Cases" \
        "Tests extract_step_name() with unusual but valid patterns."
    
    source_sbatch_functions
    
    echo "  [Action] Testing extract_step_name() edge cases..."
    
    local result
    
    # Test 1: Job file with numbers in step name
    echo "  [Test] run_02_step2_0.job"
    result=$(extract_step_name "run_02_step2_0.job")
    assert_equals "step2" "$result" "Handles numbers in step name"
    
    # Test 2: Simple job name with trailing number
    echo "  [Test] custom_job_1.job"
    result=$(extract_step_name "custom_job_1.job")
    assert_equals "custom_job" "$result" "Removes trailing number from simple job"
    
    # Test 3: Job name without trailing number
    echo "  [Test] simple_job.job"
    result=$(extract_step_name "simple_job.job")
    assert_equals "simple_job" "$result" "Handles job without trailing number"
    
    print_test_end "Extract Step Name - Edge Cases"
}

test_num_tasks_for_file() {
    print_test_start "Num Tasks For File" \
        "Tests num_tasks_for_file() which counts tasks in launcher files."
    
    source_sbatch_functions
    
    setup_test_workspace
    
    echo "  [Action] Creating test launcher files..."
    
    # Create a launcher file with 5 tasks
    local launcher5="$TEST_WORKSPACE/run_01_test_0"
    printf "task1\ntask2\ntask3\ntask4\ntask5\n" > "$launcher5"
    
    # Create a launcher file with 1 task
    local launcher1="$TEST_WORKSPACE/run_02_single_0"
    echo "single_task" > "$launcher1"
    
    local result
    
    # Test 1: 5-task file
    echo "  [Test] Launcher with 5 tasks"
    result=$(num_tasks_for_file "${launcher5}.job")
    assert_equals "5" "$result" "Counts 5 tasks correctly"
    
    # Test 2: 1-task file  
    echo "  [Test] Launcher with 1 task"
    result=$(num_tasks_for_file "${launcher1}.job")
    assert_equals "1" "$result" "Counts 1 task correctly"
    
    # Test 3: Non-existent file (defaults to 1)
    echo "  [Test] Non-existent launcher file"
    result=$(num_tasks_for_file "$TEST_WORKSPACE/nonexistent.job")
    assert_equals "1" "$result" "Defaults to 1 for non-existent file"
    
    teardown_test_workspace
    
    print_test_end "Num Tasks For File"
}

test_rename_stderr_stdout_file() {
    print_test_start "Rename Stderr/Stdout Files" \
        "Tests rename_stderr_stdout_file() which renames .e and .o files for retries."
    
    source_sbatch_functions
    
    setup_test_workspace
    mkdir -p "$TEST_WORKSPACE/run_files"
    
    echo "  [Action] Creating test .e and .o files..."
    
    local job_file="$TEST_WORKSPACE/run_files/run_01_test_0.job"
    touch "$job_file"
    
    # Create .e and .o files
    echo "error output" > "$TEST_WORKSPACE/run_files/run_01_test_0.e"
    echo "stdout output" > "$TEST_WORKSPACE/run_files/run_01_test_0.o"
    
    echo "  [Action] Calling rename_stderr_stdout_file..."
    rename_stderr_stdout_file "$job_file" 2>/dev/null
    
    echo "  [Check] Verifying files were renamed..."
    
    assert_file_exists "$TEST_WORKSPACE/run_files/run_01_test_0.e.1try" "Error file renamed to .e.1try"
    assert_file_exists "$TEST_WORKSPACE/run_files/run_01_test_0.o.1try" "Output file renamed to .o.1try"
    
    # Create new .e and .o files (simulating re-run)
    echo "error output 2" > "$TEST_WORKSPACE/run_files/run_01_test_0.e"
    echo "stdout output 2" > "$TEST_WORKSPACE/run_files/run_01_test_0.o"
    
    echo "  [Action] Calling rename_stderr_stdout_file again (second retry)..."
    rename_stderr_stdout_file "$job_file" 2>/dev/null
    
    assert_file_exists "$TEST_WORKSPACE/run_files/run_01_test_0.e.2try" "Error file renamed to .e.2try on second call"
    assert_file_exists "$TEST_WORKSPACE/run_files/run_01_test_0.o.2try" "Output file renamed to .o.2try on second call"
    
    teardown_test_workspace
    
    print_test_end "Rename Stderr/Stdout Files"
}

test_regression_no_hardcoded_jobs() {
    print_test_start "[REGRESSION] No Hardcoded Job Names" \
        "CRITICAL: Verifies that extract_step_name works without hardcoded special job list."
    
    source_sbatch_functions
    
    echo "  [Purpose] After refactoring, new job types should work automatically."
    echo "  [Purpose] No need to edit sbatch_conditional.bash when adding new job types."
    
    local result
    
    # Test that ANY job name works, not just hardcoded ones
    local test_jobs=(
        "smallbaseline_wrapper.job"
        "insarmaps.job"
        "ingest_insarmaps.job"
        "horzvert_timeseries.job"
        "create_miaplpy_jobfiles.job"
        "new_future_job.job"
        "another_new_step.job"
        "upload_data.job"
        "process_chunk.job"
    )
    
    echo "  [Check] Testing that ALL job types extract correctly without hardcoding..."
    
    for job in "${test_jobs[@]}"; do
        local expected="${job%.job}"  # Remove .job extension
        result=$(extract_step_name "$job")
        assert_equals "$expected" "$result" "Extracts '$expected' from '$job'"
    done
    
    print_test_end "[REGRESSION] No Hardcoded Job Names"
}

#######################################
# Run All Tests
#######################################

run_all_tests() {
    print_header "sbatch_conditional.bash TEST SUITE"
    
    echo ""
    echo "Script under test: $SBATCH_SCRIPT"
    
    print_section "SECTION 1: HELP & USAGE TESTS"
    test_help_flag
    
    print_section "SECTION 2: EXTRACT STEP NAME TESTS"
    test_extract_step_name_run_files
    test_extract_step_name_special_jobs
    test_extract_step_name_edge_cases
    
    print_section "SECTION 3: UTILITY FUNCTION TESTS"
    test_num_tasks_for_file
    test_rename_stderr_stdout_file
    
    print_section "SECTION 4: REGRESSION TESTS"
    test_regression_no_hardcoded_jobs
    
    print_summary
}

# Run tests if executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    run_all_tests
    exit $?
fi
