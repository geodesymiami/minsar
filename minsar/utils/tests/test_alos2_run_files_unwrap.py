#!/usr/bin/env python3
"""Tests for the unwrap method switch in minsar.utils.alos2_run_files (alos2Stack.unwMethod)."""

import unittest

from minsar.utils import alos2_run_files as arf

UNWRAP_LINE = "/isce2/alosStack/unwrap_snaphu.py -idir ../../dates_resampled -ref_date_stack 210101 -ref_date 210101 -sec_date 210115"


def fake_steps():
    """One step per program of the run-file plan, with unwrap_snaphu.py in run_15."""
    steps = []
    for _, spec in arf.RUN_FILES:
        for program, loop in spec:
            line = UNWRAP_LINE if program == "unwrap_snaphu.py" else f"/isce2/alosStack/{program} -x"
            steps.append(arf.Step(program, loop, [[line]], ["210101-210115"] if loop else [None]))
    return steps


class TestAlos2UnwrapMethod(unittest.TestCase):
    def plan(self, tmp_method):
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            for index in (1, 2, 4):
                (Path(tmp) / f"cmd_{index}.sh").write_text("")
            with mock.patch.object(arf, "_parse_cmd", side_effect=[fake_steps(), [], []]):
                return dict(arf.plan_alos2_run_files(tmp, tmp_method))

    def test_snaphu_is_default(self):
        for method in ("snaphu", "auto", None):
            body = self.plan(method)["run_15_unwrap"][0][1]
            self.assertEqual(body, [UNWRAP_LINE], msg=method)

    def test_whirlwind_replaces_only_the_unwrap_script(self):
        planned = self.plan("whirlwind")
        body = planned["run_15_unwrap"][0][1]
        self.assertEqual(body, [UNWRAP_LINE.replace("unwrap_snaphu.py", "unwrap_whirlwind.py")])
        others = [line for name, tasks in planned.items() if name != "run_15_unwrap" for _, lines in tasks for line in lines]
        self.assertFalse(any("whirlwind" in line for line in others))

    def test_unknown_method_raises(self):
        with self.assertRaises(RuntimeError):
            self.plan("icu")


if __name__ == "__main__":
    unittest.main()
