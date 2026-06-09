#!/usr/bin/env python3
"""Append or remove the overlay switch-parameter debug table.

Usage:
  apply_debug_table.py append [OVERLAY.html]
  apply_debug_table.py remove [OVERLAY.html]
  apply_debug_table.py status [OVERLAY.html]
  apply_debug_table.py sync [OVERLAY.html]   # push fragment files into overlay markers

Default OVERLAY.html: minsar/html/overlay.html (next to this directory's parent).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent
DEFAULT_OVERLAY = DIR.parent / "overlay.html"

MARKERS = {
    "css": (
        "<!-- debug-table-overlay:BEGIN:css -->",
        "<!-- debug-table-overlay:END:css -->",
        DIR / "debug_table_overlay.css",
    ),
    "html": (
        "<!-- debug-table-overlay:BEGIN:html -->",
        "<!-- debug-table-overlay:END:html -->",
        DIR / "debug_table_overlay.html",
    ),
    "js": (
        "/* debug-table-overlay:BEGIN:inline-js */",
        "/* debug-table-overlay:END:inline-js */",
        DIR / "debug_table_overlay.inline.js",
    ),
}

HOOK_REPLACEMENTS = [
    ("dbgDisplayLog(", "__odt_hook('dbgDisplayLog', "),
    ("dbgSwitchLog(", "__odt_hook('dbgSwitchLog', "),
    ("beginSwitchDebugRow(", "__odt_hook('beginSwitchDebugRow', "),
    ("recordSwitchDebugReloadUrl(", "__odt_hook('recordSwitchDebugReloadUrl', "),
    ("recordSwitchDebugSentPost(", "__odt_hook('recordSwitchDebugSentPost', "),
    ("recordSwitchDebugReceived(", "__odt_hook('recordSwitchDebugReceived', "),
    ("scheduleSwitchDebugFinalize(", "__odt_hook('scheduleSwitchDebugFinalize', "),
]

ODT_HOOK_STUB = """
        function __odt_hook(name, ...args) {
            const hooks = window.__overlayDebugHooks;
            if (hooks && typeof hooks[name] === 'function') {
                hooks[name](...args);
            }
        }
"""

PRODUCTION_JS_SNIPPET = """
        const MAX_DISPLAY_REAPPLY = 3;
        let displayReapplyCountByIndex = new Map();

        function urlDisplayParamsFromSrc(src) {
            if (!src) return {};
            try {
                const u = new URL(src, window.location.href);
                return {
                    contours: u.searchParams.get('contours') || u.searchParams.get('contour'),
                    pixelSize: u.searchParams.get('pixelSize'),
                    background: u.searchParams.get('background'),
                    opacity: u.searchParams.get('opacity'),
                    autoColorScale: u.searchParams.get('autoColorScale'),
                    minScale: u.searchParams.get('minScale'),
                    maxScale: u.searchParams.get('maxScale'),
                    colorscale: u.searchParams.get('colorscale')
                };
            } catch (e) {
                return {};
            }
        }

        function displayParamsMismatchExpected(rawMerged) {
            const expected = mapParamsWithOverlayUserDisplay(currentMapParams);
            const psMismatch = expected.pixelSize != null && rawMerged.pixelSize != null &&
                formatUrlNumber(rawMerged.pixelSize) !== formatUrlNumber(expected.pixelSize);
            const contourMismatch = effectiveContour(rawMerged) !== effectiveContour(expected);
            return psMismatch || contourMismatch;
        }

        function maybeReapplyDisplayParamsToActiveIframe(senderIndex, rawMerged) {
            if (!(Date.now() < datasetSwitchSuppressUntil || switchOpInFlight)) return;
            if (senderIndex !== activeDatasetIdx) return;
            if (!displayParamsMismatchExpected(rawMerged)) return;
            const count = displayReapplyCountByIndex.get(senderIndex) || 0;
            if (count >= MAX_DISPLAY_REAPPLY) return;
            displayReapplyCountByIndex.set(senderIndex, count + 1);
            broadcastContourAndPixelSizeToIframe(senderIndex);
            setTimeout(() => broadcastContourAndPixelSizeToIframe(senderIndex), 700);
            __odt_hook('dbgDisplayLog', 'overlay.html:reapplyDisplay', 're-postMessage after child default', {
                senderIndex, label: iframeLabelForLog(senderIndex),
                attempt: count + 1,
                rawPixelSize: rawMerged.pixelSize,
                rawContour: effectiveContour(rawMerged),
                expectedPixelSize: mapParamsWithOverlayUserDisplay(currentMapParams).pixelSize,
                expectedContour: effectiveContour(mapParamsWithOverlayUserDisplay(currentMapParams))
            }, 'H');
        }
