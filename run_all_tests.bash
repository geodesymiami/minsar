#!/usr/bin/env bash
#
# Unified test runner for minsar project
# Runs both Python (unittest) and Bash test suites
#
# Usage: ./run_all_tests.bash [OPTIONS]
#
# Options:
#   --help, -h        Show this help message
#   --python-only     Run only Python tests
#   --bash-only       Run only Bash tests
#   --verbose, -v     Verbose output
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
TESTS_DIR="$SCRIPT_DIR/tests"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Flags
RUN_PYTHON=true
RUN_BASH=true
VERBOSE=false

# Results tracking
PYTHON_RESULT=0
BASH_RESULT=0

#######################################
# Functions
#######################################

show_help() {
    cat << 'EOF'
Usage: ./run_all_tests.bash [OPTIONS]

Unified test runner for the minsar project.
Runs both Python (unittest) and Bash test suites.

Options:
  --help, -h        Show this help message
  --python-only     Run only Python tests
  --bash-only       Run only Bash tests
  --verbose, -v     Verbose output

Examples:
  ./run_all_tests.bash                # Run all tests
  ./run_all_tests.bash --python-only  # Run only Python tests
  ./run_all_tests.bash --bash-only    # Run only Bash tests
  ./run_all_tests.bash -v             # Run all tests with verbose output

Exit codes:
  0 = All tests passed
  1 = One or more tests failed
EOF
}

print_banner() {
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║                                                                          ║${NC}"
    echo -e "${BOLD}║                      MINSAR UNIFIED TEST RUNNER                          ║${NC}"
    echo -e "${BOLD}║                                                                          ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Project root: $SCRIPT_DIR"
    echo ""
}

run_python_tests() {
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  PYTHON TESTS (unittest)${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    cd "$SCRIPT_DIR"
    
    local verbosity=""
    if $VERBOSE; then
        verbosity="-v"
    fi
    
    # Hybrid test discovery approach:
    # 1. Discover tests in tests/ directory (integration tests)
    # 2. Discover tests in minsar/*/tests/ directories (colocated unit tests)
    # We explicitly list directories to avoid importing problematic modules
    # NOTE: tools/ directory is excluded (contains third-party code)
    
    local exit_code=0
    local tests_found=false
    
    # Define test locations (add more as colocated tests are created)
    # Pattern: minsar/<module>/tests/ for colocated tests
    local test_locations=(
        "tests"                    # Integration tests
        "minsar/utils/tests"       # Utils unit tests
        "minsar/objects/tests"     # Objects unit tests (when created)
    )
    
    for location in "${test_locations[@]}"; do
        if [[ -d "$SCRIPT_DIR/$location" ]]; then
            local test_files
            test_files=$(find "$SCRIPT_DIR/$location" -maxdepth 1 -name "test_*.py" 2>/dev/null | head -1)
            
            if [[ -n "$test_files" ]]; then
                tests_found=true
                echo ""
                echo -e "${BLUE}Running tests in: $location/${NC}"
                python -m unittest discover -s "$location" -p "test_*.py" $verbosity
                local result=$?
                if [[ $result -ne 0 ]]; then
                    exit_code=1
                fi
            fi
        fi
    done
    
    if ! $tests_found; then
        echo -e "${BLUE}No Python test files found${NC}"
        echo -e "${BLUE}Skipping Python tests.${NC}"
        return 0
    fi
    
    if [[ $exit_code -eq 0 ]]; then
        echo ""
        echo -e "${GREEN}✓ PYTHON TESTS PASSED${NC}"
    else
        echo ""
        echo -e "${RED}✗ PYTHON TESTS FAILED${NC}"
    fi
    
    return $exit_code
}

run_bash_tests() {
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  BASH TESTS${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    local bash_runner="$TESTS_DIR/run_bash_tests.bash"
    
    if [[ ! -f "$bash_runner" ]]; then
        echo -e "${RED}ERROR: Bash test runner not found: $bash_runner${NC}"
        return 1
    fi
    
    bash "$bash_runner"
    local exit_code=$?
    
    return $exit_code
}

print_final_summary() {
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║                        FINAL TEST SUMMARY                                ║${NC}"
    echo -e "${BOLD}╠══════════════════════════════════════════════════════════════════════════╣${NC}"
    
    if $RUN_PYTHON; then
        if [[ $PYTHON_RESULT -eq 0 ]]; then
            printf "${BOLD}║${NC}  Python tests:  ${GREEN}%-10s${NC}                                            ${BOLD}║${NC}\n" "PASSED"
        else
            printf "${BOLD}║${NC}  Python tests:  ${RED}%-10s${NC}                                            ${BOLD}║${NC}\n" "FAILED"
        fi
    else
        printf "${BOLD}║${NC}  Python tests:  ${BLUE}%-10s${NC}                                            ${BOLD}║${NC}\n" "SKIPPED"
    fi
    
    if $RUN_BASH; then
        if [[ $BASH_RESULT -eq 0 ]]; then
            printf "${BOLD}║${NC}  Bash tests:    ${GREEN}%-10s${NC}                                            ${BOLD}║${NC}\n" "PASSED"
        else
            printf "${BOLD}║${NC}  Bash tests:    ${RED}%-10s${NC}                                            ${BOLD}║${NC}\n" "FAILED"
        fi
    else
        printf "${BOLD}║${NC}  Bash tests:    ${BLUE}%-10s${NC}                                            ${BOLD}║${NC}\n" "SKIPPED"
    fi
    
    echo -e "${BOLD}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
    
    local total_result=$((PYTHON_RESULT + BASH_RESULT))
    
    echo ""
    if [[ $total_result -eq 0 ]]; then
        echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║                        ALL TESTS PASSED                                  ║${NC}"
        echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
        return 0
    else
        echo -e "${RED}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${RED}║                       SOME TESTS FAILED                                  ║${NC}"
        echo -e "${RED}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
        return 1
    fi
}

#######################################
# Main
#######################################

main() {
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --help|-h)
                show_help
                exit 0
                ;;
            --python-only)
                RUN_PYTHON=true
                RUN_BASH=false
                shift
                ;;
            --bash-only)
                RUN_PYTHON=false
                RUN_BASH=true
                shift
                ;;
            --verbose|-v)
                VERBOSE=true
                shift
                ;;
            *)
                echo "Unknown option: $1"
                echo "Use --help for usage information."
                exit 1
                ;;
        esac
    done
    
    print_banner
    
    # Run test suites
    if $RUN_PYTHON; then
        run_python_tests
        PYTHON_RESULT=$?
    fi
    
    if $RUN_BASH; then
        run_bash_tests
        BASH_RESULT=$?
    fi
    
    # Print summary and exit
    print_final_summary
}

main "$@"
