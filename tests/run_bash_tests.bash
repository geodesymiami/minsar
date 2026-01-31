#!/usr/bin/env bash
#
# Meta test runner for minsar bash test suite
# Run with: bash tests/run_all_tests.bash
#
# This script runs all individual test suites and aggregates results.
# Designed to be called from CI/CD systems (CircleCI, GitHub Actions, etc.)
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

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Test suite configuration
# Add new test files here as they are created
TEST_SUITES=(
    "test_run_workflow.bash"
    "test_submit_jobs.bash"
    "test_sbatch_conditional.bash"
)

# Results tracking
TOTAL_SUITES=0
PASSED_SUITES=0
FAILED_SUITES=0
FAILED_SUITE_NAMES=()

#######################################
# Functions
#######################################

print_banner() {
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║                                                                          ║${NC}"
    echo -e "${BOLD}║                    MINSAR BASH TEST SUITE RUNNER                         ║${NC}"
    echo -e "${BOLD}║                                                                          ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Project root: $PROJECT_ROOT"
    echo "Test directory: $SCRIPT_DIR"
    echo ""
}

run_test_suite() {
    local suite_name="$1"
    local suite_path="$SCRIPT_DIR/$suite_name"
    
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  RUNNING: ${suite_name}${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    ((TOTAL_SUITES++))
    
    if [[ ! -f "$suite_path" ]]; then
        echo -e "${RED}ERROR: Test suite not found: $suite_path${NC}"
        ((FAILED_SUITES++))
        FAILED_SUITE_NAMES+=("$suite_name (NOT FOUND)")
        return 1
    fi
    
    # Run the test suite
    bash "$suite_path"
    local exit_code=$?
    
    if [[ $exit_code -eq 0 ]]; then
        echo ""
        echo -e "${GREEN}✓ SUITE PASSED: ${suite_name}${NC}"
        ((PASSED_SUITES++))
        return 0
    else
        echo ""
        echo -e "${RED}✗ SUITE FAILED: ${suite_name}${NC}"
        ((FAILED_SUITES++))
        FAILED_SUITE_NAMES+=("$suite_name")
        return 1
    fi
}

print_final_summary() {
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║                     FINAL TEST RESULTS SUMMARY                           ║${NC}"
    echo -e "${BOLD}╠══════════════════════════════════════════════════════════════════════════╣${NC}"
    printf "${BOLD}║${NC}  Total test suites run:         %-5s${BOLD}║${NC}\n" "$TOTAL_SUITES"
    printf "${BOLD}║${NC}  ${GREEN}Suites passed:                 %-5s${NC}${BOLD}║${NC}\n" "$PASSED_SUITES"
    printf "${BOLD}║${NC}  ${RED}Suites failed:                 %-5s${NC}${BOLD}║${NC}\n" "$FAILED_SUITES"
    echo -e "${BOLD}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
    
    if [[ $FAILED_SUITES -gt 0 ]]; then
        echo ""
        echo -e "${RED}Failed suites:${NC}"
        for suite in "${FAILED_SUITE_NAMES[@]}"; do
            echo -e "  ${RED}✗${NC} $suite"
        done
    fi
    
    echo ""
    if [[ $FAILED_SUITES -eq 0 ]]; then
        echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║                    ✅ ALL TEST SUITES PASSED ✅                          ║${NC}"
        echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
        return 0
    else
        echo -e "${RED}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${RED}║                   ⚠️  SOME TEST SUITES FAILED ⚠️                          ║${NC}"
        echo -e "${RED}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
        return 1
    fi
}

show_usage() {
    echo "Usage: $0 [OPTIONS] [SUITE_NAME...]"
    echo ""
    echo "Options:"
    echo "  --help, -h      Show this help message"
    echo "  --list          List available test suites"
    echo "  --quiet, -q     Only show summary (suppress individual test output)"
    echo ""
    echo "If no SUITE_NAME is provided, all test suites are run."
    echo ""
    echo "Examples:"
    echo "  $0                              # Run all tests"
    echo "  $0 test_run_workflow.bash       # Run specific test suite"
    echo "  $0 --list                       # List available suites"
    echo ""
}

list_suites() {
    echo "Available test suites:"
    echo ""
    for suite in "${TEST_SUITES[@]}"; do
        local suite_path="$SCRIPT_DIR/$suite"
        if [[ -f "$suite_path" ]]; then
            echo -e "  ${GREEN}✓${NC} $suite"
        else
            echo -e "  ${RED}✗${NC} $suite (not found)"
        fi
    done
    echo ""
}

#######################################
# Main
#######################################

main() {
    local suites_to_run=()
    local quiet_mode=false
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --help|-h)
                show_usage
                exit 0
                ;;
            --list)
                list_suites
                exit 0
                ;;
            --quiet|-q)
                quiet_mode=true
                shift
                ;;
            *)
                suites_to_run+=("$1")
                shift
                ;;
        esac
    done
    
    # If no specific suites requested, run all
    if [[ ${#suites_to_run[@]} -eq 0 ]]; then
        suites_to_run=("${TEST_SUITES[@]}")
    fi
    
    print_banner
    
    echo "Test suites to run: ${#suites_to_run[@]}"
    for suite in "${suites_to_run[@]}"; do
        echo "  - $suite"
    done
    
    # Run each test suite
    for suite in "${suites_to_run[@]}"; do
        if $quiet_mode; then
            run_test_suite "$suite" > /dev/null 2>&1
        else
            run_test_suite "$suite"
        fi
    done
    
    # Print final summary
    print_final_summary
    
    # Exit with appropriate code
    if [[ $FAILED_SUITES -eq 0 ]]; then
        exit 0
    else
        exit 1
    fi
}

# Run main
main "$@"
