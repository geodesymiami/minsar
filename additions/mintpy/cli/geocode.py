#!/usr/bin/env python3
############################################################
# MinSAR: Thin wrapper over MintPy geocode.py
# Adds .he5 (HDFEOS5) support; delegates to geocode_hdfeos5.
# All other input: delegate to geocode_orig (unmodified MintPy).
# Keep changes minimal for smooth MintPy upstream adoption.
############################################################


import sys


def main(iargs=None):
    iargs = iargs or sys.argv[1:]
    # MinSAR: support .he5 (HDFEOS5) input - delegate to geocode_hdfeos5
    try:
        from mintpy.cli.geocode_orig import create_parser
        parser = create_parser()
        inps = parser.parse_args(args=iargs)
        if inps.file and any(f.endswith('.he5') for f in inps.file):
            from mintpy.geocode_hdfeos5 import main as he5_main
            he5_main(iargs)
            return
    except SystemExit as e:
        if e.code != 0:
            raise
    # Standard path: delegate to MintPy geocode
    from mintpy.cli.geocode_orig import main as std_main
    std_main(iargs)


if __name__ == '__main__':
    main(sys.argv[1:])
