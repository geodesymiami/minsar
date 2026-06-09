"""Pure helpers for overlay display-param transfer across dataset switches.

Mirrors the contract implemented in minsar/html/overlay.html (contours, pixelSize,
background, autoColorScale). Used by unit tests; keep in sync when overlay URL logic changes.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

INSARMAP_URL_DEFAULTS = {
    "contours": "false",
    "pixelSize": "3",
    "background": "hillshade",
    "opacity": "80",
    "autoColorScale": "true",
}


def normalize_contour(value) -> str | None:
    if value is None or value == "":
        return None
    v = str(value).lower()
    if v in ("on", "true", "1"):
        return "true"
    if v in ("off", "false", "0"):
        return "false"
    return str(value)


def effective_contour(params: dict) -> str:
    raw = params.get("contour") or params.get("contours") or INSARMAP_URL_DEFAULTS["contours"]
    return normalize_contour(raw) or INSARMAP_URL_DEFAULTS["contours"]


def format_url_number(value) -> str:
    if value is None or value == "":
        return ""
    try:
        f = float(value)
        if f == int(f):
            return str(int(f))
        return str(f)
    except (TypeError, ValueError):
        return str(value)


def url_display_params_from_src(src: str) -> dict:
    """Parse display-related query params from an insarmaps iframe URL."""
    if not src:
        return {}
    try:
        parsed = urlparse(src)
        q = parse_qs(parsed.query)

        def first(key):
            return q[key][0] if key in q and q[key] else None

        return {
            "contours": first("contours") or first("contour"),
            "pixelSize": first("pixelSize"),
            "background": first("background"),
            "opacity": first("opacity"),
            "autoColorScale": first("autoColorScale"),
            "pointLat": first("pointLat"),
            "pointLon": first("pointLon"),
            "refPointLat": first("refPointLat"),
            "refPointLon": first("refPointLon"),
            "minScale": first("minScale"),
            "maxScale": first("maxScale"),
        }
    except Exception:
        return {}


def map_params_with_overlay_user_display(map_params: dict, overlay_user_display: dict) -> dict:
    """Apply overlay-owned user intent over possibly stale parent mapParams."""
    p = dict(map_params)
    if overlay_user_display.get("contour") is not None:
        p["contour"] = overlay_user_display["contour"]
    if overlay_user_display.get("pixelSize") not in (None, ""):
        p["pixelSize"] = overlay_user_display["pixelSize"]
    if overlay_user_display.get("background") is not None:
        p["background"] = overlay_user_display["background"]
    if overlay_user_display.get("opacity") is not None:
        p["opacity"] = overlay_user_display["opacity"]
    return p


def embed_display_params_for_warm_url(map_params: dict) -> dict:
    """Query params embedded in cross-dataset warm/reload URLs (includeContours/includePixelSize)."""
    out = {}
    if map_params.get("pixelSize"):
        out["pixelSize"] = format_url_number(map_params["pixelSize"])
    if map_params.get("pointLat") and map_params.get("pointLon"):
        out["pointLat"] = str(map_params["pointLat"])
        out["pointLon"] = str(map_params["pointLon"])
    contour = effective_contour(map_params)
    if contour:
        out["contours"] = contour
    bg = map_params.get("background")
    if bg and bg != INSARMAP_URL_DEFAULTS["background"]:
        out["background"] = bg
    ac = map_params.get("autoColorScale")
    if map_params.get("minScale") and map_params.get("maxScale"):
        out["autoColorScale"] = "false"
        out["minScale"] = str(map_params["minScale"])
        out["maxScale"] = str(map_params["maxScale"])
    elif ac is not None and str(ac) != INSARMAP_URL_DEFAULTS["autoColorScale"]:
        out["autoColorScale"] = str(ac)
    return out


def display_params_mismatch(
    overlay_user_display: dict,
    current_map_params: dict,
    received_merged: dict,
) -> bool:
    """True when child iframe reports display params that differ from overlay intent."""
    expected = map_params_with_overlay_user_display(current_map_params, overlay_user_display)
    ps_mismatch = (
        expected.get("pixelSize") is not None
        and received_merged.get("pixelSize") is not None
        and format_url_number(received_merged["pixelSize"])
        != format_url_number(expected["pixelSize"])
    )
    contour_mismatch = effective_contour(received_merged) != effective_contour(expected)
    bg_mismatch = (
        expected.get("background") not in (None, "")
        and received_merged.get("background") not in (None, "")
        and received_merged["background"] != expected["background"]
    )
    return ps_mismatch or contour_mismatch or bg_mismatch


def iframe_point_match_expected(src: str, map_params: dict) -> bool:
    """True when iframe URL carries the same point/ref as mapParams (overlay iframePointMatchExpected)."""
    if not map_params.get("pointLat") or not map_params.get("pointLon"):
        return True
    if not src:
        return False
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(src).query)

    def first(key):
        return q[key][0] if key in q and q[key] else None

    url_lat, url_lon = first("pointLat"), first("pointLon")
    if url_lat is None or url_lon is None:
        return False
    expected_key = (
        str(map_params.get("pointLat")),
        str(map_params.get("pointLon")),
        str(map_params.get("refPointLat") or ""),
        str(map_params.get("refPointLon") or ""),
    )
    url_key = (
        url_lat, url_lon,
        str(first("refPointLat") or ""),
        str(first("refPointLon") or ""),
    )
    return expected_key == url_key


def format_debug_coord(lat, lon) -> str:
    """Format lat,lon for switch debug table (overlay switchDebugFmtCoord)."""
    if lat is None or lon is None or lat == "" or lon == "":
        return "—"
    try:
        a = float(lat)
        b = float(lon)
    except (TypeError, ValueError):
        return "—"
    return f"{a:.4f},{b:.4f}"


def switch_debug_fmt_val(value) -> str:
    """Normalize bool/string for debug table (overlay switchDebugFmtVal)."""
    if value is True or value == "true" or value == "on" or value == 1:
        return "true"
    if value is False or value == "false" or value == "off" or value == 0:
        return "false"
    if value is None or value == "":
        return "—"
    if isinstance(value, str):
        v = value.strip()
        if v.lower() == "true":
            return "true"
        if v.lower() == "false":
            return "false"
        return v
    return str(value)


def switch_debug_match(expected: str | None, actual: str | None) -> str:
    """Return ok/bad/pending/na — mirrors overlay.html switchDebugMatch."""
    exp_norm = switch_debug_fmt_val(expected)
    act_norm = switch_debug_fmt_val(actual)
    if exp_norm == "—":
        return "na"
    if act_norm == "—":
        return "pending"
    if exp_norm == "?" and act_norm == "true":
        return "ok"
    if exp_norm == act_norm:
        return "ok"
    if "," in exp_norm and "," in act_norm:
        e = exp_norm.split(",")
        a = act_norm.split(",")
        if len(e) == 2 and len(a) == 2:
            try:
                if abs(float(e[0]) - float(a[0])) < 0.001 and abs(float(e[1]) - float(a[1])) < 0.001:
                    return "ok"
            except ValueError:
                pass
    return "bad"


def merge_point_from_insarmaps_message(url_path: str, event_data: dict, base_params: dict) -> dict:
    """Merge pointLat/pointLon from URL and postMessage body (overlay mergeParamsFromInsarmapsMessage)."""
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url_path or "")
    q = parse_qs(parsed.query)

    def first(key):
        return q[key][0] if key in q and q[key] else None

    def from_event(key):
        return event_data.get(key) if event_data else None

    return {
        "pointLat": first("pointLat") or from_event("pointLat") or base_params.get("pointLat"),
        "pointLon": first("pointLon") or from_event("pointLon") or base_params.get("pointLon"),
        "refPointLat": first("refPointLat") or from_event("refPointLat") or base_params.get("refPointLat"),
        "refPointLon": first("refPointLon") or from_event("refPointLon") or base_params.get("refPointLon"),
    }


def switch_debug_charts_match(
    expected_charts: str | None,
    actual_charts: str | None,
    expected_point: str | None,
    actual_point: str | None,
) -> str:
    """Charts row match — mirrors overlay switchDebugChartsMatch."""
    base = switch_debug_match(expected_charts, actual_charts)
    if base in ("ok", "na", "pending"):
        return base
    exp_charts = switch_debug_fmt_val(expected_charts)
    exp_pt = "—" if expected_point is None else str(expected_point).strip()
    act_pt = "—" if actual_point is None else str(actual_point).strip()
    if (
        exp_charts in ("true", "?")
        and switch_debug_fmt_val(actual_charts) == "false"
        and exp_pt != "—"
        and act_pt != "—"
        and switch_debug_match(exp_pt, act_pt) == "ok"
    ):
        return "ok"
    return base


def expected_charts_for_switch(from_state_charts_visible, has_point_selection: bool) -> str:
    """Expected timeseries chart row when building switch debug (overlay beginSwitchDebugRow)."""
    if from_state_charts_visible is not None:
        return switch_debug_fmt_val(from_state_charts_visible)
    if has_point_selection:
        return "true"
    return "—"


def post_message_display_payload(overlay_user_display: dict, current_map_params: dict) -> dict:
    """Payload fields sent via insarmaps-set-contour / insarmaps-set-pixelSize on switch."""
    params = map_params_with_overlay_user_display(current_map_params, overlay_user_display)
    payload = {
        "contour": effective_contour(params) == "true",
        "pixelSize": float(params["pixelSize"]) if params.get("pixelSize") not in (None, "") else None,
    }
    return payload
