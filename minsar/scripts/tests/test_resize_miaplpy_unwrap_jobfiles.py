#!/usr/bin/env python3
"""Unit tests for resize_miaplpy_unwrap_jobfiles helpers (tiling / PPN)."""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from minsar.scripts.resize_miaplpy_unwrap_jobfiles import (
    BYTES_PER_PIXEL,
    RUN05_BASE,
    compute_ppn,
    mem_per_task_mib,
    parse_num_tiles_from_command,
    parse_num_tiles_from_run_files,
    parse_num_tiles_from_tasks,
    plan_job_split,
)


class TestParseNumTiles(unittest.TestCase):
    def test_default_when_missing(self):
        self.assertEqual(parse_num_tiles_from_command('unwrap_ifgram.py --ifg x.int'), 1)

    def test_explicit(self):
        cmd = 'unwrap_ifgram.py --num_tiles 25 --ifg x.int'
        self.assertEqual(parse_num_tiles_from_command(cmd), 25)

    def test_tasks_take_maximum(self):
        tasks = [
            'unwrap_ifgram.py --num_tiles 1 --ifg a.int\n',
            'unwrap_ifgram.py --num_tiles 25 --ifg b.int\n',
        ]
        self.assertEqual(parse_num_tiles_from_tasks(tasks), 25)

    def test_empty_tasks(self):
        self.assertEqual(parse_num_tiles_from_tasks([]), 1)

    def test_run_files_prefer_max_over_stale_master(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / RUN05_BASE).write_text(
                'unwrap_ifgram.py --num_tiles 1 --ifg a.int\n'
            )
            (run_dir / f'{RUN05_BASE}_0').write_text(
                'unwrap_ifgram.py --num_tiles 25 --ifg b.int\n'
            )
            tasks = ['unwrap_ifgram.py --num_tiles 1 --ifg a.int\n']
            self.assertEqual(parse_num_tiles_from_run_files(run_dir, tasks), 25)


class TestMemPerTask(unittest.TestCase):
    def test_single_tile_full_scene(self):
        length, width = 3692, 12136
        expected = length * width * BYTES_PER_PIXEL / (1024.0 ** 2)
        self.assertAlmostEqual(mem_per_task_mib(length, width, BYTES_PER_PIXEL), expected)
        self.assertAlmostEqual(
            mem_per_task_mib(length, width, BYTES_PER_PIXEL, num_tiles=1), expected
        )

    def test_tiled_divides_by_num_tiles(self):
        length, width = 3692, 12136
        full = mem_per_task_mib(length, width, BYTES_PER_PIXEL, num_tiles=1)
        tiled = mem_per_task_mib(length, width, BYTES_PER_PIXEL, num_tiles=25)
        self.assertAlmostEqual(tiled, full / 25.0)


class TestComputePpn(unittest.TestCase):
    def test_single_tile_memory_limited(self):
        # ~17.5 GiB task on 192 GB / 48 CPU node -> raw PPN 10, minus margin 2 -> 8
        mem_mib = mem_per_task_mib(3692, 12136, BYTES_PER_PIXEL, num_tiles=1)
        ppn = compute_ppn(mem_mib, 192000, 48, num_tiles=1)
        self.assertEqual(ppn, 8)

    def test_etna_sized_scene_avoids_cliff_ppn(self):
        # EtnaSenD124: 3558x7242, observed ~9.5 GiB peak; PPN=18 caused 3/64 OOM
        mem_mib = mem_per_task_mib(3558, 7242, BYTES_PER_PIXEL, num_tiles=1)
        ppn = compute_ppn(mem_mib, 192000, 48, num_tiles=1)
        self.assertEqual(ppn, 16)

    def test_big1_scene_uses_margin_two(self):
        # miaplpy_Big1 2851x6354: margin 1 gave PPN=25 and 1/64 snaphu OOM
        mem_mib = mem_per_task_mib(2851, 6354, BYTES_PER_PIXEL, num_tiles=1)
        ppn = compute_ppn(mem_mib, 192000, 48, num_tiles=1)
        self.assertEqual(ppn, 24)

    def test_tiled_25_cpu_capped_to_one(self):
        # OPERA-like: --nproc 25 on 48-core SKX -> at most one unwrap per node
        mem_mib = mem_per_task_mib(3692, 12136, BYTES_PER_PIXEL, num_tiles=25)
        ppn = compute_ppn(mem_mib, 192000, 48, num_tiles=25)
        self.assertEqual(ppn, 1)

    def test_tiled_2_memory_and_cpu_cap(self):
        mem_mib = mem_per_task_mib(3692, 12136, BYTES_PER_PIXEL, num_tiles=2)
        ppn = compute_ppn(mem_mib, 192000, 48, num_tiles=2)
        mem_ppn = max(1, int(math.floor(192000 / mem_mib)) - 2)
        cpu_ppn = 48 // 2
        self.assertEqual(ppn, min(mem_ppn, cpu_ppn))
        self.assertEqual(ppn, 19)


class TestPlanJobSplitTiled(unittest.TestCase):
    def test_ppn1_splits_across_max_nodes(self):
        # 84 tasks, PPN=1, MAX_NODES=16 -> multiple jobfiles
        plans = plan_job_split(84, ppn=1, max_nodes_pj=16, scale_node_number=True, existing_nodes=9)
        self.assertGreaterEqual(len(plans), 2)
        self.assertEqual(sum(p[1] - p[0] for p in plans), 84)
        self.assertTrue(all(p[2] <= 16 for p in plans))


if __name__ == '__main__':
    unittest.main()
