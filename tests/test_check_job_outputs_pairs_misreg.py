#!/usr/bin/env python3
"""Unit tests for pairs_misreg ESD handling in check_job_outputs.py."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_CHECK_JOB_OUTPUTS = os.path.join(_REPO_ROOT, "minsar", "scripts", "check_job_outputs.py")
os.environ.setdefault("MINSAR_HOME", _REPO_ROOT)

_MISSING = object()
_STUBBED_MODULES: dict[str, object] = {}


def _stash_module(name: str, module: object) -> None:
    if name not in _STUBBED_MODULES:
        _STUBBED_MODULES[name] = sys.modules.get(name, _MISSING)
    sys.modules[name] = module


def _bootstrap_stubs() -> None:
    """Stubs only for loading check_job_outputs; restored in tearDown."""
    minsar_pkg = types.ModuleType("minsar")
    minsar_pkg.__path__ = [os.path.join(_REPO_ROOT, "minsar")]
    _stash_module("minsar", minsar_pkg)

    utils_pkg = types.ModuleType("minsar.utils")
    utils_pkg.__path__ = [os.path.join(_REPO_ROOT, "minsar", "utils")]
    _stash_module("minsar.utils", utils_pkg)

    def _check_words(filepath, phrase):
        with open(filepath, encoding="utf-8", errors="replace") as fh:
            return phrase in fh.read()

    js_mod = types.ModuleType("minsar.job_submission")
    js_mod.check_words_in_file = _check_words
    _stash_module("minsar.job_submission", js_mod)

    _stash_module("minsar.utils.process_utilities", types.ModuleType("minsar.utils.process_utilities"))

    if "numpy" not in sys.modules:
        _stash_module("numpy", MagicMock())

    nats_stub = types.ModuleType("natsort")
    nats_stub.natsorted = sorted
    _stash_module("natsort", nats_stub)

    scripts_pkg = types.ModuleType("minsar.scripts")
    scripts_pkg.__path__ = [os.path.join(_REPO_ROOT, "minsar", "scripts")]
    _stash_module("minsar.scripts", scripts_pkg)


def _restore_stubbed_modules() -> None:
    for name, previous in _STUBBED_MODULES.items():
        if previous is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous  # type: ignore[assignment]
    _STUBBED_MODULES.clear()


def _load_check_job_outputs():
    spec = importlib.util.spec_from_file_location("check_job_outputs_testmod", _CHECK_JOB_OUTPUTS)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPairsMisregEsd(unittest.TestCase):
    def setUp(self):
        _bootstrap_stubs()
        self.cjo = _load_check_job_outputs()

    def tearDown(self):
        _restore_stubbed_modules()

    @patch("builtins.print")
    def test_record_adds_path_and_matched_line(self, _mock_print):
        ef = None
        with tempfile.TemporaryDirectory() as td:
            ef = os.path.join(td, "run_07_pairs_misreg_0_20170101_20170202_1.e")
            with open(ef, "w", encoding="utf-8") as f:
                f.write(
                    f"some noise\n{self.cjo.ESD_PAIRS_MISREG_PHRASE}\n"
                    "Traceback (most recent call last):\n"
                )
            matched = []
            diag = set()
            self.cjo.record_pairs_misreg_esd_errors("run_07_pairs_misreg_0", [ef], matched, diag)
            self.assertEqual(diag, {self.cjo.job_output_canonical_path(ef)})
            self.assertEqual(len(matched), 1)
            self.assertIn(self.cjo.USER_ERROR_ESD_PAIRS_MISREG, matched[0])
            self.assertIn(os.path.basename(ef), matched[0])

    def test_non_pairs_job_noop(self):
        with tempfile.TemporaryDirectory() as td:
            ef = os.path.join(td, "run_07_other_step_0.e")
            with open(ef, "w", encoding="utf-8") as f:
                f.write(f"{self.cjo.ESD_PAIRS_MISREG_PHRASE}\n")
            matched = []
            diag = set()
            self.cjo.record_pairs_misreg_esd_errors("run_07_other_step_0", [ef], matched, diag)
            self.assertFalse(diag)
            self.assertFalse(matched)

    @patch("builtins.print")
    def test_generic_traceback_not_counted_when_esd_diagnosed(self, _mock_print):
        check_words_in_file = sys.modules["minsar.job_submission"].check_words_in_file

        with tempfile.TemporaryDirectory() as td:
            ef = os.path.join(td, "run_99_pairs_misreg_x_20170101_20170202_1.e")
            with open(ef, "w", encoding="utf-8") as f:
                f.write(
                    f"{self.cjo.ESD_PAIRS_MISREG_PHRASE}\nTraceback (most recent call last):\n"
                )
            matched = []
            diag = set()
            self.cjo.record_pairs_misreg_esd_errors("run_99_pairs_misreg_x", [ef], matched, diag)
            file = ef
            error_string = "Traceback"
            skip_tb = (
                error_string == "Traceback"
                and self.cjo.job_output_canonical_path(file) in diag
            )
            generic_hits = 0
            if not skip_tb and check_words_in_file(file, error_string):
                generic_hits += 1
            self.assertEqual(generic_hits, 0)


if __name__ == "__main__":
    unittest.main()
