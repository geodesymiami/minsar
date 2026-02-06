# overlay.html Architecture Documentation

## Overview

`overlay.html` is a multi-dataset InSAR map viewer that embeds multiple insarmaps instances (each showing a different dataset like Descending, Ascending, Vertical, Horizontal) in iframes and synchronizes their view state (position, zoom, display parameters). It also supports **Time Controls** mode: one iframe per time period for the active dataset (step-through or play).

---

## 1. What Triggers the Loading of Data

“Loading” here means setting `iframe.src` (so the browser loads the insarmaps page) or creating new iframes and setting their `src`.

### 1.1 Page load (initial)

1. **Fetch `insarmaps.log`** – list of insarmaps URLs (one per dataset).
2. **Parse and sort** – URLs sorted by dataset type (desc → asc → horz → vert).
3. **Initial params** – `currentMapParams` from overlay URL (hash or query) or from the first insarmaps URL.
4. **One panel per URL** – each gets a `.panel` and an **iframe**.
5. **Initial iframe `src`** – each iframe gets `src` via `buildInsarmapsUrl(baseUrl, dataset, lat, lon, zoom, currentMapParams)`. So **all dataset iframes load once** with the same map params. Only one panel is visible; others use `visibility: hidden` but stay in the DOM, so their iframes still load.
6. **Loading overlay** – hidden on first `postMessage` type `insarmaps-url-update`, or after 15s timeout.

So the only trigger for **initial** load is **page load**: every dataset iframe gets one URL and loads once.

### 1.2 postMessage from the active iframe (sync)

When the user changes something **inside** the visible insarmaps iframe (pan, zoom, time slider, color scale, background, contour, etc.), insarmaps sends:

`window.parent.postMessage({ type: 'insarmaps-url-update', url: '/start/...?params...' }, '*');`

Overlay’s handler (debounced 1500 ms):

1. Parses the URL and builds a **sync key** (lat, lon, zoom, minScale, maxScale, startDate, endDate, pixelSize, background, opacity, contour).
2. If key equals `lastSyncedKey`, does nothing.
3. Updates `currentMapParams` and overlay hash URL.
4. Finds the **sender** iframe index.
5. For **every other** dataset iframe, builds a new URL with `currentMapParams` and sets **`iframe.src = newUrl`** (reload).

So: **Trigger** = any insarmaps URL change in the active iframe. **Effect** = all iframes **except the active one** are reloaded with the new params. The active iframe is **not** reloaded.

### 1.3 Dataset change (dropdown)

- **Time Controls closed:** `selectDataset(index)` only switches visibility and updates overlay URL. No iframe reload; contour is kept in sync by postMessage to all iframes (§ 7).
- **Time Controls open:** `selectDataset(index)` calls `handleDatasetChangeInTimeControls(index)` → `loadPeriodsForDataset(newDatasetIdx)`: **clears** period panels and **creates new** period panels (and iframes) for the new dataset. So “loading” here is **new period iframes**, not the main dataset iframes.

### 1.4 Time Controls: open and change period

- **Open Time Controls:** `openTimeControls()` → `loadPeriodsForDataset(activeDatasetIdx)`. Creates one panel per period, each with its own iframe (URL includes that period’s startDate/endDate). So **opening** triggers **loading of N period iframes**.
- **Change period (◀/▶/Play):** `showPeriod(periodIdx)` only changes which period panel is visible. **No iframe reload.**
- **Change period length or Sequential:** Calls `loadPeriodsForDataset(activeDatasetIdx)` again → period panels cleared and recreated → **all period iframes loaded again**.

### 1.5 Summary: when is an iframe loaded?

| Trigger | What loads | Which iframes |
|--------|------------|----------------|
| Page load | Initial URL per dataset | All dataset iframes |
| postMessage (any param in active iframe) | New URL on others | All dataset iframes **except** sender |
| Dataset dropdown (Time Controls off) | No reload; show/hide panel only | None |
| Dataset dropdown (Time Controls on) | New period panels | New period iframes for selected dataset |
| Open Time Controls | Period panels | All period iframes for current dataset |
| Change period (◀/▶/Play) | Nothing | None |
| Change period length / Sequential | Rebuild periods | Period iframes recreated and loaded |

