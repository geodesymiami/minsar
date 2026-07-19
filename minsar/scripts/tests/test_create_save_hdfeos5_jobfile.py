#!/usr/bin/env python3
"""Unit tests for create_save_hdfeos5_jobfile helpers."""

import importlib.util
import unittest
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / 'create_save_hdfeos5_jobfile.py'
    spec = importlib.util.spec_from_file_location('create_save_hdfeos5_jobfile', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load_module()


class TestGetNetworkPrefix(unittest.TestCase):

    def test_delaunay_4(self):
        self.assertEqual(MOD.get_network_prefix('network_delaunay_4'), 'Del4')

    def test_single_reference(self):
        self.assertEqual(MOD.get_network_prefix('network_single_reference'), 'Sing')

    def test_sequential_3(self):
        self.assertEqual(MOD.get_network_prefix('network_sequential_3'), 'Seq3')

    def test_mini_stacks(self):
        self.assertEqual(MOD.get_network_prefix('network_mini_stacks'), 'Mini')

    def test_unknown_raises(self):
        with self.assertRaises(Exception):
            MOD.get_network_prefix('network_unknown_type')


class TestBuildJobCommands(unittest.TestCase):

    def test_contains_save_bash_and_plot_gate(self):
        cmds = MOD.build_job_commands('/scratch/proj/network_delaunay_4', 'Del4', 0.7, 0.75)
        body = '\n'.join(cmds)
        self.assertIn('cd /scratch/proj/network_delaunay_4', body)
        self.assertIn('save_miaplpy_hdfeos5.bash', body)
        self.assertIn('--prefix Del4', body)
        self.assertIn('--filter 0.7', body)
        self.assertIn('--mask-thresh 0.75', body)
        self.assertIn('mintpy\\.plot', body)
        self.assertIn('plot_mintpy_summary_pngs.py', body)
        self.assertNotIn('view.py', body)
        self.assertNotIn('save_hdfeos5.py', body)

    def test_no_filter_flag(self):
        cmds = MOD.build_job_commands('/tmp/network_single_reference', 'Sing', None, 0.6)
        body = '\n'.join(cmds)
        self.assertIn('--no-filter', body)
        self.assertNotIn('--filter ', body)

    def test_plot_gate_checks_no_false_zero(self):
        body = '\n'.join(MOD.build_job_commands('/tmp/n', 'Sing', 0.7, 0.7))
        self.assertIn('"$plot_val" == "no"', body)
        self.assertIn('"$plot_val" == "false"', body)
        self.assertIn('"$plot_val" == "0"', body)


if __name__ == '__main__':
    unittest.main()
