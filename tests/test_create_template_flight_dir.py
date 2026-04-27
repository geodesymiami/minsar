#!/usr/bin/env python3
"""Tests for create_template.py --flight-dir."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_CT_PATH = _REPO / "minsar" / "scripts" / "create_template.py"


def _load_create_template():
    spec = importlib.util.spec_from_file_location("create_template", _CT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ct = _load_create_template()

_MINI_DUMMY = """ssaraopt.relativeOrbit             = 109
ssaraopt.startDate                 = 20141001
ssaraopt.endDate                   = auto
miaplpy.subset.lalo                  = 0:1,2:3
"""

_COVERAGE = {
    "asc_relorbit": 11,
    "asc_label": "A11",
    "desc_relorbit": 22,
    "desc_label": "D22",
    "processing_subset": "1.0:2.0,3.0:4.0",
}


def _make_dummy(tmp: Path) -> Path:
    p = tmp / "dummy.template"
    p.write_text(_MINI_DUMMY)
    return p


class TestFlightDirBehavior(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._orig_cwd)

    def _run_in_tmp(self, args: list[str], tmp: Path, *, dummy: Path):
        os.chdir(tmp)
        argv = [
            "36.331:36.486,25.318:25.492",
            "Proj",
            *args,
        ]
        with mock.patch.object(ct, "_get_dummy_template_path", return_value=dummy):
            with mock.patch.object(
                ct, "_run_get_sar_coverage", return_value=dict(_COVERAGE)
            ):
                with mock.patch.object(ct, "_run_create_opposite_orbit") as m_opp:
                    rc, _path = ct.main(argv)
        self.assertEqual(rc, 0)
        return m_opp

    def test_asc_writes_one_template_and_skips_opposite(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            dummy = _make_dummy(tmp)
            m_opp = self._run_in_tmp(["--flight-dir", "asc"], tmp, dummy=dummy)
            m_opp.assert_not_called()
            out = tmp / "ProjA11.template"
            self.assertTrue(out.is_file(), f"missing {out}")
            text = out.read_text()
            self.assertIn("= 11", text)
            self.assertTrue(
                text.endswith("\n"),
                "template must end with newline (consistent with opposite-orbit awk output)",
            )
            self.assertNotIn("ProjD22.template", [p.name for p in tmp.iterdir()])

    def test_desc_writes_one_desc_template_and_skips_opposite(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            dummy = _make_dummy(tmp)
            m_opp = self._run_in_tmp(["--flight-dir", "desc"], tmp, dummy=dummy)
            m_opp.assert_not_called()
            out = tmp / "ProjD22.template"
            self.assertTrue(out.is_file(), f"missing {out}")
            text = out.read_text()
            self.assertIn("= 22", text)
            self.assertTrue(text.endswith("\n"))

    def test_both_calls_opposite_orbit(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            dummy = _make_dummy(tmp)
            m_opp = self._run_in_tmp(["--flight-dir", "both"], tmp, dummy=dummy)
            m_opp.assert_called_once()
            out = tmp / "ProjA11.template"
            self.assertTrue(out.is_file(), f"missing {out}")
            self.assertTrue(
                out.read_text().endswith("\n"),
                "primary template must end with newline when --flight-dir both",
            )
            cargs, ckwargs = m_opp.call_args
            self.assertEqual(ckwargs, {})
            self.assertEqual(cargs[0], out)
            self.assertEqual(cargs[1], tmp)

    def test_default_flight_dir_is_both(self):
        parser = ct.create_parser()
        ns = parser.parse_args(["x", "y"])
        self.assertEqual(ns.flight_dir, "both")
