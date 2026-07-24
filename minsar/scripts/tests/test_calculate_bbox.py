#!/usr/bin/env python3
"""Unit tests for calculate_bbox.py (asc+desc AOI expansion)."""

from __future__ import annotations

import unittest

from minsar.scripts.calculate_bbox import (
    contains_bounds,
    expand_bbox_for_asc_desc,
    format_sn_we,
    main,
)
from minsar.utils.convert_bbox import _input_to_bounds


class TestCalculateBbox(unittest.TestCase):
    def test_expands_and_contains_input(self):
        inp = (37.475, 37.841, 14.913, 15.251)
        out = expand_bbox_for_asc_desc(*inp)
        self.assertTrue(contains_bounds(out, inp))
        s, n, w, e = out
        # Strictly larger area (at least one side grows)
        area_in = (inp[1] - inp[0]) * (inp[3] - inp[2])
        area_out = (n - s) * (e - w)
        self.assertGreater(area_out, area_in)

    def test_format_sn_we(self):
        self.assertEqual(
            format_sn_we(37.475, 37.841, 14.913, 15.251, digits=3),
            "37.475:37.841,14.913:15.251",
        )

    def test_margin_grows_further(self):
        inp = (37.475, 37.841, 14.913, 15.251)
        base = expand_bbox_for_asc_desc(*inp)
        padded = expand_bbox_for_asc_desc(*inp, margin_deg=0.05)
        self.assertTrue(contains_bounds(padded, base))
        self.assertLess(padded[0], base[0])
        self.assertGreater(padded[1], base[1])

    def test_cli_prints_expanded(self):
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["37.475:37.841,14.913:15.251"])
        self.assertEqual(rc, 0)
        text = buf.getvalue()
        self.assertIn("expanded", text)
        self.assertIn("miaplpy.subset.lalo", text)
        # Expanded line contains a larger box than input
        inp = _input_to_bounds("37.475:37.841,14.913:15.251")
        # parse expanded from "expanded   : S:N,W:E"
        for line in text.splitlines():
            if line.startswith("expanded"):
                box = line.split(":", 1)[1].strip()
                out = _input_to_bounds(box)
                self.assertTrue(contains_bounds(out, inp))
                break
        else:
            self.fail("no expanded line")

    def test_help(self):
        import io
        from contextlib import redirect_stdout, redirect_stderr

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                main(["--help"])
            except SystemExit as exc:
                self.assertEqual(exc.code, 0)
        combined = out.getvalue() + err.getvalue()
        self.assertIn("AOI", combined)
        self.assertIn("Examples:", combined)


if __name__ == "__main__":
    unittest.main()
