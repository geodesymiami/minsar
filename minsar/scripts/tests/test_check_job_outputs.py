#!/usr/bin/env python3
"""
Unit tests for check_job_outputs.py

Verifies that all job names from job_defaults.cfg are handled in check_job_outputs.py.
"""
import unittest
import re
import os
from pathlib import Path


def get_minsar_home():
    """Get MINSAR_HOME from environment or derive from file location."""
    minsar_home = os.getenv('MINSAR_HOME')
    if minsar_home:
        return Path(minsar_home)
    # Derive from this file's location: minsar/scripts/tests/ -> minsar root
    return Path(__file__).parent.parent.parent.parent


def parse_job_names_from_defaults_cfg():
    """
    Parse all job names from job_defaults.cfg.
    
    Returns:
        set: Set of job names defined in job_defaults.cfg
    """
    minsar_home = get_minsar_home()
    cfg_path = minsar_home / 'minsar' / 'defaults' / 'job_defaults.cfg'
    
    job_names = set()
    
    with open(cfg_path, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments, empty lines, and header lines
            if not line or line.startswith('#') or line.startswith('-'):
                continue
            # Skip the header row
            if line.startswith('jobname'):
                continue
            
            # First whitespace-separated token is the job name
            parts = line.split()
            if parts:
                job_name = parts[0]
                # Skip if it looks like a comment or header
                if not job_name.startswith('#') and not job_name.startswith('-'):
                    job_names.add(job_name)
    
    return job_names


def extract_all_string_literals_from_check_job_outputs():
    """
    Extract all string literals from check_job_outputs.py that could be job name references.
    
    Returns:
        set: Set of all string literals that look like job names
    """
    minsar_home = get_minsar_home()
    script_path = minsar_home / 'minsar' / 'scripts' / 'check_job_outputs.py'
    
    string_literals = set()
    
    # Match any string literal that looks like a job name (alphanumeric + underscore)
    pattern = re.compile(r"['\"]([a-zA-Z][a-zA-Z0-9_]*)['\"]")
    
    with open(script_path, 'r') as f:
        content = f.read()
        matches = pattern.findall(content)
        for match in matches:
            string_literals.add(match)
    
    return string_literals


def is_job_handled_in_script(job_name, script_literals):
    """
    Check if a job name from config is handled in check_job_outputs.py.
    
    A job is considered handled if:
    1. Its exact name appears in the script, OR
    2. A prefix of its name appears (e.g., 'miaplpy' handles 'miaplpy_load_data')
    
    Args:
        job_name: Job name from job_defaults.cfg
        script_literals: Set of string literals from check_job_outputs.py
        
    Returns:
        tuple: (is_handled, matching_pattern)
    """
    # Exact match
    if job_name in script_literals:
        return True, job_name
    
    # Check if any script literal is a prefix of this job name
    for literal in script_literals:
        if job_name.startswith(literal) and len(literal) > 2:
            return True, f"prefix '{literal}'"
        # Also check substring match (e.g., 'miaplpy' in 'miaplpy_load_data')
        if literal in job_name and len(literal) > 3:
            return True, f"contains '{literal}'"
    
    return False, None


class TestAllConfigJobsAreHandled(unittest.TestCase):
    """Test that all job names from job_defaults.cfg are handled in check_job_outputs.py."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures once for all tests."""
        cls.cfg_job_names = parse_job_names_from_defaults_cfg()
        cls.script_literals = extract_all_string_literals_from_check_job_outputs()
    
    def test_config_parsing_works(self):
        """Verify we successfully parsed job names from job_defaults.cfg."""
        self.assertGreater(len(self.cfg_job_names), 0, 
                          "Failed to parse any job names from job_defaults.cfg")
    
    def test_all_config_jobs_are_handled(self):
        """
        Verify all job names from job_defaults.cfg are handled in check_job_outputs.py.
        
        This ensures no job is forgotten when adding new jobs to the config.
        """
        unhandled_jobs = []
        
        for job_name in sorted(self.cfg_job_names):
            is_handled, match = is_job_handled_in_script(job_name, self.script_literals)
            if not is_handled:
                unhandled_jobs.append(job_name)
        
        self.assertEqual(len(unhandled_jobs), 0,
            f"Jobs in job_defaults.cfg not handled in check_job_outputs.py:\n"
            f"  {unhandled_jobs}\n"
            f"Add handling for these jobs in check_job_outputs.py")


if __name__ == '__main__':
    unittest.main(verbosity=2)
