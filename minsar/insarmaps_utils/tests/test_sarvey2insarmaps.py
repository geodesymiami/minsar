#!/usr/bin/env python3
"""Unit tests for sarvey2insarmaps ingest filename helpers."""
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("MINSAR_HOME", _REPO_ROOT)
os.environ.setdefault("SSARAHOME", _REPO_ROOT)

password_mod = types.ModuleType("password_config")
password_mod.docker_insaruser = "user"
password_mod.docker_insarpass = "pass"
password_mod.docker_databasepass = "dbpass"
password_mod.docker_databaseuser = "dbuser"
sys.modules["password_config"] = password_mod

import sarvey2insarmaps as s2i


DATASET = "TSX_000_20170923_20211006_N2593W08013_N2592W08013_N2592W08012_N2593W08012"


class TestIngestBasename(unittest.TestCase):
    def test_no_suffix_or_output_tag(self):
        self.assertEqual(s2i.build_ingest_basename(DATASET), DATASET)

    def test_user_suffix_only(self):
        self.assertEqual(
            s2i.build_ingest_basename(DATASET, user_suffix="thermal"),
            f"{DATASET}_thermal",
        )

    def test_output_dir_tag_and_user_suffix(self):
        self.assertEqual(
            s2i.build_ingest_basename(DATASET, output_suffix="coh80", user_suffix="thermal"),
            f"{DATASET}_coh80_thermal",
        )

    def test_csv_filename_with_suffix(self):
        self.assertEqual(
            s2i.build_ingest_csv_filename(DATASET, user_suffix="thermal"),
            f"{DATASET}_thermal.csv",
        )

    def test_csv_filename_with_suffix_and_geocorr(self):
        self.assertEqual(
            s2i.build_ingest_csv_filename(DATASET, user_suffix="thermal", geocorr=True),
            f"{DATASET}_thermal_geocorr.csv",
        )

    def test_normalize_user_suffix_strips_underscores(self):
        self.assertEqual(s2i.normalize_user_suffix("_thermal_"), "thermal")

    def test_normalize_user_suffix_rejects_empty(self):
        with self.assertRaisesRegex(ValueError, "non-empty"):
            s2i.normalize_user_suffix("   ")

    def test_normalize_user_suffix_rejects_path_separators(self):
        with self.assertRaisesRegex(ValueError, "path separators"):
            s2i.normalize_user_suffix("bad/name")


if __name__ == "__main__":
    unittest.main()
