# overlay.html Architecture Documentation

**Last updated:** 2026-06-07 (autoColorScale sync; default-ref period switch)

## Overview

`overlay.html` is a multi-dataset InSAR map viewer. It embeds one **insarmaps** iframe per dataset (Descending, Ascending, Horizontal, Vertical) and keeps their **view state** in sync: map position, color scale, time period, pixel size, contours, time-series point, and custom reference point.

The overlay page is served from the **data server** (e.g. `http://149.165.154.65/data/HDF5EOS/.../overlay.html`). Each iframe loads **insarmaps** from a separate origin (e.g. `http://149.165.153.50`). That cross-origin split is central to the design.

**Primary source file:** `minsar/html/overlay.html`  
**Companion insarmaps changes:** `tools/insarmaps/public/js/mainPage.js`, `mainMap.js`, `GraphsController.js` (required for custom ref + narrowed dates on dataset switch).

---

## 1. High-level architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  overlay.html  (data server origin, e.g. 149.165.154.65)               │
│                                                                         │
│  State: currentMapParams, userNarrowedDateRange, iframeSynced, ...     │
│                                                                         │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐                    │
│  │ iframe0 │  │ iframe1 │  │ iframe2 │  │ iframe3 │   one per dataset  │
│  │  desc   │  │   asc   │  │  horz   │  │  vert   │                    │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘                    │
│       │            │            │            │                          │
│       └────────────┴────────────┴────────────┘                          │
│                         │                                               │
│              postMessage (both directions)                                │
│                         │                                               │
└─────────────────────────┼───────────────────────────────────────────────┘
                          ▼
              insarmaps (separate origin, e.g. 149.165.153.50)
```

### Two sync mechanisms (do not conflate them)

| Mechanism | When used | What it can set |
|-----------|-----------|-----------------|
| **URL reload** (`iframe.src = buildInsarmapsUrl(...)`) | Background warm, dataset switch, pan/zoom/scale sync to other iframes | Everything insarmaps reads from URL: view, scales, dates, point, ref, pixelSize, contour, colorscale |
| **postMessage** | Contours, narrowed dates after custom-ref switch, ref-applied ack, chart dot clicks | Only what insarmaps explicitly handles in `mainPage.js` listeners |

**Critical rule:** The overlay **cannot** call `iframe.contentWindow.myMap...` (cross-origin `SecurityError`). All in-iframe control after load must go through **postMessage** or a **new URL reload**.

---

## 2. Data sources and URL building

### insarmaps.log

Read at page load. Two line types (see `minsar/html/README.md`):

1. **Full URL** — template for map options (lat/lon/zoom, scales, dates, point, etc.).
2. **Dataset name only** — expanded via `expandDatasetNameLine()` using the first full URL.

Datasets are sorted: **desc → asc → horz → vert**.

### expandDatasetNameLine — mintpy pitfall

Mintpy logs often put **descending-only** params on the first URL line (`colorscale=velocity`, `startDate`, `endDate`, `pointLat`/`pointLon`). Name-only lines (e.g. `S1_asc_...`) must **not** inherit those.

`TEMPLATE_PARAMS_STRIP_ON_EXPAND` deletes before building asc/horz/vert URLs:

`pointLat`, `pointLon`, `refPointLat`, `refPointLon`, `colorscale`, `startDate`, `endDate`

| Param in ascending iframe URL | sarvey-style log | mintpy-style log (before strip) |
|------------------------------|------------------|----------------------------------|
| `refPointLat`/`refPointLon` | when user sets ref | when user sets ref |
| `colorscale=velocity` | usually absent | was copied from desc — **strip** |
| `startDate`/`endDate` | usually absent | was copied from desc — **strip on expand** |
| `pointLat`/`pointLon` | usually absent | was copied from desc — **strip on expand** |

### buildInsarmapsUrl()

Builds `/start/{lat}/{lon}/{zoom}?flyToDatasetCenter=false&startDataset=...&{params}&_t=...`

- `_t` — cache-bust on every intentional reload.
- `mapParamsForIframeLoad(mapParams, loadKind)` may strip params per load kind (see §5).

### Overlay URL (bookmarkable)

Hash-based (preferred):

```
overlay.html#/start/0.7480/-77.9687/9.8000?startDataset=S1_desc_...&minScale=-3&maxScale=3&startDate=...&endDate=...
```

---

## 3. In-memory state (what a rewrite must preserve)

| Variable | Purpose |
|----------|---------|
| `currentMapParams` | Authoritative overlay state: view, scales, dates, point, ref, pixelSize, contour, colorscale, background, opacity, `autoColorScale` |
| `userNarrowedDateRange` | User's intentionally narrowed period; survives iframe "widen" noise during refSwitch |
| `periodSelectionSource` | How period was set: `'slider'`, `'chart-dot'`, `'iframe-sync'`, or null |
| `baselineMissionDateRange` | Mission-wide first/last date (union of all datasets); used to detect "full period" vs narrowed |
| `datasetDateRanges` | Per-dataset `first_date`/`last_date` from insarmaps postMessages |
| `iframeSynced` / `iframePointSynced` | Per-iframe sync keys — skip reload if URL already matches |
| `iframeWarmInFlight` | Background preload in progress |
| `pendingDateSyncByIndex` | Awaiting `insarmaps-set-dates-applied` ack for narrowed dates |
| `refAppliedForDateSyncByIndex` | Custom ref confirmed on iframe; gates date postMessage |
| `activeSwitchTracking` | Per-switch debug outcome: refOk, datesOk (see §12) |

### Sync keys

```javascript
getSyncKey(params)      // view + display + dates + point + ref + colorscale
getViewSyncKey(params)  // same as getSyncKey but without startDate/endDate
getPointKey(params)     // pointLat/Lon + refPointLat/Lon only
```

---

## 4. Page load and iframe lifecycle

1. Fetch `insarmaps.log` (10s timeout; error → redirect back).
2. Parse, sort, seed `baselineMissionDateRange` from template URLs.
3. Create one `.panel` + iframe per dataset; only **active** iframe gets `src` immediately.
4. On active `onload` → `scheduleWarmAll()` preloads background iframes.
5. Loading overlay hidden on first `insarmaps-url-update` or 15s timeout.

Background iframes use `visibility: visible` + `z-index: -1` so they load without blocking the active view.

---

## 5. Dataset switch — the critical path

`selectDataset(index)`:

1. Show/hide panels (instant).
2. **If custom ref** (`hasCustomRefPoint`): `reloadDatasetIframe(index, 'switch-dataset-ref', 'refSwitch')` — **always force reload**.
3. **Else**: `syncDatasetIframeOnSwitch(index)` — reload only if sync key stale.
4. postMessage `insarmaps-set-contour` to newly visible iframe.
5. `beginSwitchTracking(from, to)` for debug logging.

### mapParamsForIframeLoad — load kinds

When **custom ref** is set:

| loadKind | Stripped from URL | Kept |
|----------|-------------------|------|
| `refSwitch` | `colorscale`, **`startDate`**, **`endDate`** | `pointLat`/`pointLon`, `refPointLat`/`refPointLon`, scales, view, pixelSize, contour |
| `crossDataset` | `colorscale` only | dates, point, ref, everything else |
| `dateAfterRef` | `colorscale`, `contour`, `pixelSize` | dates + ref (sarvey full-period only; see below) |

**Why refSwitch drops dates:** Loading custom ref + narrowed dates in one URL makes insarmaps run date recolor **before** custom ref recolor applies → map shows default-referenced data with a custom ref marker. Fix: phase 1 = ref only; phase 2 = dates via postMessage.

### Two-phase flow (custom ref + narrowed period)

```
User on Desc: custom ref + narrowed period
        │
        ▼
