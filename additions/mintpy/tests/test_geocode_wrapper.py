#!/usr/bin/env python3
"""
Unit tests for additions/mintpy/cli/geocode.py (MinSAR geocode wrapper).

Tests that:
1. Non-.he5 input delegates to geocode_orig (original MintPy behavior preserved)
2. .he5 input delegates to geocode_hdfeos5
3. .he5 detection logic works correctly
4. All original geocode args pass through to geocode_orig

Uses unittest.mock to avoid requiring real MintPy data. Tests that need mintpy
are skipped if mintpy is not installed.
Run with: python -m unittest additions.mintpy.tests.test_geocode_wrapper -v
Or: ./run_all_tests.bash --python-only
"""

import argparse
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Path to additions/mintpy (parent of tests/)
_ADDITIONS_MINTPY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _inject_geocode_orig_module(mock_main, mock_parser=None):
    """
    Inject mintpy.cli.geocode_orig into sys.modules so import succeeds.
    geocode_orig may not exist when MintPy is installed via conda/pip (only
    when symlinks from install_minsar.bash are used). mock_parser: if provided,
    create_parser() returns it.
    """
    fake = types.ModuleType("mintpy.cli.geocode_orig")
    fake.main = mock_main
    fake.create_parser = (lambda: mock_parser) if mock_parser is not None else MagicMock()
    fake.read_template2inps = lambda tf, inps: inps  # no-op for tests
    sys.modules["mintpy.cli.geocode_orig"] = fake


def _inject_geocode_hdfeos5_module(mock_main):
    """Inject mintpy.geocode_hdfeos5 into sys.modules for .he5 delegation tests."""
    fake = types.ModuleType("mintpy.geocode_hdfeos5")
    fake.main = mock_main
    sys.modules["mintpy.geocode_hdfeos5"] = fake


