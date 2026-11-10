"""Tests for PlotData output naming update-date placeholder logic."""

import sys
import unittest
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLOTDATA_SRC = PROJECT_ROOT / "tools" / "PlotData" / "src"
if str(PLOTDATA_SRC) not in sys.path:
    sys.path.insert(0, str(PLOTDATA_SRC))

from plotdata.helper_functions import get_output_filename  # noqa: E402


BASE_METADATA = {
    "mission": "S1",
    "relative_orbit": "61",
    "relative_orbit_second": "69",
    "post_processing_method": "miaplpy",
    "first_date": "2017-07-31",
    "last_date": "2022-06-30",
    "data_footprint": "POLYGON((124.03 12.79,124.07 12.79,124.07 12.75,124.03 12.75,124.03 12.79))",
}


class TestPlotDataUpdatePlaceholderNaming(unittest.TestCase):
    def test_recent_last_date_uses_placeholder(self):
        metadata = dict(BASE_METADATA)
        metadata["last_date"] = "2026-04-20"
        metadata["cfg.mintpy.save.hdfEos5.update"] = "yes"

        out = get_output_filename(metadata, template=None, direction="vert", today=date(2026, 4, 25))
        self.assertIn("_XXXXXXXX_", out)

    def test_stale_last_date_keeps_real_date(self):
        metadata = dict(BASE_METADATA)
        metadata["cfg.mintpy.save.hdfEos5.update"] = "yes"

        out = get_output_filename(metadata, template=None, direction="vert", today=date(2026, 5, 5))
        self.assertIn("_20220630_", out)
        self.assertNotIn("_XXXXXXXX_", out)

    def test_boundary_31_days_uses_placeholder(self):
        metadata = dict(BASE_METADATA)
        metadata["last_date"] = "2026-03-26"  # 31 days before 2026-04-26
        metadata["cfg.mintpy.save.hdfEos5.update"] = "yes"

        out = get_output_filename(metadata, template=None, direction="horz", today=date(2026, 4, 26))
        self.assertIn("_XXXXXXXX_", out)

    def test_dataset_suffix_is_after_corners(self):
        ds = get_output_filename(BASE_METADATA, template=None, direction="vert", suffix="DS")
        filt = get_output_filename(BASE_METADATA, template=None, direction="vert", suffix="filtDS")
        self.assertTrue(ds.endswith("_DS.he5"))
        self.assertTrue(filt.endswith("_filtDS.he5"))
        self.assertNotEqual(ds, filt)
        plain = get_output_filename(BASE_METADATA, template=None, direction="vert")
        self.assertFalse(plain.endswith("_DS.he5"))


if __name__ == "__main__":
    unittest.main()
