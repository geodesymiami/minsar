#!/usr/bin/env python3
"""Unit tests for filter_egms_hits.py (no live EGMS API)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from minsar.scripts.filter_egms_hits import filter_hits, hit_matches, normalize_relative_orbit


def _sample_result() -> dict:
    return {
        "id": "qid-1",
        "hits": [
            {
                "filename": "EGMS_L2a_044_0221_IW2_VV_2020_2024_1.zip",
                "productLevel": "L2A",
                "release": "2020-2024",
                "direction": "ascending",
                "relativeOrbit": "044",
                "swath": "IW2",
            },
            {
                "filename": "EGMS_L2a_124_0851_IW2_VV_2020_2024_1.zip",
                "productLevel": "L2A",
                "release": "2020-2024",
                "direction": "descending",
                "relativeOrbit": "124",
                "swath": "IW2",
            },
            {
                "filename": "EGMS_L2a_044_0220_IW1_VV_2020_2024_1.zip",
                "productLevel": "L2A",
                "release": "2020-2024",
                "direction": "ascending",
                "relativeOrbit": "044",
                "swath": "IW1",
            },
        ],
    }


class TestNormalizeOrbit(unittest.TestCase):
    def test_pad(self):
        self.assertEqual(normalize_relative_orbit(44), "044")
        self.assertEqual(normalize_relative_orbit("044"), "044")
        self.assertEqual(normalize_relative_orbit(124), "124")


class TestHitMatches(unittest.TestCase):
    def test_orbit_and_swath(self):
        hit = _sample_result()["hits"][0]
        self.assertTrue(hit_matches(hit, relative_orbit=44, swath="IW2"))
        self.assertFalse(hit_matches(hit, relative_orbit=124, swath="IW2"))
        self.assertFalse(hit_matches(hit, relative_orbit=44, swath="IW1"))


class TestFilterHits(unittest.TestCase):
    def test_filter_orbit_swath(self):
        out = filter_hits(_sample_result(), relative_orbit=44, swath="IW2")
        self.assertEqual(len(out["hits"]), 1)
        self.assertEqual(out["hits"][0]["filename"], "EGMS_L2a_044_0221_IW2_VV_2020_2024_1.zip")
        self.assertEqual(out["id"], "qid-1")

    def test_filter_direction(self):
        out = filter_hits(_sample_result(), direction="descending")
        self.assertEqual(len(out["hits"]), 1)
        self.assertEqual(out["hits"][0]["relativeOrbit"], "124")

    def test_roundtrip_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hits.json"
            path.write_text(json.dumps(_sample_result()), encoding="utf-8")
            from minsar.scripts.filter_egms_hits import load_result

            loaded = load_result(path)
            self.assertEqual(len(loaded["hits"]), 3)


if __name__ == "__main__":
    unittest.main()
