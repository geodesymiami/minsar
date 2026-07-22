#!/usr/bin/env python3
"""Unit tests for egms_concat_csv.py (tiny synthetic CSVs; no live EGMS)."""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from minsar.scripts.egms_concat_csv import (
    check_compatible,
    concatenate,
    default_output_path,
    flight_direction_from_track_angle,
    format_burst_tag,
    format_swath_tag,
    normalize_flight_direction,
    parse_filename_meta,
    resolve_inputs,
    sort_paths,
)


class TestParseFilename(unittest.TestCase):
    def test_orbit_burst_swath(self):
        m = parse_filename_meta(Path("EGMS_L2a_044_0221_IW2_VV_2020_2024_1.zip"))
        self.assertEqual(m["orbit"], "044")
        self.assertEqual(m["burst"], "0221")
        self.assertEqual(m["swath"], "IW2")
        self.assertEqual(m["level"], "2a")
        self.assertEqual(m["pol"], "VV")
        self.assertEqual(m["yr_start"], "2020")
        self.assertEqual(m["yr_end"], "2024")


class TestDefaultOutput(unittest.TestCase):
    def test_egms_burst_zips(self):
        paths = [
            Path("/data/egms/EGMS_L2a_044_0220_IW2_VV_2020_2024_1.zip"),
            Path("/data/egms/EGMS_L2a_044_0221_IW2_VV_2020_2024_1.zip"),
            Path("/data/egms/EGMS_L2a_044_0222_IW2_VV_2020_2024_1.zip"),
        ]
        out = default_output_path(paths, flight_direction="asc")
        self.assertEqual(
            out,
            Path("/data/egms/S1_asc_044_egms_IW2_220-221-222_VV_2020_2024_concat.csv"),
        )

    def test_mixed_subswaths_iw12(self):
        paths = [
            Path("/data/egms/EGMS_L2a_124_0850_IW2_VV_2020_2024_1.zip"),
            Path("/data/egms/EGMS_L2a_124_0851_IW1_VV_2020_2024_1.zip"),
            Path("/data/egms/EGMS_L2a_124_0851_IW2_VV_2020_2024_1.zip"),
            Path("/data/egms/EGMS_L2a_124_0852_IW1_VV_2020_2024_1.zip"),
            Path("/data/egms/EGMS_L2a_124_0852_IW2_VV_2020_2024_1.zip"),
        ]
        out = default_output_path(paths, flight_direction="desc")
        self.assertEqual(
            out,
            Path("/data/egms/S1_desc_124_egms_IW12_850-851-852_VV_2020_2024_concat.csv"),
        )

    def test_burst_tag(self):
        self.assertEqual(format_burst_tag({"0220", "0221", "0222"}), "220-221-222")
        self.assertEqual(format_burst_tag({"0221"}), "221")

    def test_flight_direction_from_track_angle(self):
        self.assertEqual(flight_direction_from_track_angle(10.0), "asc")
        self.assertEqual(flight_direction_from_track_angle(200.0), "desc")
        self.assertEqual(normalize_flight_direction("D"), "desc")
        self.assertEqual(normalize_flight_direction("asc"), "asc")

    def test_swath_tag_order(self):
        self.assertEqual(format_swath_tag({"IW2", "IW1"}), "IW12")
        self.assertEqual(format_swath_tag({"IW3", "IW1", "IW2"}), "IW123")

    def test_non_egms_fallback(self):
        paths = [Path("/tmp/a.csv"), Path("/tmp/b.csv")]
        self.assertEqual(default_output_path(paths), Path("/tmp/concat.csv"))

    def test_mixed_parent_uses_cwd(self):
        paths = [
            Path("/data/egms/EGMS_L2a_044_0220_IW2_VV_2020_2024_1.zip"),
            Path("/other/EGMS_L2a_044_0221_IW2_VV_2020_2024_1.zip"),
        ]
        self.assertEqual(default_output_path(paths), Path.cwd() / "concat.csv")


class TestCompat(unittest.TestCase):
    def test_mixed_orbit_rejected(self):
        paths = [
            Path("EGMS_L2a_044_0221_IW2_VV_2020_2024_1.zip"),
            Path("EGMS_L2a_124_0851_IW2_VV_2020_2024_1.zip"),
        ]
        with self.assertRaises(ValueError):
            check_compatible(paths, allow_mixed=False)

    def test_mixed_subswath_allowed(self):
        paths = [
            Path("EGMS_L2a_124_0851_IW1_VV_2020_2024_1.zip"),
            Path("EGMS_L2a_124_0851_IW2_VV_2020_2024_1.zip"),
        ]
        check_compatible(paths, allow_mixed=False)


class TestConcat(unittest.TestCase):
    def test_concat_two_csvs(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            a = d / "EGMS_L2a_044_0220_IW2_VV_2020_2024_1.csv"
            b = d / "EGMS_L2a_044_0221_IW2_VV_2020_2024_1.csv"
            # b is north/west-ish vs a
            a.write_text(
                "pid,latitude,longitude,v\n"
                "1,37.47,15.06,1.0\n"
                "2,37.47,15.07,1.1\n",
                encoding="utf-8",
            )
            b.write_text(
                "pid,latitude,longitude,v\n"
                "3,37.79,14.98,2.0\n"
                "4,37.80,14.99,2.1\n",
                encoding="utf-8",
            )
            out = d / "out.csv"
            ordered = sort_paths([a, b], "geo", sample_rows=10)
            # west first (b), then east (a)
            self.assertEqual([p.name for p in ordered], [b.name, a.name])
            n = concatenate(ordered, out)
            self.assertEqual(n, 4)
            lines = out.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(lines[0], "pid,latitude,longitude,v")
            self.assertTrue(lines[1].startswith("3,"))

    def test_zip_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            csv_name = "EGMS_L2a_044_0220_IW2_VV_2020_2024_1.csv"
            csv_path = d / csv_name
            csv_path.write_text("pid,latitude,longitude\n1,37.5,15.0\n", encoding="utf-8")
            zpath = d / "EGMS_L2a_044_0220_IW2_VV_2020_2024_1.zip"
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.write(csv_path, arcname=csv_name)
            out = d / "out.csv"
            n = concatenate([zpath], out)
            self.assertEqual(n, 1)


class TestResolve(unittest.TestCase):
    def test_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            f = d / "EGMS_L2a_044_0220_IW2_VV_2020_2024_1.csv"
            f.write_text("pid,latitude,longitude\n1,1,1\n", encoding="utf-8")

            class A:
                inputs: list = []
                dir = str(d)
                pattern = "EGMS_L2a_044_*.csv"

            paths = resolve_inputs(A())  # type: ignore[arg-type]
            self.assertEqual(len(paths), 1)


if __name__ == "__main__":
    unittest.main()
