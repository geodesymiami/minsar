#!/usr/bin/env python3
"""
Unit tests for minsar/utils/system_utils.py

This is a colocated test file in the standard Python structure:
    minsar/utils/tests/test_system_utils.py

Run with:
    python -m unittest minsar.utils.tests.test_system_utils -v
    
Or run all Python tests:
    ./run_all_tests.bash --python-only
"""

import unittest
import sys
import os
import tempfile
import warnings

# Add minsar to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Suppress resource warnings from subprocess in tests
warnings.filterwarnings("ignore", category=ResourceWarning)


class TestSystemUtils(unittest.TestCase):
    """Tests for minsar/utils/system_utils.py
    
    These tests verify the system detection utilities work correctly.
    They have no external dependencies beyond the Python standard library.
    """

    def test_detect_operating_system_returns_string(self):
        """detect_operating_system should return a non-empty string"""
        from minsar.utils.system_utils import detect_operating_system
        
        result = detect_operating_system()
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_detect_operating_system_known_values(self):
        """detect_operating_system should return expected OS names"""
        from minsar.utils.system_utils import detect_operating_system
        
        result = detect_operating_system()
        # Should be one of these known values
        known_systems = ["macOS", "Linux", "Windows"]
        self.assertIn(result, known_systems, 
                      f"Unexpected OS: {result}")

    def test_are_we_on_slurm_system_returns_valid_value(self):
        """are_we_on_slurm_system should return False or a valid status string"""
        from minsar.utils.system_utils import are_we_on_slurm_system
        
        result = are_we_on_slurm_system()
        valid_values = [False, "compute_node", "login_node"]
        self.assertIn(result, valid_values,
                      f"Unexpected SLURM status: {result}")

    def test_get_system_name_returns_string(self):
        """get_system_name should return a non-empty string"""
        from minsar.utils.system_utils import get_system_name
        
        result = get_system_name()
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)
        self.assertNotEqual(result, "unknown")

    def test_get_system_info_returns_dict(self):
        """get_system_info should return a dictionary with expected keys"""
        from minsar.utils.system_utils import get_system_info
        
        result = get_system_info()
        self.assertIsInstance(result, dict)
        
        # Check for expected keys
        expected_keys = ["os", "system_name", "slurm_status", "python_version", "architecture"]
        for key in expected_keys:
            self.assertIn(key, result, f"Missing expected key: {key}")

    def test_get_system_info_python_version_format(self):
        """get_system_info python_version should be in X.Y.Z format"""
        from minsar.utils.system_utils import get_system_info
        
        result = get_system_info()
        python_version = result["python_version"]
        
        # Should have at least major.minor format
        parts = python_version.split(".")
        self.assertGreaterEqual(len(parts), 2, 
                                f"Invalid version format: {python_version}")
        # Major and minor should be numeric
        self.assertTrue(parts[0].isdigit(), f"Major version not numeric: {parts[0]}")
        self.assertTrue(parts[1].isdigit(), f"Minor version not numeric: {parts[1]}")

    def test_get_all_ip_addresses_returns_dict(self):
        """get_all_ip_addresses should return a dictionary"""
        from minsar.utils.system_utils import get_all_ip_addresses
        
        result = get_all_ip_addresses()
        self.assertIsInstance(result, dict)
        # Should have at least public_ip key (even if unavailable)
        self.assertIn("public_ip", result)


