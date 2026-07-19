#!/usr/bin/env python3
"""Unit tests for exclude_season_slc.py."""

import importlib.util
import tempfile
import unittest
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "exclude_season_slc.py"
    spec = importlib.util.spec_from_file_location("exclude_season_slc", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load_module()


class TestListDateDirs(unittest.TestCase):
    def test_lists_yyyymmdd_dirs_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "20240115").mkdir()
            (root / "20240601").mkdir()
            (root / "excludeSeason_0101-0331").mkdir()
            (root / "excludeSeason").mkdir()
            (root / "notadate").mkdir()
            (root / "20240115.txt").write_text("x")
            dates = {p.name for p in MOD.list_slc_date_dirs(root)}
            self.assertEqual(dates, {"20240115", "20240601"})

    def test_exclude_season_dest_name(self):
        self.assertEqual(
            MOD.exclude_season_dest_name("0101-0331"),
            "excludeSeason_0101-0331",
        )


class TestMoveExcludeSeason(unittest.TestCase):
    def test_moves_winter_window(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for d in ("20231020", "20240110", "20240601", "20240901"):
                (root / d).mkdir()
            moved = MOD.move_exclude_season_slc(root, "1015-0515", dry_run=False)
            self.assertEqual(sorted(moved), ["20231020", "20240110"])
            dest = root / "excludeSeason_1015-0515"
            self.assertTrue((dest / "20231020").is_dir())
            self.assertTrue((dest / "20240110").is_dir())
            self.assertTrue((root / "20240601").is_dir())
            self.assertTrue((root / "20240901").is_dir())
            self.assertFalse((root / "20231020").exists())

    def test_dry_run_no_move(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "20240110").mkdir()
            moved = MOD.move_exclude_season_slc(root, "0101-0331", dry_run=True)
            self.assertEqual(moved, ["20240110"])
            self.assertTrue((root / "20240110").is_dir())
            self.assertFalse((root / "excludeSeason_0101-0331").exists())

    def test_invalid_season_raises(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                MOD.move_exclude_season_slc(Path(td), "bad", dry_run=True)


if __name__ == "__main__":
    unittest.main()