selectDataset(Asc)
        │
        ▼
Phase 1: refSwitch reload
  URL: point + ref + scales + view  (NO startDate/endDate)
        │
        ▼
insarmaps applies ref from URL → postMessage insarmaps-ref-applied
        │
        ▼
Phase 2: overlay postMessage insarmaps-set-dates { startDate, endDate }
        │
        ▼
insarmaps applies dates → postMessage insarmaps-set-dates-applied
        │
        ▼
Done: Asc has custom ref + narrowed period
```

`scheduleNarrowedDateSync()` / `maybeStartDateSyncAfterRef()` orchestrate phase 2. Phase 2 waits for `insarmaps-ref-applied` when `awaitRef` is true.

### dateAfterRef (legacy second URL load)

`shouldRunDateAfterRef()` — only for **non-mintpy** datasets when period is **full mission** (`isFullMissionDateRange()`). Mintpy always skips; narrowed periods always use postMessage instead.

---

## 6. postMessage protocol

### iframe → overlay (insarmaps sends)

| type | Purpose |
|------|---------|
| `insarmaps-url-update` | Any URL change (pan, zoom, slider, scales, ref, point). Includes `url`, optional `firstDate`/`lastDate`. Debounced 1500ms for background sync. |
| `insarmaps-ref-applied` | Custom ref recolor succeeded. `{ refPointLat, refPointLon }`. Triggers phase-2 date sync. |
| `insarmaps-ref-failed` | Ref application failed; overlay may auto-retry refSwitch. |
| `insarmaps-set-dates-applied` | Ack that dates were applied inside iframe. |
| `insarmaps-timeseries-date` | User clicked a date on the displacement chart (Time Controls period selection). |

### overlay → iframe (overlay sends)

| type | Purpose | Handler in insarmaps |
|------|---------|---------------------|
| `insarmaps-set-contour` | `{ value: true/false }` — no reload | `mainPage.js` |
| `insarmaps-set-dates` | `{ startDate, endDate }` YYYYMMDD — cross-origin date apply | `mainPage.js` → `GraphsController.applyInsarDateRangeFromYyyymmdd()` |
| `insarmaps-set-auto-color-scale` | `{ mode: 'true'\|'false', minScale?, maxScale? }` — URL `autoColorScale=true\|false`; `true`=data min/max centered on 0, `false`=manual (+ `minScale`/`maxScale`) | `mainMap.setAutoColorScaleMode()` / `disableAutoColorScaleWithLimits()` |

**No `insarmaps-set-point` or `insarmaps-set-ref`** — point and ref must go in the **iframe URL** on reload.

---

## 7. Narrowed time period — capture and resolve

### Problem this solves

After `refSwitch`, the iframe loads without dates and temporarily reports the **full dataset span** in `insarmaps-url-update`. Without guards, overlay would overwrite the user's narrowed period.

### captureUserNarrowedDateRange()

Records `{ startDate, endDate }` when the user narrows via slider or chart. Rejects:

- Log-template full-span dates from `insarmaps.log`
- Dataset full-span (`first_date`–`last_date`)
- Widen attempts relative to stored narrow range

### resolveDatesFromIframeUpdate()

For each incoming date update, returns an **action**:

| action | Meaning |
|--------|---------|
| `captured-user-narrow` | New user narrow accepted |
| `rejected-widen-kept-user` | Iframe tried to widen; kept `userNarrowedDateRange` |
| `rejected-dataset-full-kept-user` | Iframe reported full dataset span during refSwitch load |
| `rejected-log-template-kept-user` | Iframe echoed insarmaps.log template dates |
| `rejected-iframe-drift-kept-slider-narrow` | Default ref only: insarmaps acquisition snap on `active-postMessage`; kept `userNarrowedDateRange` from slider |
| `accepted-active` | Normal active iframe date change |
| `ignored-background` | Background iframe widen ignored |

### reassertNarrowedDatesToIframe — do not over-use

Sends another `insarmaps-set-dates` when overlay rejects a widen. **Over-aggressive reassert caused slider snap-back** (post-fix32): reassert fired during user slider drags and redundant set-dates triggered map refresh.

`shouldReassertAfterDateReject()` now skips:

- `path === 'url-update-debounced'` (user dragging)
- Within 2.5s of last slider capture
- All `rejected-widen-kept-user` (expected during refSwitch)

---

## 8. Default-ref narrowed period — warm, drift pin, and seamless switch

### Problem (2026 debug)

With **default ref** and a slider-narrowed period, Desc→Asc switch showed: narrowed period → full period flash → reload → narrowed period. After several toggles it became seamless.

**Root causes:**

1. **Acquisition snap drift** — After the user stops dragging, insarmaps keeps posting slightly different `startDate`/`endDate` (nearest SAR acquisitions). Overlay `currentMapParams` drifted ~10 days from what background pre-warm had loaded.
2. **URL date mismatch** — Active Desc iframe often has **no** `startDate`/`endDate` in `iframe.src` after slider use (dates live in insarmaps internal state only). `syncDatasetIframeOnSwitch` compared sync keys but not URL dates, or skipped reload while content was stale.
3. **Cross-dataset calendar dates** — The same calendar range does not mean the same URL dates on Desc vs Asc; insarmaps snaps per dataset inside `applyInsarDateRangeFromYyyymmdd()`.

### Three-layer fix (default ref only)

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| **Pin intent** | `rejected-iframe-drift-kept-slider-narrow` in `resolveDatesFromIframeUpdate()` | After slider capture (`periodSelectionSource === 'slider'`), reject acquisition snap on `active-postMessage`; keep `userNarrowedDateRange` |
| **Pre-warm** | `schedulePeriodBackgroundWarm()` / `flushPeriodBackgroundWarm()` | Reload **background** iframes with `mapParamsForPeriodSync()` (uses pinned `userNarrowedDateRange`). Reason suffix `:period` bypasses preload-in-progress skips. `iframeSynced` committed on **onload**, not on `setIframeSrc` start |
| **Switch** | `syncDatasetIframeOnSwitch()` set-dates fast path | If view params match (`getViewSyncKey`) and period is narrowed: `insarmaps-set-dates` postMessage instead of full reload — **including when sync-key skip would apply** (calendar URL dates ≠ per-dataset snapped display). Insarmaps snaps per dataset without iframe flash |

**Custom ref is unchanged** — still `refSwitch` reload → wait `insarmaps-ref-applied` → `insarmaps-set-dates`. Drift pin and set-dates fast path are gated on `!hasCustomRefPoint()`.

### Active-iframe postMessage flow

When the **active** iframe changes pan/zoom/scales/dates (not contour-only):

1. **Immediate path** (`active-postMessage`): default-ref period changes → `schedulePeriodBackgroundWarm()` after 150ms (`PERIOD_WARM_DEBOUNCE_MS`). Updates `currentMapParams` when `datesChanged` even if `backgroundsWarmed && !keyChanged` (period-only slider moves after initial warm).
2. **Debounced path** (1500ms `SYNC_DEBOUNCE_MS`): `flushPeriodBackgroundWarm()` if `backgroundsPeriodWarmNeeded()` (checks sync keys, URL dates, in-flight loads).
3. Update `currentMapParams` (dates through `resolveDatesFromIframeUpdate()`).
4. Active iframe is **never** reloaded for period-only changes (default ref).

**Contour-only:** postMessage `insarmaps-set-contour` to all iframes — no reload.

**Cooldown:** Non-active iframe messages ignored for 3s after a sync (`SYNC_COOLDOWN_MS`). Active iframe bypasses cooldown.

### Key helpers

| Function | Role |
|----------|------|
| `mapParamsForPeriodSync()` | Overlay `currentMapParams` with pinned `userNarrowedDateRange` dates |
| `backgroundsPeriodWarmNeeded()` | True if any background has wrong sync key, wrong URL dates, or warm in-flight |
| `iframeDatesMatchExpected()` | Compare `iframe.src` query dates to expected YYYYMMDD |
| `applyDatesToIframeOnSwitch()` | postMessage `insarmaps-set-dates` on dataset switch (default ref fast path) |
| `maybeCatchupWarmAfterLoad()` | After background onload, schedule period catch-up warm if still stale |

---

## 9. What must transfer on dataset switch (checklist for rewrites)

When switching Desc ↔ Asc ↔ Horz ↔ Vert, these should persist:

| State | How it transfers | Common failure |
|-------|------------------|----------------|
| Map view (lat/lon/zoom) | In reload URL | Usually OK |
| minScale / maxScale | In reload URL | Usually OK |
| **Custom ref** (`refPointLat`/`refPointLon`) | `refSwitch` URL + insarmaps ref recolor | Marker shows but **data not re-referenced** if dates/colorscale race ref |
| **Time-series point** (`pointLat`/`pointLon`) | In reload URL | Lost if `mapParamsForIframeLoad` strips point |
| **Narrowed period (custom ref)** | Phase 2 `insarmaps-set-dates` postMessage after ref | Lost if dates in refSwitch URL; lost if cross-origin slider access attempted |
| **Narrowed period (default ref)** | Pre-warm backgrounds + set-dates on switch | Drift if acquisition snap overwrites slider intent; flash if full URL reload used when only dates differ |
| pixelSize | In reload URL (refSwitch keeps it) | Lost if stripped in `dateAfterRef` |
| contours | URL on reload + `insarmaps-set-contour` on switch | Timing: hidden iframe may miss contour message |
| colorscale | Stripped on cross-dataset when custom ref | Intentional — `colorscale=velocity` races ref recolor on mintpy |

---

## 10. Bug history — lessons for a clean rewrite

These bugs were found during 2026 debugging (mintpy/qChiles, testChiles, testMiami/sarvey). A rewrite should implement the **correct behaviour** without repeating the trial-and-error fixes.

### 10.1 Custom ref not applied on switched dataset

**Symptom:** Ref marker correct; displacement data still default-referenced.

**Causes (layered):**

1. **URL param races** — `colorscale=velocity` + `startDate`/`endDate` in same load as `refPointLat`/`refPointLon` → insarmaps date recolor runs before ref recolor.
2. **False "already synced"** — `iframeSynced` matched but insarmaps never applied ref internally.
3. **Tile timing in insarmaps** — `refreshDatasetWithNewReferencePoint()` before tiles rendered → silent no-op.
4. **expandDatasetNameLine** — mintpy asc inherited desc-only params from template URL.

**Fix pattern:** `refSwitch` = minimal URL (ref + point + scales, no dates/colorscale); wait for `insarmaps-ref-applied`; then `insarmaps-set-dates`.

**Full detail on waiting, user messages, watchdogs, and what remains broken:** see **§19**.

### 10.2 Time period lost on switch

**Symptom:** After switch, slider shows full dataset span.

**Causes:**

1. Dates stripped from switch URL (correct for ref) but phase 2 never ran.
2. Cross-origin attempt to set slider via `iframe.contentWindow.myMap.graphsController` — **blocked**.
3. `reassertNarrowedDatesToIframe` fighting user slider drags.
4. `mainPage.js` calling `refreshDatasetWithNewReferencePoint` on every `insarmaps-set-dates` even when dates unchanged → slider reset.

**Fix pattern:** postMessage dates only; `datesChanged` guard before map refresh; conservative reassert.

### 10.3 Time-series graph lost on switch

**Symptom:** No displacement chart after switch.

**Cause:** `mapParamsForIframeLoad` stripped `pointLat`/`pointLon` while fixing ref.

**Fix:** Always keep point in refSwitch/crossDataset URLs.

### 10.4 Slider snap-back after ref + switch

**Symptom:** Slider works without custom ref; breaks after ref + Desc→Asc or Asc→Desc.

**Cause:** Feedback loop — overlay reassert + insarmaps redundant refresh on unchanged dates.

**Fix (post-fix32):** `shouldReassertAfterDateReject()` + `datesChanged` check in `mainPage.js` `insarmaps-set-dates` handler.

### 10.5 Background warm with partial ref

**Symptom:** Asc preloaded with `refPointLat` only, `refPointLon` null.

**Fix:** `hasPartialCustomRef()` — do not warm until both coords present.

### 10.6 Default-ref narrowed period not seamless on switch

**Symptom:** First Desc→Asc after narrowing shows full period, reload flicker, or wrong dates; improves after repeated toggles.

**Causes:**

1. Background warm used dates that drifted after slider stopped (insarmaps acquisition snap).
2. `iframeSynced` set before iframe onload → false "already synced".
3. Switch compared sync keys only; `iframe.src` often missing date query params on active dataset.
4. Full iframe reload shows insarmaps full-span load before dates apply.

**Fix pattern (default ref only):** Pin slider intent → pre-warm with `mapParamsForPeriodSync()` → on switch use `insarmaps-set-dates` when view matches (§8). Does **not** apply to custom-ref switch path.

---

## 11. Insarmaps companion requirements

Overlay alone is insufficient for custom ref + narrowed dates. Insarmaps must provide:

| Feature | File | Notes |
|---------|------|-------|
| `insarmaps-set-dates` handler | `mainPage.js` | Applies dates; replies `insarmaps-set-dates-applied`. Only `refreshDatasetWithNewReferencePoint` when **dates actually changed**. |
| `insarmaps-ref-applied` postMessage | `mainMap.js` | After custom ref recolor verified. |
| `applyInsarDateRangeFromYyyymmdd()` | `GraphsController.js` | Slider + chart navigator sync; `_programmaticDateSync` flag to avoid feedback loops. |
| Deferred ref until tiles loaded | `mainMap.js` | `applyStartingDatasetPointSelections` (waits for `queryRenderedFeatures` before synthetic click). |
| `insarmaps-ref-failed` postMessage | `mainMap.js` | When URL ref apply exhausts retries. |

Deploy overlay to **data server**; deploy insarmaps JS to **insarmaps server** (different hosts).

---

## 12. Debugging — switch-result table

Switch-result tables were built from debug instrumentation (since removed). The tracking hooks (`beginSwitchTracking`, `logSwitchOutcomePart`) remain in code but no longer emit logs. To re-enable debugging, add fetch/post to a log ingest endpoint at these locations. Key log messages for building switch-result tables:

| Log `message` | Source | Use |
|---------------|--------|-----|
| `switch attempt` | `beginSwitchTracking` | Start of switch: from/to, `userNarrowedAtSwitch`, `hasCustomRef` |
| `switch outcome` | `logSwitchOutcome` | End: `outcome`, `refOk`, `datesOk`, `elapsedMs` |
| `ref applied postMessage received` | ref-applied handler | Ref phase success |
| `postMessage set-dates sent` | `tryApplyNarrowedDatesToIframe` | Date phase started |
| `postMessage date sync applied` | `onDateSyncApplied` | Date phase ack |
| `date resolve` | `logDateResolve` | Widen rejects, `willReassert` |
| `user slider drag` | `GraphsController.js` | Confirms slider not fighting overlay |

### Switch-result table format

Build one row per completed switch from `switch attempt` + `switch outcome` pairs:

| # | Switch | Period (start → end) | pixel_size | contours | Ref | Dates | Outcome |
|---|--------|----------------------|------------|----------|-----|-------|---------|
| 1 | Desc → Asc | 20160525 → 20190820 | 6.5 | on | ✓ (`refIndex:1`, coords match) | ✓ (`onDateSyncApplied`) | **success** |
| 2 | Desc → Asc | 20150914 → 20260304 | 6.5 | on | ✗ (no `ref-applied` in time) | ✗ (`no-ack`) | **FAILED** |

**Column sources:**

- **Switch** — `fromLabel` → `toLabel` from `switch attempt`
- **Period** — `userNarrowedAtSwitch` or `currentMapParams` at switch time
- **pixel_size / contours** — `currentMapParams.pixelSize`, `currentMapParams.contour`
- **Ref** — `refOk` from `switch outcome`; verify with `insarmaps-ref-applied` + coord match
- **Dates** — `datesOk`; verify with `insarmaps-set-dates-applied` matching pending range
- **Outcome** — `outcome` field: `success`, `ref-failed`, `dates-failed`, `ref-and-dates-failed`

### Example outcomes from test sessions (2026-06)

| Scenario | Custom ref | Narrowed period | Typical result after fixes |
|----------|------------|-----------------|---------------------------|
| Reload, no ref, slider on Desc+Asc | No | Any | ✓ both datasets |
| No ref, narrow slider, wait, Desc↔Asc switch | No | Yes | ✓ seamless (§8 set-dates path) |
| Ref on Desc, switch to Asc | Yes | No | ✓ ref transfers |
| Ref on Desc, narrow slider, switch to Asc | Yes | Yes | ✓ ref + period (post-fix32) |
| Full mission period | Yes | No (full) | ✓ sarvey may use dateAfterRef URL phase |

---

## 13. Time Controls mode

(Unchanged core behaviour; custom-ref sync above applies to main dataset iframes, not period iframes.)

- **Open Time Controls:** `loadPeriodsForDataset()` — one iframe per period for active dataset.
- **Change period (◀/▶/Play):** `showPeriod(idx)` — show/hide only, no reload.
- **Dataset switch with TC on:** `restoreToBaselineState()` for new dataset.

### Known limitation: Reference point in Time Controls mode (unresolved, 2026-02-13)

Changing ref in the visible period iframe does not re-reference other period iframes' data. Only the visible period applies the new ref. Documented for retry later.

---

## 14. Period Selection Mode (+/−)

Pure UI toggle for registering start/end dates from chart dot clicks. No reload on enter/exit. `insarmaps-timeseries-date` postMessage feeds the Start/End inputs. Sets `periodSelectionSource` to `'chart-dot'` (distinct from slider-driven period in §8).

---

## 15. Action summary table (current behaviour)

| User action | Overlay response | Iframes reloaded? |
|-------------|------------------|-----------------|
| Pan/zoom/scales/background/opacity/slider | Debounced sync → reload **other** datasets | Others only |
| Contour toggle | `insarmaps-set-contour` to **all** | None |
| Dataset switch, **no custom ref**, narrowed period | Show/hide; set-dates if view matches, else reload | Target only if view stale |
| Dataset switch, **no custom ref**, full period | Show/hide; reload target if stale | Target if stale |
| Dataset switch, **custom ref** | `refSwitch` reload → wait ref → `set-dates` postMessage | Target always |
| Point/ref click | Warm background iframes with new URL | Backgrounds |
| Time Controls period step | Show/hide period panel | None |

---

## 16. Key functions (quick reference)

| Function | Role |
|----------|------|
| `parseInsarmapsLogUrls()` | Parse log; expand name-only lines |
| `expandDatasetNameLine()` | Build per-dataset URL; strip template params |
| `buildInsarmapsUrl()` | Full iframe URL with cache-bust |
| `mapParamsForIframeLoad()` | Strip params per load kind (refSwitch critical) |
| `selectDataset()` | Dataset switch orchestration |
| `reloadDatasetIframe()` | Force iframe reload with reason + loadKind |
| `syncDatasetIframeOnSwitch()` | Default ref: skip reload, set-dates fast path, or full reload |
| `scheduleWarmAll()` / `warmAllBackgroundIframes()` | Background preload |
| `resolveDatesFromIframeUpdate()` | Accept/reject date changes from iframes |
| `captureUserNarrowedDateRange()` | Store user's narrowed period |
| `mapParamsForPeriodSync()` | Merge pinned `userNarrowedDateRange` into params for warm/switch |
| `backgroundsPeriodWarmNeeded()` | Whether backgrounds need period re-warm |
| `applyDatesToIframeOnSwitch()` | Default-ref switch: postMessage dates without reload |
| `scheduleNarrowedDateSync()` / `tryApplyNarrowedDatesToIframe()` | Custom-ref phase-2 date postMessage |
| `schedulePeriodBackgroundWarm()` / `flushPeriodBackgroundWarm()` | Default-ref period pre-warm of background datasets |
| `maybeCatchupWarmAfterLoad()` | Period catch-up warm after background iframe onload |
| `maybeStartDateSyncAfterRef()` | Start dates after `insarmaps-ref-applied` |
| `shouldReassertAfterDateReject()` | Guard against reassert feedback loops |
| `beginSwitchTracking()` / `logSwitchOutcomePart()` | Debug switch tables |
| `getSyncKey()` / `getViewSyncKey()` / `getPointKey()` | Staleness detection |

---

## 17. Known limitations

### Contours may not show when switching frames

Contour is applied via postMessage without reload. Hidden iframes may not be ready when the message arrives. See historical analysis in git history of this file. Workaround: toggle contour again after switch.

### Cross-origin

Overlay and insarmaps are different origins. All in-iframe manipulation after load requires postMessage or URL reload.

### Mintpy vs sarvey log formats

Mintpy `insarmaps.log` first lines carry more query params. Any rewrite must treat **per-dataset URL building** and **template param stripping** as first-class, not an afterthought.

---

## 19. Reference point application — waiting, user messages, and recovery

**Rewrite priority.** This is the hardest unsolved part of overlay.html. The reference **marker** can appear while displacement **data** still uses the database default reference. Dataset switch with a narrowed period depends on ref finishing before date sync — if ref never completes, dates and slider also fail.

### 19.1 Symptom vs internal state

| What user sees | What may be true internally |
|----------------|----------------------------|
| Black ref marker at correct location | `addReferencePointSourceAndLayer` ran |
| Map colors look like default reference | `refreshDatasetWithNewReferencePoint` never ran or ran on empty tiles |
| Time series graph shows wrong reference | `/point` displacement fetch failed or used stale ref |
| Switch "succeeds" but map wrong on new dataset | `insarmaps-ref-applied` never received, or received from **wrong** iframe |
| Status banner "still loading" for 15+ s | Ref genuinely stuck, not merely slow |

### 19.2 Why ref application is asynchronous and fragile

Insarmaps was built for **user click** on a rendered InSAR point, not for overlay-driven cross-origin sync. On iframe load with `refPointLat`/`refPointLon` in the URL, `applyStartingDatasetPointSelections()` in `mainMap.js`:

1. Waits for `onceRendered` (map style loaded — **not** the same as InSAR tiles queryable).
2. Calls `map.queryRenderedFeatures(pt)` at the ref coordinates.
3. If no feature → retry up to **40** `onceRendered` cycles; else post `insarmaps-ref-failed` (`url-ref-retries-exhausted`).
4. On hit → `leftClickOnAPoint` → async `/point` fetch for displacements.
5. Waits up to **80** more `onceRendered` cycles for `nonDefaultReferencePoint()`; else `url-ref-wait-exhausted`.

**Failure modes:**

- Iframe loaded while **hidden** (background warm) — tiles may never become queryable.
- **Cold datasets** (especially Vert/Horz first switch) — tiles slow; retries exhaust.
- **Date recolor races ref** — if dates hit URL or `insarmaps-set-dates` before ref ready, `mainPage.js` logs `waitingForRef: true` and map stays default-referenced.
- **False success signal** — in overlay iframe mode, `addReferencePointFromClick` posts `insarmaps-ref-applied` when the **click path** completes but sets `_deferRefRecolorUntilSetDates = true`; map recolor waits for parent's `insarmaps-set-dates`. Overlay treats ref-applied as "phase 1 done" even though **map pixels may not be re-referenced yet**.

### 19.3 Two-phase switch depends on ref acknowledgment

```
refSwitch reload
    → insarmaps applyStartingDatasetPointSelections
    → (hopefully) insarmaps-ref-applied
    → overlay maybeStartDateSyncAfterRef
    → insarmaps-set-dates
    → insarmaps-set-dates-applied
