#!/usr/bin/env python3
"""Step selection and project-name inference for ISCE3 workflows."""

import sys
import unittest
from pathlib import Path

import importlib.util

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from minsar.utils import isce3_steps

_SPEC = importlib.util.spec_from_file_location(
    "create_isce3_runfiles",
    _REPO / "minsar" / "src" / "minsar" / "cli" / "create_isce3_runfiles.py",
)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

infer_dataset_from_name = _MOD.infer_dataset_from_name


class TestInferDatasetFromName(unittest.TestCase):
    def test_cslc_opera_template_stem(self) -> None:
        self.assertEqual(
            infer_dataset_from_name("unittestHawaiiPunaCSLCOperaSenD87"),
            ("cslc", "opera"),
        )

    def test_safe_single_run_and_disp_aliases(self) -> None:
        self.assertEqual(infer_dataset_from_name("HawaiiPunaSAFESenD87"), ("safe", None))
        self.assertEqual(infer_dataset_from_name("HawaiiPunaCSLCSenD87.template"), ("cslc", None))
        self.assertEqual(infer_dataset_from_name("HawaiiPunaDISPS1SenD87"), ("disp", None))
        self.assertEqual(infer_dataset_from_name("HawaiiPunaDISPSenD87"), ("disp", None))

    def test_bare_name_has_no_tokens(self) -> None:
        self.assertEqual(infer_dataset_from_name("HawaiiPunaSenD87"), (None, None))


class TestStageSelection(unittest.TestCase):
    def test_post_does_not_include_dolphin_science(self) -> None:
        self.assertEqual(
            isce3_steps._post_stage_names("cslc", "opera"),
            ("reformat_disp", "dolphin_2_hdfeos5", "ingest_insarmaps"),
        )
        post = isce3_steps.selected_stage_names("cslc", "opera", phase="post")
        self.assertNotIn("disp_s1_process", post)
        self.assertIn("dolphin_2_hdfeos5", post)
        self.assertNotIn("dolphin_wrapped", post)
        self.assertIn("ingest_insarmaps", isce3_steps.selected_stage_names("safe", "single-run", phase="post"))

    def test_dostep_hdfeos5_is_single_stage(self) -> None:
        selected = isce3_steps.selected_stage_names(
            "cslc",
            "opera",
            dostep="dolphin2hdfeos5",
        )
        self.assertEqual(selected, frozenset({"dolphin_2_hdfeos5"}))

    def test_start_hdfeos5_through_end(self) -> None:
        selected = isce3_steps.selected_stage_names(
            "cslc",
            "opera",
            start="dolphin_2_hdfeos5",
        )
        self.assertEqual(
            selected,
            frozenset({"dolphin_2_hdfeos5", "ingest_insarmaps"}),
        )

    def test_download_keeps_disp_reformat_and_not_opera_reformat(self) -> None:
        download = isce3_steps.selected_stage_names("disp", "single-run", phase="download")
        self.assertIn("reformat_disp", download)
        opera_download = isce3_steps.selected_stage_names("cslc", "opera", phase="download")
        self.assertNotIn("reformat_disp", opera_download)
        self.assertIn("reformat_disp", isce3_steps.selected_stage_names("cslc", "opera", phase="post"))

    def test_dolphin_phase_still_includes_later_products(self) -> None:
        dolphin = isce3_steps.selected_stage_names("cslc", "single-run", phase="dolphin")
        self.assertIn("dolphin_wrapped", dolphin)
        self.assertIn("dolphin_2_hdfeos5", dolphin)
        self.assertNotIn("download_cslc", dolphin)


if __name__ == "__main__":
    unittest.main()
