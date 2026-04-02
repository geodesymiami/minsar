#!/usr/bin/env bash
# rename_mintpy_dir.bash

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    helptext="
Rename a mintpy/miaplpy directory and update references in upload.log and index.html files.

Usage:
    $SCRIPT_NAME <old_name> <new_name>    # Rename directory and update files
    $SCRIPT_NAME <new_name>               # Update files only (auto-detect old name)

Examples:
    $SCRIPT_NAME mintpy mintpy_test
    $SCRIPT_NAME mintpy_test mintpy_20_20_0.6
    $SCRIPT_NAME mintpy_25_25_0.5

Description:
    With two arguments:
        - Renames directory from old_name to new_name
        - Updates new_name/pic/upload.log and new_name/pic/index.html
    
    With one argument:
        - Detects current directory name from files
        - Updates <current_name>/pic/upload.log and<current_name>/pic/index.html

    "
    printf "%s" "$helptext"
    exit 0
fi

# Check arguments
if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Error: Invalid number of arguments"
    echo "Usage: $SCRIPT_NAME <old_name> <new_name>"
    echo "   or: $SCRIPT_NAME <new_name>"
    echo "Use --help for more information"
    exit 1
fi

WORK_DIR="$PWD"
RENAMED_DIR=false  # Track whether we actually renamed the directory

if [[ $# -eq 2 ]]; then
    # Two arguments: rename directory
    OLD_NAME="${1%/}"  # Strip trailing slash
    NEW_NAME="${2%/}"  # Strip trailing slash
    
    # Check if old directory exists
    if [[ ! -d "$OLD_NAME" ]]; then
        echo "Error: Directory '$OLD_NAME' does not exist"
        exit 1
    fi
    
    # Check if new directory already exists
    if [[ -d "$NEW_NAME" ]]; then
        echo "Error: Directory '$NEW_NAME' already exists"
        exit 1
    fi
    
    echo "Renaming directory: $OLD_NAME -> $NEW_NAME"
    mv "$OLD_NAME" "$NEW_NAME"
    RENAMED_DIR=true
    
    DIR_NAME="$NEW_NAME"
else
    # One argument: detect old name from files and update
    NEW_NAME="${1%/}"  # Strip trailing slash
    
    # Check if the directory already exists (already renamed manually)
    if [[ -d "$NEW_NAME" ]]; then
        echo "Directory '$NEW_NAME' already exists (already renamed)"
        echo "Will detect old name from files and update them"
        
        DIR_NAME="$NEW_NAME"
        OLD_NAME=""
        
        # Try to detect old name from upload.log
        UPLOAD_LOG="$DIR_NAME/pic/upload.log"
        if [[ -f "$UPLOAD_LOG" ]]; then
            # Extract directory name from URL in upload.log
            # URL format: http://.../project_name/dir_name/pic
            OLD_NAME=$(grep -o '/[^/]*/pic' "$UPLOAD_LOG" | head -1 | sed 's|/pic$||' | sed 's|^/||')
            if [[ -n "$OLD_NAME" && "$OLD_NAME" != "pic" ]]; then
                echo "Detected old name from upload.log: $OLD_NAME"
            else
                OLD_NAME=""
            fi
        fi
        
        # If not found in upload.log, try index.html
        if [[ -z "$OLD_NAME" ]]; then
            INDEX_HTML="$DIR_NAME/pic/index.html"
            if [[ -f "$INDEX_HTML" ]]; then
                # Extract from <h2>dir_name/pic</h2>
                OLD_NAME=$(grep -o '<h2>[^<]*</h2>' "$INDEX_HTML" | head -1 | sed 's|<h2>||' | sed 's|</h2>||' | sed 's|/pic||')
                if [[ -n "$OLD_NAME" ]]; then
                    echo "Detected old name from index.html: $OLD_NAME"
                fi
            fi
        fi
        
        if [[ -z "$OLD_NAME" ]]; then
            echo "Error: Could not detect old directory name from files"
            echo "Checked $DIR_NAME/pic/upload.log and $DIR_NAME/pic/index.html"
            exit 1
        fi
    else
        # Directory doesn't exist, try to find and rename it
        OLD_NAME=""
        
        # Look for directories that might be the old name
        for dir in */; do
            dir="${dir%/}"
            
            # Check if this directory has pic/upload.log or pic/index.html
            if [[ -f "$dir/pic/upload.log" ]] || [[ -f "$dir/pic/index.html" ]]; then
                OLD_NAME="$dir"
                break
            fi
        done
        
        if [[ -z "$OLD_NAME" ]]; then
            echo "Error: Could not auto-detect old directory name"
            echo "No directory with pic/upload.log or pic/index.html found"
            exit 1
        fi
        
        echo "Auto-detected old directory name: $OLD_NAME"
        echo "Renaming directory: $OLD_NAME -> $NEW_NAME"
        mv "$OLD_NAME" "$NEW_NAME"
        RENAMED_DIR=true
        
        DIR_NAME="$NEW_NAME"
    fi
fi

echo ""
echo "Updating files in $DIR_NAME/pic/"

# Update upload.log if it exists
UPLOAD_LOG="$DIR_NAME/pic/upload.log"
if [[ -f "$UPLOAD_LOG" ]]; then
    echo "Updating $UPLOAD_LOG"
    
    # Read the current content
    OLD_CONTENT=$(cat "$UPLOAD_LOG")
    
    # Replace old directory name with new name in the URL
    # Handle both cases: with or without trailing slash
    NEW_CONTENT=$(echo "$OLD_CONTENT" | sed "s|/${OLD_NAME}/|/${NEW_NAME}/|g")
    
    # Write back
    echo "$NEW_CONTENT" > "$UPLOAD_LOG"
    
    echo "  Updated URL: $NEW_CONTENT"
else
    echo "Warning: $UPLOAD_LOG not found, skipping"
fi

# Update index.html if it exists
INDEX_HTML="$DIR_NAME/pic/index.html"
if [[ -f "$INDEX_HTML" ]]; then
    echo "Updating $INDEX_HTML"
    
    # Replace the header line: <h2>old_name/pic</h2> -> <h2>new_name/pic</h2>
    sed -i.bak "s|<h2>${OLD_NAME}/pic</h2>|<h2>${NEW_NAME}/pic</h2>|g" "$INDEX_HTML"
    
    # Also update any other references to the old directory name
    sed -i.bak "s|>${OLD_NAME}/pic<|>${NEW_NAME}/pic<|g" "$INDEX_HTML"
    
    # Remove backup file
    rm -f "${INDEX_HTML}.bak"
    
    echo "  Updated header: <h2>${NEW_NAME}/pic</h2>"
else
    echo "Warning: $INDEX_HTML not found, skipping"
fi

echo ""
if [[ "$RENAMED_DIR" = true ]]; then
    echo "Done! Directory renamed to: $DIR_NAME"
else
    echo "Done! Files updated in: $DIR_NAME"
fi
echo "Updated files:"
[[ -f "$UPLOAD_LOG" ]] && echo " $UPLOAD_LOG"
[[ -f "$INDEX_HTML" ]] && echo " $INDEX_HTML"

