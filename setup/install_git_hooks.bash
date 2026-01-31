#!/usr/bin/env bash
#
# Install git hooks for the minsar project
#
# This configures Git to use the hooks in setup/hooks/ directory
# instead of the default .git/hooks/ directory.
#
# Usage: bash setup/install_git_hooks.bash
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOKS_DIR="$REPO_ROOT/setup/hooks"

echo "Installing git hooks..."
echo "  Hooks directory: $HOOKS_DIR"

# Configure git to use our hooks directory
git -C "$REPO_ROOT" config core.hooksPath setup/hooks

echo ""
echo "Git hooks installed successfully!"
echo ""
echo "The following hooks are now active:"
for hook in "$HOOKS_DIR"/*; do
    if [[ -x "$hook" && -f "$hook" ]]; then
        echo "  - $(basename "$hook")"
    fi
done
echo ""
echo "To disable hooks, run: git config --unset core.hooksPath"
echo ""
