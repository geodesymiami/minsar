#!/usr/bin/env python3
"""Test minsar.utils.unwrap_whirlwind on a synthetic phase ramp (skipped without whirlwind / isce / gdal)."""

import os
import tempfile
import unittest

import numpy as np

try:
    import whirlwind  # noqa: F401
    import isce  # noqa: F401
    from isceobj.Util.ImageUtil import ImageLib as IML
    from osgeo import gdal  # noqa: F401
    HAVE_DEPS = True
except Exception:
    HAVE_DEPS = False


@unittest.skipUnless(HAVE_DEPS, "whirlwind, isce and gdal are required")
class TestUnwrapWhirlwind(unittest.TestCase):
    def test_ramp(self):
        from minsar.utils.unwrap_whirlwind import unwrap_isce_ifgram
        length, width = 120, 150
        yy, xx = np.mgrid[0:length, 0:width]
        phase = (0.15 * xx + 0.08 * yy).astype(np.float32)          # about 5 cycles
        igram = np.exp(1j * phase).astype(np.complex64)
        igram[:10, :20] = 0                                         # no-data corner
        corr = np.full((length, width), 0.95, dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            ifg, cor, unw = (os.path.join(tmp, name) for name in ("filt.int", "filt.cor", "filt.unw"))
            igram.tofile(ifg)
            corr.tofile(cor)
            IML.renderISCEXML(ifg, bands=1, nyy=length, nxx=width, datatype="complex64", scheme="BIL")
            IML.renderISCEXML(cor, bands=1, nyy=length, nxx=width, datatype="float32", scheme="BIL")
            unwrap_isce_ifgram(ifg, cor, unw, nlooks=20, num_threads=1)

            for path in (unw, unw + ".xml", unw + ".vrt", unw + ".conncomp", unw + ".conncomp.xml", unw + ".conncomp.vrt"):
                self.assertTrue(os.path.isfile(path), msg=path)
            out = np.fromfile(unw, dtype=np.float32).reshape(length, 2, width)
            conncomp = np.fromfile(unw + ".conncomp", dtype=np.uint8).reshape(length, width)
        valid = igram != 0
        np.testing.assert_allclose(out[:, 0, :], np.abs(igram), atol=1e-5)
        self.assertTrue(np.all(out[:, 1, :][~valid] == 0))
        self.assertTrue(np.all(conncomp[~valid] == 0))
        diff = (out[:, 1, :] - phase)[valid]
        diff -= 2 * np.pi * np.round(np.median(diff) / (2 * np.pi))   # unwrapped phase is known up to 2 pi n
        self.assertLess(np.abs(diff).max(), 0.01)
        self.assertGreater((conncomp[valid] > 0).mean(), 0.9)


if __name__ == "__main__":
    unittest.main()
