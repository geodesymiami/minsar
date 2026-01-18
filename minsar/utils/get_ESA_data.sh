#!/usr/bin/env bash
set -euo pipefail

# get_ESA_data.sh
# Bulk-download ESA ERS/Envisat SAR products from esar-ds.eo.esa.int using a cookies.txt file.
#
# Key behavior:
# - Uses cookies for authentication (SAML/Shibboleth).
# - Handles ESA "ProductDownloadResponse ACCEPTED / RetryAfter" by polling.
# - Resumes partial downloads.
# - Runs in parallel (default: 6 granules).

PROG="$(basename "$0")"

usage() {
  cat <<'EOF'
get_ESA_data.sh — download ESA ERS/Envisat SAR data from esar-ds.eo.esa.int

Usage:
  get_ESA_data.sh <urls.txt|URL> [--cookies FILE] [--outdir DIR] [--parallel N] [--max-wait SECONDS] [--poll-max N]
  get_ESA_data.sh --help

Arguments:
  urls.txt or URL    Either a file containing URLs (one per line) or a single URL for quick testing

Examples:
  get_ESA_data.sh urls.txt                                  # Uses ~/cookies-esa-int.txt by default
  get_ESA_data.sh urls.txt --cookies /path/to/cookies.txt   # Use custom cookies file
  get_ESA_data.sh urls.txt --outdir SLC --parallel 3        # Try 3 parallel downloads
  get_ESA_data.sh https://esar-ds.eo.esa.int/oads/data/ASA_IMS_1P/ASA_IMS_1PNESA20100225_155310_000000152087_00140_41777_0000.N1

Options:
  --cookies FILE     Cookies file in Netscape format (default: ~/cookies-esa-int.txt)
  --outdir DIR       Output directory (default: .)
  --parallel N       Number of parallel downloads (default: 2, ESA typically allows 1-2)
  --poll-max N       Max polling attempts per URL before giving up (default: 200)
  --max-wait SECONDS Cap any single RetryAfter wait to this many seconds (default: 1800)

Authentication:
  ESA uses EO Sign In (SAML/Shibboleth). Export cookies from Firefox using "Export Cookies" extension:
    https://addons.mozilla.org/firefox/addon/export-cookies-txt/
  1. Log in at https://esar-ds.eo.esa.int/oads/access/collection/ASA_IMS_1P 
  2. Start any download to create session cookie (e.g. https://esar-ds.eo.esa.int/oads/data/ASA_IMS_1P/ASA_IMS_1PNESA20100225_155310_000000152087_00140_41777_0000.N1)
  3. Click on "puzzle" icon right of addressbar, select "Export Cookies" and save to ~/cookies-esa-int.txt
  4. Make it read-only to protect: chmod 444 ~/cookies-esa-int.txt

Verify cookies:
  Check that your cookies file contains the required Shibboleth session:
    grep -i '_shibsession_' ~/cookies-esa-int.txt
  You should see a line with "esar-ds.eo.esa.int" and "_shibsession_" in it.
  If missing, re-login and export cookies again.

Getting the list of URLs:
  1. Go to https://esar-ds.eo.esa.int/socat/ASA_IMS_1P
  2. Run geographic search with date range
  3. Click "bulk download lists" and save as HTML
  4. Extract URLs: grep -oE 'https://esar-ds\.eo\.esa\.int/oads/data/[^" <]+' bulk.html | sort -u > urls.txt

Notes:
  - Cookies expire. Re-export and rerun; downloads will resume.
  - Already-downloaded files (>1MB) are skipped.
  - The original cookies file is NOT modified (script makes working copies per download job).
  - Downloaded files are validated to ensure they contain SAR data and not HTML error pages.
  - Invalid HTML files are automatically deleted and download will be retried.

EOF
}

cookies_file="$HOME/cookies-esa-int.txt"
outdir="."
parallel=2
poll_max=200
max_wait=1800
urls_file=""
urls_input=""
temp_urls_file=""
wrapper_script=""

die() { echo "[ERROR] $*" >&2; exit 2; }

cleanup() {
  if [[ -n "$temp_urls_file" && -f "$temp_urls_file" ]]; then
    rm -f "$temp_urls_file"
  fi
  if [[ -n "$wrapper_script" && -f "$wrapper_script" ]]; then
    rm -f "$wrapper_script"
  fi
}
trap cleanup EXIT

# --- Parse args ---
if [[ $# -eq 0 ]]; then
  usage; exit 1
fi

# Check for help first, even if not first argument
for arg in "$@"; do
  if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
    usage; exit 0
  fi
done

# Parse options first to find URLs file/URL
while [[ $# -gt 0 ]]; do
  case "$1" in
    --cookies) cookies_file="$2"; shift 2 ;;
    --outdir) outdir="$2"; shift 2 ;;
    --parallel) parallel="$2"; shift 2 ;;
    --poll-max) poll_max="$2"; shift 2 ;;
    --max-wait) max_wait="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *)
      # This should be the URLs file or URL
      if [[ -z "$urls_input" ]]; then
        urls_input="$1"
        shift
      else
        die "Unexpected argument: $1 (use --help)" 
      fi
      ;;
  esac
