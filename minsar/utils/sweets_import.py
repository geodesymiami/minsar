"""Import sweets/isce3 without pyre consuming this script's CLI flags."""

from __future__ import annotations

import sys
from contextlib import contextmanager


@contextmanager
def hide_argv_from_pyre():
    """Pyre (isce3/journal) parses sys.argv on import; hide our flags first."""
    saved = sys.argv
    sys.argv = [saved[0]]
    try:
        yield
    finally:
        sys.argv = saved
