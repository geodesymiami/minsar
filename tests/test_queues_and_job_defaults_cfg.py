#!/usr/bin/env python3
"""
Tests for format and parsing of minsar/defaults/queues.cfg and minsar/defaults/job_defaults.cfg.

Verifies that the code in job_submission.py and process_utilities.py that reads these files
still works. Run with:
  python -m unittest discover -s tests -p 'test_queues_and_job_defaults_cfg.py' -v
Or: ./run_all_tests.bash --python-only
"""

import os
import sys
import unittest

# Ensure MINSAR_HOME is set so defaults are found (pathObj.defaultdir, queue_config_file)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.environ.get('MINSAR_HOME'):
    os.environ['MINSAR_HOME'] = _REPO_ROOT

# Import after env so path resolution is correct
import minsar.utils.process_utilities as putils
from minsar.objects.auto_defaults import queue_config_file, supported_platforms


# Required columns used by job_submission.set_job_queue_values when reading queues.cfg
QUEUES_CFG_REQUIRED_COLUMNS = [
    'PLATFORM_NAME', 'QUEUENAME', 'CPUS_PER_NODE', 'THREADS_PER_CORE',
    'MEM_PER_NODE', 'MAX_NODES_PU', 'MAX_NODES_PJ', 'MAX_JOBS_PU', 'MAX_SUBMIT',
    'WALLTIME_FACTOR',
]
# Optional (older format used MAX_NODES_PER_JOB); rerun logic uses MAX_WALLTIME, QUEUE_AT_MAX_WALLTIME
QUEUES_CFG_OPTIONAL_COLUMNS = ['MAX_NODES_PER_JOB', 'SJOBS_STEP_MAX_TASKS', 'SJOBS_TOTAL_MAX_TASKS', 'MAX_WALLTIME', 'QUEUE_AT_MAX_WALLTIME']

# Fields required by get_config_defaults for job_defaults.cfg (used by job_submission.get_memory_walltime and rerun logic)
JOB_DEFAULTS_REQUIRED_FIELDS = [
    'c_walltime', 's_walltime', 'seconds_factor', 'c_memory', 's_memory',
    'num_threads', 'io_load', 'rerun_walltime_factor', 'switch_queue_at_max_walltime', 'rerun_walltime_factor_switch',
]


class TestQueuesCfgFormatAndParsing(unittest.TestCase):
    """Check queues.cfg format and that the reader logic used by job_submission still works."""

    def test_queues_cfg_file_exists(self):
        """queues.cfg must exist at MINSAR_HOME/minsar/defaults/queues.cfg."""
        self.assertTrue(os.path.isfile(queue_config_file),
                        f'queues.cfg not found: {queue_config_file}')

    def test_queues_cfg_has_required_header_columns(self):
        """queues.cfg first line must be header containing PLATFORM_NAME and columns used by set_job_queue_values."""
        with open(queue_config_file, 'r') as f:
            lines = f.readlines()
        self.assertGreater(len(lines), 0, 'queues.cfg is empty')
        header = lines[0].strip().split()
        self.assertEqual(header[0], 'PLATFORM_NAME',
                         'First column of queues.cfg must be PLATFORM_NAME')
        for col in QUEUES_CFG_REQUIRED_COLUMNS:
            self.assertIn(col, header, f'queues.cfg header must contain column: {col}')

    def test_queues_cfg_data_lines_match_header_width(self):
        """Each non-comment, non-empty data line must have at least as many columns as required."""
        with open(queue_config_file, 'r') as f:
            lines = f.readlines()
        header = lines[0].strip().split()
        n_required = len(QUEUES_CFG_REQUIRED_COLUMNS)
        # Build index of required columns in header (some columns may be in different order)
        max_index = max(header.index(c) for c in QUEUES_CFG_REQUIRED_COLUMNS)
        min_cols = max_index + 1
        for i, line in enumerate(lines[1:], start=2):
            raw = line.strip()
            if not raw or raw.startswith('#'):
                continue
            # Strip trailing # comment for column count
            if '#' in raw:
                raw = raw[:raw.index('#')].strip()
            parts = raw.split()
            self.assertGreaterEqual(len(parts), min_cols,
                                    f'queues.cfg line {i} has {len(parts)} columns, need at least {min_cols}')

    def test_queues_cfg_parsing_matches_job_submission_reader(self):
        """Parse queues.cfg the same way set_job_queue_values does and assert we can read a known platform row."""
        with open(queue_config_file, 'r') as f:
            lines = f.readlines()
        queue_header = None
        for line in lines:
            if line.startswith('PLATFORM_NAME'):
                queue_header = lines[0].split()
                break
        self.assertIsNotNone(queue_header, 'Header line PLATFORM_NAME not found')
        # Find first data row for a supported platform (e.g. stampede3)
        platform_name = 'stampede3'
        self.assertIn(platform_name, supported_platforms)
        found = False
        for line in lines:
            if line.startswith('#') or not line.strip():
                continue
            split_values = line.split()
            if split_values and split_values[0] == platform_name:
                default_queue = split_values[queue_header.index('QUEUENAME')]
                _ = int(split_values[queue_header.index('CPUS_PER_NODE')])
                _ = int(split_values[queue_header.index('THREADS_PER_CORE')])
                _ = int(split_values[queue_header.index('MAX_SUBMIT')])
                _ = int(split_values[queue_header.index('MEM_PER_NODE')])
                _ = float(split_values[queue_header.index('WALLTIME_FACTOR')])
                col = 'MAX_NODES_PJ' if 'MAX_NODES_PJ' in queue_header else 'MAX_NODES_PER_JOB'
                _ = int(split_values[queue_header.index(col)])
                found = True
                break
        self.assertTrue(found, f'No row for platform {platform_name} in queues.cfg')


class TestJobDefaultsCfgFormatAndParsing(unittest.TestCase):
    """Check job_defaults.cfg format and that get_config_defaults (used by job_submission) still works."""

    def test_job_defaults_cfg_loads_with_get_config_defaults(self):
        """get_config_defaults('job_defaults.cfg') must load without error."""
        config = putils.get_config_defaults(config_file='job_defaults.cfg')
        self.assertIsNotNone(config)

    def test_job_defaults_cfg_has_default_section(self):
        """job_defaults.cfg must have a 'default' section."""
        config = putils.get_config_defaults(config_file='job_defaults.cfg')
        self.assertIn('default', config.sections(),
                      'job_defaults.cfg must have section "default"')

    def test_job_defaults_cfg_default_section_has_required_fields(self):
        """default section must have all fields read by get_memory_walltime."""
        config = putils.get_config_defaults(config_file='job_defaults.cfg')
        for key in JOB_DEFAULTS_REQUIRED_FIELDS:
            self.assertTrue(config.has_option('default', key),
                            f'job_defaults.cfg [default] missing option: {key}')

    def test_job_defaults_cfg_dict_like_access_works(self):
        """Config must support dict-like access used in job_submission.get_memory_walltime."""
        config = putils.get_config_defaults(config_file='job_defaults.cfg')
        c_walltime = config['default']['c_walltime']
        c_memory = config['default']['c_memory']
        num_threads = config['default']['num_threads']
        self.assertIsInstance(c_walltime, str)
        self.assertIsInstance(c_memory, str)
        self.assertIsInstance(num_threads, str)
        # At least one known section besides default (e.g. dem_rsmas)
        self.assertIn('dem_rsmas', config.sections(),
                      'job_defaults.cfg should have section dem_rsmas')
        self.assertTrue(config.has_option('dem_rsmas', 'c_walltime'))


if __name__ == '__main__':
    unittest.main()