---

## 2. How Data Are Cached

### 2.1 No application-level cache of “data”

Overlay does **not** cache tiles or API responses. It only keeps: **`currentMapParams`**, **`iframeSynced`** (per-iframe sync key), **`lastSyncedKey`**. So “cache” here means “we don’t reload the sender iframe on sync” and “we don’t reload period iframes when stepping.”

### 2.2 Cache-busting when building URLs

`buildInsarmapsUrl()` adds `_t={timestamp}_{urlCounter}_{uniqueId?}`. So every URL we set is unique; the browser does not serve a cached page for that iframe. Period iframes get `uniqueId` (e.g. `period_${periodIdx}`).

### 2.3 What is effectively “cached” (not reloaded)

- **Sender iframe on sync** – we never set the active iframe’s `src` again.
- **Period panels** – once created, their `src` is not updated by postMessage; we only **show** another panel when changing period.

---

## 3. What Happens When Switching Iframes (Dataset Dropdown)

### 3.1 Time Controls closed

1. `frameSelect` change → `selectDataset(selectedIndex)`.
2. All panels hidden; selected panel shown (visibility, z-index, pointer-events).
3. `updateOverlayUrl(...)` updates overlay hash.
4. **No reload.** The newly visible iframe was last reloaded with current params (including contour) when it was synced.

### 3.2 Time Controls open

1. `selectDataset(index)` sees `timeControlsActive` and index change → `handleDatasetChangeInTimeControls(index)` and return.
2. `loadPeriodsForDataset(newDatasetIdx)`: **clearPeriods()** (remove period panels from DOM), then create new period panels/iframes for the new dataset.
3. `showPeriod(0)`, `updateControls()`.

So “switching iframe” (dataset) with Time Controls on = **replace** the set of period panels with that for the new dataset. Main dataset panels are unchanged.

---

## 4. What Happens When a New startDate/endDate Is Selected

### 4.1 Via time slider (inside insarmaps)

1. User drags time slider in active iframe → insarmaps sends postMessage with new URL (new startDate/endDate).
2. Overlay (after debounce): update `currentMapParams`, overlay URL; for every **other** dataset iframe set **`iframe.src = newUrl`**.
3. Active iframe is **not** reloaded; all other dataset iframes **reload** with new dates.

### 4.2 Via Time Controls (overlay)

1. Opening Time Controls creates one iframe **per period** (each URL has that period’s startDate/endDate).
2. ◀/▶/Play → `showPeriod(periodIdx)`: only the selected period panel is shown; `currentMapParams.startDate`/`endDate` and overlay URL updated. **No iframe reload.**

So: **Time slider** = one iframe per dataset; change dates → reload other dataset iframes. **Time Controls** = one iframe per period; change period → show that period’s iframe (no reload).

---

## 5. Same Behavior for Different Datasets vs Different Time Periods

- **Different datasets:** One iframe per dataset. Switching dataset = show that panel (no reload). When one iframe sends postMessage, we reload **all other dataset iframes** so they share the same params (including startDate/endDate).
- **Different time periods (Time Controls):** One iframe per period for the **active** dataset. Switching period = show that period panel (no reload).

So both “dataset” and “period” are “which iframe to show.” Difference: dataset iframes are created at **page load** and **synced** on postMessage; period iframes are created when **Time Controls open** and are **not** updated by postMessage (sync only touches `iframeDatasets` indices).

---

## 6. Difference in Actions Between User Options

Changes **inside** the active insarmaps iframe trigger postMessage → debounce → update `currentMapParams`. **All params** (including contour, color limits, background, time slider, etc.) are synced by reloading all other dataset iframes. The active iframe is never reloaded.

| User action | Where | What overlay does | Iframes reloaded? |
|-------------|--------|-------------------|--------------------|
| **Color limits** (minScale/maxScale) | Insarmaps | postMessage → set `src` on other iframes | All except active |
| **Background** | Insarmaps | Same | All except active |
| **Contour** | Insarmaps | Reload other iframes with `contours=true/false` in URL | All except sender |
| **Dataset** (dropdown) | Overlay | Show/hide panel only; if Time Controls on, load periods for new dataset | None (or new period iframes only when Time Controls on) |
| **Period** via **time slider** | Insarmaps | postMessage → set `src` on other iframes | All except active |
| **Period** via **Time Controls** (◀/▶/Play) | Overlay | `showPeriod(idx)` – change visible period panel | None |

