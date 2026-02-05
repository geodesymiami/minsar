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
- **Close Time Controls (uncheck):** `restoreToBaselineState()` clears period panels and shows the active dataset panel. **startDate/endDate are not reset**: the last-viewed period’s range (e.g. the 2-year window you had selected in TC) is kept in `currentMapParams`. **All dataset iframes** are reloaded with that same `currentMapParams` (lat, lon, zoom, colorscale, pixelSize, minScale, maxScale, background, opacity, contour, startDate, endDate), and the overlay URL is updated so the parent/URL reflects the same date range.

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

### 1.6 Active vs non-active panels: who gets reloaded

**Active panel** = the one the user is currently viewing.

- **Dataset mode (Time Controls off):** The **active** panel is the dataset selected in the dropdown (e.g. Descending). Overlay tracks this as `activeDatasetIdx`. Only that panel is visible; the others are hidden but still in the DOM.
- **Time Controls on:** The **active** panel is the visible period panel (e.g. period 2 of 5). The dataset dropdown still has a selected dataset (`activeDatasetIdx`); the period panels belong to that dataset.

**Sender** = the iframe that just sent a `postMessage` (e.g. `insarmaps-url-update`). Overlay identifies it by matching `event.source` to each iframe’s `contentWindow`. Usually the sender is the **active** iframe (the user changed something there). Sometimes a **non-active** (hidden) iframe sends a message too (e.g. when it finishes loading).

**Reload rule:** On a **reload sync**, overlay sets `iframe.src = newUrl` only for **non-active, non-sender** iframes.

| Panel / iframe | Reloaded on sync? | Reason |
|----------------|-------------------|--------|
| **Active dataset iframe** (the one you’re looking at) | **No** | Overlay never reloads it. The user’s changes are already visible there; reload would be redundant and would flash. |
| **Sender iframe** (the one that sent the postMessage) | **No** | It already has the new state (it sent the URL that triggered sync). Reloading it would duplicate work and can cause double load. |
| **Other dataset iframes** (hidden panels, same dataset list) | **Yes** | They need the new params; overlay has no message API for display params, so it sets `iframe.src` so they load the new URL. |
| **Period iframes** (Time Controls on) | **Yes** (after cooldown), except sender | Same idea: other period panels get `iframe.src` so they match the new view/display; the period that sent the message is not reloaded. The **active dataset** iframe (the main dataset panel, not a period panel) is also never reloaded. |

So: the **active** panel and the **sender** panel are never reloaded. All **other** panels (other datasets, or other periods when Time Controls on) are updated by reload. That is why changing scale/colorscale/background in the panel you’re viewing feels instant—that iframe never reloads. The other panels update by reloading with the new URL.

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
4. **No reload.** The newly visible iframe already has contour in sync (overlay sends `insarmaps-set-contour` to all iframes when contour changes).

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

## 6. The Two Sync Actions (easy-to-remember names)

Overlay keeps all iframes in sync in **two** ways: either we **reload** other iframes (new URL), or we send a **message only** (contour). There is no third sync type.

### Data vs display: when is reload actually needed?

- **Params that change what data is loaded** (reload is the right way to sync): **lat, lon, zoom, startDate, endDate**. Changing these means different tiles or a different time range must be loaded. Other iframes need to load that new data, so setting `iframe.src` to a new URL is appropriate.
- **Params that only change how the same data is displayed** (reload not needed in principle): **minScale, maxScale, colorscale, pixelSize, background, opacity, contour**. The same data is already there; only rendering (color scale, limits, background, contour layer) changes. These *could* be synced by postMessage if insarmaps listened for messages and called its existing JS APIs (e.g. `colorScale.setMinMax()`, `colorScale.setScale()`), like it already does for `insarmaps-set-contour`.

So we only **need** to reload when view or date range changes. Colorscale and minScale/maxScale do not require different data; they could be message-only sync in the future.

### Sync 1: **Reload sync** (view & date – and today, display too)

