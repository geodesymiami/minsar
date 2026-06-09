# Plan: Remove Debug Instrumentation From overlay.html

## Summary
Remove all debug instrumentation from `minsar/html/overlay.html` while preserving functional behavior. This includes debug UI hooks, debug logging calls, outbound debug ingest network calls, and embedded debug build/session metadata.

## Key Components Affected
- `minsar/html/overlay.html` — remove instrumentation blocks and invocations
- Potentially `minsar/html/ARCHITECTURE.md` — update if instrumentation is currently documented as active behavior

## Action Items
- [ ] Identify all debug instrumentation markers, helpers, and call sites in `overlay.html`
- [ ] Remove debug table panel markup and any duplicate debug-only DOM blocks
- [ ] Remove debug helper functions and constants (e.g., hook functions, debug session IDs, debug log wrappers)
- [ ] Remove outbound debug ingest `fetch(...)` calls and instrumentation-only comments/regions
- [ ] Verify `overlay.html` still parses and core behavior remains unchanged
- [ ] Run relevant tests and/or smoke checks

## Execution Plan (Detailed Change Instructions)
1. Scan `minsar/html/overlay.html` for instrumentation signatures (`debug`, `__odt_hook`, debug table markers, localhost ingest calls, debug build/session constants).
2. Remove debug-only HTML blocks:
   - debug table panel region and duplicated debug fragments if present.
3. Remove debug-only JavaScript:
   - instrumentation helper functions and wrappers
   - debug state trackers used only for logs/telemetry
   - calls to debug hooks inside operational flows, without changing non-debug control logic.
4. Remove external debug telemetry network calls (localhost ingest endpoints).
5. Re-read edited regions for syntax correctness and no dangling references.
6. Run lint diagnostics on `overlay.html` and execute targeted tests/smoke checks relevant to overlay behavior.
7. Update docs if they mention active instrumentation that no longer exists.

## Key Commands & Flows
- Code search in `overlay.html` for instrumentation markers (`debug`, `__odt_hook`, `localhost`, `switch-debug`)
- Optional targeted tests:
  - `python -m unittest discover -s tests -p "test_overlay_display_transfer.py" -v`
- Lint/diagnostic check on edited file via IDE diagnostics

## TODO List
- [ ] Capture baseline instrumentation occurrences
- [ ] Remove instrumentation from HTML
- [ ] Remove instrumentation from JS
- [ ] Verify no leftover debug identifiers
- [ ] Run focused tests/smoke checks
- [ ] Update docs if needed