So: **Color limits, background, time slider, contour** → postMessage → reload all other dataset iframes. **Dataset dropdown** → no reload; only show/hide panel. **Period via Time Controls** → no reload; only which period panel is visible.

---

## 7. Contour toggle – synced by reload (same as other params)

Contour is synced by **reloading** other iframes with `contours=true` or `contours=false` in the URL. This is more reliable than the previous postMessage approach, which often failed when target iframes were not ready. Insarmaps applies contour on load via `getUrlVar("contours")`.


### Parameter values

- Overlay and matrix use **`contours`** (with 's') in iframe URLs to match insarmaps. Overlay's own hash may use `contour` for brevity.

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              overlay.html                                    │
│                                                                             │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────────────┐  │
│  │ insarmaps.log│───>│ URL Parsing      │───>│ iframe Creation          │  │
│  │ (data source)│    │ getOverlayUrlParams│   │ buildInsarmapsUrl()      │  │
│  └──────────────┘    └──────────────────┘    └──────────────────────────┘  │
│                                                          │                  │
│                                                          ▼                  │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                    IFRAMES (one per dataset)                          │  │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐                  │  │
│  │  │ iframe0 │  │ iframe1 │  │ iframe2 │  │ iframe3 │                  │  │
│  │  │  desc   │  │   asc   │  │  horz   │  │  vert   │                  │  │
│  │  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘                  │  │
│  │       │            │            │            │                        │  │
│  │       └────────────┴────────────┴────────────┘                        │  │
│  │                           │                                           │  │
│  │                    postMessage()                                      │  │
│  │                    (insarmaps-url-update)                             │  │
│  │                           │                                           │  │
│  └───────────────────────────┼──────────────────────────────────────────┘  │
│                              ▼                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                  Message Handler (window.addEventListener)            │  │
│  │                                                                       │  │
│  │  0. If sender is a period iframe → return (ignore; prevents reload)   │  │
│  │  1. Parse incoming URL from sender iframe                             │  │
│  │  2. Extract lat/lon/zoom and query params                             │  │
│  │  3. Create syncKey (JSON of all sync-relevant params)                 │  │
│  │  4. Compare with lastSyncedKey (skip if identical)                    │  │
│  │  5. Update currentMapParams                                           │  │
│  │  6. Update overlay.html URL (hash-based)                              │  │
│  │  7. Reload ALL OTHER iframes with new params                          │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Dropdown: show/hide panel only. Contour: postMessage to all iframes.      │  │
│  │  If Time Controls open: loadPeriodsForDataset(newIdx) → new panels.       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Initialization Sequence

### 1. Page Load
```
1. Show "Loading InSAR Data..." overlay
2. Fetch insarmaps.log
3. Parse URLs from log file
4. Sort URLs by dataset type (desc, asc, horz, vert)
5. Read overlay.html URL params (hash or query string)
6. Initialize currentMapParams from URL or first insarmaps URL
7. Create iframe for each URL entry
8. Set initial active iframe based on URL params
9. Show dropdown selector (only if multiple datasets)
10. Hide loading overlay on first postMessage (insarmaps-url-update) or after 15s timeout
```

### 2. What Triggers Data Loading (summary)

| Trigger | What Happens | iframes Affected |
|---------|--------------|------------------|
| **Page Load** | All iframes get `src` set with initial params | ALL |
| **Dropdown Change** | Show/hide panel only. If Time Controls on: new period iframes for new dataset | None / new period only |
| **postMessage (any param in active iframe)** | Other iframes get new `src` after debounce | ALL EXCEPT sender |

See **§ 1. What Triggers the Loading of Data** and **§ 6. Difference in Actions Between User Options** for full detail.

### 11.3 insarmaps sending postMessage on dataset load

