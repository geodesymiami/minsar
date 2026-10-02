#!/usr/bin/env python3
############################################################
# MinSAR: Thin wrapper over MintPy geocode.py
# Adds .he5 (HDFEOS5) support; delegates to hdfeos5_geocode_helper.
# All other input: delegate to geocode_orig (unmodified MintPy).
# Keep changes minimal for smooth MintPy upstream adoption.
############################################################


import sys


def main(iargs=None):
    iargs = iargs or sys.argv[1:]
    # MinSAR: support .he5 (HDFEOS5) input - delegate to hdfeos5_geocode_helper
    try:
        from mintpy.cli.geocode_orig import create_parser, read_template2inps
        from mintpy.utils import utils as ut
        parser = create_parser()
        inps = parser.parse_args(args=iargs)
        inps.argv = iargs
        if getattr(inps, 'templateFile', None):
            inps = read_template2inps(inps.templateFile, inps)
        inps.file = ut.get_file_list(inps.file)
        if inps.file and any(f.endswith('.he5') for f in inps.file):
            from mintpy.hdfeos5_geocode_helper import geocode_he5
            geocode_he5(inps)
            return
    except SystemExit as e:
        if e.code != 0:
            raise
    # Standard path: delegate to MintPy geocode
    from mintpy.cli.geocode_orig import main as std_main
    std_main(iargs)


if __name__ == '__main__':
    main(sys.argv[1:])
