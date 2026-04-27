#!/usr/bin/env python3
"""Tests for minsar.utils.sar_platform (shared with get_sar_coverage / create_template)."""

import unittest

from minsar.utils.sar_platform import SAR_PLATFORM_KNOWN, normalize_sar_platform_token


class TestSarPlatform(unittest.TestCase):
    def test_sentinel_aliases_map_to_s1(self):
        for s in ("S1", "SEN", "Sen", "SENTINEL1", "Sentinel-1", "sentinel-1"):
            self.assertEqual(normalize_sar_platform_token(s), "S1", msg=s)
            self.assertIn(normalize_sar_platform_token(s), SAR_PLATFORM_KNOWN)

    def test_nisar_aliases(self):
        for s in ("NISAR", "Nisar", "NİSAR", "nisar"):
            self.assertEqual(normalize_sar_platform_token(s), "NISAR", msg=s)

    def test_alos2(self):
        self.assertEqual(normalize_sar_platform_token("ALOS2"), "ALOS2")
        self.assertEqual(normalize_sar_platform_token("ALOS"), "ALOS2")

    def test_unknown_passthrough(self):
        self.assertEqual(normalize_sar_platform_token("UNKNOWN"), "UNKNOWN")
        self.assertNotIn("UNKNOWN", SAR_PLATFORM_KNOWN)


if __name__ == "__main__":
    unittest.main()