To avoid the "Could not determine date range" alert when opening Time Controls before any user interaction, insarmaps sends a postMessage as soon as a dataset loads. In `mainMap.js`, when `currentArea = feature` is set in `loadDatasetFromFeature`, it calls `notifyParentOfUrlState()`. That sends the same `insarmaps-url-update` message format with `firstDate` and `lastDate` from the dataset’s `attributekeys`/`attributevalues`, so the overlay has the date range for Time Controls without requiring interaction. **Timing**: this can arrive several seconds after page load (insarmaps must load area markers, find the dataset, and set `currentArea`). If the user clicks Time Controls before that, the overlay uses the wait mechanism (§ 11.4).

### 11.4 Overlay wait-for-postMessage when date range is missing

When the user opens Time Controls and the overlay has no `dataFirstDate`/`dataLastDate` (no URL periods, no prior postMessage), instead of immediately alerting and closing, the overlay:

1. Shows the Time Controls panel with "Waiting for map data…" in the period indicator.
2. Starts a 5-second timer (`DATE_RANGE_WAIT_MS`).
3. Waits for a postMessage with `firstDate`/`lastDate` from insarmaps.
4. If a postMessage arrives with dates: clears the timer, calls `loadPeriodsForDataset(activeDatasetIdx)`, shows the first period, and updates controls.
5. If the 5-second timer fires and dates are still missing: shows the alert and closes Time Controls.

This handles the case where insarmaps is still loading or the deployed insarmaps does not yet include `notifyParentOfUrlState`. It does not require changes to insarmaps.

---

## Key Functions

### `getOverlayUrlParams()`
Parses overlay.html's URL (hash-based or legacy path-based) and extracts:
- `view` or `startDataset` (which dataset to show)
- `lat`, `lon`, `zoom` (map position)
- Display params: `minScale`, `maxScale`, `startDate`, `endDate`, `pixelSize`, `background`, `opacity`, `contour`
- `timeControls`, `periods` (when Time Controls are in the URL; see § 11.1)

### `buildInsarmapsUrl(baseUrl, dataset, lat, lon, zoom, mapParams)`
Constructs a full insarmaps URL with:
- Path: `/start/{lat}/{lon}/{zoom}`
- Query: `flyToDatasetCenter=false&startDataset={dataset}&{all mapParams}&_t={timestamp}`

The `_t` timestamp parameter forces browser to reload the iframe (cache-busting).

### `updateOverlayUrl(viewCodeOrDataset, mapParams, currentDataset, timeControlsActive, periodsArray)`
Updates the browser URL (hash-based) to reflect current state for bookmarking/sharing. When `timeControlsActive` and `periodsArray` are provided, adds `timeControls=true` and `periods=...` to the URL.

## Synchronization Mechanism

### postMessage Flow (from insarmaps)
When insarmaps changes its URL state (pan, zoom, slider change), it calls:
```javascript
window.parent.postMessage({
    type: 'insarmaps-url-update',
    url: '/start/lat/lon/zoom?params...'
}, '*');
```

### Debounce & Cooldown

See **§ 10. Wait and Cooldown Periods** for full detail.

- **SYNC_DEBOUNCE_MS = 1500ms**: Debounce – wait for user to stop before processing postMessage
- **SYNC_COOLDOWN_MS = 3000ms**: Ignore messages from non-active iframes for 3s after a sync
- **PERIOD_SYNC_COOLDOWN_MS = 5000ms**: Don’t reload period iframes on period-iframe message within 5s of TC open (now moot: we ignore all period-iframe messages)

### syncKey Comparison
```javascript
const syncKey = JSON.stringify({
    lat, lon, zoom,
    minScale, maxScale,
    startDate, endDate,
    pixelSize, background, opacity, contour
});
if (syncKey === lastSyncedKey) return; // Skip if no actual change
```

---

## 10. Wait and Cooldown Periods

The overlay uses two timing mechanisms to prevent sync loops and batch rapid user input.

### 10.1 Debounce (SYNC_DEBOUNCE_MS = 1500 ms)

**What it does**: When a `postMessage` arrives, the overlay does **not** process it immediately. It clears any pending timeout and starts a new 1500 ms timer. Processing runs only after 1500 ms pass with no new message.

**Purpose**: Batch rapid changes (e.g. user dragging time slider or panning). A single sync is performed after the user pauses.

**User interaction during debounce**: The site **fully accepts** user interaction. The user can keep panning, zooming, or changing sliders. The overlay simply delays when it applies the sync (update params, reload other iframes). Nothing is blocked.