done

[[ -z "$urls_input" ]] && die "URLs file or URL is required. Use --help for usage."

# Check if input is a URL or a file
if [[ "$urls_input" =~ ^https?:// ]]; then
  # It's a URL - create temporary file
  temp_urls_file="$(mktemp)"
  echo "$urls_input" > "$temp_urls_file"
  urls_file="$temp_urls_file"
  echo "[INFO] Testing single URL: $urls_input"
elif [[ -f "$urls_input" ]]; then
  # It's a file
  urls_file="$urls_input"
else
  die "Input is neither a valid file nor a URL: $urls_input"
fi

mkdir -p "$outdir"

# --- Helper function ---
download_one() {
  local url="$1"
  local cookie="$2"
  local outdir="$3"
  local poll_max="$4"
  local max_wait="$5"

  local out="$outdir/$(basename "$url")"
  
  # Create a per-process cookie file to avoid race conditions in parallel downloads
  # This allows curl to update session cookies without conflicts
  local cookie_copy="$(mktemp)"
  cp "$cookie" "$cookie_copy"
  trap "rm -f '$cookie_copy'" RETURN

  # Check if file exists and determine if complete
  if [[ -f "$out" ]]; then
    local sz
    sz=$(wc -c < "$out" | tr -d ' ')
    
    # If very small (< 1MB), likely error response - retry
    if [[ "$sz" -lt 1000000 ]]; then
      echo "[INFO] $(basename "$out") is small ($sz bytes), will retry"
    else
      # File exists and is large - check if it needs resuming
      # Try a range request to see if server accepts resume
      local tmp_header="$(mktemp)"
      if curl -sI -b "$cookie_copy" -c "$cookie_copy" -r "${sz}-" --max-time 30 "$url" -o "$tmp_header" 2>/dev/null; then
        # Check if server returns 206 (partial content) or 416 (range not satisfiable = complete)
        if grep -q "HTTP/[0-9.]\+ 416" "$tmp_header"; then
          echo "[SKIP] $(basename "$out") already complete (${sz} bytes)"
          rm -f "$tmp_header"
          return 0
        elif grep -q "HTTP/[0-9.]\+ 206" "$tmp_header"; then
          echo "[RESUME] $(basename "$out") incomplete at ${sz} bytes, resuming..."
        fi
      fi
      rm -f "$tmp_header"
    fi
  fi

  local attempt=0
  while (( attempt < poll_max )); do
    attempt=$((attempt+1))

    # Fetch first 2KB to detect "ACCEPTED/RetryAfter" XML without downloading the whole file.
    local tmp
    tmp="$(mktemp)"
    curl -sL -b "$cookie_copy" -c "$cookie_copy" -r 0-2047 --max-time 60 "$url" -o "$tmp" || true

    if grep -q "<ProductDownloadResponse" "$tmp"; then
      local wait_s
      wait_s=$(sed -n 's/.*<RetryAfter>\([0-9]\+\)<\/RetryAfter>.*/\1/p' "$tmp" | head -n1 || true)
      [[ -z "${wait_s:-}" ]] && wait_s=300
      # Cap wait to avoid absurd sleeps
      if (( wait_s > max_wait )); then wait_s="$max_wait"; fi
      echo "[WAIT] $(basename "$out") attempt $attempt/$poll_max RetryAfter=${wait_s}s"
      rm -f "$tmp"
      sleep "$wait_s"
      continue
    fi

    # If it looks like HTML, auth is broken or expired.
    if head -c 200 "$tmp" | grep -qi "<html"; then
      rm -f "$tmp"
      die "Got HTML (likely login page) for: $url
Cookie likely expired or missing _shibsession_... for esar-ds.eo.esa.int"
    fi

    rm -f "$tmp"
    echo "[DL]  $(basename "$out") attempt $attempt/$poll_max"
    # Now do the full download with resume
    # Timeout options: --max-time prevents infinite hangs, --speed-limit/--speed-time aborts if too slow
    if ! curl -L -C - -b "$cookie_copy" -c "$cookie_copy" \
         --max-time 7200 \
         --speed-limit 1000 --speed-time 300 \
         --retry 3 --retry-delay 5 --retry-max-time 600 \
         -o "$out" "$url"; then
      echo "[WARN] curl failed or timed out, will retry..."
      sleep 10
      continue
    fi
    # Basic sanity: if still tiny, keep polling
    local sz
    sz=$(wc -c < "$out" | tr -d ' ')
    if [[ "$sz" -lt 1000000 ]]; then
      echo "[WARN] Downloaded only ${sz} bytes (too small). Will retry."
      sleep 5
      continue
    fi
    
    # Validate that file contains SAR data and not HTML
    local first_line
    first_line=$(head -n 1 "$out" 2>/dev/null || echo "")
    if [[ "$first_line" =~ ^[[:space:]]*\<\!DOCTYPE[[:space:]]+html ]] || [[ "$first_line" =~ ^[[:space:]]*\<html ]]; then
      echo "[ERROR] Downloaded file contains HTML instead of SAR data: $(basename "$out")"
      rm -f "$out"
      echo "[WARN] Removed invalid HTML file, will retry..."
      sleep 10
      continue
    fi
    
    return 0
  done

  die "Exceeded poll-max=$poll_max for URL: $url"
}

# --- Validate cookies ---
[[ -f "$cookies_file" ]] || die "Cookies file not found: $cookies_file"

echo "[INFO] Checking cookies file: $cookies_file"
if ! egrep -qi 'esar-ds\.eo\.esa\.int.*_shibsession_|_shibsession_' "$cookies_file"; then
  echo "[ERROR] Could not find _shibsession_... in $cookies_file"
  echo "        Your cookies file is missing the required Shibboleth session."
  echo ""
  echo "To verify your cookies, run:"
  echo "  grep -i '_shibsession_' $cookies_file"
  echo ""
  echo "If the session is missing or expired, please:"
  echo "  1. Log in at https://esar-ds.eo.esa.int/oads/access/collection/ASA_IMS_1P"
  echo "  2. Start a download to create the session cookie"
  echo "  3. Export cookies using the Firefox 'Export Cookies' extension"
  echo ""
  die "Invalid or expired cookies file"
fi
echo "[INFO] Found valid Shibboleth session in cookies file"

# --- Download URLs in parallel ---
# Create a temporary wrapper script for parallel execution
wrapper_script="$(mktemp)"
cat > "$wrapper_script" << 'WRAPPER_EOF'
#!/bin/bash
set -euo pipefail

die() { echo "[ERROR] $*" >&2; exit 2; }

download_one() {
  local url="$1"
  local cookie="$2"
  local outdir="$3"
  local poll_max="$4"
  local max_wait="$5"

  local out="$outdir/$(basename "$url")"
  
  # Create a per-process cookie file to avoid race conditions in parallel downloads
  # This allows curl to update session cookies without conflicts
  local cookie_copy="$(mktemp)"
  cp "$cookie" "$cookie_copy"
  trap "rm -f '$cookie_copy'" RETURN

  # Check if file exists and determine if complete
  if [[ -f "$out" ]]; then
    local sz
    sz=$(wc -c < "$out" | tr -d ' ')
    
    # If very small (< 1MB), likely error response - retry
    if [[ "$sz" -lt 1000000 ]]; then
      echo "[INFO] $(basename "$out") is small ($sz bytes), will retry"
    else
      # File exists and is large - check if it needs resuming
      # Try a range request to see if server accepts resume
      local tmp_header="$(mktemp)"
      if curl -sI -b "$cookie_copy" -c "$cookie_copy" -r "${sz}-" --max-time 30 "$url" -o "$tmp_header" 2>/dev/null; then
        # Check if server returns 206 (partial content) or 416 (range not satisfiable = complete)
        if grep -q "HTTP/[0-9.]\+ 416" "$tmp_header"; then
          echo "[SKIP] $(basename "$out") already complete (${sz} bytes)"
          rm -f "$tmp_header"
          return 0
        elif grep -q "HTTP/[0-9.]\+ 206" "$tmp_header"; then
          echo "[RESUME] $(basename "$out") incomplete at ${sz} bytes, resuming..."
        fi
      fi
      rm -f "$tmp_header"
    fi
  fi

  local attempt=0
  while (( attempt < poll_max )); do
    attempt=$((attempt+1))

    # Fetch first 2KB to detect "ACCEPTED/RetryAfter" XML without downloading the whole file.
    local tmp
    tmp="$(mktemp)"
    curl -sL -b "$cookie_copy" -c "$cookie_copy" -r 0-2047 --max-time 60 "$url" -o "$tmp" || true

    if grep -q "<ProductDownloadResponse" "$tmp"; then
      local wait_s
      wait_s=$(sed -n 's/.*<RetryAfter>\([0-9]\+\)<\/RetryAfter>.*/\1/p' "$tmp" | head -n1 || true)
      [[ -z "${wait_s:-}" ]] && wait_s=300
      # Cap wait to avoid absurd sleeps
      if (( wait_s > max_wait )); then wait_s="$max_wait"; fi
      echo "[WAIT] $(basename "$out") attempt $attempt/$poll_max RetryAfter=${wait_s}s"
      rm -f "$tmp"
      sleep "$wait_s"
      continue
    fi

    # If it looks like HTML, auth is broken or expired.
    if head -c 200 "$tmp" | grep -qi "<html"; then
      rm -f "$tmp"
      die "Got HTML (likely login page) for: $url
Cookie likely expired or missing _shibsession_... for esar-ds.eo.esa.int"
    fi

    rm -f "$tmp"
    echo "[DL]  $(basename "$out") attempt $attempt/$poll_max"
    # Now do the full download with resume
    # Timeout options: --max-time prevents infinite hangs, --speed-limit/--speed-time aborts if too slow
    if ! curl -L -C - -b "$cookie_copy" -c "$cookie_copy" \
         --max-time 7200 \
         --speed-limit 1000 --speed-time 300 \
         --retry 3 --retry-delay 5 --retry-max-time 600 \
         -o "$out" "$url"; then
      echo "[WARN] curl failed or timed out, will retry..."
      sleep 10
      continue
    fi
    # Basic sanity: if still tiny, keep polling
    local sz
    sz=$(wc -c < "$out" | tr -d ' ')
    if [[ "$sz" -lt 1000000 ]]; then
      echo "[WARN] Downloaded only ${sz} bytes (too small). Will retry."
      sleep 5
      continue
    fi
    
    # Validate that file contains SAR data and not HTML
    local first_line
    first_line=$(head -n 1 "$out" 2>/dev/null || echo "")
    if [[ "$first_line" =~ ^[[:space:]]*\<\!DOCTYPE[[:space:]]+html ]] || [[ "$first_line" =~ ^[[:space:]]*\<html ]]; then
      echo "[ERROR] Downloaded file contains HTML instead of SAR data: $(basename "$out")"
      rm -f "$out"
      echo "[WARN] Removed invalid HTML file, will retry..."
      sleep 10
      continue
    fi
    
    return 0
  done

  die "Exceeded poll-max=$poll_max for URL: $url"
}

# xargs passes: cookies_file outdir poll_max max_wait URL
# download_one expects: url cookie outdir poll_max max_wait
# Reorder arguments: URL is $5, cookies_file is $1
download_one "$5" "$1" "$2" "$3" "$4"
WRAPPER_EOF

chmod +x "$wrapper_script"

echo "[INFO] Downloading $(awk 'NF && $0 !~ /^#/' "$urls_file" | wc -l | tr -d ' ') files with $parallel parallel jobs"

# Filter blanks/comments, strip carriage returns (Windows line endings), and pass to wrapper script
awk 'NF && $0 !~ /^#/' "$urls_file" \
  | tr -d '\r' \
  | xargs -n 1 -P "$parallel" "$wrapper_script" "$cookies_file" "$outdir" "$poll_max" "$max_wait"

echo "[DONE] All downloads complete"