```

If step 3 never happens, phase 2 is blocked (`pending.awaitRef === true`) or date sync returns `waitingForRef: true` and fails with `no-ack`.

**Waiting helps when ref is slow; waiting does not help when ref is stuck.** Session logs showed a Vert switch where the user waited **31 s** but `insarmaps-ref-applied` never arrived — only `url point applied`, not `url ref applied`.

### 19.4 User-facing messages (`#ref-status-indicator`)

Orange banner below the dataset dropdown (`aria-live="polite"`). Shown via `updateRefStatusIndicator(text, visible)`.

| When shown | Message text |
|------------|--------------|
| Date sync gave up retries but ref still pending (`shouldDeferDateSyncFailure`) | `Applying reference point on {label}… Map and time series may be incomplete until it finishes.` |
| **8 s** after switch with ref still pending (`REF_STATUS_ADVISE_MS`) | `Reference point is still loading on {label}. Switch to another view and back, or wait — we will retry automatically.` |
| **15 s** watchdog triggers auto-retry (`REF_STUCK_WATCHDOG_MS`) | `Retrying reference point load on {label}…` |
| Auto-retry exhausted (`MAX_REF_AUTO_RETRIES = 1`) | `Reference point did not load on {label}. Switch to another dataset and back to retry.` |
| `insarmaps-ref-failed` received from active iframe | `Reference point could not be applied on {label}. Retrying…` |