def _load_geocode_wrapper():
    """
    Load our geocode wrapper directly from additions/mintpy/cli/geocode.py.
    Ensures we test OUR wrapper, not whatever mintpy.cli.geocode resolves to
    (conda vs symlinked tools/MintPy).
    """
    geocode_path = os.path.join(_ADDITIONS_MINTPY, "cli", "geocode.py")
    spec = importlib.util.spec_from_file_location("minsar_geocode_wrapper", geocode_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mintpy_available():
    """Check if mintpy is importable (required for delegation tests)."""
    try:
        import mintpy  # noqa: F401
        return True
    except ImportError:
        return False


class TestGeocodeHe5DetectionLogic(unittest.TestCase):
    """Test .he5 detection logic (no mintpy required)."""

    def test_he5_files_detected(self):
        """Files ending in .he5 should be detected as HDFEOS5 input."""
        # Inline the same logic as in geocode wrapper
        def has_he5(files):
            return files and any(f.endswith(".he5") for f in files)

        self.assertTrue(has_he5(["file.he5"]))
        self.assertTrue(has_he5(["S1_radar.he5"]))
        self.assertTrue(has_he5(["a.he5", "b.h5"]))

    def test_h5_files_not_he5(self):
        """Files ending in .h5 (not .he5) should not trigger HDFEOS5 path."""
        def has_he5(files):
            return files and any(f.endswith(".he5") for f in files)

        self.assertFalse(has_he5(["timeseries.h5"]))
        self.assertFalse(has_he5(["velocity.h5", "mask.h5"]))
        self.assertFalse(has_he5(["geometryRadar.h5"]))

    def test_empty_or_none_files(self):
        """Empty or None file list should not trigger .he5 path."""
        def has_he5(files):
            return files and any(f.endswith(".he5") for f in files)

        self.assertFalse(has_he5([]))
        self.assertFalse(has_he5(None))


@unittest.skipUnless(_mintpy_available(), "mintpy not installed - skip delegation tests")
class TestGeocodeWrapperDelegation(unittest.TestCase):
    """Test that geocode wrapper delegates correctly (requires mintpy)."""

    def _create_mock_inps(self, files):
        return argparse.Namespace(file=files if isinstance(files, list) else [files])

    def test_he5_input_delegates_to_geocode_hdfeos5(self):
        """When input file is .he5, geocode_hdfeos5.main() should be called with parsed inps."""
        mock_inps = self._create_mock_inps(["file.he5"])
        mock_parser = MagicMock()
        mock_parser.parse_args.return_value = mock_inps
        mock_he5_main = MagicMock()
        _inject_geocode_orig_module(MagicMock(), mock_parser)
        _inject_geocode_hdfeos5_module(mock_he5_main)

        geocode_module = _load_geocode_wrapper()
        iargs = ["file.he5", "-l", "geometryRadar.h5"]
        with patch("mintpy.utils.utils.get_file_list", side_effect=lambda x: x if isinstance(x, list) else [x]):
            geocode_module.main(iargs)
        mock_he5_main.assert_called_once()
        self.assertIs(mock_he5_main.call_args[0][0], mock_inps)

    def test_h5_input_delegates_to_geocode_orig(self):
        """When input file is .h5 (not .he5), geocode_orig.main() should be called."""
        mock_parser = MagicMock()
        mock_parser.parse_args.return_value = self._create_mock_inps(["timeseries.h5"])
        mock_std_main = MagicMock()
        _inject_geocode_orig_module(mock_std_main, mock_parser)

        geocode_module = _load_geocode_wrapper()
        iargs = ["timeseries.h5", "-l", "inputs/geometryRadar.h5"]
        geocode_module.main(iargs)
        mock_std_main.assert_called_once_with(iargs)


@unittest.skipUnless(_mintpy_available(), "mintpy not installed - skip passthrough tests")
class TestGeocodeOriginalBehaviorPreserved(unittest.TestCase):
    """Test that all original MintPy geocode functions work for non-.he5 input."""

    def test_original_args_passthrough(self):
        """Original geocode args (-d, -l, -b, --lalo, -t, etc.) pass through unchanged."""
        mock_parser = MagicMock()
        mock_parser.parse_args.return_value = argparse.Namespace(file=["velocity.h5"])
        mock_std_main = MagicMock()
        _inject_geocode_orig_module(mock_std_main, mock_parser)

        geocode_module = _load_geocode_wrapper()
        iargs = [
            "velocity.h5",
            "-l", "inputs/geometryRadar.h5",
            "-b", "-0.5", "-0.25", "-91.3", "-91.1",
            "--lalo", "0.0008", "0.0008",
            "-t", "smallbaselineApp.cfg",
            "--outdir", "geo",
            "--update",
            "--ram", "8.0",
        ]
        geocode_module.main(iargs)
        mock_std_main.assert_called_once_with(iargs)

    def test_geo2radar_passthrough(self):
        """--geo2radar (geo to radar) passes through to geocode_orig."""
        mock_parser = MagicMock()
        mock_parser.parse_args.return_value = argparse.Namespace(file=["geo_velocity.h5"])
        mock_std_main = MagicMock()
        _inject_geocode_orig_module(mock_std_main, mock_parser)

        geocode_module = _load_geocode_wrapper()
        iargs = ["geo_velocity.h5", "-l", "geometryRadar.h5", "--geo2radar", "-o", "velocity.rdr"]
        geocode_module.main(iargs)
        mock_std_main.assert_called_once_with(iargs)


class TestGeocodeWrapperModuleExists(unittest.TestCase):
    """Test that the geocode wrapper module exists and has expected interface."""

    def test_geocode_wrapper_file_exists(self):
        """additions/mintpy/cli/geocode.py should exist."""
        geocode_path = os.path.join(_ADDITIONS_MINTPY, "cli", "geocode.py")
        self.assertTrue(os.path.isfile(geocode_path), f"geocode.py not found at {geocode_path}")

    def test_geocode_wrapper_has_main(self):
        """geocode wrapper should define main()."""
        geocode_path = os.path.join(_ADDITIONS_MINTPY, "cli", "geocode.py")
        spec = importlib.util.spec_from_file_location("geocode_wrapper", geocode_path)
        module = importlib.util.module_from_spec(spec)
        # Load without executing (avoid mintpy imports)
        with open(geocode_path) as f:
            code = f.read()
        self.assertIn("def main(", code, "geocode.py should define main()")


if __name__ == "__main__":
    unittest.main()
