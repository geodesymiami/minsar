#!/usr/bin/env python3
"""Unit tests for egms_search.py (mocked API; no live CLMS auth)."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from minsar.scripts.egms_search import (
    aoi_to_egms_bbox,
    build_search_query,
    format_hit_line,
    normalize_level,
    pick_latest_release,
    print_hits,
    resolve_releases,
    search_products,
    write_curl_script,
)


class TestNormalizeLevel(unittest.TestCase):
    def test_l2a_variants(self):
        self.assertEqual(normalize_level("L2A"), "L2A")
        self.assertEqual(normalize_level("l2a"), "L2A")
        self.assertEqual(normalize_level("basic"), "L2A")

    def test_invalid(self):
        with self.assertRaises(ValueError):
            normalize_level("L1")


class TestAoiToEgmsBbox(unittest.TestCase):
    def test_sn_we_rectangle(self):
        bbox = aoi_to_egms_bbox("37.525:37.825,15.050:15.210")
        self.assertAlmostEqual(bbox[0][0], 15.05, places=5)
        self.assertAlmostEqual(bbox[0][1], 37.525, places=5)
        self.assertAlmostEqual(bbox[1][0], 15.21, places=5)
        self.assertAlmostEqual(bbox[1][1], 37.825, places=5)

    def test_wkt_polygon(self):
        wkt = "Polygon((14.75 37.51, 15.25 37.51, 15.25 37.88, 14.75 37.88, 14.75 37.51))"
        bbox = aoi_to_egms_bbox(wkt)
        self.assertEqual(bbox, [[14.75, 37.51], [15.25, 37.88]])

    def test_rejects_span_over_5_deg(self):
        with self.assertRaises(ValueError) as ctx:
            aoi_to_egms_bbox("30:40,10:20")
        self.assertIn("5", str(ctx.exception))


class TestPickLatestRelease(unittest.TestCase):
    def test_picks_latest_end_year(self):
        self.assertEqual(pick_latest_release(["2019-2023", "2020-2024"]), "2020-2024")

    def test_empty(self):
        with self.assertRaises(ValueError):
            pick_latest_release([])


class TestBuildSearchQuery(unittest.TestCase):
    def test_required_fields(self):
        q = build_search_query(
            bbox=[[15.0, 37.5], [15.2, 37.8]],
            level="L2A",
            releases=["2020-2024"],
            direction="descending",
            relative_orbit=124,
            swath="IW2",
        )
        self.assertEqual(q["levels"], ["L2A"])
        self.assertEqual(q["releases"], ["2020-2024"])
        self.assertEqual(q["bbox"], [[15.0, 37.5], [15.2, 37.8]])
        self.assertEqual(q["direction"], "descending")
        self.assertEqual(q["relativeOrbit"], 124)
        self.assertEqual(q["swath"], "IW2")


class TestResolveReleases(unittest.TestCase):
    def test_explicit_releases(self):
        out = resolve_releases({"Authorization": "Bearer x"}, "2019-2023,2020-2024")
        self.assertEqual(out, ["2019-2023", "2020-2024"])

    @patch("minsar.scripts.egms_search.fetch_releases", side_effect=TimeoutError("timed out"))
    def test_fallback_when_api_unavailable(self, _mock_fetch):
        buf = io.StringIO()
        with patch("sys.stderr", buf):
            out = resolve_releases({"Authorization": "Bearer x"}, None)
        self.assertEqual(out, ["2020-2024"])
        self.assertIn("Warning", buf.getvalue())


class TestSearchAndPrint(unittest.TestCase):
    @patch("minsar.scripts.egms_search.requests.post")
    def test_search_products(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "status": True,
            "id": "qid-1",
            "hits": [{"filename": "EGMS_L2A_demo.zip", "filesize": 1024, "productLevel": "L2A"}],
        }
        mock_post.return_value = mock_resp
        result = search_products({"Authorization": "Bearer x"}, {"levels": ["L2A"]})
        self.assertEqual(result["id"], "qid-1")
        self.assertEqual(len(result["hits"]), 1)

    def test_print_hits(self):
        result = {
            "id": "qid-1",
            "hits": [
                {
                    "filename": "EGMS_L2A_demo.zip",
                    "filesize": 2048,
                    "productLevel": "L2A",
                    "productType": "BASIC",
                    "release": "2020-2024",
                    "direction": "ascending",
                }
            ],
        }
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            print_hits(result)
        out = buf.getvalue()
        self.assertIn("Found 1 product", out)
        self.assertIn("EGMS_L2A_demo.zip", out)
        self.assertIn("direction=ascending", out)

    def test_format_hit_line(self):
        line = format_hit_line({"filename": "a.zip", "productLevel": "L2A", "filesize": 512})
        self.assertIn("a.zip", line)
        self.assertIn("L2A", line)


class TestWriteCurlScript(unittest.TestCase):
    def test_writes_curl_with_resume_and_token(self):
        result = {
            "id": "qid-abc",
            "hits": [{"filename": "EGMS_demo.zip", "filesize": 6}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "dl.sh"
            write_curl_script(result, script, outdir="./egms")
            text = script.read_text(encoding="utf-8")
            self.assertIn("clms_get_access_token.py", text)
            self.assertIn("curl -fL", text)
            self.assertIn("-C -", text)
            self.assertIn("--http1.1", text)
            self.assertIn("--connect-timeout 120", text)
            self.assertIn("--retry 20", text)
            self.assertIn("EGMS_demo.zip", text)
            self.assertIn("id=qid-abc", text)
            self.assertTrue(script.stat().st_mode & 0o100)

    def test_write_json_and_url_tsv(self):
        from minsar.scripts.egms_search import write_json_listing, write_url_tsv

        result = {
            "id": "qid-abc",
            "hits": [{"filename": "EGMS_demo.zip", "filesize": 6}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            jpath = write_json_listing(result, Path(tmp) / "hits.json")
            data = json.loads(jpath.read_text(encoding="utf-8"))
            self.assertEqual(data["id"], "qid-abc")
            self.assertEqual(len(data["hits"]), 1)
            tsv = write_url_tsv(result, Path(tmp) / "urls.tsv")
            line = tsv.read_text(encoding="utf-8").strip()
            self.assertIn("EGMS_demo.zip\t", line)
            self.assertIn("id=qid-abc", line)

    def test_empty_hits_raises(self):
        with self.assertRaises(RuntimeError):
            write_curl_script({"id": "qid", "hits": []}, "/tmp/nope.sh")


if __name__ == "__main__":
    unittest.main()
