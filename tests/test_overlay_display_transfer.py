#!/usr/bin/env python3
"""Unit tests for overlay display-param transfer (contours, pixelSize, background, point)."""

import unittest

from minsar.utils.overlay_display_transfer import (
    display_params_mismatch,
    effective_contour,
    embed_display_params_for_warm_url,
    expected_charts_for_switch,
    format_debug_coord,
    iframe_point_match_expected,
    map_params_with_overlay_user_display,
    merge_point_from_insarmaps_message,
    post_message_display_payload,
    switch_debug_charts_match,
    switch_debug_match,
    switch_debug_fmt_val,
    url_display_params_from_src,
    resolve_switch_dates,
)


class TestUrlDisplayParamsFromSrc(unittest.TestCase):
    def test_parses_contours_pixel_size_background(self):
        src = (
            "/start/0.77/-77.87/11.9?contours=true&pixelSize=3.8"
            "&background=streets&autoColorScale=false&minScale=-2&maxScale=2"
        )
        p = url_display_params_from_src(src)
        self.assertEqual(p["contours"], "true")
        self.assertEqual(p["pixelSize"], "3.8")
        self.assertEqual(p["background"], "streets")
        self.assertEqual(p["autoColorScale"], "false")

    def test_contour_alias(self):
        p = url_display_params_from_src("/start/0/0/1?contour=on&pixelSize=6")
        self.assertEqual(p["contours"], "on")
        self.assertEqual(p["pixelSize"], "6")

    def test_parses_point_from_url(self):
        src = "/start/0.77/-77.87/11.9?pointLat=0.77420&pointLon=-77.87070&contours=true"
        p = url_display_params_from_src(src)
        self.assertEqual(p["pointLat"], "0.77420")
        self.assertEqual(p["pointLon"], "-77.87070")

    def test_parses_manual_scale_from_url(self):
        src = "/start/0.77/-77.87/11.9?minScale=-1.5&maxScale=1.5&autoColorScale=false"
        p = url_display_params_from_src(src)
        self.assertEqual(p["minScale"], "-1.5")
        self.assertEqual(p["maxScale"], "1.5")
        self.assertEqual(p["autoColorScale"], "false")


class TestOverlayUserDisplayOverride(unittest.TestCase):
    def test_user_intent_overrides_stale_parent_on_switch(self):
        """Desc iframe.src may be stale (false/null) while overlayUserDisplay holds true intent."""
        parent = {"contour": "false", "pixelSize": "6", "background": None}
        overlay_user = {"contour": "true", "pixelSize": "3.8", "background": "streets"}
        merged = map_params_with_overlay_user_display(parent, overlay_user)
        self.assertEqual(effective_contour(merged), "true")
        self.assertEqual(merged["pixelSize"], "3.8")
        self.assertEqual(merged["background"], "streets")


class TestWarmUrlEmbedding(unittest.TestCase):
    def test_warm_url_carries_display_params_to_next_dataset(self):
        map_params = {
            "contour": "true",
            "pixelSize": "3.8",
            "background": "streets",
            "autoColorScale": "true",
        }
        q = embed_display_params_for_warm_url(map_params)
        self.assertEqual(q["contours"], "true")
        self.assertEqual(q["pixelSize"], "3.8")
        self.assertEqual(q["background"], "streets")
        self.assertNotIn("autoColorScale", q)

    def test_manual_scale_mode_in_warm_url(self):
        map_params = {
            "contour": "false",
            "pixelSize": "4",
            "autoColorScale": "false",
            "minScale": "-1.5",
            "maxScale": "1.5",
        }
        q = embed_display_params_for_warm_url(map_params)
        self.assertEqual(q["autoColorScale"], "false")
        self.assertEqual(q["minScale"], "-1.5")
        self.assertEqual(q["maxScale"], "1.5")

    def test_warm_url_includes_explicit_velocity_colorscale(self):
        """Regression: omitting default velocity can leak stale displacement on switch."""
        q = embed_display_params_for_warm_url({"colorscale": "velocity"})
        self.assertEqual(q["colorscale"], "velocity")

    def test_warm_url_includes_dates_for_selected_period(self):
        q = embed_display_params_for_warm_url({
            "startDate": "20210417",
            "endDate": "20260509",
            "colorscale": "velocity",
        })
        # Date embedding for warm URL is handled by overlay, but parser helper must support dates.
        src = "/start/0/0/1?startDate=20210417&endDate=20260509&colorscale=velocity"
        parsed = url_display_params_from_src(src)
        self.assertEqual(parsed["startDate"], "20210417")
        self.assertEqual(parsed["endDate"], "20260509")
        self.assertEqual(parsed["colorscale"], "velocity")


