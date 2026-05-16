#!/usr/bin/env python3
"""Unit tests for pairs_misreg ESD handling in check_job_outputs.py."""
from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
os.environ.setdefault("MINSAR_HOME", _REPO_ROOT)


def _bootstrap_stubs_before_import():
    """check_job_outputs imports heavy stacks; stubs avoid numpy/h5py/etc. at import."""
    minsar_pkg = sys.modules.setdefault("minsar", types.ModuleType("minsar"))
    if getattr(minsar_pkg, "__path__", None) is None:
        minsar_pkg.__path__ = [os.path.join(_REPO_ROOT, "minsar")]

    utils_pkg = sys.modules.setdefault("minsar.utils", types.ModuleType("minsar.utils"))
    if getattr(utils_pkg, "__path__", None) is None:
        utils_pkg.__path__ = [os.path.join(_REPO_ROOT, "minsar", "utils")]

    def _check_words(filepath, phrase):
        with open(filepath, encoding="utf-8", errors="replace") as fh:
            return phrase in fh.read()

    js_mod = types.ModuleType("minsar.job_submission")
    js_mod.check_words_in_file = _check_words
    sys.modules["minsar.job_submission"] = js_mod

    putils_stub = types.ModuleType("minsar.utils.process_utilities")
    sys.modules["minsar.utils.process_utilities"] = putils_stub

    sys.modules.setdefault("numpy", MagicMock())

    nats_stub = types.ModuleType("natsort")
    nats_stub.natsorted = sorted
    sys.modules["natsort"] = nats_stub

    scripts_pkg = sys.modules.setdefault("minsar.scripts", types.ModuleType("minsar.scripts"))
    if getattr(scripts_pkg, "__path__", None) is None:
        scripts_pkg.__path__ = [os.path.join(_REPO_ROOT, "minsar", "scripts")]


_bootstrap_stubs_before_import()

from minsar.scripts.check_job_outputs import (
    ESD_PAIRS_MISREG_PHRASE,
    USER_ERROR_ESD_PAIRS_MISREG,
    job_output_canonical_path,
    record_pairs_misreg_esd_errors,
)


class TestPairsMisregEsd(unittest.TestCase):
    @patch("builtins.print")
    def test_record_adds_path_and_matched_line(self, _mock_print):
        with tempfile.TemporaryDirectory() as td:
            ef = os.path.join(td, "run_07_pairs_misreg_0_20170101_20170202_1.e")
            with open(ef, "w", encoding="utf-8") as f:
                f.write(
                    f"some noise\n{ESD_PAIRS_MISREG_PHRASE}\n"
                    "Traceback (most recent call last):\n"
                )
            matched = []
            diag = set()
            record_pairs_misreg_esd_errors("run_07_pairs_misreg_0", [ef], matched, diag)
            self.assertEqual(diag, {job_output_canonical_path(ef)})
            self.assertEqual(len(matched), 1)
            self.assertIn(USER_ERROR_ESD_PAIRS_MISREG, matched[0])
            self.assertIn(os.path.basename(ef), matched[0])

    def test_non_pairs_job_noop(self):
        with tempfile.TemporaryDirectory() as td:
            ef = os.path.join(td, "run_07_other_step_0.e")
            with open(ef, "w", encoding="utf-8") as f:
                f.write(f"{ESD_PAIRS_MISREG_PHRASE}\n")
            matched = []
            diag = set()
            record_pairs_misreg_esd_errors("run_07_other_step_0", [ef], matched, diag)
            self.assertFalse(diag)
            self.assertFalse(matched)

    @patch("builtins.print")
    def test_generic_traceback_not_counted_when_esd_diagnosed(self, _mock_print):
        from minsar.job_submission import check_words_in_file

        with tempfile.TemporaryDirectory() as td:
            ef = os.path.join(td, "run_99_pairs_misreg_x_20170101_20170202_1.e")
            with open(ef, "w", encoding="utf-8") as f:
                f.write(
                    f"{ESD_PAIRS_MISREG_PHRASE}\nTraceback (most recent call last):\n"
                )
            matched = []
            diag = set()
            record_pairs_misreg_esd_errors("run_99_pairs_misreg_x", [ef], matched, diag)
            file = ef
            error_string = "Traceback"
            skip_tb = (
                error_string == "Traceback"
                and job_output_canonical_path(file) in diag
            )
            generic_hits = 0
            if not skip_tb and check_words_in_file(file, error_string):
                generic_hits += 1
            self.assertEqual(generic_hits, 0)


if __name__ == "__main__":
    unittest.main()
