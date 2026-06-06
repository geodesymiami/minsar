# Plan: Fix clicked point not showing when switching datasets

## Summary

When a user clicks a point on one dataset (e.g. Descending) and then switches to another (e.g. Ascending) via the dropdown, the clicked point marker does not appear on the newly visible iframe.

Root cause: same class of bug as the known contour limitation — dataset switch is show/hide only (no reload), and point coordinates are not fully propagated to background iframes.

## Key Components Affected

- `minsar/html/overlay.html` — `buildInsarmapsUrl()`, `getSyncKey()`, `selectDataset()`
- `minsar/html/ARCHITECTURE.md` — document fix and update stale Issue 2 note

## Diagnosis

1. **`buildInsarmapsUrl()` omits `pointLat`/`pointLon`** — only `refPointLat`/`refPointLon` are passed to insarmaps iframe URLs. Insarmaps uses `pointLat`/`pointLon` for the clicked-point marker.

2. **`getSyncKey()` omits `pointLat`/`pointLon`** — `iframeSynced` thinks background iframes are up-to-date even when they lack the point params.

3. **`selectDataset()` does not reload stale iframes** — on dropdown change, panels are shown/hidden only (like contours). If a background iframe was never loaded with the current point, switching to it shows the old state.

When the active iframe sends a point-click `postMessage`, other iframes are reloaded — but without `pointLat`/`pointLon` in the URL, so they never get the marker.

## Action Items

- [x] Add `pointLat`/`pointLon` to `buildInsarmapsUrl()`
- [x] Add `pointLat`/`pointLon` to `getSyncKey()`
- [x] In `selectDataset()`, reload the newly visible iframe when `iframeSynced.get(index) !== getSyncKey(currentMapParams)`
- [x] Update `ARCHITECTURE.md` with the fix and corrected sync behaviour

## Execution Plan (Detailed Change Instructions)

### 1. `buildInsarmapsUrl()` (~line 607)

After `refPointLon`, add:
```javascript
if (mapParams.pointLat) params.set('pointLat', mapParams.pointLat);
if (mapParams.pointLon) params.set('pointLon', mapParams.pointLon);
```

### 2. `getSyncKey()` (~line 683)

Add `pointLat` and `pointLon` to the JSON object (alongside `refPointLat`/`refPointLon`).

### 3. `selectDataset()` (~line 1000)

After showing the selected panel, before contour postMessage:
```javascript
const expectedSyncKey = getSyncKey(currentMapParams);
const visibleIframe = document.getElementById(`iframe${index}`);
if (visibleIframe && iframeSynced.get(index) !== expectedSyncKey) {
    const dataset = iframeDatasets.get(index);
    if (dataset && currentMapParams.lat && currentMapParams.lon && currentMapParams.zoom) {
        visibleIframe.src = buildInsarmapsUrl(
            baseUrl, dataset,
            currentMapParams.lat, currentMapParams.lon, currentMapParams.zoom,
            currentMapParams
        );
        iframeSynced.set(index, expectedSyncKey);
    }
}
```

This reloads only when stale (e.g. point changed since last load), not on every switch.

### 4. Update ARCHITECTURE.md

- Correct Issue 2 note (point params are synced again, with reload-on-switch safety net)
- Add brief note under Known limitations or a new "Fixed" section

## Key Commands & Flows

- Manual test: open overlay with multiple datasets → click a point on Descending → switch to Ascending → marker should appear at same location
- No automated tests exist for overlay.html (browser-only behaviour)

## TODO List

- [x] Implement changes
- [ ] Manual verification in browser
- [x] Update ARCHITECTURE.md