### 10.2 Cooldown (SYNC_COOLDOWN_MS = 3000 ms)

**What it does**: After a sync is applied, the overlay sets `lastSyncTime`. For the next 3000 ms, postMessages from **non-active** iframes are **ignored**. Messages from the **active** iframe are **always processed**.

**Purpose**: Avoid feedback loops. When we reload other iframes, they load and may send their own postMessage. Ignoring those for 3 s prevents a cascade of reloads.

**User interaction during cooldown**: The user **can still interact** with the active iframe (the one they’re viewing). Those messages are processed. Only messages from background/hidden iframes are ignored.

### 10.3 Period sync cooldown (PERIOD_SYNC_COOLDOWN_MS = 5000 ms)

**What it does**: Used when deciding whether to reload period iframes on a sync. Reload of other period iframes is skipped if the message came from a period iframe and it has been less than 5 s since Time Controls opened.

**Note**: The overlay now **ignores all postMessages from period iframes** (see § 11), so this cooldown is largely redundant for that path.

---

## 11. Time Controls URL and Full-Page Reload Fix

### 11.1 Time Controls in the URL

When Time Controls are active, the overlay adds `timeControls=true` and `periods=...` to the hash URL:

```
overlay.html#/start/0.7480/-77.9687/9.8?startDataset=...&timeControls=true&periods=20141027:20161027,20161027:20181028,...
```

- **Period format**: `periods=start1:end1,start2:end2,...` (comma-separated; `@` also accepted).
- **When generated**: When the user enables Time Controls, periods are derived from the default period length (years) and the dataset’s `first_date`/`last_date` via `calculatePeriods()`.
- **When used**: If the URL already has `timeControls=true` and `periods`, the overlay uses those periods and does not recalculate. The Period input is hidden. Auto-open runs after ~1.2 s.
- **startDate/endDate**: When the URL has Time Controls, overlay `startDate` and `endDate` are taken from the first period.

### 11.2 Full-page reload bug and solution

**Symptom**: The overlay page sometimes reloaded repeatedly (especially in Safari, and always showing the first period). Reloads could continue until one browser was closed.

**Root cause**: Period iframes send `postMessage` when they load (e.g. via `notifyParentOfUrlState` in insarmaps). The overlay treated these like dataset-iframe messages: it updated `currentMapParams`, called `updateOverlayUrl` (replaceState), and sometimes reloaded other iframes. That produced a loop: period iframe loads → postMessage → overlay updates and reloads → period iframe reloads → postMessage → …

**Solution**: The overlay **ignores postMessages from period iframes entirely**. At the start of the postMessage handler, it detects whether the sender is a period iframe. If so, it returns immediately—no `currentMapParams` update, no `updateOverlayUrl`, no iframe reloads. Period state is driven only by overlay logic (arrows, Play, etc.), not by period iframe messages.

## Comparison: Dataset Switch vs Time Slider Change

### Dataset Switch (Dropdown Change)
```
User selects "Ascending" in dropdown
    │
    ▼
1. Hide all panels (visibility, z-index, pointer-events)
2. Show selected panel (panel${index})
3. Update currentViewCode, currentDataset
4. Update overlay.html hash URL
5. updatePeriodHeader()
    │
    ▼
No iframe.src is set. The newly visible iframe is NOT reloaded.
(If Time Controls open: handleDatasetChangeInTimeControls → loadPeriodsForDataset → new period iframes.)
```

**Key point**: No iframe is reloaded when switching via dropdown. Contour state is synced by overlay sending `insarmaps-set-contour` to all iframes when the user toggles contour.

### Time Slider Change (postMessage)
```
User drags time slider in iframe0 (Descending)
    │
    ▼
insarmaps calls appendOrReplaceUrlVar() which sends:
    postMessage({ type: 'insarmaps-url-update', url: '...' })
    │
    ▼
overlay.html receives message
    │
    ▼
1. Check cooldown (skip if < 3000ms since last sync)
2. Clear previous debounce timer
3. Start new debounce timer (1500ms)
    │
    ▼ (after 1500ms)
4. Parse URL from message
5. Create syncKey
6. Compare with lastSyncedKey (skip if same)
7. Update currentMapParams
8. Update overlay.html hash URL
9. Find sender iframe (iframe0)
10. Set lastSyncTime = Date.now()
11. For each OTHER iframe (1, 2, 3):
    - Build new URL with currentMapParams
    - Set iframe.src = newUrl  ← IFRAME RELOADS
```

