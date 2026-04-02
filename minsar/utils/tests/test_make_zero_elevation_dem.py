#!/usr/bin/env python3
"""
Unit tests for minsar/utils/make_zero_elevation_dem.py

Run with:
    python -m unittest minsar.utils.tests.test_make_zero_elevation_dem -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root for minsar imports
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

from minsar.utils.make_zero_elevation_dem import (
    calculate_geoid_height,
    do_swap_in_place,
    ensure_dem_xml_for_fix,
    get_auxiliary_files,
    resolve_dem_path,
)


class TestCalculateGeoidHeight(unittest.TestCase):
    """
    Tests for calculate_geoid_height (EGM96 via PROJ/pyproj).

    Requires PROJ with EGM96 datum support. If PROJ is not properly installed
    (e.g. missing geoid grids), these tests will fail with RuntimeError.
    Note: sign and exact value can differ between Linux and Mac due to PROJ
    version/convention differences; we check magnitude and sensible range.
    """

    # Miami, FL (approx): lat=25.76, lon=-80.19
    # EGM96 geoid undulation magnitude in south Florida is ~25-30 m.
    MIAMI_LAT = 25.76
    MIAMI_LON = -80.19
    MIAMI_EGM96_MAGNITUDE_MIN = 20  # meters (absolute value)
    MIAMI_EGM96_MAGNITUDE_MAX = 35  # meters

    def test_miami_geoid_height_sensible(self):
        """Miami EGM96 geoid height has expected magnitude (~25-30 m)."""
        result = calculate_geoid_height(self.MIAMI_LON, self.MIAMI_LAT)
        mag = abs(result)
        self.assertGreaterEqual(
            mag,
            self.MIAMI_EGM96_MAGNITUDE_MIN,
            f"Geoid height |{result}| m too small for Miami (expected ~25-30 m). "
            "PROJ/EGM96 may not be installed correctly.",
        )
        self.assertLessEqual(
            mag,
            self.MIAMI_EGM96_MAGNITUDE_MAX,
            f"Geoid height |{result}| m too large for Miami (expected ~25-30 m). "
            "PROJ/EGM96 may not be installed correctly.",
        )


class TestResolveDemPath(unittest.TestCase):
    """Tests for resolve_dem_path."""

    def test_resolve_file_path_returns_self(self):
        """Given a valid .dem file, returns it resolved."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "elevation_N25_N27_W082_W078.dem"
            p.touch()
            result = resolve_dem_path(p)
            self.assertEqual(result.resolve(), p.resolve())

    def test_resolve_directory_finds_dem(self):
        """Given a directory with one .dem, returns that file."""
        with tempfile.TemporaryDirectory() as d:
            dem = Path(d) / "elevation_N25_N27_W082_W078.dem"
            dem.touch()
            result = resolve_dem_path(Path(d))
            self.assertEqual(result.resolve(), dem.resolve())

    def test_resolve_directory_excludes_zero_dem(self):
        """Directory with only *_zero.dem raises FileNotFoundError."""
        with tempfile.TemporaryDirectory() as d:
            zero = Path(d) / "elevation_N25_N27_W082_W078_zero.dem"
            zero.touch()
            with self.assertRaises(FileNotFoundError) as ctx:
                resolve_dem_path(Path(d))
            self.assertIn("No primary", str(ctx.exception))

    def test_resolve_directory_prefers_primary_over_zero(self):
        """Directory with both .dem and _zero.dem returns primary."""
        with tempfile.TemporaryDirectory() as d:
            primary = Path(d) / "elevation_N25_N27_W082_W078.dem"
            zero = Path(d) / "elevation_N25_N27_W082_W078_zero.dem"
            primary.touch()
            zero.touch()
            result = resolve_dem_path(Path(d))
            self.assertEqual(result.resolve(), primary.resolve())

    def test_resolve_zero_dem_file_raises(self):
        """Explicit *_zero.dem file raises ValueError."""
        with tempfile.TemporaryDirectory() as d:
            zero = Path(d) / "elevation_N25_N27_W082_W078_zero.dem"
            zero.touch()
            with self.assertRaises(ValueError) as ctx:
                resolve_dem_path(zero)
            self.assertIn("_zero", str(ctx.exception))

    def test_resolve_nonexistent_raises(self):
        """Nonexistent path raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            resolve_dem_path(Path("/nonexistent/dem/path.dem"))


class TestGetAuxiliaryFiles(unittest.TestCase):
    """Tests for get_auxiliary_files."""

    def test_returns_only_existing(self):
        """Only returns paths that exist."""
        with tempfile.TemporaryDirectory() as d:
            dem = Path(d) / "foo.dem"
            dem.touch()
            (Path(d) / "foo.hdr").touch()
            result = get_auxiliary_files(dem)
            self.assertEqual(len(result), 2)  # .dem and .hdr
            self.assertTrue(any("foo.dem" in str(p) for p in result))
            self.assertTrue(any("foo.hdr" in str(p) for p in result))

    def test_returns_empty_when_none_exist(self):
        """Returns list with only .dem when no other auxiliary files exist."""
        with tempfile.TemporaryDirectory() as d:
            dem = Path(d) / "foo.dem"
            dem.touch()
            result = get_auxiliary_files(dem)
            self.assertEqual(len(result), 1)  # just .dem
            self.assertEqual(result[0].name, "foo.dem")


class TestDryRunProducesNoFileChanges(unittest.TestCase):
    """Test that --dry-run produces no file changes."""

    def test_dry_run_swap_in_place_does_not_modify_files(self):
        """--dry-run with --swap-in-place prints plan but does not modify files."""
        with tempfile.TemporaryDirectory() as d:
            dem_dir = Path(d) / "DEM"
            dem_dir.mkdir()
            dem = dem_dir / "elevation_N25_N27_W082_W078.dem"
            dem.touch()
            (dem_dir / "elevation_N25_N27_W082_W078.hdr").touch()

            import minsar.utils.make_zero_elevation_dem as m

            orig_argv = sys.argv
            try:
                sys.argv = [
                    "make_zero_elevation_dem.py",
                    str(dem_dir),
                    "--swap-in-place",
                    "--dry-run",
                ]
                m.main()
            finally:
                sys.argv = orig_argv

            # Dry-run must not create or rename anything
            self.assertFalse(
                (dem_dir / "elevation_N25_N27_W082_W078_zero.dem").exists()
            )
            self.assertTrue((dem_dir / "elevation_N25_N27_W082_W078.dem").exists())
            self.assertFalse(
                (dem_dir / "elevation_N25_N27_W082_W078_orig.dem").exists()
            )


class TestEnsureDemXmlForFix(unittest.TestCase):
    """Tests for ensure_dem_xml_for_fix (copy _orig.dem.xml so fixImageXml has XML)."""

    def test_copies_orig_xml_when_main_xml_missing(self):
        """When .dem.xml is missing and _orig.dem.xml exists, copy it."""
        with tempfile.TemporaryDirectory() as d:
            dem = Path(d) / "elevation.dem"
            dem.touch()
            orig_xml = Path(d) / "elevation_orig.dem.xml"
            orig_xml.write_text("<imageFile>elevation_orig.dem</imageFile>")
            self.assertFalse((Path(d) / "elevation.dem.xml").exists())
            ensure_dem_xml_for_fix(dem)
            main_xml = Path(d) / "elevation.dem.xml"
            self.assertTrue(main_xml.exists())
            self.assertEqual(main_xml.read_text(), orig_xml.read_text())

    def test_does_nothing_when_main_xml_exists(self):
        """When .dem.xml already exists, do not overwrite with _orig."""
        with tempfile.TemporaryDirectory() as d:
            dem = Path(d) / "elevation.dem"
            dem.touch()
            main_xml = Path(d) / "elevation.dem.xml"
            main_xml.write_text("<imageFile>elevation.dem</imageFile>")
            orig_xml = Path(d) / "elevation_orig.dem.xml"
            orig_xml.write_text("<imageFile>elevation_orig.dem</imageFile>")
            ensure_dem_xml_for_fix(dem)
            self.assertEqual(main_xml.read_text(), "<imageFile>elevation.dem</imageFile>")

    def test_does_nothing_when_orig_xml_missing(self):
        """When _orig.dem.xml does not exist, do not create .dem.xml."""
        with tempfile.TemporaryDirectory() as d:
            dem = Path(d) / "elevation.dem"
            dem.touch()
            ensure_dem_xml_for_fix(dem)
            self.assertFalse((Path(d) / "elevation.dem.xml").exists())


class TestDoSwapInPlaceBackupOnly(unittest.TestCase):
    """Test that do_swap_in_place renames to _orig (keeps .dem so rasterio can open)."""

    def test_backup_only_renames_to_orig(self):
        """do_swap_in_place renames base.dem -> base_orig.dem, base.hdr -> base_orig.hdr."""
        with tempfile.TemporaryDirectory() as d:
            dem = Path(d) / "foo.dem"
            dem.touch()
            hdr = Path(d) / "foo.hdr"
            hdr.touch()
            do_swap_in_place(dem, dry_run=False)
            self.assertFalse(dem.exists())
            self.assertFalse(hdr.exists())
            self.assertTrue((Path(d) / "foo_orig.dem").exists())
            self.assertTrue((Path(d) / "foo_orig.hdr").exists())
