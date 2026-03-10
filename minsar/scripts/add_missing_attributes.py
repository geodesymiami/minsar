#!/usr/bin/env python3
"""Entry point for add_missing_attributes: add ORBIT_DIRECTION and relative_orbit to H5 files."""

import sys

from minsar.src.minsar.cli.add_missing_attributes import main

if __name__ == "__main__":
    sys.exit(main())
