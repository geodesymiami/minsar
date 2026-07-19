#!/usr/bin/env python3
"""Unit tests for create_mintpy_jobfile helpers."""

import importlib.util
import tempfile
import unittest
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "create_mintpy_jobfile.py"
    spec = importlib.util.spec_from_file_location("create_mintpy_jobfile", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load_module()


class TestBuildJobCommands(unittest.TestCase):
    def test_contains_summary_plot_gate(self):
        cmds = MOD.build_job_commands("/te/Proj.template", "mintpy_2024")
        body = "\n".join(cmds)
        self.assertIn("smallbaselineApp.py /te/Proj.template --dir mintpy_2024", body)
        self.assertIn("mintpy_2024/smallbaselineApp.cfg", body)
        self.assertIn("plot_mintpy_summary_pngs.py --dir mintpy_2024", body)
        self.assertIn('"$plot_val" == "no"', body)
        self.assertIn("create_html.py mintpy_2024/pic", body)


class TestEffectiveTemplate(unittest.TestCase):
    def test_explicit_mintpy_plot_uses_custom(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            custom = td / "proj.template"
            custom.write_text(
                "ssaraopt.startDate = 20230101\n"
                "ssaraopt.endDate = 20241231\n"
                "mintpy.plot = yes\n"
            )
            proc = td / "mintpy"
            out = MOD.effective_template_for_job(str(custom), str(proc))
            self.assertEqual(out, str(custom))
            self.assertFalse((proc / ".minsar_mintpy_template.template").exists())

    def test_omitted_mintpy_plot_injects_from_span(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            custom = td / "proj.template"
            custom.write_text(
                "ssaraopt.startDate = 20230101\n"
                "ssaraopt.endDate = 20241231\n"
                "mintpy.plot.maxMemory = auto\n"
            )
            proc = td / "mintpy"
            out = MOD.effective_template_for_job(str(custom), str(proc))
            injected = proc / ".minsar_mintpy_template.template"
            self.assertEqual(out, str(injected))
            text = injected.read_text()
            self.assertRegex(text, r"(?m)^\s*mintpy\.plot\s*=\s*no\s*$")


if __name__ == "__main__":
    unittest.main()
