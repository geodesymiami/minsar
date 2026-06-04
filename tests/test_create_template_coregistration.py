#!/usr/bin/env python3
"""Tests for topsStack.coregistration / --geometry in create_template.py."""
import unittest

from minsar.scripts.create_template import (
    _resolve_coregistration,
    _substitute_template,
    create_parser,
)


class TestResolveCoregistration(unittest.TestCase):
    def test_default_nesd(self) -> None:
        co, err = _resolve_coregistration(coregistration=None, geometry_mode=False)
        self.assertIsNone(err)
        self.assertEqual(co, "NESD")

    def test_geometry_shortcut(self) -> None:
        co, err = _resolve_coregistration(coregistration=None, geometry_mode=True)
        self.assertIsNone(err)
        self.assertEqual(co, "geometry")

    def test_explicit_nesd(self) -> None:
        co, err = _resolve_coregistration(coregistration="NESD", geometry_mode=False)
        self.assertIsNone(err)
        self.assertEqual(co, "NESD")

    def test_explicit_geometry(self) -> None:
        co, err = _resolve_coregistration(coregistration="geometry", geometry_mode=False)
        self.assertIsNone(err)
        self.assertEqual(co, "geometry")

    def test_geometry_plus_explicit_geometry_ok(self) -> None:
        co, err = _resolve_coregistration(coregistration="geometry", geometry_mode=True)
        self.assertIsNone(err)
        self.assertEqual(co, "geometry")

    def test_geometry_conflicts_with_nesd_explicit(self) -> None:
        co, err = _resolve_coregistration(coregistration="NESD", geometry_mode=True)
        self.assertIsNotNone(err)
        self.assertIsNone(co)


class TestSubstituteTemplateCoregistration(unittest.TestCase):
    def test_replaces_geometry(self) -> None:
        content = (
            "ssaraopt.relativeOrbit             = 1\n"
            "topsStack.coregistration           = NESD  # comment\n"
        )
        out = _substitute_template(
            content,
            relative_orbit=99,
            subset_lalo="1:2,3:4",
            start_date=None,
            end_date=None,
            exclude_season=None,
            tops_stack_coregistration="geometry",
        )
        self.assertRegex(out, r"topsStack\.coregistration\s*=\s*geometry\b")

    def test_keeps_comment_after_value(self) -> None:
        content = "topsStack.coregistration           = NESD  # [NESD geometry]\n"
        out = _substitute_template(
            content,
            relative_orbit=1,
            subset_lalo="1:2,3:4",
            start_date=None,
            end_date=None,
            exclude_season=None,
            tops_stack_coregistration="geometry",
        )
        self.assertIn("# [NESD geometry]", out)


class TestCreateParserCoregistration(unittest.TestCase):
    def test_parser_accepts_geometry_and_coregistration(self) -> None:
        p = create_parser(add_help=False)
        ns = p.parse_args(["0:1,2:3", "X", "--geometry"])
        self.assertTrue(ns.geometry_mode)

        ns2 = p.parse_args(["0:1,2:3", "X", "--coregistration", "NESD"])
        self.assertEqual(ns2.tops_coregistration, "NESD")
        self.assertFalse(ns2.geometry_mode)
