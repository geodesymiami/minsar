# Concise Code and Messages

Keep code comments and output messages concise and to the point.

## Messages
- Use short, clear messages without unnecessary explanations
- Avoid verbose instructions or suggestions in output
- Don't repeat information already obvious from context

### Examples

**Bad:**
```bash
echo "Output radar .he5 file already exists: $OUTPUT_FILE_ABS"
echo "Skipping conversion - use a different output name or delete existing file"
```

**Good:**
```bash
echo "Output file already exists: $OUTPUT_FILE_ABS"
```

**Bad:**
```bash
echo "Cleaning up temporary directory: $TEMP_DIR"
rm -rf "$TEMP_DIR"
echo "Temporary directory removed"
```

**Good:**
```bash
rm -rf "$TEMP_DIR"
```

## Comments
- Comments should explain "why", not "what" (code shows "what")
- Keep comments brief and focused
- Remove obvious comments

### Examples

**Bad:**
```bash
# Move extracted files to temp directory for processing
for geo_file in "${GEO_FILES[@]}"; do
    mv "$geo_file" "$TEMP_DIR/"
done
```

**Good:**
```bash
# Move to temp directory
for geo_file in "${GEO_FILES[@]}"; do
    mv "$geo_file" "$TEMP_DIR/"
done
```

**Bad:**
```bash
# Find all extracted geo_*.h5 files in the input directory
GEO_FILES=(geo_*.h5)
```

**Good:**
```bash
# Find extracted files
GEO_FILES=(geo_*.h5)
```

## Function Names and Variables
- Use clear, descriptive names that reduce need for comments
- Prefer self-documenting code over comments

## Temporary Files and Directories
- Create temporary directories in the working directory, not system /tmp
- Use pattern: `tmp_<purpose>_$$_${RANDOM}` for unique names
- Always use absolute paths to avoid issues when changing directories

### Example

**Bad:**
```bash
TEMP_DIR=$(mktemp -d -t myprocess_XXXXXX)  # Creates in /tmp
```

**Bad:**
```bash
TEMP_DIR="${WORK_DIR}/tmp_myprocess_$$_${RANDOM}"  # Relative path
mkdir -p "$TEMP_DIR"
```

**Good:**
```bash
TEMP_DIR="$(cd "$WORK_DIR" && pwd)/tmp_myprocess_$$_${RANDOM}"  # Absolute path
mkdir -p "$TEMP_DIR"
```
