#!/usr/bin/env python3
"""Unit tests for EGMS metadata helpers and lat/lon detection."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from egms_metadata import (
    build_egms_attributes,
    center_line_utc_from_product_id,
    flight_direction_from_track_angle,
    parse_egms_filename,
    parse_egms_xml,
)
from insarmaps_csv_geo import csv_mean_lat_lon, _detect_lat_lon_fieldnames


class TestEgmsFilename(unittest.TestCase):
    def test_parse_etna_style_name(self):
        p = "EGMS_L2a_044_0221_IW2_VV_2020_2024_1.csv"
        out = parse_egms_filename(p)
        self.assertEqual(out["relative_orbit"], 44)
        self.assertEqual(out["egms_burst_id"], "0221")
        self.assertEqual(out["beam_swath"], 2)
        self.assertEqual(out["beam_mode"], "IW")


class TestEgmsXml(unittest.TestCase):
    def test_parse_minimal_xml(self):
        xml = """<?xml version='1.0' encoding='UTF-8'?>
<BURST>
  <product_level>L2a</product_level>
  <track>044</track>
  <burst_id>0221</burst_id>
  <sub_swath>2</sub_swath>
  <dataset>
    <image>
      <product_id>S1A_IW_SLC__1SDV_20200110T165613_20200110T165639_030741_03864C_8DD2</product_id>
    </image>
  </dataset>
</BURST>
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            f.write(xml)
            path = f.name
        try:
            out = parse_egms_xml(path)
            self.assertEqual(out["relative_orbit"], 44)
            self.assertEqual(out["egms_burst_id"], "0221")
            self.assertEqual(out["beam_swath"], 2)
            self.assertEqual(out["CENTER_LINE_UTC"], 16 * 3600 + 56 * 60 + 13)
        finally:
            os.unlink(path)


class TestEgmsHelpers(unittest.TestCase):
    def test_center_line_utc(self):
        pid = "S1A_IW_SLC__1SDV_20200110T165613_20200110T165639_030741_03864C_8DD2"
        self.assertEqual(center_line_utc_from_product_id(pid), 60973)

    def test_flight_direction_from_track_angle(self):
        self.assertEqual(flight_direction_from_track_angle(349.61), "A")
        self.assertEqual(flight_direction_from_track_angle(10.0), "A")
        self.assertEqual(flight_direction_from_track_angle(180.0), "D")

    def test_build_attrs_cli_override(self):
        attrs = build_egms_attributes(
            "EGMS_L2a_044_0221_IW2_VV_2020_2024_1.csv",
            xml_path=None,
            flight_direction="D",
            relative_orbit=99,
            project_name="EtnaEGMS",
            track_angle=350.0,
        )
        self.assertEqual(attrs["flight_direction"], "D")
        self.assertEqual(attrs["relative_orbit"], 99)
        self.assertEqual(attrs["PROJECT_NAME"], "EtnaEGMS")
        self.assertEqual(attrs["post_processing_method"], "EGMS")
        self.assertEqual(attrs["beam_swath"], 2)


class TestLatLonEgms(unittest.TestCase):
    def test_detect_lowercase_latitude_longitude(self):
        lat, lon = _detect_lat_lon_fieldnames(["pid", "latitude", "longitude", "20200104"])
        self.assertEqual(lat, "latitude")
        self.assertEqual(lon, "longitude")

    def test_csv_mean_lowercase(self):
        lines = [
            "latitude,longitude,20200104",
            "37.7,15.0,1",
            "37.8,15.1,2",
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("\n".join(lines) + "\n")
            path = f.name
        try:
            ml, mo = csv_mean_lat_lon(path)
            self.assertAlmostEqual(ml, 37.75)
            self.assertAlmostEqual(mo, 15.05)
        finally:
            os.unlink(path)


class TestConverterLatLon(unittest.TestCase):
    def test_converter_detects_egms_columns(self):
        import importlib.util

        script = (
            Path(__file__).resolve().parents[3]
            / "tools"
            / "insarmaps_scripts"
            / "hdfeos5_or_csv_2json_mbtiles.py"
        )
        if not script.is_file():
            self.skipTest(f"converter not found at {script}")
        try:
            import mintpy  # noqa: F401
        except ImportError:
            self.skipTest("mintpy not installed")

        spec = importlib.util.spec_from_file_location("hdfeos5_or_csv_2json_mbtiles", script)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        lat, lon = mod.detect_lat_lon_columns(["latitude", "longitude", "20200104"])
        self.assertEqual(lat, "latitude")
        self.assertEqual(lon, "longitude")


class TestResolveIngestStep(unittest.TestCase):
    def test_default_all(self):
        from egms2insarmaps import create_parser, resolve_ingest_step

        args = create_parser().parse_args(["x.csv"])
        self.assertEqual(resolve_ingest_step(args), "all")

    def test_step1_aliases(self):
        from egms2insarmaps import create_parser, resolve_ingest_step

        for argv in (
            ["x.csv", "--step", "1"],
            ["x.csv", "--skip-upload"],
            ["x.csv", "--hdfeos5_2json_mbtiles"],
        ):
            self.assertEqual(resolve_ingest_step(create_parser().parse_args(argv)), "step1", argv)

    def test_step2_aliases(self):
        from egms2insarmaps import create_parser, resolve_ingest_step

        for argv in (
            ["x.csv", "--step", "2"],
            ["x.csv", "--json_mbtiles2insarmaps"],
        ):
            self.assertEqual(resolve_ingest_step(create_parser().parse_args(argv)), "step2", argv)

    def test_conflict(self):
        from egms2insarmaps import create_parser, resolve_ingest_step

        args = create_parser().parse_args(["x.csv", "--step", "1", "--json_mbtiles2insarmaps"])
        with self.assertRaises(ValueError):
            resolve_ingest_step(args)


if __name__ == "__main__":
    unittest.main()
