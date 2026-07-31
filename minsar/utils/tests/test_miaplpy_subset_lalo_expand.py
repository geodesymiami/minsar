#!/usr/bin/env python3
"""Unit tests for miaplpy.subset.lalo expansion from AOI + platform heading."""

from __future__ import annotations

import unittest

from minsar.utils.miaplpy_subset_lalo_expand import (
    DEFAULT_ASC_HEADING_DEG,
    DEFAULT_DESC_HEADING_DEG,
    bounds_contain,
    expand_aoi_to_subset_lines,
    expand_bounds_asymmetric_lat,
    expand_bounds_for_heading,
    expand_for_orbits,
    format_subset_lalo,
    heading_skew_delta_lat,
)


class TestExpandBounds(unittest.TestCase):
    def setUp(self):
        # Etna-like small AOI from user example
        self.aoi = (37.796, 37.861, 15.109, 15.159)

    def test_defaults_match_mintpy_style(self):
        self.assertEqual(DEFAULT_ASC_HEADING_DEG, -13.0)
        self.assertEqual(DEFAULT_DESC_HEADING_DEG, -167.0)

    def test_asymmetric_contains_aoi_and_differs(self):
        out = expand_for_orbits(self.aoi, mode="asymmetric_lat")
        self.assertTrue(bounds_contain(out["asc"], self.aoi))
        self.assertTrue(bounds_contain(out["desc"], self.aoi))
        self.assertNotEqual(out["asc"], out["desc"])
        # Asc pads south only; Desc pads north only; lon unchanged
        self.assertLess(out["asc"][0], self.aoi[0])
        self.assertEqual(out["asc"][1], self.aoi[1])
        self.assertEqual(out["desc"][0], self.aoi[0])
        self.assertGreater(out["desc"][1], self.aoi[1])
        self.assertEqual(out["asc"][2:], self.aoi[2:])
        self.assertEqual(out["desc"][2:], self.aoi[2:])

    def test_skew_delta_matches_formula(self):
        delta = heading_skew_delta_lat(*self.aoi, DEFAULT_ASC_HEADING_DEG)
        asc = expand_bounds_asymmetric_lat(*self.aoi, DEFAULT_ASC_HEADING_DEG, "asc")
        self.assertAlmostEqual(self.aoi[0] - asc[0], delta, places=10)

    def test_aabb_contains_aoi(self):
        for heading in (DEFAULT_ASC_HEADING_DEG, DEFAULT_DESC_HEADING_DEG, -13.275):
            expanded = expand_bounds_for_heading(*self.aoi, heading)
            self.assertTrue(
                bounds_contain(expanded, self.aoi),
                msg=f"heading={heading}: {expanded} should contain {self.aoi}",
            )

    def test_aabb_asc_equals_desc_for_rectangle(self):
        out = expand_for_orbits(self.aoi, mode="aabb")
        for a, b in zip(out["asc"], out["desc"]):
            self.assertAlmostEqual(a, b, places=9)

    def test_zero_heading_aabb_matches_aoi(self):
        aoi = (10.0, 10.1, 20.0, 20.1)
        exp = expand_bounds_for_heading(*aoi, 0.0)
        for a, b in zip(exp, aoi):
            self.assertAlmostEqual(a, b, places=5)

    def test_lines_format_asymmetric(self):
        lines = expand_aoi_to_subset_lines(*self.aoi)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("miaplpy.subset.lalo"))
        self.assertIn("# Asc", lines[0])
        self.assertIn("# Desc", lines[1])
        asc_box = lines[0].split("=")[1].split("#")[0].strip()
        desc_box = lines[1].split("=")[1].split("#")[0].strip()
        self.assertNotEqual(asc_box, desc_box)

    def test_format_subset_lalo(self):
        self.assertEqual(
            format_subset_lalo(37.796, 37.861, 15.109, 15.159),
            "37.796:37.861,15.109:15.159",
        )


if __name__ == "__main__":
    unittest.main()
