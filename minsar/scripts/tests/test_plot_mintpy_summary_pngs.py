#!/usr/bin/env python3
"""Unit tests for the mintpy.plot gate in plot_mintpy_summary_pngs.py."""

import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "plot_mintpy_summary_pngs.py"
    spec = importlib.util.spec_from_file_location("plot_mintpy_summary_pngs", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load_module()


class TestMintpyPlotGate(unittest.TestCase):
    def _write(self, directory: Path, text: str) -> Path:
        cfg = directory / "smallbaselineApp.cfg"
        cfg.write_text(text)
        return cfg

    def test_commented_no_is_off(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self._write(
                Path(td),
                "mintpy.plot                        = no  #[yes / no], auto for yes\n"
                "mintpy.plot.maxMemory              = 0.2\n",
            )
            self.assertEqual(MOD.read_mintpy_plot_value(str(cfg)), "no")
            self.assertTrue(MOD.mintpy_plot_is_off("no"))

    def test_off_values(self):
        for value in ("no", "false", "0", "NO", "False"):
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory() as td:
                    cfg = self._write(Path(td), f"mintpy.plot = {value}\n")
                    got = MOD.read_mintpy_plot_value(str(cfg))
                    self.assertTrue(MOD.mintpy_plot_is_off(got), got)

    def test_on_and_missing_are_not_off(self):
        cases = {
            "yes": "mintpy.plot = yes\n",
            "true": "mintpy.plot = true\n",
            "1": "mintpy.plot = 1\n",
            "auto": "mintpy.plot = auto  #[yes / no]\n",
            "missing": "mintpy.plot.maxMemory = 0.2\n",
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as td:
                    cfg = self._write(Path(td), text)
                    got = MOD.read_mintpy_plot_value(str(cfg))
                    self.assertFalse(MOD.mintpy_plot_is_off(got), got)

    def test_main_skips_when_plot_yes_with_comment(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(
                Path(td),
                "mintpy.plot = yes  #[yes / no], auto for yes, plot files to pic folder\n",
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = MOD.main(["--dir", td, "-t", "smallbaselineApp.cfg"])
            self.assertEqual(rc, 0)
            self.assertIn("mintpy.plot is on (yes); skip summary PNGs", buf.getvalue())

    def test_main_skips_when_key_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(Path(td), "mintpy.plot.maxMemory = 0.2\n")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = MOD.main(["--dir", td, "-t", "smallbaselineApp.cfg"])
            self.assertEqual(rc, 0)
            self.assertIn("mintpy.plot is on (unset); skip summary PNGs", buf.getvalue())

    def test_omitted_template_does_not_use_gate_flag(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            self._write(td, "mintpy.plot = yes\n")
            path, explicit = MOD._resolve_template(str(td), None)
            self.assertFalse(explicit)
            self.assertEqual(path, str(td / "smallbaselineApp.cfg"))


if __name__ == "__main__":
    unittest.main()