Banner clears when `insarmaps-ref-applied` is accepted and `clearRefRecoveryState()` runs.

### 19.5 postMessage contract (ref-specific)

**iframe → overlay**

| type | When sent | Payload |
|------|-----------|---------|
| `insarmaps-ref-applied` | Ref click + displacement fetch succeeded (overlay path may defer map recolor) | `{ refPointLat, refPointLon }` |
| `insarmaps-ref-failed` | URL ref apply exhausted retries or apply failed | `{ reason, isRef, refPointLat?, refPointLon? }` |

**`reason` values from insarmaps:**

| reason | Meaning |
|--------|---------|
| `url-ref-retries-exhausted` | No queryable InSAR feature at ref coords after 40 tile-wait cycles |
| `url-ref-wait-exhausted` | Click happened but `nonDefaultReferencePoint()` never became true after 80 cycles |
| `url-ref-apply-failed` | `clickAtLatLon` callback returned false |
| `url-point-retries-exhausted` | Time-series point click failed (point phase before ref) |

**overlay acceptance rules (`shouldAcceptRefAppliedForDateSync`):**

- Accept only from **active iframe** (`activeDatasetIdx`) or **current switch target** (`activeSwitchTracking.to`).
- **Ignore** ref-applied from background warm reloads (e.g. Desc finishing warm while user switched to Asc) — logged as `ignored background ref-applied`.

