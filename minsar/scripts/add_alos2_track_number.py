#!/usr/bin/env python3
"""Write the ALOS-2 path number onto the reference track XML before MintPy."""

import argparse
import re
import sys
from pathlib import Path

COMMENT_RE = re.compile(r"<!--\s*minsar\.trackNumber=\d+\s*-->")


def add_alos2_track_number(template_file, work_dir):
    """Insert ``<!-- minsar.trackNumber=N -->`` into the reference track XML.

    ISCE ``ProductManager`` exits if ``trackNumber`` is a real property on the
    Track component, so the value is stored as a comment. MintPy's
    ``extract_alosStack_metadata`` reads that comment into ``trackNumber``,
    which becomes ``relative_orbit``.
    """
    from minsar.objects.dataset_template import Template

    options = Template(str(template_file)).get_options()
    track_number = _required_int(options, "ssaraopt.relativeOrbit")
    reference_date = _reference_yymmdd(options, work_dir)
    track_xml = Path(work_dir) / "dates_resampled" / reference_date / f"{reference_date}.track.xml"
    if not track_xml.is_file():
        raise SystemExit(f"reference track XML not found: {track_xml}")

    comment = f"<!-- minsar.trackNumber={track_number} -->"
    text = track_xml.read_text()
    if COMMENT_RE.search(text):
        updated = COMMENT_RE.sub(comment, text, count=1)
    else:
        needle = "<productmanager_name>\n"
        if needle not in text:
            raise SystemExit(f"unrecognized track XML (no productmanager root): {track_xml}")
        updated = text.replace(needle, needle + comment + "\n", 1)

    if updated != text:
        track_xml.write_text(updated)
        print(f"trackNumber {track_number} written to {track_xml}")
    else:
        print(f"trackNumber {track_number} already in {track_xml}")
    return track_xml


def _required_int(options, key):
    value = str(options.get(key, "")).strip()
    if value.lower() in ("", "auto", "none"):
        raise SystemExit(f"template is missing {key}")
    if not re.fullmatch(r"\d+", value):
        raise SystemExit(f"{key} must be an integer, got {value!r}")
    return int(value)


def _first_date_dir(work_dir):
    """First YYMMDD folder under SLC/ (the stack's reference when none is set), else dates_resampled/."""
    for sub in ("SLC", "dates_resampled"):
        names = sorted(p.name for p in (Path(work_dir) / sub).glob("[0-9]" * 6) if p.is_dir())
        if names:
            return names[0]
    return None


def _reference_yymmdd(options, work_dir="."):
    value = str(options.get("alos2Stack.referenceDate", "")).strip()
    if value.lower() in ("", "auto", "none"):
        value = str(options.get("stripmapStack.referenceDate", "")).strip()
    if value.lower() in ("", "auto", "none"):
        value = _first_date_dir(work_dir)
        if not value:
            raise SystemExit(f"alos2Stack.referenceDate is auto and no YYMMDD folder found in {work_dir}/SLC")
    if len(value) == 8 and value.isdigit():
        value = value[2:]
    if not re.fullmatch(r"\d{6}", value):
        raise SystemExit(f"alos2Stack.referenceDate must be YYYYMMDD or YYMMDD, got {value!r}")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Write trackNumber into the reference ALOS-2 track XML from ssaraopt.relativeOrbit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  add_alos2_track_number.py parCameroonAlos2D89.template\n"
            "  add_alos2_track_number.py --work-dir \"$PWD\" parCameroonAlos2D89.template"
        ),
    )
    parser.add_argument("template", metavar="TEMPLATE", help="template with ssaraopt.relativeOrbit and alos2Stack.referenceDate")
    parser.add_argument("--work-dir", default=".", metavar="DIR", help="directory that contains dates_resampled (default: .)")
    args = parser.parse_args(argv)
    template = Path(args.template)
    if not template.is_file():
        raise SystemExit(f"template not found: {template}")
    add_alos2_track_number(template, Path(args.work_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