class TestDisplayParamsMismatch(unittest.TestCase):
    def test_detects_mintpy_default_reset_after_reload(self):
        """Child posts pixelSize=6 after parent intended 3.8 (Asc→Desc reload bug)."""
        overlay_user = {"contour": "true", "pixelSize": "3.8"}
        parent = {"contour": "true", "pixelSize": "3.8"}
        received = {"contour": "false", "pixelSize": "6"}
        self.assertTrue(display_params_mismatch(overlay_user, parent, received))

    def test_no_mismatch_when_child_matches(self):
        overlay_user = {"contour": "true", "pixelSize": "3.8"}
        parent = {"contour": "true", "pixelSize": "3.8"}
        received = {"contour": "true", "pixelSize": "3.8"}
        self.assertFalse(display_params_mismatch(overlay_user, parent, received))


class TestPostMessagePayload(unittest.TestCase):
    def test_switch_broadcast_payload(self):
        overlay_user = {"contour": "true", "pixelSize": "3.8"}
        parent = {"contour": "false", "pixelSize": "6"}
        payload = post_message_display_payload(overlay_user, parent)
        self.assertTrue(payload["contour"])
        self.assertAlmostEqual(payload["pixelSize"], 3.8)


class TestPointTransfer(unittest.TestCase):
    def test_warm_url_includes_point(self):
        map_params = {
            "contour": "true",
            "pixelSize": "4",
            "pointLat": "0.7742",
            "pointLon": "-77.8707",
        }
        q = embed_display_params_for_warm_url(map_params)
        self.assertEqual(q["contours"], "true")
        self.assertEqual(q["pointLat"], "0.7742")
        self.assertEqual(q["pointLon"], "-77.8707")
        src = (
            "/start/0.77/-77.87/11.9?pointLat=0.7742&pointLon=-77.8707"
            "&contours=true&pixelSize=4"
        )
        self.assertTrue(iframe_point_match_expected(src, map_params))

    def test_point_mismatch_when_url_missing_point(self):
        map_params = {"pointLat": "0.7742", "pointLon": "-77.8707"}
        src = "/start/0.77/-77.87/11.9?contours=true&pixelSize=4"
        self.assertFalse(iframe_point_match_expected(src, map_params))

    def test_no_point_required_when_parent_has_no_selection(self):
        src = "/start/0.77/-77.87/11.9?contours=true"
        self.assertTrue(iframe_point_match_expected(src, {}))

    def test_merge_point_from_message_body_when_url_omits(self):
        """Insarmaps may send pointLat/pointLon in postMessage but not in URL path."""
        url = "/start/0.77/-77.87/11.9?contours=true&pixelSize=4"
        event = {"pointLat": "0.77420", "pointLon": "-77.87070"}
        merged = merge_point_from_insarmaps_message(url, event, {})
        self.assertEqual(merged["pointLat"], "0.77420")
        self.assertEqual(merged["pointLon"], "-77.87070")

    def test_merge_point_prefers_url_over_stale_base(self):
        url = "/start/0.77/-77.87/11.9?pointLat=0.8000&pointLon=-77.9000"
        base = {"pointLat": "0.7742", "pointLon": "-77.8707"}
        merged = merge_point_from_insarmaps_message(url, {}, base)
        self.assertEqual(merged["pointLat"], "0.8000")
        self.assertEqual(merged["pointLon"], "-77.9000")