### 19.6 Overlay recovery mechanisms (what we built)

| Mechanism | Timing / trigger | Action |
|-----------|------------------|--------|
| `scheduleNarrowedDateSync` + `awaitRef` | On iframe load after refSwitch | Hold `insarmaps-set-dates` until ref-applied |
| `REF_AWAIT_WATCHDOG_MS` (6 s) | No ref-applied yet | Force `tryApplyNarrowedDatesToIframe` anyway (may still get `waitingForRef`) |
| `shouldDeferDateSyncFailure` | `no-ack` while ref pending | **Keep** pending; show "Applying reference point…"; do **not** mark switch dates failed |
| `reassert` with `awaitRef` | Iframe reports full-span widen | Update pending dates only; no set-dates until ref applied (post-fix28) |
| `scheduleRefRecoveryWatchdogs` | Switch + date-sync-deferred | 8 s advisory banner; 15 s auto `refSwitch` retry |
| `tryRefStuckRecovery` | 15 s watchdog or ref-failed | `reloadDatasetIframe(..., 'refSwitch')` once (`MAX_REF_AUTO_RETRIES = 1`) |
| `handleInsarmapsRefFailed` | `insarmaps-ref-failed` on active iframe | Banner + immediate `tryRefStuckRecovery` |
| `refAppliedForDateSyncByIndex` | Set on accepted ref-applied | Gates reassert and date-sync failure handling |

