# Overlay switch-parameter debug table

Optional debug UI (fixed panel at bottom of `overlay.html`) that tracks parameter transfer across dataset switches: contours, pixelSize, background, opacity, autoColorScale, minScale, maxScale, point, chart, dates.

## Files

| File | Purpose |
|------|---------|
| `debug_table_overlay.css` | Panel styles (inlined into `<style>` in overlay) |
| `debug_table_overlay.html` | Panel DOM (injected before `</body>`) |
| `debug_table_overlay.inline.js` | Table logic + agent logging (inlined in overlay `<script>`; needs closure over overlay globals) |
| `apply_debug_table.py` | Append / remove / sync / status |

## Quick commands

From repo root:

```bash
# Insert debug table into overlay.html (also adds __odt_hook stubs if missing)
python3 minsar/html/debug_table_overlay/apply_debug_table.py append

# Strip debug content (keeps markers + harmless __odt_hook no-ops)
python3 minsar/html/debug_table_overlay/apply_debug_table.py remove

# Push edits from fragment files into overlay markers
python3 minsar/html/debug_table_overlay/apply_debug_table.py sync

# Check whether debug regions are populated
python3 minsar/html/debug_table_overlay/apply_debug_table.py status
```

Target a different overlay path:

```bash
python3 minsar/html/debug_table_overlay/apply_debug_table.py append /path/to/overlay.html
```

## Deploy with overlay

Copy the whole directory next to the deployed overlay:

```text
/data/.../mintpy/overlay.html
/data/.../mintpy/debug_table_overlay/   # only needed if you use external assets; inline splice does not require this at runtime
```

The apply script **inlines** CSS/HTML/JS into `overlay.html`, so deploy is just the updated `overlay.html` (no extra HTTP requests).

## How insertion works

`apply_debug_table.py append`:

1. Adds marker pairs if missing:
   - `<!-- debug-table-overlay:BEGIN:css -->` … `END:css -->` inside `<style>`
   - `<!-- debug-table-overlay:BEGIN:html -->` … `END:html -->` after `#container`
   - `/* debug-table-overlay:BEGIN:inline-js */` … `END:inline-js */` in main `<script>`
2. Adds `__odt_hook()` stub and production helpers (`urlDisplayParamsFromSrc`, `maybeReapplyDisplayParamsToActiveIframe`, …) if missing.
3. Rewrites direct debug calls to `__odt_hook('functionName', …)` so overlay runs without debug (no-ops).
4. Fills markers from `debug_table_overlay.*` fragment files.

`remove` clears the three marker regions; `__odt_hook` calls remain safe no-ops.

## Cursor / AI prompt

Say:

> **append debug table to overlay**

The agent should run:

```bash
python3 minsar/html/debug_table_overlay/apply_debug_table.py append minsar/html/overlay.html
```

To remove:

> **remove debug table from overlay**

```bash
python3 minsar/html/debug_table_overlay/apply_debug_table.py remove minsar/html/overlay.html
```

Reusable prompt (exact wording):

> **append debug table to overlay**
> Update `minsar/html/debug_table_overlay/{debug_table_overlay.css,debug_table_overlay.html,debug_table_overlay.inline.js}` as needed, then run:
> `python3 minsar/html/debug_table_overlay/apply_debug_table.py sync minsar/html/overlay.html`
> Finally deploy `minsar/html/overlay.html`.

## Editing the debug table

1. Edit `debug_table_overlay.css`, `.html`, or `.inline.js` in this directory.
2. Run `apply_debug_table.py sync` to update `overlay.html`.
3. Bump `OVERLAY_DEBUG_BUILD` in `debug_table_overlay.inline.js` when verifying a new build.

## Build label

Panel title shows `Switch parameter debug (OVERLAY_DEBUG_BUILD)`. Current: see `OVERLAY_DEBUG_BUILD` in `debug_table_overlay.inline.js`.

## Agent logging

When debug is appended, `dbgDisplayLog` / `dbgSwitchLog` POST to the Cursor debug ingest URL (session `b4a2c9`). Disable or change in `debug_table_overlay.inline.js` if not debugging.