class TestStandaloneUtilityFunctions(unittest.TestCase):
    """Tests for utility functions that can be tested in isolation.
    
    These tests don't require the full minsar environment with all dependencies.
    """

    def test_file_counting(self):
        """Test basic file line counting logic"""
        # Create a temporary file with known number of lines
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("line1\n")
            f.write("line2\n")
            f.write("line3\n")
            temp_path = f.name
        
        try:
            # Simple line count implementation (same as file_len)
            with open(temp_path, 'r') as file:
                line_count = len(file.readlines())
            self.assertEqual(line_count, 3)
        finally:
            os.unlink(temp_path)

    def test_walltime_multiplication_logic(self):
        """Test walltime multiplication logic"""
        # Inline implementation of multiply_walltime for testing
        def multiply_walltime(wall_time, factor):
            import math
            wall_time_parts = [int(s) for s in wall_time.split(':')]
            hours = wall_time_parts[0]
            minutes = wall_time_parts[1]
            try:
                seconds = wall_time_parts[2]
            except:
                seconds = 0
            seconds_total = seconds + minutes * 60 + hours * 3600
            seconds_new = seconds_total * factor
            hours = math.floor(seconds_new / 3600)
            minutes = math.floor((seconds_new - hours * 3600) / 60)
            seconds = math.floor((seconds_new - hours * 3600 - minutes * 60))
            if len(wall_time_parts) == 2:
                return '{:02d}:{:02d}'.format(hours, minutes)
            else:
                return '{:02d}:{:02d}:{:02d}'.format(hours, minutes, seconds)
        
        # Test cases
        self.assertEqual(multiply_walltime("01:00:00", 2), "02:00:00")
        self.assertEqual(multiply_walltime("00:30:00", 3), "01:30:00")
        self.assertEqual(multiply_walltime("01:30", 2), "03:00")
        self.assertEqual(multiply_walltime("00:15:30", 4), "01:02:00")

    def test_project_name_extraction_logic(self):
        """Test project name extraction from file paths"""
        # Inline implementation of get_project_name for testing
        def get_project_name(custom_template_file):
            project_name = None
            if custom_template_file:
                project_name = os.path.splitext(
                    os.path.basename(custom_template_file))[0]
            return project_name
        
        # Test cases
        self.assertEqual(get_project_name("/path/to/GalapagosSenDT128.template"), 
                        "GalapagosSenDT128")
        self.assertEqual(get_project_name("/home/user/samples/TestProject.template"), 
                        "TestProject")
        self.assertIsNone(get_project_name(None))
        self.assertIsNone(get_project_name(""))

    def test_project_name_parsing_logic(self):
        """Test project name parsing into components"""
        import re
        
        # Inline implementation of split_project_name for testing
        def split_project_name(project_name):
            location_name, sat_track = re.split('SenAT|SenDT', project_name)
            if 'SenAT' in project_name:
                sat_direction = 'SenAT'
            elif 'SenDT' in project_name:
                sat_direction = 'SenDT'
            else:
                raise Exception('ERROR project name must contain SenDT or SenAT')
            return location_name, sat_direction, sat_track
        
        # Test ascending track
        loc, sat, track = split_project_name("GalapagosSenAT128")
        self.assertEqual(loc, "Galapagos")
        self.assertEqual(sat, "SenAT")
        self.assertEqual(track, "128")
        
        # Test descending track
        loc, sat, track = split_project_name("PichinchaSenDT142")
        self.assertEqual(loc, "Pichincha")
        self.assertEqual(sat, "SenDT")
        self.assertEqual(track, "142")
        
        # Test invalid name raises exception
        with self.assertRaises(Exception):
            split_project_name("InvalidProjectName")

    def test_time_summation_logic(self):
        """Test time summation logic"""
        import math
        
        # Inline implementation of sum_time for testing
        def sum_time(time_str_list):
            if time_str_list:
                seconds_sum = 0
                for item in time_str_list:
                    item_parts = item.split(':')
                    try:
                        days, hours = item_parts[0].split('-')
                        hours = int(days) * 24 + int(hours)
                    except:
                        hours = int(item_parts[0])
                    minutes = int(item_parts[1])
                    try:
                        seconds = int(item_parts[2])
                    except:
                        seconds = 0
                    seconds_total = seconds + minutes * 60 + hours * 3600
                    seconds_sum = seconds_sum + seconds_total
                hours = math.floor(seconds_sum / 3600)
                minutes = math.floor((seconds_sum - hours * 3600) / 60)
                seconds = math.floor((seconds_sum - hours * 3600 - minutes * 60))
                if len(item_parts) == 2:
                    return '{:02d}:{:02d}'.format(hours, minutes)
                else:
                    return '{:02d}:{:02d}:{:02d}'.format(hours, minutes, seconds)
            else:
                return '00:00:00'
        
        # Test cases
        self.assertEqual(sum_time(["01:00:00", "00:30:00", "00:15:00"]), "01:45:00")
        self.assertEqual(sum_time([]), "00:00:00")
        self.assertEqual(sum_time(["1-00:00:00", "0-12:00:00"]), "36:00:00")


class TestEnvironmentDetection(unittest.TestCase):
    """Tests that verify the testing environment itself"""

    def test_python_version_is_3(self):
        """Verify Python 3 is being used"""
        self.assertGreaterEqual(sys.version_info.major, 3,
                                "Python 3 is required")

    def test_minsar_directory_exists(self):
        """Verify minsar package directory exists"""
        # This test file is at minsar/utils/tests/test_system_utils.py
        # So minsar dir is: tests -> utils -> minsar
        minsar_path = os.path.join(os.path.dirname(__file__), '..', '..')
        self.assertTrue(os.path.isdir(minsar_path),
                        f"minsar directory not found at {minsar_path}")

    def test_system_utils_module_exists(self):
        """Verify system_utils module can be imported"""
        try:
            from minsar.utils import system_utils
            self.assertTrue(hasattr(system_utils, 'detect_operating_system'))
        except ImportError as e:
            self.fail(f"Failed to import system_utils: {e}")


if __name__ == '__main__':
    unittest.main()