### 19.7 Chronology of fix attempts (2026)

| Iteration | What we tried | Result |
|-----------|---------------|--------|
| Early | Put ref + dates in one switch URL | Ref lost — date recolor races ref |
| post-fix9–11 | `refSwitch` without dates; postMessage dates | Correct architecture; ref still flaky inside insarmaps |
| insarmaps | `applyStartingDatasetPointSelections` waits for tiles | Better; still fails on hidden/cold iframes |
| insarmaps | `_deferRefRecolorUntilSetDates`; ref-applied before set-dates | Overlay can proceed to dates; map recolor lags |
| post-fix25 | `shouldAcceptRefAppliedForDateSync` | Fixed Desc background stealing Asc date sync |
| post-fix28 | `no-ack` keeps pending while ref expected; reassert awaits ref | Fixed premature date failure; watchdog can still fire |
| post-fix29 | 8 s / 15 s watchdogs, user banner, `insarmaps-ref-failed`, 1 auto-retry | User visibility; helps slow ref; **stuck ref still fails** after 1 retry |
| post-fix32 | Stop reassert fighting slider; `datesChanged` guard | Slider fixed after ref+switch; ref stuck unchanged |

### 19.8 What a rewrite should do differently

Problems in the current design that a clean implementation could address:

1. **Synthetic click is the wrong abstraction** — Simulate click only because insarmaps has no `insarmaps-set-ref` API. A rewrite should add an explicit server-side or API-level "re-reference dataset to lat/lon" that does not depend on `queryRenderedFeatures` on a hidden iframe.

