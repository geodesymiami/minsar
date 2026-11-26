#!/usr/bin/env python3
"""Tests for update_looks_in_runfiles.py (rerun a processed dataset with other looks)."""
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from minsar.scripts import update_looks_in_runfiles as ul  # noqa: E402

TEMPLATE = "asf.platform = SENTINEL-1A\ntopsStack.azimuthLooks = 10\ntopsStack.rangeLooks = 40\n"
MERGE = "mergeBursts : \nmultilook : True\nrange_looks : 15\nazimuth_looks : 5\n"
UNW = "unwrap : \ndefomax : 2\nrlks : 15\nalks : 5\nmethod : whirlwind\n"
ALOS2_RECT = "rect_range_offset.py -ref_date 200107 -nrlks1 1 -nalks1 14\n"
ALOS2_LOOK = (
    "look_coherence.py -ref_date 200107 -nrlks1 1 -nalks1 14 -nrlks2 5 -nalks2 2\n"
    "filt.py -idir ../../dates_resampled/200107/insar/200107_1rlks_14alks.wbd -nrlks1 1 -nalks1 14 -nrlks2 5 -nalks2 2\n"
)
ALOS2_GEOCODE = "geocode.py -input filt_200107-200204_5rlks_28alks.unw -nrlks 5 -nalks 28 -bbox -8.3/-8.1/117.9/118.0\n"


class TestUpdateLooksInRunfiles(unittest.TestCase):
    def project(self, tmp, coregistration_step=12):
        work = Path(tmp)
        (work / "run_files").mkdir()
        (work / "configs").mkdir()
        (work / "run_files" / f"run_{coregistration_step:02d}_merge_reference_secondary_slc").write_text("")
        (work / "configs" / "config_merge_igram_20160605_20160629").write_text(MERGE)
        (work / "configs" / "config_igram_unw_20160605_20160629").write_text(UNW)
        (work / "configs" / "config_reference").write_text("topo : \n")
        (work / "t.template").write_text(TEMPLATE)
        return work

    def test_configs_get_the_template_looks(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.project(tmp)
            self.assertEqual(ul.main([str(work / "t.template"), "--work-dir", str(work), "--isce-start", "12"]), 0)
            self.assertEqual((work / "configs" / "config_merge_igram_20160605_20160629").read_text(),
                             "mergeBursts : \nmultilook : True\nrange_looks : 40\nazimuth_looks : 10\n")
            self.assertEqual((work / "configs" / "config_igram_unw_20160605_20160629").read_text(),
                             "unwrap : \ndefomax : 2\nrlks : 40\nalks : 10\nmethod : whirlwind\n")
            self.assertEqual((work / "configs" / "config_reference").read_text(), "topo : \n")

    def test_isce_start_after_the_first_looks_step_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.project(tmp)
            self.assertEqual(ul.main([str(work / "t.template"), "--work-dir", str(work), "--isce-start", "15"]), 1)
            self.assertEqual((work / "configs" / "config_igram_unw_20160605_20160629").read_text(), UNW)

    def test_geometry_coregistration_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.project(tmp, coregistration_step=7)
            self.assertEqual(ul.first_looks_step(work, "topsStack"), 7)
            self.assertEqual(ul.main([str(work / "t.template"), "--work-dir", str(work), "--isce-start", "8"]), 1)

    def test_auto_looks_resolve_to_defaults(self):
        self.assertEqual(ul.template_looks("asf.platform = SENTINEL-1A\n", "topsStack"), {"rangeLooks": 9, "azimuthLooks": 3})
        self.assertEqual(ul.template_looks("asf.platform = ALOS2\nalos2Stack.rangeLooks = auto\n", "alos2Stack"),
                         {"rangeLooks": 5, "azimuthLooks": 28})

    def test_print_step(self):
        import contextlib
        import io
        for step in (12, 7):
            with tempfile.TemporaryDirectory() as tmp:
                work = self.project(tmp, coregistration_step=step)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(ul.main([str(work / "t.template"), "--work-dir", str(work), "--print-step"]), 0)
                self.assertEqual(out.getvalue().strip(), str(step))
                self.assertEqual((work / "configs" / "config_igram_unw_20160605_20160629").read_text(), UNW)

    def alos2_project(self, tmp, azimuth_looks=14, range_looks=2):
        work = Path(tmp)
        (work / "run_files" / "tasks").mkdir(parents=True)
        (work / "t.template").write_text(
            f"asf.platform = ALOS2\nalos2Stack.rangeLooks = {range_looks}\nalos2Stack.azimuthLooks = {azimuth_looks}\n")
        run = work / "run_files"
        (run / "run_11_rect_range_offset").write_text("bash tasks/run_11_rect_range_offset_200107-200204.bash\n")
        (run / "run_12_diff_look_filt").write_text("bash tasks/run_12_diff_look_filt_200107-200204.bash\n")
        (run / "run_12_diff_look_filt_0.job").write_text("#SBATCH -J run_12\n")
        (run / "tasks" / "run_11_rect_range_offset_200107-200204.bash").write_text(ALOS2_RECT)
        (run / "tasks" / "run_12_diff_look_filt_200107-200204.bash").write_text(ALOS2_LOOK)
        (run / "tasks" / "run_16_geocode_200107-200204.bash").write_text(ALOS2_GEOCODE)
        return work

    def test_alos2_run_files_get_the_template_looks(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.alos2_project(tmp)
            tasks = work / "run_files" / "tasks"
            self.assertEqual(ul.main([str(work / "t.template"), "--work-dir", str(work), "--isce-start", "12"]), 0)
            self.assertEqual((tasks / "run_12_diff_look_filt_200107-200204.bash").read_text(),
                             "look_coherence.py -ref_date 200107 -nrlks1 1 -nalks1 14 -nrlks2 2 -nalks2 1\n"
                             "filt.py -idir ../../dates_resampled/200107/insar/200107_1rlks_14alks.wbd -nrlks1 1 -nalks1 14 -nrlks2 2 -nalks2 1\n")
            self.assertEqual((tasks / "run_16_geocode_200107-200204.bash").read_text(),
                             "geocode.py -input filt_200107-200204_2rlks_14alks.unw -nrlks 2 -nalks 14 -bbox -8.3/-8.1/117.9/118.0\n")
            self.assertEqual((tasks / "run_11_rect_range_offset_200107-200204.bash").read_text(), ALOS2_RECT)
            self.assertEqual((work / "run_files" / "run_12_diff_look_filt_0.job").read_text(), "#SBATCH -J run_12\n")
            # the same looks again change nothing, and going back works from the edited files
            before = (tasks / "run_16_geocode_200107-200204.bash").read_text()
            self.assertEqual(ul.main([str(work / "t.template"), "--work-dir", str(work)]), 0)
            self.assertEqual((tasks / "run_16_geocode_200107-200204.bash").read_text(), before)

    def test_alos2_azimuth_not_a_multiple_of_looks1(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.alos2_project(tmp, azimuth_looks=20)
            self.assertEqual(ul.main([str(work / "t.template"), "--work-dir", str(work)]), 1)
            self.assertEqual((work / "run_files" / "tasks" / "run_16_geocode_200107-200204.bash").read_text(), ALOS2_GEOCODE)

    def test_alos2_first_step_name_is_in_the_run_file_plan(self):
        from minsar.utils.alos2_run_files import RUN_FILES
        self.assertIn("run_12_diff_look_filt", [name for name, _ in RUN_FILES])


if __name__ == "__main__":
    unittest.main()
