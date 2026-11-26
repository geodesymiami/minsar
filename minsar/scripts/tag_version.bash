#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TESTED_VERSIONS_REL="setup/tested_versions.cfg"

show_help() {
    cat <<EOF
usage: $SCRIPT_NAME [-h] [--dry-run] {major|minor|patch|X.Y.Z} MESSAGE

Creates the next annotated version tag on main. Records the installed dependency
versions in $TESTED_VERSIONS_REL and commits that file first if it changed.
Requires a clean tree on main that matches origin/main. Does not push.
Rules for when to tag: docs/README_versioning.md

options:
  -h, --help     show this help
  --dry-run      print what would be done

Examples:
  $SCRIPT_NAME minor "support of WHIRLWIND for ISCE2"
  $SCRIPT_NAME patch "MintPy updated to v1.6.4-9-gabc1234"
  $SCRIPT_NAME 0.5.0 "first tagged version"
  $SCRIPT_NAME --dry-run minor "test"
EOF
}

dry_run=0
POSITIONAL=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) show_help; exit 0 ;;
        --dry-run) dry_run=1; shift ;;
        -?*)
            echo "Error: Unknown option: $1"
            echo "Use $SCRIPT_NAME --help for available options"
            exit 1
            ;;
        *) POSITIONAL+=("$1"); shift ;;
    esac
done

if [[ ${#POSITIONAL[@]} -ne 2 || -z "${POSITIONAL[1]}" ]]; then
    echo "Error: expected {major|minor|patch|X.Y.Z} and MESSAGE"
    echo "Use $SCRIPT_NAME --help for available options"
    exit 1
fi
bump="${POSITIONAL[0]}"
message="${POSITIONAL[1]}"

cd "$REPO_ROOT"

refuse() {
    echo "Error: $1"
    [[ "$dry_run" == "1" ]] || exit 1
}

branch=$(git rev-parse --abbrev-ref HEAD)
[[ "$branch" == "main" ]] || refuse "not on main (on $branch)"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || refuse "working tree has uncommitted changes"
git fetch --quiet origin main
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || refuse "HEAD differs from origin/main (push or pull first)"

latest_tag=$(git tag -l 'v[0-9]*' --sort=-v:refname | head -1)
if [[ "$bump" =~ ^v?([0-9]+\.[0-9]+\.[0-9]+)$ ]]; then
    new_tag="v${BASH_REMATCH[1]}"
elif [[ "$bump" =~ ^(major|minor|patch)$ ]]; then
    if [[ -z "$latest_tag" ]]; then
        echo "Error: no version tag exists yet, give the first one as X.Y.Z"
        exit 1
    fi
    IFS=. read -r major minor patch <<< "${latest_tag#v}"
    case "$bump" in
        major) new_tag="v$((major + 1)).0.0" ;;
        minor) new_tag="v${major}.$((minor + 1)).0" ;;
        patch) new_tag="v${major}.${minor}.$((patch + 1))" ;;
    esac
else
    echo "Error: expected major, minor, patch or X.Y.Z, got: $bump"
    exit 1
fi

if git rev-parse -q --verify "refs/tags/${new_tag}" >/dev/null; then
    echo "Error: tag ${new_tag} already exists"
    exit 1
fi

echo "${latest_tag:-no tag} -> ${new_tag}: ${message}"

new_tested_versions=$("${SCRIPT_DIR}/minsar_version.bash" --components)
if [[ "$dry_run" == "1" ]]; then
    if [[ ! -f "$TESTED_VERSIONS_REL" ]] || ! diff -q <(echo "$new_tested_versions") "$TESTED_VERSIONS_REL" >/dev/null; then
        echo "$TESTED_VERSIONS_REL would change:"
        diff <(cat "$TESTED_VERSIONS_REL" 2>/dev/null) <(echo "$new_tested_versions") || true
    fi
    exit 0
fi

echo "$new_tested_versions" > "$TESTED_VERSIONS_REL"
git add "$TESTED_VERSIONS_REL"
if ! git diff --cached --quiet -- "$TESTED_VERSIONS_REL"; then
    git commit --quiet -m "tested_versions.cfg: dependency versions for ${new_tag}" -- "$TESTED_VERSIONS_REL"
fi
git tag -a "$new_tag" -m "$message"

echo "git push origin main ${new_tag}"
