#!/usr/bin/env python3
"""Modify insarmaps.log start coordinates from a reference InsarMaps URL."""

import argparse
import re
import shutil
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse


REMOTEHOST_VOLCDEF = "http://149.165.154.65"
REMOTE_DIR = "/data/HDF5EOS/"
BACKUP_NAME = "orig_insarmaps.log"
START_RE = re.compile(r"(/start/)-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?")
START_VALUE_RE = re.compile(r"/start/(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)")

EXAMPLES = """Examples:
  modify_insarmapslog.py insarmaps.log "http://149.165.154.65/data/HDF5EOS/Kerinci/miaplpy/overlay.html#/start/-1.6959/101.2711/13.9520?minScale=-0.75&maxScale=0.75&background=satellite"
  modify_insarmapslog.py Kerinci/miaplpy/insarmaps.log "http://149.165.153.50/start/-8.2733/123.5110/14.8136?minScale=-1.5&maxScale=1.5&background=satellite&pixelSize=5.6"
  modify_insarmapslog.py Kerinci/miaplpy/insarmaps.log "https://insarmaps.miami.edu/start/-1.6964/101.2698/14.4283?minScale=-0.8&maxScale=0.8&background=satellite"
"""


def _extract_start_values(reference_url):
    """Return rounded lat, lon, and zoom strings from a reference URL."""
    match = START_VALUE_RE.search(reference_url)
    if not match:
        raise ValueError(f"No /start/<lat>/<lon>/<zoom> section found in URL: {reference_url}")

    lat, lon, zoom = (float(value) for value in match.groups())
    return f"{lat:.3f}", f"{lon:.3f}", f"{zoom:.1f}"


def _reference_query_params(reference_url):
    """Return query parameters from a URL path query or from an overlay URL fragment query."""
    parsed = urlparse(reference_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))

    if "?" in parsed.fragment:
        fragment_query = parsed.fragment.split("?", 1)[1]
        params.update(parse_qsl(fragment_query, keep_blank_values=True))

    return params


def _page_name_from_reference(reference_url):
    parsed = urlparse(reference_url)
    if parsed.path.endswith("/index.html"):
        return "index.html"
    return "overlay.html"


def _project_path_from_reference(reference_url):
    parsed = urlparse(reference_url)
    path = parsed.path
    if REMOTE_DIR not in path or not (path.endswith("/overlay.html") or path.endswith("/index.html")):
        return None

    project_with_page = path.split(REMOTE_DIR, 1)[1]
    return Path(project_with_page).parent.as_posix()


def _project_path_from_logfile(logfile):
    parent = Path(logfile).parent
    remote_marker = REMOTE_DIR.rstrip("/") + "/"
    parent_text = parent.as_posix()
    if remote_marker in parent_text:
        return parent_text.split(remote_marker, 1)[1].strip("/")

    if parent_text not in ("", "."):
        if not parent.is_absolute():
            return parent_text.strip("/")

        parts = parent.parts
        if len(parts) >= 2:
            return Path(*parts[-2:]).as_posix()

    absolute_parent = Path(logfile).resolve().parent.as_posix()
    if remote_marker in absolute_parent:
        return absolute_parent.split(remote_marker, 1)[1].strip("/")

    parts = Path(absolute_parent).parts
    if len(parts) >= 2:
        return Path(*parts[-2:]).as_posix()

    raise ValueError(f"Cannot derive project path from logfile path: {logfile}")


def _project_path(reference_url, logfile):
    return _project_path_from_reference(reference_url) or _project_path_from_logfile(logfile)


def replace_start_values(line, reference_url):
    """Replace the /start/<lat>/<lon>/<zoom> values in one InsarMaps URL line."""
    lat, lon, zoom = _extract_start_values(reference_url)
    replacement = rf"\g<1>{lat}/{lon}/{zoom}"
    updated, count = START_RE.subn(replacement, line, count=1)
    if count != 1:
        raise ValueError(f"No /start/<lat>/<lon>/<zoom> section found in log line: {line}")
    return updated


def build_overlay_url(reference_url, logfile):
    """Build the remote overlay URL printed after modifying insarmaps.log.

    The printed URL deliberately omits ``/start/<lat>/<lon>/<zoom>``; those values
    are only used to rewrite ``insarmaps.log`` lines.
    """
    params = _reference_query_params(reference_url)
    printed_params = [(key, params[key]) for key in ("minScale", "maxScale", "background", "pixelSize") if key in params]
    query = urlencode(printed_params)
    query_suffix = f"?{query}" if query else ""

    project = _project_path(reference_url, logfile).strip("/")
    page = _page_name_from_reference(reference_url)
    return f"{REMOTEHOST_VOLCDEF}{REMOTE_DIR}{project}/{page}#/{query_suffix}"


def modify_insarmaps_log(reference_url, logfile):
    """Create orig_insarmaps.log if needed, rewrite insarmaps.log, and return the printed URL."""
    logfile = Path(logfile)
    backup = logfile.with_name(BACKUP_NAME)
    if not backup.exists():
        shutil.copy2(logfile, backup)

    original_text = logfile.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)
    updated_lines = [replace_start_values(line, reference_url) for line in lines]
    logfile.write_text("".join(updated_lines), encoding="utf-8")
    return build_overlay_url(reference_url, logfile)


def create_parser():
    parser = argparse.ArgumentParser(
        description="Modify an insarmaps.log file using lat/lon/zoom and display parameters from a reference InsarMaps URL.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EXAMPLES,
    )
    parser.add_argument("logfile", type=Path, help="Path to insarmaps.log.")
    parser.add_argument("url", help="Reference InsarMaps URL containing /start/<lat>/<lon>/<zoom> and optional display parameters (quote it in the shell).")
    return parser


def main(argv=None):
    parser = create_parser()
    args = parser.parse_args(argv)
    print(modify_insarmaps_log(args.url, args.logfile))


if __name__ == "__main__":
    main()
