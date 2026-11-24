#!/usr/bin/env python3
"""Set the number of looks in a template file (called by minsarApp.bash for its looks options)."""

import argparse
import sys
from pathlib import Path

from minsar.utils.template_looks import add_looks_arguments, check_option_spellings, set_looks_in_template_text, stack_prefix

EXAMPLE = """
Examples:
    set_template_looks.py $TE/GalapagosSenD128.template --rangeLooks 20 --azimuthLooks 5
    set_template_looks.py $TE/GalapagosSenD128.template --range-looks 20
    set_template_looks.py $TE/TamboraAlos2D25.template --alos2Stack.rangeLooks 2 --alos2Stack.azimuthLooks 14
"""


def create_parser():
    parser = argparse.ArgumentParser(description="Set topsStack or alos2Stack rangeLooks / azimuthLooks in a template file.",
                                     epilog=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter, allow_abbrev=False)
    parser.add_argument("template", metavar="TEMPLATE", help="template file, edited in place")
    add_looks_arguments(parser)
    return parser


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    args = create_parser().parse_args(argv)
    path = Path(args.template)
    if not path.is_file():
        print(f"ERROR: template not found: {path}", file=sys.stderr)
        return 1
    text = path.read_text()
    try:
        check_option_spellings(argv, stack_prefix(text))
        text, changed = set_looks_in_template_text(text, args.range_looks, args.azimuth_looks)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if changed:
        path.write_text(text)
    for key, value in changed.items():
        print(f"{key} = {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
