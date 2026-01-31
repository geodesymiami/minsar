# Development Guide

This guide covers development workflows, coding conventions, and testing practices for MinSAR.

## Development Environment Setup

### Prerequisites

1. Access to an HPC cluster with SLURM (Stampede2/3, Frontera)
2. Conda environment with Python 3.8+
3. Git for version control

### Initial Setup

```bash
# Clone the repository
git clone https://github.com/geodesymiami/rsmas_insar.git
cd rsmas_insar

# Source the environment
cd setup
source platforms_defaults.bash
source environment.bash
cd ..

# Add to PATH
export PATH=$MINSAR_HOME/minsar/bin:$PATH
export PATH=$ISCE_STACK/topsStack:$PATH
```

### Environment Variables

Key variables that must be set:

```bash
export MINSAR_HOME=/path/to/minsar
export RSMASINSAR_HOME=$MINSAR_HOME  # Alias
export SCRATCHDIR=/scratch/user
export TEMPLATES=$HOME/Templates
export SAMPLESDIR=$MINSAR_HOME/samples
```

## Code Organization Principles

### Bash vs Python

| Use Bash for | Use Python for |
|--------------|----------------|
| Job orchestration | Data processing |
| SLURM interaction | Template parsing |
| Environment setup | Complex logic |
| File operations | Validation |

### Script Categories

1. **Entry Points** (`minsar/bin/`): User-facing scripts with help text
2. **Libraries** (`minsar/lib/`): Sourced utilities, no direct execution
3. **Helpers** (`minsar/scripts/`): Called by entry points
4. **Utilities** (`minsar/utils/`): Standalone tools

## Coding Conventions

### Bash Scripts

```bash
#!/usr/bin/env bash
set -eo pipefail  # Exit on error, pipe failure

# Source shared libraries
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/workflow_utils.sh"

# Help text for all user-facing scripts
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    helptext="
    Description of script
    
    usage: script.bash [OPTIONS]
    
    Examples:
        script.bash --option value
    "
    echo -e "$helptext"
    exit 0
fi

# Parse arguments with while loop + case
while [[ $# -gt 0 ]]; do
    case $key in
        --option)
            value="$2"
            shift 2
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
    esac
done
```

**Conventions**:
- Use `[[ ]]` for conditionals (not `[ ]`)
- Quote variables: `"$var"` not `$var`
- Use `$(command)` not backticks
- Check exit status explicitly when needed

### Python Scripts

```python
#!/usr/bin/env python3
"""
Module docstring explaining purpose.
"""

import argparse
from pathlib import Path

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Script description')
    parser.add_argument('template_file', help='Path to template file')
    parser.add_argument('--option', default='value', help='Option description')
    args = parser.parse_args()
    
    # Implementation
    
if __name__ == '__main__':
    main()
```

**Conventions**:
- Use `argparse` for CLI arguments
- Use `pathlib.Path` for file paths
- Include docstrings for modules and functions
- Type hints encouraged for new code

## Adding New Features

### Adding a New Processing Step

1. **Create the job file generator** (`minsar/scripts/create_<step>_jobfile.py`)
2. **Register in minsarApp.bash** (add flag and execution block)
3. **Add to job_defaults.cfg** (walltime, memory settings)
4. **Update documentation**

### Adding a New CLI Command

1. Create module in `minsar/src/minsar/cli/`
2. Add to `minsar/workflow/__init__.py` if needed
3. Create entry point in `minsar/bin/` or call directly

### Adding a New Utility Function

For bash utilities:
```bash
# Add to minsar/lib/workflow_utils.sh
function my_function() {
    local arg1="$1"
    # Implementation
    echo "$result"
}
```

For Python utilities:
```python
# Add to minsar/objects/ or minsar/utils/
def my_function(arg1):
    """Function description."""
    return result
```

## Testing

MinSAR uses a unified testing framework that supports both Python (unittest) and Bash tests.

### Test Organization (Hybrid Approach)

**Prefer colocated tests** in a `tests/` subdirectory next to the code:

```
minsar/
├── run_all_tests.bash              # Top-level unified test runner
├── tests/                          # Integration tests & Bash tests
│   ├── __init__.py
│   ├── run_bash_tests.bash         # Bash test orchestrator
│   ├── test_helpers.bash           # Shared Bash utilities
│   ├── test_run_workflow.bash      # Workflow tests
│   ├── test_submit_jobs.bash
│   └── test_sbatch_conditional.bash
├── minsar/
│   └── utils/
│       ├── system_utils.py
│       └── tests/                  # Colocated unit tests
│           ├── __init__.py
│           └── test_system_utils.py
```

| Test Type | Where to Put It |
|-----------|-----------------|
| Unit tests for a module | `minsar/<module>/tests/test_foo.py` |
| Integration/end-to-end tests | `tests/` directory |
| Bash workflow tests | `tests/` directory |

### Running Tests

```bash
# Run ALL tests (Python + Bash) - recommended
./run_all_tests.bash

# Run only Python tests
./run_all_tests.bash --python-only

# Run only Bash tests
./run_all_tests.bash --bash-only

# Run with verbose output
./run_all_tests.bash -v
```

### Running Individual Test Suites

```bash
# Run specific Bash test suite
bash tests/run_bash_tests.bash test_run_workflow.bash

# Run specific Python test file (colocated)
python -m unittest minsar.utils.tests.test_system_utils -v

# Run specific Python test file (centralized)
python -m unittest tests.test_utils -v

# Discover and run all Python tests
python -m unittest discover -s . -p "test_*.py" -v
```

### Writing Bash Tests

Test file structure (`tests/test_*.bash`):

```bash
#!/usr/bin/env bash

# Source test helpers
source "$(dirname "$0")/test_helpers.bash"

test_my_feature() {
    echo -e "\n${YELLOW}Test: My Feature${NC}"
    
    setup_test_workspace
    
    # Test logic
    result=$(my_function "input")
    
    assert_equals "expected" "$result" "Feature should return expected"
    assert_file_exists "$path" "File should be created"
    
    teardown_test_workspace
}

# Run tests
test_my_feature
```

### Writing Python Tests

Test file structure (`tests/test_*.py`):

```python
#!/usr/bin/env python3
"""Unit tests for module."""
import unittest

class TestMyFeature(unittest.TestCase):
    """Tests for my_feature function."""
    
    def test_basic_functionality(self):
        """Test basic case."""
        result = my_function("input")
        self.assertEqual(result, "expected")
    
    def test_edge_case(self):
        """Test edge case."""
        with self.assertRaises(ValueError):
            my_function(None)

if __name__ == '__main__':
    unittest.main()
```

### Test Utilities (Bash)

| Function | Purpose |
|----------|---------|
| `setup_test_workspace` | Create temp directory |
| `teardown_test_workspace` | Clean up temp directory |
| `create_mock_run_files DIR N` | Create N mock job files |
| `assert_equals EXPECTED ACTUAL MSG` | Exact match assertion |
| `assert_contains HAYSTACK NEEDLE MSG` | Substring assertion |
| `assert_file_exists PATH MSG` | File existence check |
| `assert_exit_code EXPECTED ACTUAL MSG` | Exit code check |

### Test Utilities (Python)

| Method | Purpose |
|--------|---------|
| `self.assertEqual(a, b)` | Exact match |
| `self.assertIn(item, list)` | Membership check |
| `self.assertTrue(expr)` | Boolean check |
| `self.assertIsInstance(obj, cls)` | Type check |
| `self.assertRaises(Error)` | Exception check |

### CI/CD Integration

Tests are automatically run in CircleCI on every push. The unified test runner (`run_all_tests.bash`) is called during the CI pipeline.

### Adding New Python Tests (Colocated)

To add unit tests for a module like `minsar/objects/auto_defaults.py`:

```bash
# 1. Create the tests directory
mkdir -p minsar/objects/tests

# 2. Add __init__.py to make it a package
echo "# Tests for minsar/objects" > minsar/objects/tests/__init__.py

# 3. Create the test file
cat > minsar/objects/tests/test_auto_defaults.py << 'EOF'
#!/usr/bin/env python3
"""Unit tests for minsar/objects/auto_defaults.py"""
import unittest
from minsar.objects.auto_defaults import PathFind

class TestPathFind(unittest.TestCase):
    """Tests for PathFind class."""
    
    def test_pathfind_instantiation(self):
        """PathFind should instantiate without errors."""
        pf = PathFind()
        self.assertIsNotNone(pf)

if __name__ == '__main__':
    unittest.main()
EOF

# 4. Register the directory in run_all_tests.bash
# Edit the test_locations array to include "minsar/objects/tests"
```

