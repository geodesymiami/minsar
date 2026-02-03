# overlay.html Architecture Documentation

## Overview

`overlay.html` is a multi-dataset InSAR map viewer that embeds multiple insarmaps instances (each showing a different dataset like Descending, Ascending, Vertical, Horizontal) in iframes and synchronizes their view state (position, zoom, display parameters).

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
│  │                  Dropdown Handler (frameSelect.change)                │  │
│  │                                                                       │  │
│  │  1. Switch active panel (CSS display:none/block)                      │  │
│  │  2. Update currentViewCode and currentDataset                         │  │
│  │  3. Update overlay.html URL                                           │  │
│  │  4. Reload SELECTED iframe with currentMapParams                      │  │
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
10. Hide loading overlay when first iframe loads
```

### 2. What Triggers Data Loading

| Trigger | What Happens | iframes Affected |
|---------|--------------|------------------|
| **Page Load** | All iframes get `src` set with initial params | ALL |
| **Dropdown Change** | Selected iframe reloaded with current params | SELECTED only |
| **postMessage (map pan/zoom)** | Other iframes reloaded after debounce | ALL EXCEPT sender |
| **postMessage (slider change)** | Other iframes reloaded after debounce | ALL EXCEPT sender |

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

### Debounce & Cooldown
- **SYNC_DEBOUNCE_MS = 1500ms**: Wait for user to stop interacting before syncing
- **SYNC_COOLDOWN_MS = 3000ms**: Ignore incoming messages for 3s after syncing (prevents feedback loops)

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
1. Hide current panel (CSS display:none)
2. Show selected panel (CSS display:block)
3. Update currentViewCode = 'asc'
4. Update currentDataset = 'S1_asc_...'
5. Update overlay.html hash URL
6. Build new insarmaps URL with currentMapParams
7. Set lastSyncTime = Date.now() (cooldown)
8. Set iframe.src = newUrl  ← IFRAME RELOADS
    │
    ▼
iframe loads, insarmaps renders, sends postMessage
    │
    ▼
postMessage ignored (within cooldown period)
```

**Key point**: Only the SELECTED iframe is reloaded. Other iframes are not touched.

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
| Dropdown switch | Selected only | YES |
| Pan/zoom | All except sender | YES |
| Time slider | All except sender | YES |
| Color scale | All except sender | YES |
| Pixel size | All except sender | YES |
| Background | All except sender | YES |
| Opacity | All except sender | YES |

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

**Solution implemented**: Added a loading overlay with spinner that shows "Loading InSAR Data..." until the first iframe fires its `load` event.

## Caching Behavior

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
| startDate | Time range start | Time slider |
| endDate | Time range end | Time slider |
| pixelSize | Point size | Pixel slider |
| background | Map background | Layer selector |
| opacity | Layer opacity | Opacity slider |
| contour | Contour display | Contour toggle |

## NOT Synchronized (by design)

| Parameter | Reason |
|-----------|--------|
| pointLat/pointLon | Causes rectangle cut-off bug |
| refPointLat/refPointLon | Causes rectangle cut-off bug |
| startDataset | Each iframe has its own dataset |