class TestSwitchDebugMatch(unittest.TestCase):
    def test_format_debug_coord(self):
        self.assertEqual(format_debug_coord(0.7742, -77.8707), "0.7742,-77.8707")
        self.assertEqual(format_debug_coord(None, None), "—")

    def test_charts_wildcard_expected_question_mark(self):
        """Fast-path cache leaves expected charts as ?; UI reports true."""
        self.assertEqual(switch_debug_match("?", "true"), "ok")

    def test_charts_match_when_point_selected(self):
        self.assertEqual(expected_charts_for_switch(None, True), "true")
        self.assertEqual(switch_debug_match("true", "true"), "ok")
        self.assertEqual(switch_debug_match("true", True), "ok")

    def test_point_coords_fuzzy_match(self):
        exp = format_debug_coord("0.77420", "-77.87070")
        act = format_debug_coord("0.77425", "-77.87075")
        self.assertEqual(switch_debug_match(exp, act), "ok")

    def test_point_coords_exact_match(self):
        coord = format_debug_coord(0.7742, -77.8707)
        self.assertEqual(switch_debug_match(coord, coord), "ok")

    def test_na_when_expected_dash(self):
        self.assertEqual(switch_debug_match("—", "true"), "na")

    def test_pending_when_actual_missing(self):
        self.assertEqual(switch_debug_match("true", "—"), "pending")

    def test_switch_debug_fmt_val_bools(self):
        self.assertEqual(switch_debug_fmt_val(True), "true")
        self.assertEqual(switch_debug_fmt_val(False), "false")

    def test_charts_match_when_point_matches_but_charts_false(self):
        """insarmaps may report chartsVisible false while chart is on screen."""
        pt = format_debug_coord(0.8121, -77.9252)
        self.assertEqual(
            switch_debug_charts_match("?", "false", pt, pt),
            "ok",
        )
        self.assertEqual(
            switch_debug_charts_match("true", "false", pt, pt),
            "ok",
        )

    def test_charts_no_infer_when_points_differ(self):
        exp = format_debug_coord(0.8121, -77.9252)
        act = format_debug_coord(0.8000, -77.9000)
        self.assertEqual(switch_debug_charts_match("true", "false", exp, act), "bad")


class TestSwitchStatePrecedence(unittest.TestCase):
    def test_colorscale_velocity_explicit_state_beats_stale_displacement(self):
        """Regression: after displacement->velocity, switch must keep velocity."""
        parsed = url_display_params_from_src("/start/0/0/1?colorscale=velocity")
        self.assertEqual(parsed["colorscale"], "velocity")
        q = embed_display_params_for_warm_url({"colorscale": "velocity"})
        self.assertEqual(q["colorscale"], "velocity")

    def test_latest_user_period_beats_older_from_state_on_switch(self):
        """Regression: period 2 selection must win over cached period 1 on dataset switch."""
        user_period = {"startDate": "20210809", "endDate": "20250502"}  # period 2
        from_state = {"startDate": "20141027", "endDate": "20180720"}   # period 1
        narrowed = {"startDate": "20141106", "endDate": "20181022"}     # stale target snap
        chosen = resolve_switch_dates(user_period, from_state, narrowed)
        self.assertEqual(chosen, user_period)

    def test_switch_uses_from_state_when_no_user_period(self):
        from_state = {"startDate": "20141027", "endDate": "20180720"}
        narrowed = {"startDate": "20141106", "endDate": "20181022"}
        chosen = resolve_switch_dates(None, from_state, narrowed)
        self.assertEqual(chosen, from_state)


if __name__ == "__main__":
    unittest.main()
