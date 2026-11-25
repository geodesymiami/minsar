---
paths:
  - "tests/**"
  - "**/tests/**"
  - "**/test_*.py"
  - "**/test_*.bash"
---

# Tests

Conventions for existing tests. Do not create or extend tests unless explicitly asked (see `CLAUDE.md`). Full details, templates and assertion tables are in `.cursor/rules/testing.mdc`.

- Python tests use `unittest`. Bash tests source `tests/test_helpers.bash` (`assert_equals`, `assert_contains`, `assert_not_contains`, `assert_file_exists`, `assert_exit_code`, `setup_test_workspace`, `teardown_test_workspace`, `create_mock_run_files`).
- Unit tests are colocated in `<module>/tests/` (with `__init__.py`); integration and Bash workflow tests are in top-level `tests/`.
- New Python test directories are registered in the `test_locations` array of `run_all_tests.bash`; new Bash suites in the `TEST_SUITES` array of `tests/run_bash_tests.bash`.
- Tests must run on both macOS and Linux (see `.claude/rules/bash.md`).
- When asked for tests, cover what can break (error paths, edge cases, parsing, state transitions, integration points), not trivial getters, pass-throughs or one-liners.
- Tests run in CircleCI and must pass before merging.