2. **`insarmaps-ref-applied` semantics are ambiguous** — Today it means "click path finished", not "map tiles re-referenced". Split into `ref-displacements-ready` and `ref-map-recolored`, or block ref-applied until `refreshDatasetWithNewReferencePoint` confirms.

3. **Hidden iframe ref apply** — Background warm + ref in URL is unreliable. Options: do not warm with ref until user switches; or apply ref only when iframe becomes visible; or use a dedicated visible reload on switch (current `refSwitch` force reload).

4. **Stuck vs slow detection** — Distinguish tile-wait exhaustion (`ref-failed`) from slow load (extend retries when iframe visible). `MAX_REF_AUTO_RETRIES = 1` is minimal; cold Vert may need more or a user-triggered retry button.

5. **Date sync must never run before ref** — `waitingForRef` in insarmaps is correct; overlay must never spam set-dates (reassert guards, post-fix28/32). Keep this invariant in any rewrite.

6. **Do not use ref-applied from wrong iframe** — Any multi-iframe design needs switch-target gating from day one.

### 19.9 Debug log lines for ref-wait problems

| Log `message` | Interpretation |
|---------------|----------------|
| `url ref retries exhausted` | No tile at ref coords — stuck or hidden iframe |
| `url ref wait exhausted` | Click worked but displacements never became non-default |
| `posting insarmaps-ref-failed` | Insarmaps giving up; overlay should retry |
| `ignored background ref-applied` | Correct — prevented wrong-iframe date sync |
| `date sync deferred awaiting ref` | Dates held; user banner may show |
| `ref slow advisory shown` | 8 s passed without ref-applied |
| `ref stuck auto retry` | 15 s watchdog fired refSwitch reload |
| `ref recovery exhausted` | Auto-retry used up; user must switch away and back |
| `waitingForRef: true` (insarmaps) | set-dates arrived too early |
| `switch outcome` + `ref-failed` | Switch table Ref column = ✗ |

