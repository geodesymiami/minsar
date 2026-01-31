#!/usr/bin/env bash
#
# Shared test utilities for minsar bash test suite
# Source this file in individual test files
#

#######################################
# Configuration
#######################################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Test counters (can be used by sourcing scripts)
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

print_header() {
    local title="$1"
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║                                                                          ║${NC}"
    echo -e "${BOLD}║               ${title}${NC}"
    echo -e "${BOLD}║                                                                          ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
}

print_section() {
    local section_name="$1"
    echo ""
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  ${section_name}${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════════${NC}"
}

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

print_summary() {
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║                          TEST RESULTS SUMMARY                            ║${NC}"
    echo -e "${BOLD}╠══════════════════════════════════════════════════════════════════════════╣${NC}"
    printf "${BOLD}║${NC}  Total tests run:               %-5s${BOLD}║${NC}\n" "$TESTS_RUN"
    printf "${BOLD}║${NC}  ${GREEN}Passed:                        %-5s${NC}${BOLD}║${NC}\n" "$TESTS_PASSED"
    printf "${BOLD}║${NC}  ${RED}Failed:                        %-5s${NC}${BOLD}║${NC}\n" "$TESTS_FAILED"
    echo -e "${BOLD}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
    
    if [[ $TESTS_FAILED -eq 0 ]]; then
        echo ""
        echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║                        ✅ ALL TESTS PASSED ✅                            ║${NC}"
        echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
        return 0
    else
        echo ""
        echo -e "${RED}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${RED}║                        ⚠️  SOME TESTS FAILED ⚠️                           ║${NC}"
        echo -e "${RED}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
        return 1
    fi
}

#######################################
# Assertion Functions
#######################################

assert_equals() {
    local expected="$1"
    local actual="$2"
    local message="$3"
    
    ((TESTS_RUN++))
    
    if [[ "$expected" == "$actual" ]]; then
        echo -e "  ${GREEN}✓ PASS${NC}: $message"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "  ${RED}✗ FAIL${NC}: $message"
        echo -e "       Expected: '$expected'"
        echo -e "       Actual:   '$actual'"
        ((TESTS_FAILED++))
        return 1
    fi
}

assert_contains() {
    local haystack="$1"
    local needle="$2"
    local message="$3"
    
    ((TESTS_RUN++))
    
    if [[ "$haystack" == *"$needle"* ]]; then
        echo -e "  ${GREEN}✓ PASS${NC}: $message"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "  ${RED}✗ FAIL${NC}: $message"
        echo -e "       String does not contain: '$needle'"
        ((TESTS_FAILED++))
        return 1
    fi
}

assert_not_contains() {
    local haystack="$1"
    local needle="$2"
    local message="$3"
    
    ((TESTS_RUN++))
    
    if [[ "$haystack" != *"$needle"* ]]; then
        echo -e "  ${GREEN}✓ PASS${NC}: $message"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "  ${RED}✗ FAIL${NC}: $message"
        echo -e "       String should NOT contain: '$needle'"
        ((TESTS_FAILED++))
        return 1
    fi
}

assert_file_exists() {
    local path="$1"
    local message="$2"
    
    ((TESTS_RUN++))
    
    if [[ -f "$path" ]]; then
        echo -e "  ${GREEN}✓ PASS${NC}: $message"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "  ${RED}✗ FAIL${NC}: $message"
        echo -e "       File does not exist: '$path'"
        ((TESTS_FAILED++))
        return 1
    fi
}

assert_dir_exists() {
    local path="$1"
    local message="$2"
    
    ((TESTS_RUN++))
    
    if [[ -d "$path" ]]; then
        echo -e "  ${GREEN}✓ PASS${NC}: $message"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "  ${RED}✗ FAIL${NC}: $message"
        echo -e "       Directory does not exist: '$path'"
        ((TESTS_FAILED++))
        return 1
    fi
}

assert_exit_code() {
    local expected="$1"
    local actual="$2"
    local message="$3"
    
    ((TESTS_RUN++))
    
    if [[ "$expected" -eq "$actual" ]]; then
        echo -e "  ${GREEN}✓ PASS${NC}: $message"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "  ${RED}✗ FAIL${NC}: $message"
        echo -e "       Expected exit code: $expected"
        echo -e "       Actual exit code:   $actual"
        ((TESTS_FAILED++))
        return 1
    fi
}

assert_matches_regex() {
    local string="$1"
    local pattern="$2"
    local message="$3"
    
    ((TESTS_RUN++))
    
    if [[ "$string" =~ $pattern ]]; then
        echo -e "  ${GREEN}✓ PASS${NC}: $message"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "  ${RED}✗ FAIL${NC}: $message"
        echo -e "       String '$string' does not match pattern '$pattern'"
        ((TESTS_FAILED++))
        return 1
    fi
}

#######################################
# Test Workspace Functions
#######################################

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
        "load_data"
        "phase_linking"
        "concatenate_patches"
        "generate_ifgram"
        "unwrap_ifgram"
        "load_ifgram"
        "ifgram_correction"
        "invert_network"
        "timeseries_correction"
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
            local launcher_file="$runfiles_dir/run_${stepnum}_${step_name}_${j}"
            echo "task1" > "$launcher_file"
        done
    done
    
    touch "$workspace/log"
    
    echo "  [Setup] Created MiaplPy structure: miaplpy/network_${network_type}/run_files/"
}
