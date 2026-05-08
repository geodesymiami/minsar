#!/usr/bin/env python3
"""Tests for modify_insarmapslog."""

from pathlib import Path
import io
import tempfile
import unittest
from contextlib import redirect_stdout

from minsar.utils.modify_insarmapslog import (
    build_overlay_url,
    main,
    modify_insarmaps_log,
    replace_start_values,
)


OVERLAY_REF_URL = (
    "http://149.165.154.65/data/HDF5EOS/Kerinci/miaplpy/overlay.html#/start/-1.6959/101.2711/13.9520"
    "?startDataset=S1_desc_091_miaplpy_20141023_XXXXXXXX_filtDel4DS&minScale=-0.75&maxScale=0.75"
    "&startDate=20141023&endDate=20260423&background=satellite&contour=false&pointLat=-1.69083&pointLon=101.26100"
)

START_REF_URL = (
    "http://149.165.153.50/start/-8.2733/123.5110/14.8136?flyToDatasetCenter=false"
    "&startDataset=S1_desc_163_miaplpy_20151222_20201125_XXXXXXXX_filtDel4DS"
    "&minScale=-1.5&maxScale=1.5&contours=true&background=satellite&pixelSize=5.6&opacity=73"
)


class TestModifyInsarmapsLog(unittest.TestCase):
    def test_replace_start_values_rounds_reference_coordinates(self):
        line = "https://insarmaps.miami.edu/start/-1.6989/101.2639/13.4?flyToDatasetCenter=false&startDataset=S1_asc"

        updated = replace_start_values(line, OVERLAY_REF_URL)

        self.assertEqual(
            updated,
            "https://insarmaps.miami.edu/start/-1.696/101.271/14.0?flyToDatasetCenter=false&startDataset=S1_asc",
        )

    def test_build_overlay_url_from_overlay_reference_uses_fixed_host_and_remote_dir(self):
        url = build_overlay_url(OVERLAY_REF_URL, Path("insarmaps.log"))

        self.assertEqual(
            url,
            "http://149.165.154.65/data/HDF5EOS/Kerinci/miaplpy/overlay.html#/start/-1.696/101.271/14.0"
            "?minScale=-0.75&maxScale=0.75&background=satellite",
        )
        self.assertNotIn("startDataset", url)

    def test_build_overlay_url_from_start_reference_uses_logfile_project_path(self):
        logfile = Path("Kerinci/miaplpy/insarmaps.log")

        url = build_overlay_url(START_REF_URL, logfile)

        self.assertEqual(
            url,
            "http://149.165.154.65/data/HDF5EOS/Kerinci/miaplpy/overlay.html#/start/-8.273/123.511/14.8"
            "?minScale=-1.5&maxScale=1.5&background=satellite&pixelSize=5.6",
        )

    def test_build_overlay_url_from_absolute_remote_dir_logfile(self):
        logfile = Path("/data/HDF5EOS/Kerinci/miaplpy/insarmaps.log")

        url = build_overlay_url(START_REF_URL, logfile)

        self.assertIn("/data/HDF5EOS/Kerinci/miaplpy/overlay.html", url)
        self.assertNotIn("/data/HDF5EOS/data/HDF5EOS/", url)

    def test_modify_log_creates_backup_once_and_rewrites_all_lines(self):
        original = "\n".join(
            [
                "https://insarmaps.miami.edu/start/-1.6989/101.2639/13.4?flyToDatasetCenter=false&startDataset=S1_vert",
                "https://insarmaps.miami.edu/start/-1.6989/101.2639/13.3?flyToDatasetCenter=false&startDataset=S1_desc",
            ]
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "Kerinci" / "miaplpy" / "insarmaps.log"
            log.parent.mkdir(parents=True)
            log.write_text(original + "\n", encoding="utf-8")

            printed_url = modify_insarmaps_log(OVERLAY_REF_URL, log)
            backup = log.with_name("orig_insarmaps.log")

            self.assertTrue(backup.exists())
            self.assertEqual(backup.read_text(encoding="utf-8"), original + "\n")
            self.assertIn("/start/-1.696/101.271/14.0?", log.read_text(encoding="utf-8"))
            self.assertEqual(
                printed_url,
                "http://149.165.154.65/data/HDF5EOS/Kerinci/miaplpy/overlay.html#/start/-1.696/101.271/14.0"
                "?minScale=-0.75&maxScale=0.75&background=satellite",
            )

            backup.write_text("keep this backup\n", encoding="utf-8")
            modify_insarmaps_log(START_REF_URL, log)
            self.assertEqual(backup.read_text(encoding="utf-8"), "keep this backup\n")

    def test_cli_takes_logfile_first_then_url(self):
        original = (
            "https://insarmaps.miami.edu/start/-1.6989/101.2639/13.4"
            "?flyToDatasetCenter=false&startDataset=S1_desc\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "Kerinci" / "miaplpy" / "insarmaps.log"
            log.parent.mkdir(parents=True)
            log.write_text(original, encoding="utf-8")

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                main([str(log), OVERLAY_REF_URL])

            self.assertEqual(
                buffer.getvalue().strip(),
                "http://149.165.154.65/data/HDF5EOS/Kerinci/miaplpy/overlay.html"
                "#/start/-1.696/101.271/14.0?minScale=-0.75&maxScale=0.75&background=satellite",
            )
            self.assertIn("/start/-1.696/101.271/14.0?", log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