---

## 18. Recreating overlay.html — minimum viable design

If rebuilding from scratch with a new implementation:

1. **One iframe per dataset**, background preload after active load.
2. **Single `currentMapParams` object** plus explicit `userNarrowedDateRange` for narrowed-period semantics.
3. **Two sync channels:** URL reload for bulk state; postMessage for contour + dates-after-ref only.
4. **Custom ref switch = two phases:** ref URL without dates → wait `insarmaps-ref-applied` → `insarmaps-set-dates`.
5. **Never put dates + custom ref in the same refSwitch URL** when period is narrowed.
6. **Strip `colorscale` on cross-dataset loads** when custom ref is set.
7. **Strip template params** in `expandDatasetNameLine` for name-only log lines.
8. **Do not call iframe internals** — design for cross-origin from day one.
9. **Insarmaps must post `insarmaps-ref-applied` and handle `insarmaps-set-dates`** — contract, not optional.
10. **Add switch-result logging** from the start (`switch attempt` / `switch outcome` with refOk + datesOk).
11. **Read §19 before designing ref sync** — synthetic URL click + wait is the main fragility; plan explicit ref API or visible-only apply.

---

## Related files

| File | Role |
|------|------|
| `minsar/html/overlay.html` | Implementation |
| `minsar/html/README.md` | insarmaps.log format, template list |
| `tools/insarmaps/public/js/mainPage.js` | postMessage listeners |
| `tools/insarmaps/public/js/mainMap.js` | Ref point application, ref-applied message |
| `tools/insarmaps/public/js/GraphsController.js` | Date slider, chart navigator |
| `create_insarmaps_framepages.py` | Copies templates to project directory |