"""


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def region_content(text: str, begin: str, end: str) -> str | None:
    i = text.find(begin)
    if i < 0:
        return None
    j = text.find(end, i + len(begin))
    if j < 0:
        return None
    return text[i + len(begin):j]


def replace_region(text: str, begin: str, end: str, body: str) -> str:
    i = text.find(begin)
    if i < 0:
        raise SystemExit(f"Marker not found: {begin}")
    j = text.find(end, i + len(begin))
    if j < 0:
        raise SystemExit(f"Marker not found: {end}")
    middle = body
    if middle and not middle.startswith("\n"):
        middle = "\n" + middle
    if middle and not middle.endswith("\n"):
        middle = middle + "\n"
    return text[: i + len(begin)] + middle + text[j:]


def has_marker(text: str, begin: str) -> bool:
    return begin in text


def ensure_markers(text: str) -> str:
    """Insert empty marker blocks at standard anchors if missing."""
    if not has_marker(text, MARKERS["css"][0]):
        text = text.replace(
            "        .page-footer {",
            MARKERS["css"][0] + "\n" + MARKERS["css"][1] + "\n        .page-footer {",
            1,
        )
    if not has_marker(text, MARKERS["html"][0]):
        text = text.replace(
            '    <div class="container" id="container"></div>',
            '    <div class="container" id="container"></div>\n'
            + MARKERS["html"][0] + "\n" + MARKERS["html"][1],
            1,
        )
    if not has_marker(text, MARKERS["js"][0]):
        anchor = "        let canonicalUserRefCoords = null;"
        insert = (
            "\n" + MARKERS["js"][0] + "\n" + MARKERS["js"][1] + "\n"
        )
        text = text.replace(anchor, insert + anchor, 1)
    if "function __odt_hook(" not in text:
        anchor = "        const lastKnownPointByIndex = new Map();  // index -> { pointLat, pointLon }"
        if anchor not in text:
            anchor = "        const lastKnownPointByIndex = new Map();"
        text = text.replace(
            anchor,
            anchor + "\n" + ODT_HOOK_STUB + PRODUCTION_JS_SNIPPET,
            1,
        )
    return text


def apply_hooks(text: str) -> str:
    for old, new in HOOK_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def strip_legacy_debug_block(text: str) -> str:
    """Remove old inline debug if markers not yet present (one-time migration)."""
    if has_marker(text, MARKERS["js"][0]):
        return text
    # Remove CSS block
    text = re.sub(
        r"\n        \.switch-debug-panel \{.*?        \.switch-debug-panel \.legend \{[^}]+\}\n",
        "\n",
        text,
        count=1,
        flags=re.DOTALL,
    )
    # Remove HTML panel
    text = re.sub(
        r"\n    <div id=\"switch-debug-panel\".*?</div>\n",
        "\n",
        text,
        count=1,
        flags=re.DOTALL,
    )
    # Remove inline JS from OVERLAY_DEBUG_BUILD through stuck-watchdog interval
    text = re.sub(
        r"\n        const OVERLAY_DEBUG_BUILD = .*?        \}, 5000\);\n        // #endregion\n",
        "\n",
        text,
        count=1,
        flags=re.DOTALL,
    )
    return text


def append_debug(overlay_path: Path) -> None:
    text = read_text(overlay_path)
    text = strip_legacy_debug_block(text)
    text = ensure_markers(text)
    text = apply_hooks(text)
    for _begin, end, frag in MARKERS.values():
        body = read_text(frag)
        if not body.endswith("\n"):
            body += "\n"
        text = replace_region(text, _begin, end, body)
    write_text(overlay_path, text)
    print(f"Appended debug table to {overlay_path}")


def remove_debug(overlay_path: Path) -> None:
    text = read_text(overlay_path)
    for begin, end, _frag in MARKERS.values():
        if has_marker(text, begin):
            text = replace_region(text, begin, end, "\n")
    write_text(overlay_path, text)
    print(f"Removed debug table content from {overlay_path} (markers kept; __odt_hook stubs remain)")


def sync_debug(overlay_path: Path) -> None:
    append_debug(overlay_path)


def status_debug(overlay_path: Path) -> None:
    text = read_text(overlay_path)
    for name, (begin, end, frag) in MARKERS.items():
        content = region_content(text, begin, end)
        active = content is not None and content.strip() != ""
        print(f"{name}: {'ACTIVE' if active else 'empty'} (fragment: {frag.name})")
    print(f"__odt_hook: {'yes' if 'function __odt_hook(' in text else 'no'}")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    overlay = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OVERLAY
    if not overlay.is_file():
        raise SystemExit(f"Overlay not found: {overlay}")
    if cmd == "append":
        append_debug(overlay)
    elif cmd == "remove":
        remove_debug(overlay)
    elif cmd == "sync":
        sync_debug(overlay)
    elif cmd == "status":
        status_debug(overlay)
    else:
        raise SystemExit(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