### Adding New Bash Tests

To add a new Bash test suite:

```bash
# 1. Create the test file
cat > tests/test_my_feature.bash << 'EOF'
#!/usr/bin/env bash
source "$(dirname "$0")/test_helpers.bash"

test_my_feature() {
    print_test_start "My Feature" "Tests the my_feature functionality"
    
    setup_test_workspace
    
    # Your test logic here
    result=$(some_function "input")
    
    assert_equals "expected" "$result" "Should return expected value"
    
    teardown_test_workspace
    print_test_end "My Feature"
}

# Run tests
test_my_feature
print_summary
EOF

# 2. Register in tests/run_bash_tests.bash
# Add "test_my_feature.bash" to the TEST_SUITES array
```

## Debugging

### Common Debug Techniques

```bash
# Enable verbose output
set -x

# Check variable values
echo "DEBUG: var=$var"

# Check script flow
echo "DEBUG: reached checkpoint 1"

# Test sbatch without submitting
sbatch --test-only job.job

# Check job status
sacct -j <jobid> --format=JobID,State,ExitCode
```

### Log Files

| Log | Location | Purpose |
|-----|----------|---------|
| Main log | `$WORKDIR/log` | High-level command history |
| Workflow log | `$WORKDIR/workflow.N.log` | Detailed job monitoring |
| Job stdout | `run_files/*.o` | Job output |
| Job stderr | `run_files/*.e` | Job errors |
| Rerun log | `run_files/rerun.log` | Resubmitted jobs |

### Debugging Job Failures

1. Check job state: `sacct -j <jobid>`
2. Check stderr: `cat run_files/run_XX_step_N.e`
3. Check stdout: `cat run_files/run_XX_step_N.o`
4. Check job file: `cat run_files/run_XX_step_N.job`

## Common Modifications

### Changing Default Walltime

Edit `minsar/defaults/job_defaults.cfg`:
```
step_name    c_walltime  s_walltime  seconds_factor  ...
unwrap       00:10:00    00:02:00    0               ...
```

### Adding a New Platform

1. Add to `setup/platforms_defaults.bash`
2. Add queue info to `minsar/defaults/queues.cfg`
3. Update `install_minsar.bash` if needed

### Modifying Job Resource Limits

Edit `minsar/defaults/queues.cfg`:
```
PLATFORM   QUEUENAME  ...  MAX_JOBS  STEP_MAX_TASKS  TOTAL_MAX_TASKS
stampede3  skx        ...  5         500             150
```

## Git Workflow

### Branches

- `master`: Stable release branch
- `temp`: Development/testing branch
- Feature branches: `feature/description`

### Commit Messages

```
Short summary (50 chars or less)

Longer description if needed. Explain the why, not the what.
The code shows what changed, the message explains why.

- Bullet points for multiple changes
- Reference issues if applicable: Fixes #123
```

### Before Committing

1. Run relevant tests
2. Check for debug statements
3. Update documentation if needed
4. Verify no sensitive data (credentials, paths)

## Performance Considerations

### Job Submission

- Don't submit too many jobs at once (check `SJOBS_MAX_JOBS_PER_QUEUE`)
- Use appropriate walltime (check historical run times)
- Consider IO load for parallel tasks

### File System

- Use `$SCRATCH` for processing (faster IO)
- Avoid small file operations in parallel
- Clean up intermediate files when possible

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| "jobfile not found" | Check RUNFILES_DIR path |
| "template file required" | MiaplPy needs template argument |
| Job stuck in PENDING | Check queue limits, node availability |
| TIMEOUT | Increase walltime in job_defaults.cfg |
| Out of memory | Increase memory in job file or defaults |

### Getting Help

1. Check the error message carefully
2. Look in the appropriate log file
3. Search existing issues on GitHub
4. Check the documentation in `docs/`