- **Trigger:** Insarmaps sends `postMessage({ type: 'insarmaps-url-update', url: '...' })` after the user changes something that affects the URL (pan, zoom, time range, or any display param).
- **What can change:** lat, lon, zoom, startDate, endDate, minScale, maxScale, colorscale, pixelSize, background, opacity, contour.
- **Overlay action:** After debounce, overlay **reloads** all other iframes by setting `iframe.src` to a new URL built from `currentMapParams`. The sender and the active dataset iframe are never reloaded.
- **Why we reload today:** Insarmaps applies minScale, maxScale, colorscale, etc. from the URL when it **loads**. Overlay has no `insarmaps-set-minmax` or `insarmaps-set-colorscale` message handlers in insarmaps, so the only way to sync those today is to reload with the new URL. So we currently reload for *all* URL param changes, not only view/date—even though for display params a message-only sync would be enough if insarmaps supported it.

### Sync 2: **Contour sync** (message only)

- **Trigger:** Same postMessage from insarmaps, but overlay detects that **only** the contour parameter changed (same lat, lon, zoom, dates, scale, etc.; only `contour` differs from last sync).
- **Overlay action:** Overlay does **not** reload. It sends **postMessage** to **every** iframe (all dataset iframes and all period iframes): `{ type: 'insarmaps-set-contour', value: true|false }`. Insarmaps in each iframe adds or removes the contour layer. No reload.
- **Why message only:** Insarmaps already listens for `insarmaps-set-contour` and can toggle the contour layer without reloading. The same approach could be used for colorscale and minScale/maxScale if insarmaps added the corresponding message listeners.

### Summary table

| Sync name       | Trigger (from insarmaps) | Overlay action                          | Reload? |
|-----------------|---------------------------|-----------------------------------------|--------|
| **Reload sync** | postMessage with new URL  | Set `iframe.src` on all other iframes   | Yes    |
| **Contour sync**| postMessage, only contour changed | Send `insarmaps-set-contour` to all iframes | No  |

So: **Reload sync** = view/date (and currently display params too, because there is no message API for them). **Contour sync** = contour-only, message only. Only these two sync actions exist.

### User actions mapped to sync (current behaviour)

| User action | Where | Sync used | Iframes reloaded? |
|-------------|--------|-----------|--------------------|
| Pan, zoom, time slider | Insarmaps | **Reload sync** (different data: view/date) | All except sender and active dataset |
| Color limits, colorscale, pixel size, background, opacity | Insarmaps | **Reload sync** (same data; we reload only because no message API yet) | All except sender and active dataset |
| Contour toggle only | Insarmaps | **Contour sync** | None |
| Dataset dropdown | Overlay | None (show/hide only); if Time Controls on, new period iframes created | None / new period iframes only |
| Period ◀/▶/Play | Overlay | None (`showPeriod`) | None |

---

## 7. Contour toggle – add/remove in all iframes (no reload)

To avoid unnecessary reloads and to make contours show when switching iframes, contour is **not** synced by reloading. Instead:

1. User toggles the contour button **inside** the active insarmaps iframe.
2. Insarmaps updates its URL and sends `postMessage({ type: 'insarmaps-url-update', url: '...' })`.
3. Overlay receives the message (after debounce), updates `currentMapParams.contour` and the overlay hash URL.
4. Overlay checks whether **only** the contour param changed (same lat/lon/zoom, scale, dates, background, opacity; only `contour` differs from last sync).
   - **If only contour changed:** Overlay does **not** reload any iframe. It sends a **postMessage** to **every** dataset iframe: `{ type: 'insarmaps-set-contour', value: true|false }`. Each iframe (when embedded) listens for this and calls `myMap.addContourLines()` or `myMap.removeContourLines()` and updates the contour button state. So all iframes get the same contour state without reload; when the user switches dataset, the newly visible iframe already has contours on or off.
   - **If any other param changed:** Overlay behaves as before: reloads **all other** iframes with the new URL (which includes the current contour).

Insarmaps (mainPage.js) listens for `insarmaps-set-contour`: it adds/removes the contour layer and the button “toggled” state so the UI stays in sync.

### Parameter values

- Overlay uses **`contour=true`** and **`contour=false`** in its hash and in built iframe URLs; it normalizes `on`/`off` from insarmaps to `true`/`false`.

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

