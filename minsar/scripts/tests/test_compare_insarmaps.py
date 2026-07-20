#!/usr/bin/env python3
"""Tests for compare_insarmaps.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from minsar.scripts.compare_insarmaps import (
    build_compare_folder,
    compare_dir_name,
)


def _write_product(d: Path, *, overlay: str, log: str, download: str, data_files: str | None = None) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "overlay.html").write_text(overlay, encoding="utf-8")
    (d / "index.html").write_text("INDEX", encoding="utf-8")
    (d / "insarmaps.log").write_text(log, encoding="utf-8")
    (d / "download_commands.txt").write_text(download, encoding="utf-8")
    if data_files is not None:
        (d / "data_files.txt").write_text(data_files, encoding="utf-8")


class TestCompareInsarmaps(unittest.TestCase):
    def test_compare_dir_name(self):
        self.assertEqual(compare_dir_name(Path("miaplpy")), "miaplpy_compare")
        self.assertEqual(
            compare_dir_name(Path("miaplpy_202501_202606")),
            "miaplpy_compare",
        )
        self.assertEqual(
            compare_dir_name(Path("/data/HDF5EOS/LaPalma/mintpy")),
            "mintpy_compare",
        )
        self.assertEqual(
            compare_dir_name(Path("mintpy_201801_201901")),
            "mintpy_compare",
        )
        self.assertEqual(compare_dir_name(Path("egms_v1")), "egms_compare")
        self.assertEqual(compare_dir_name(Path("dolphin")), "dolphin_compare")

    def test_build_compare_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d1 = root / "miaplpy"
            d2 = root / "miaplpy_202501_202606"
            _write_product(
                d1,
                overlay="OVERLAY_FROM_1",
                log="url_a\nurl_b\n",
                download="wget a\nwget b\n",
                data_files="/path/a.he5\n/path/b.he5\n",
            )
            _write_product(
                d2,
                overlay="OVERLAY_FROM_2",
                log="url_c\n",
                download="wget c\n",
                data_files="/path/c.he5\n",
            )

            out = build_compare_folder(d1, d2)
            self.assertEqual(out.name, "miaplpy_compare")
            self.assertTrue(out.is_dir())
            self.assertEqual((out / "overlay.html").read_text(encoding="utf-8"), "OVERLAY_FROM_1")
            self.assertEqual((out / "index.html").read_text(encoding="utf-8"), "INDEX")
            self.assertEqual(
                (out / "insarmaps.log").read_text(encoding="utf-8"),
                "url_a\nurl_b\nurl_c\n",
            )
            self.assertEqual(
                (out / "download_commands.txt").read_text(encoding="utf-8"),
                "wget a\nwget b\nwget c\n",
            )
            self.assertEqual(
                (out / "data_files.txt").read_text(encoding="utf-8"),
                "/path/a.he5\n/path/b.he5\n/path/c.he5\n",
            )

    def test_build_compare_from_dated_first_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d1 = root / "miaplpy_202501_202606"
            d2 = root / "miaplpy"
            _write_product(
                d1,
                overlay="OVERLAY_FROM_1",
                log="url_a\n",
                download="wget a\n",
            )
            _write_product(
                d2,
                overlay="OVERLAY_FROM_2",
                log="url_b\n",
                download="wget b\n",
            )

            out = build_compare_folder(d1, d2)
            self.assertEqual(out.name, "miaplpy_compare")
            self.assertEqual((out / "overlay.html").read_text(encoding="utf-8"), "OVERLAY_FROM_1")
            self.assertEqual((out / "insarmaps.log").read_text(encoding="utf-8"), "url_a\nurl_b\n")
            self.assertEqual(
                (out / "download_commands.txt").read_text(encoding="utf-8"),
                "wget a\nwget b\n",
            )
            self.assertFalse((out / "data_files.txt").exists())

    def test_missing_download_commands_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d1 = root / "miaplpy"
            d2 = root / "miaplpy_b"
            d1.mkdir()
            d2.mkdir()
            (d1 / "overlay.html").write_text("o", encoding="utf-8")
            (d1 / "index.html").write_text("i", encoding="utf-8")
            (d1 / "insarmaps.log").write_text("u1\n", encoding="utf-8")
            (d2 / "insarmaps.log").write_text("u2\n", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                build_compare_folder(d1, d2)


if __name__ == "__main__":
    unittest.main()