**Key point**: The SENDER iframe is NOT reloaded. All OTHER iframes are reloaded.

## Critical Difference Summary

| Action | Reloaded iframes | Uses currentMapParams? |
|--------|------------------|------------------------|
| Dropdown switch | **None** (show/hide only; contour synced via postMessage) | N/A |
| Contour only | **None** (postMessage `insarmaps-set-contour` to all iframes) | N/A |
| Pan/zoom / time slider / color scale / background / opacity | All except sender | YES |

## Known Issues & Analysis

### Issue 1: Iframes Not Properly Displayed in Time Series Control Mode

**Symptom**: When using time series controls, frames don't show differences.

**Root Cause Analysis**:
The `buildInsarmapsUrl()` function passes the SAME `startDate` and `endDate` to all iframes. When insarmaps receives these parameters, it should display the data for that time range. However:

1. Each dataset may have different date ranges available
2. If the requested date range is outside the dataset's available range, insarmaps may default to its own range
3. The datasets should show different data for the same dates (they're different viewing geometries), but if parameter passing fails, they'll show their defaults

**Verification needed**: Check if `startDate`/`endDate` are actually being included in the iframe URLs being set.

### Issue 2: Rectangle Cut-off

**Symptom**: Only part of the data area displays, with the rest cut off.

**Root Cause Analysis**:
This was previously traced to `pointLat`, `pointLon`, `refPointLat`, `refPointLon` parameters causing Mapbox rendering issues. These parameters have been REMOVED from synchronization:

```javascript
// These are intentionally NOT synced:
// - pointLat, pointLon (selected point)
// - refPointLat, refPointLon (reference point)
```

**If still occurring**: The issue may be related to:
1. iframe sizing/CSS
2. Mapbox GL JS projection errors
3. Timing issues during rapid reloads

### Issue 3: Initial Loading Silence

**Symptom**: Nothing happens for several seconds on first load.

**Solution implemented**: Added a loading overlay with spinner that shows "Loading InSAR Data..." until the first `postMessage` (insarmaps-url-update) is received from any iframe, or after a 15s fallback timeout.

### Issue 4: Contour toggle – contours may not show when switching frames

**Symptom**: After toggling contours, `contour=on` (or `contour=true`) appears in overlay.html’s URL, but the loaded map in the iframe does not show contour lines.

**Current behaviour**: Overlay sends `insarmaps-set-contour` to all iframes (no reload). Contours still often do not show when switching frames. For the detailed reason, see **Known limitations** below.


See **§ 7. Contour toggle** and **Known limitations** below.

## Known limitations

### Contours do not show when switching frames

**Observed behaviour**: Contour lines do not reliably appear on the map when switching to another dataset (iframe) via the Dataset dropdown, even though the overlay URL shows `contour=true` and the overlay sends `insarmaps-set-contour` to all iframes.

**Intended behaviour**: When the user turns contours on in one iframe, overlay sends a postMessage to every iframe to add the contour layer. Switching to another iframe should then show that iframe with contours already on.

**Reasons this can fail (as far as we can tell)**:

1. **postMessage timing and iframe readiness**  
   Overlay sends `insarmaps-set-contour` as soon as it gets the URL-update message from the active iframe (after debounce). The other iframes may still be loading or their map may not be fully initialised. Insarmaps' listener runs `myMap.addContourLines()` only if `myMap` exists; if the target iframe's map is not ready yet, the call may do nothing or the layer may not attach correctly. So a frame that was hidden and never "ready" when the message was sent may never show contours.

2. **Contour layer added only after map load in insarmaps**  
   In insarmaps, contours are added on initial load from the URL via a `setTimeout(..., 1000)` so the map is ready first. When we later send `insarmaps-set-contour`, we call `addContourLines()` immediately. If the map in that iframe was loaded while **hidden** (e.g. it is not the active frame), Mapbox may not have finished layout or style loading for that document. Adding a layer in that state can fail or not render, and there is no retry. So frames that were never the active one when contours were toggled can end up without contours even after receiving the message.

3. **Cross-origin and target of postMessage**  
   Overlay does `iframe.contentWindow.postMessage(...)`. If the iframe is same-origin (same insarmaps origin), the message is delivered. If there is any cross-origin or security setup that blocks or alters messaging, the target iframe might not receive the message or might receive it in a context where `myMap` is not the same instance. That would also prevent contours from being added.

4. **No reload on dataset switch**  
   We deliberately avoid reloading the selected iframe when switching datasets (to avoid unnecessary data reloads). So the newly visible iframe is whatever state it was left in. If that iframe never successfully applied the contour layer (for the reasons above), it will still show no contours when made visible. The overlay URL and overlay-side logic are correct; the failure is in the target iframe actually applying the contour layer.

5. **Single "fire once" message**  
   Overlay sends one `insarmaps-set-contour` per contour toggle. If an iframe is not ready at that moment, it never gets a second chance unless the user toggles contour again (or we add retries / re-send when a frame becomes visible, which we do not do today).

**Why background works**: The base map (e.g. `background=satellite`) is part of the initial map style and is applied when the iframe loads. It does not depend on a separate "add layer" call or a delayed init. So when we do reload other iframes (on pan/zoom/scale/background change), they load with the new background and it shows. Contours are a separate layer added later, so they are more sensitive to timing and readiness.

**Summary**: Contours are a **known limitation**: they may not show when switching frames because (a) the non-active iframes may not be ready when the sync message is sent, (b) insarmaps adds the contour layer in a way that can fail when the map was loaded while hidden, and (c) we do not reload or re-send the contour state when the user switches dataset. The overlay URL and postMessage design are correct; the limitation is in reliably applying the contour layer in every iframe at the right time.

## Caching Behavior

See **§ 2. How Data Are Cached** for the full description.

### Browser Cache
- The `_t={timestamp}` parameter in iframe URLs forces browser to bypass cache
- Each iframe reload gets a fresh URL, preventing stale data

### insarmaps Internal Cache
- insarmaps may cache tile data internally
- This is controlled by insarmaps, not overlay.html

### There is NO explicit caching in overlay.html
- `currentMapParams` stores the current state in memory
- `lastSyncedKey` stores the last synced state to prevent duplicate syncs
- Neither of these persist across page reloads

## Single Dataset Mode

When `insarmaps.log` contains only ONE URL:
1. `singleDatasetMode = true`
2. Dropdown selector is hidden
3. Container gets extra height (no selector bar)
4. postMessage sync still works but doesn't update other iframes (there are none)

## URL Format

### Hash-based (preferred, shareable):
```
overlay.html#/start/0.7480/-77.9687/9.8000?startDataset=S1_desc_...&minScale=-3&maxScale=3
```

With Time Controls:
```
overlay.html#/start/0.7480/-77.9687/9.8000?startDataset=...&timeControls=true&periods=20141027:20161027,20161027:20181028,...
```

### Legacy path-based (backwards compatible):
```
overlay.html/start/0.7480/-77.9687/9.8000?view=desc&minScale=-3&maxScale=3
```

## Synchronized Parameters

| Parameter | Description | Source |
|-----------|-------------|--------|
| lat | Map center latitude | Map position |
| lon | Map center longitude | Map position |
| zoom | Map zoom level | Map position |
| minScale | Color scale minimum | Scale slider |
| maxScale | Color scale maximum | Scale slider |
| colorscale | Color scale type (e.g. `velocity`, `displacement`); only in URL when set (no default – insarmaps uses its own default otherwise) | Scale type toggle in insarmaps |
| startDate | Time range start | Time slider |
| endDate | Time range end | Time slider |
| pixelSize | Point size | Pixel slider |
| background | Map background | Layer selector |
| opacity | Layer opacity | Opacity slider |
| contour | Contour display (`contour=true` / `contour=false` in URL) | Contour toggle |

## NOT Synchronized (by design)

| Parameter | Reason |
|-----------|--------|
| pointLat/pointLon | Causes rectangle cut-off bug |
| refPointLat/refPointLon | Causes rectangle cut-off bug |
| startDataset | Each iframe has its own dataset |