## Key Functions

### `getOverlayUrlParams()`
Parses overlay.html's URL (hash-based or legacy path-based) and extracts:
- `view` or `startDataset` (which dataset to show)
- `lat`, `lon`, `zoom` (map position)
- Display params: `minScale`, `maxScale`, `startDate`, `endDate`, `pixelSize`, `background`, `opacity`, `contour`

### `buildInsarmapsUrl(baseUrl, dataset, lat, lon, zoom, mapParams)`
Constructs a full insarmaps URL with:
- Path: `/start/{lat}/{lon}/{zoom}`
- Query: `flyToDatasetCenter=false&startDataset={dataset}&{all mapParams}&_t={timestamp}`

The `_t` timestamp parameter forces browser to reload the iframe (cache-busting).

### `updateOverlayUrl(viewCodeOrDataset, mapParams, currentDataset)`
Updates the browser URL (hash-based) to reflect current state for bookmarking/sharing.

## Synchronization Mechanism

### postMessage Flow (from insarmaps)
When insarmaps changes its URL state (pan, zoom, slider change), it calls:
```javascript
window.parent.postMessage({
    type: 'insarmaps-url-update',
    url: '/start/lat/lon/zoom?params...'
}, '*');
```

### All delays and where the user may wait

| Delay | Constant / source | Value | Where the user waits / what it does |
|-------|--------------------|--------|--------------------------------------|
| **Sync debounce** | `SYNC_DEBOUNCE_MS` | 1500 ms | After the user stops changing the map (pan, zoom, slider, etc.), overlay waits 1.5 s before processing postMessage and reloading other iframes. So other panels update up to **1.5 s** after the last change. |
| **Contour after reload** | `setTimeout(..., 2500)` and `setTimeout(..., 6000)` | 2.5 s and 6 s | After a **reload sync**, overlay sends `insarmaps-set-contour` to reloaded iframes at **2.5 s** and again at **6 s** (so slow-loading iframes and late-drawn data layers still get contours). Contour can still appear below the data if the data layer draws after both sends (see Known limitations). |
| **Non-active iframe cooldown** | `SYNC_COOLDOWN_MS` | 3000 ms | Messages from **non-active** iframes are ignored for 3 s after the last sync. Reduces feedback when hidden iframes send URL updates. User does not see this directly. |
| **Period sync cooldown** | `PERIOD_SYNC_COOLDOWN_MS` | 5000 ms | After Time Controls are opened, postMessages **from a period iframe** do not trigger reload of other period iframes for 5 s (avoids double load). After 5 s, changing view in the visible period will reload other periods. |
| **Loading overlay fallback** | `setTimeout(hideLoadingOverlay, 15000)` | 15 s | If no postMessage is received from any iframe, the “Loading InSAR Data…” overlay is hidden after 15 s. User may wait up to **15 s** on a bad network before the overlay disappears. |

### Debounce & Cooldown (summary)
- **SYNC_DEBOUNCE_MS = 1500 ms**: Wait for user to stop interacting before applying **reload sync** or **contour sync**.
- **SYNC_COOLDOWN_MS = 3000 ms**: Ignore incoming messages from non-active iframes for 3 s after syncing (prevents feedback loops).
- **PERIOD_SYNC_COOLDOWN_MS = 5000 ms**: After opening Time Controls, ignore period-iframe messages for reload of other periods for 5 s.

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

6. **Contour below the data (layer order)**  
   After a **reload sync**, overlay sends `insarmaps-set-contour` in a **setTimeout(..., 2500)**. The order of operations is: (1) set `iframe.src` → iframe loads and draws map + data, (2) 2.5 s later send contour message → insarmaps adds contour layer. If the iframe is still loading or the data layer is drawn **after** the contour message is applied, the contour layer can end up **below** the data layer (wrong z-order). So “contours missing” and “contours below data” are both related to **timing and order**: the contour message is sent on a fixed delay, not when the iframe signals it is fully ready. Fixing this would require either a longer or adaptive delay, or insarmaps signalling “map ready” so overlay can send contour at the right time.

**Why background works**: The base map (e.g. `background=satellite`) is part of the initial map style and is applied when the iframe loads. It does not depend on a separate "add layer" call or a delayed init. So when we do reload other iframes (on pan/zoom/scale/background change), they load with the new background and it shows. Contours are a separate layer added later, so they are more sensitive to timing and readiness.

**Summary**: Contours are a **known limitation**: they may not show when switching frames (or in some period panels) because (a) the non-active iframes may not be ready when the sync message is sent, (b) insarmaps adds the contour layer in a way that can fail when the map was loaded while hidden, (c) we do not reload or re-send the contour state when the user switches dataset, and (d) the fixed 2.5 s delay after reload can cause contour to be applied before the data layer is drawn, so contour can appear **below** the data. The overlay URL and postMessage design are correct; the limitation is in reliably applying the contour layer in every iframe at the right time and in the right order.

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

## Spec for insarmaps: postMessage handlers (so Cursor can implement)

**Purpose:** This section specifies what **insarmaps** (the app that runs inside each iframe) must implement so that **overlay.html** can sync display state without reloading iframes. If you are implementing or updating insarmaps (e.g. in `tools/insarmaps/` or the insarmaps repo), read this section and add the described message listeners. Overlay already sends these message types where noted; once insarmaps handles them, overlay can be updated to use message-only sync for display params instead of reload.

When insarmaps is embedded in an iframe (e.g. from overlay.html), the **parent** sends postMessages to sync display state without reloading. Insarmaps must **listen** for these messages (when `window.parent !== window`) and apply the changes by calling existing JS APIs. Below is the contract: message types, payloads, and what insarmaps should do.

**Where to implement:** Add a single `window.addEventListener('message', ...)` in insarmaps (e.g. in the same place as URL init, or in a small embed bridge). In the handler, check `event.data && event.data.type` and run only when the page is embedded (e.g. `if (window.parent === window) return;` at the top of the handler).

**Payload convention:** Overlay sends objects like `{ type: 'insarmaps-set-contour', value: true }`. All messages are from the parent; no need to check `event.origin` if you only care about same-origin embed (overlay and insarmaps same host). For cross-origin, validate `event.origin` against your allowed parent origin.

---

### 1. `insarmaps-set-contour` (already required; implement if missing)

| Field | Value |
|-------|--------|
| **type** | `'insarmaps-set-contour'` |
| **value** | `true` or `false` (boolean) – whether contour layer should be on |

**Insarmaps must:**
- If `myMap` (or the map controller) exists and has `addContourLines` / `removeContourLines` (or equivalent): call `myMap.addContourLines()` when `value === true`, `myMap.removeContourLines()` when `value === false`.
- Update the contour toggle button state in the UI so it matches (on/off).
- Optionally update the page URL so `contour=on` or `contour=off` is reflected (so next reload stays in sync).

**Why:** Overlay uses this when the user toggles contour in one iframe so all other iframes get contour on/off without a full reload.

---

### 2. `insarmaps-set-scale-limits` (to add in insarmaps)

| Field | Value |
|-------|--------|
| **type** | `'insarmaps-set-scale-limits'` |
| **minScale** | number (e.g. -3) – color scale minimum |
| **maxScale** | number (e.g. 2) – color scale maximum |

**Insarmaps must:**
- If the map’s color scale object exists (e.g. `myMap.colorScale` or `this.map.colorScale`), call `colorScale.setMinMax(minScale, maxScale, true)` (or equivalent; the third argument `true` should trigger a redraw/apply).
- Update any visible min/max inputs or labels so the UI matches.
- Optionally update the URL (e.g. `appendOrReplaceUrlVar` or equivalent) so `minScale` and `maxScale` are in the query string.

**Why:** Overlay can then sync color limits across iframes without reload when only minScale/maxScale change.

---

### 3. `insarmaps-set-colorscale` (to add in insarmaps)

| Field | Value |
|-------|--------|
| **type** | `'insarmaps-set-colorscale'` |
| **value** | string – scale type (e.g. `'velocity'`, `'displacement'`, or whatever insarmaps uses in its URL for `colorscale`) |

**Insarmaps must:**
- If the map’s color scale object exists and has a method to set scale type (e.g. `colorScale.setScale(value)` in `ColorScale.js`), call it.
- Update any scale-type toggle or dropdown in the UI so it matches.
- Optionally update the URL so `colorscale=...` is reflected.

**Why:** Overlay can then sync colorscale type across iframes without reload.

---

### 4. Optional: `insarmaps-set-display` (single message for pixelSize, background, opacity)

If insarmaps can change these without reload, one option is a single message:

| Field | Value |
|-------|--------|
| **type** | `'insarmaps-set-display'` |
| **pixelSize** | number (optional) – point size |
| **background** | string (optional) – e.g. `'satellite'`, `'map'` |
| **opacity** | number or string (optional) – layer opacity |

**Insarmaps must:** For each present property, apply it (e.g. set layer opacity, switch background, set point size) using existing APIs and update the URL if applicable.

Alternatively, insarmaps can support separate messages (e.g. `insarmaps-set-opacity`, `insarmaps-set-background`) if that fits the codebase better. Overlay can send whichever the spec defines.

---

### 5. Optional: “map ready” signal (insarmaps → parent)

To fix “contour below data” and “contours missing” timing issues, insarmaps can postMessage to the parent when the map is fully ready (data layer drawn, layout complete). Overlay can then send `insarmaps-set-contour` (and optionally other display messages) once after “map ready” instead of on a fixed 2.5 s delay.

**Suggested message from insarmaps to parent:**
- `{ type: 'insarmaps-map-ready' }` (no payload required).

**When to send:** Once, when the map and the main data layer have been drawn (e.g. after the existing “map loaded” or “style loaded” callback, and after the first InSAR layer is rendered). Avoid sending on every pan/zoom.

**Overlay change (after insarmaps supports this):** Overlay can listen for `insarmaps-map-ready` and, for that iframe, send `insarmaps-set-contour` (and any other display messages) once, instead of relying only on the 2.5 s / 6 s timeouts after reload.

---

### Summary: what to implement in insarmaps

| Priority | Message type | Purpose |
|----------|--------------|--------|
| Required (if not already) | `insarmaps-set-contour` | Sync contour on/off without reload |
| Recommended | `insarmaps-set-scale-limits` | Sync minScale/maxScale without reload |
| Recommended | `insarmaps-set-colorscale` | Sync colorscale type without reload |
| Optional | `insarmaps-set-display` (or separate messages) | Sync pixelSize, background, opacity without reload |
| Optional | Send `insarmaps-map-ready` to parent | Lets overlay send contour at the right time and can fix contour-below-data |

**After insarmaps implements the recommended handlers:** Overlay can be updated to detect “only display params changed” (minScale, maxScale, colorscale, etc.) and send these messages to all iframes instead of doing a reload sync for those changes. That will avoid unnecessary reloads when the user only changes color scale or limits.

---

## Possible future improvements

### Visual feedback during sync / reload
Users have no clear indication when **reload sync** or **contour sync** is in progress. Possible additions:
- **Loading / syncing indicator**: While the sync debounce is active (up to 1.5 s after last change) or while other iframes are reloading, show a short “Syncing…” state (e.g. dim or highlight the control bar or the affected panels) so the user knows to wait.
- **Per-panel state**: Optionally dim or pulse panels that are currently reloading, so it is obvious which views are updating.

### Manual sync buttons
Adding one or two buttons could let users force sync when something looks wrong (e.g. contours missing, scale mismatch):
- **“Sync view & display” (reload sync)**: Builds the current URL from `currentMapParams` and sets `iframe.src` for all **other** iframes (same as what happens automatically after a postMessage, but on demand). Useful if a panel did not reload correctly or the user wants to force all panels to match the current view/display.
- **“Sync contours” (contour sync)**: Sends `insarmaps-set-contour` with the current `currentMapParams.contour` value to **all** iframes. Useful when contours are missing or out of order after a reload or dataset switch.

These would not change the two sync actions; they would just trigger the same **reload sync** or **contour sync** logic on a user click.
