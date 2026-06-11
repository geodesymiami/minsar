        const OVERLAY_DEBUG_BUILD = 'b4a2c9-display-v18';
        const SWITCH_DEBUG_MAX_HISTORY = 8;
        let switchDebugHistory = [];
        let switchDebugActive = null;
        let switchDebugFinalizeTimers = [];

        function switchDebugFmtCoord(lat, lon) {
            if (lat == null || lon == null || lat === '' || lon === '') return '—';
            const a = parseFloat(lat);
            const b = parseFloat(lon);
            if (isNaN(a) || isNaN(b)) return '—';
            return a.toFixed(4) + ',' + b.toFixed(4);
        }

        function switchDebugSnapFromIframeQuery(index, state) {
            const iframe = document.getElementById(`iframe${index}`);
            const snap = switchDebugParamsFromMapAndUrl(null, iframe && iframe.src, null);
            if (state) {
                if (state.pixelSize != null && !isNaN(parseFloat(state.pixelSize))) {
                    snap.pixelSize = switchDebugFmtVal(state.pixelSize);
                }
                if (state.contours != null) {
                    snap.contours = switchDebugFmtVal(state.contours);
                }
                if (state.colorscale != null) {
                    snap.colorscale = switchDebugFmtVal(state.colorscale);
                }
                if (state.autoColorScale != null) {
                    snap.autoColorScale = switchDebugFmtVal(state.autoColorScale);
                    if (switchDebugFmtVal(state.autoColorScale) === 'true') {
                        snap.scaleRange = '—';
                    }
                }
                if (state.minScale != null || state.maxScale != null) {
                    snap.scaleRange = switchDebugFmtScaleRange(state.minScale, state.maxScale);
                }
                if (state.pointLat != null || state.pointLon != null) {
                    snap.point = switchDebugFmtCoord(state.pointLat, state.pointLon);
                }
                if (state.refPointLat != null || state.refPointLon != null) {
                    snap.refPoint = switchDebugFmtCoord(state.refPointLat, state.refPointLon);
                }
                if (state.startDate && state.endDate) {
                    snap.dates = state.startDate + '–' + state.endDate;
                }
                if (state.chartsVisible != null) {
                    snap.charts = switchDebugFmtVal(state.chartsVisible);
                }
            }
            return snap;
        }

        function switchDebugFmtVal(v) {
            if (v === true || v === 'true' || v === 'on' || v === 1) return 'true';
            if (v === false || v === 'false' || v === 'off' || v === 0) return 'false';
            if (v == null || v === '') return '—';
            if (typeof v === 'string') {
                const s = v.trim();
                if (s.toLowerCase() === 'true') return 'true';
                if (s.toLowerCase() === 'false') return 'false';
                return s;
            }
            return String(v);
        }

        function switchDebugFmtScale(val) {
            if (val == null || val === '') return '—';
            const n = formatUrlNumber(val);
            return n === '' ? '—' : n;
        }

        function switchDebugFmtScaleRange(minVal, maxVal) {
            if (minVal == null || maxVal == null || minVal === '' || maxVal === '') return '—';
            const a = formatUrlNumber(minVal);
            const b = formatUrlNumber(maxVal);
            if (a === '' || b === '') return '—';
            return a + ',' + b;
        }

        function switchDebugScaleFields(mapParams, urlStr) {
            const scale = mapParams ? scaleStateFromMapParams(mapParams) : null;
            let minScale = scale && scale.autoColorScale === 'false' ? scale.minScale : null;
            let maxScale = scale && scale.autoColorScale === 'false' ? scale.maxScale : null;
            if (urlStr) {
                const parsed = parseInsarmapsUrlParams(urlStr);
                if (parsed) {
                    const autoFromUrl = switchDebugFmtAutoScale(null, urlStr, {
                        autoColorScale: parsed.autoColorScale
                    });
                    if (autoFromUrl === 'true') {
                        minScale = null;
                        maxScale = null;
                    } else {
                        if (parsed.minScale != null) minScale = parsed.minScale;
                        if (parsed.maxScale != null) maxScale = parsed.maxScale;
                    }
                }
            } else if (scale && scale.autoColorScale === 'true') {
                minScale = null;
                maxScale = null;
            }
            return switchDebugFmtScaleRange(minScale, maxScale);
        }

        function switchDebugFmtAutoScale(mapParams, urlStr, urlP) {
            if (mapParams && mapParams.autoColorScale != null && mapParams.autoColorScale !== '') {
                return switchDebugFmtVal(mapParams.autoColorScale);
            }
            if (urlP && urlP.autoColorScale != null && urlP.autoColorScale !== '') {
                return switchDebugFmtVal(urlP.autoColorScale);
            }
            if (urlStr) {
                try {
                    const u = new URL(urlStr, window.location.href);
                    if (u.searchParams.get('minScale') != null && u.searchParams.get('maxScale') != null &&
                        u.searchParams.get('autoColorScale') == null) {
                        return 'false';
                    }
                } catch (e) {}
            }
            return '—';
        }

        function switchDebugParamsFromMapAndUrl(mapParams, urlStr, chartsVisible) {
            const urlP = urlDisplayParamsFromSrc(urlStr || '');
            let pointLat = mapParams && mapParams.pointLat;
            let pointLon = mapParams && mapParams.pointLon;
            let refLat = mapParams && mapParams.refPointLat;
            let refLon = mapParams && mapParams.refPointLon;
            let colorscale = mapParams ? effectiveColorscale(mapParams) : null;
            if (urlStr) {
                const parsed = parseInsarmapsUrlParams(urlStr);
                if (parsed) {
                    if (parsed.pointLat != null) pointLat = parsed.pointLat;
                    if (parsed.pointLon != null) pointLon = parsed.pointLon;
                    if (parsed.refPointLat != null) refLat = parsed.refPointLat;
                    if (parsed.refPointLon != null) refLon = parsed.refPointLon;
                    if (parsed.colorscale != null) colorscale = parsed.colorscale;
                }
            }
            if (!colorscale && urlP.colorscale) {
                colorscale = urlP.colorscale;
            }
            if (!colorscale) {
                colorscale = INSARMAP_URL_DEFAULTS.colorscale;
            }
            const dates = (mapParams && mapParams.startDate && mapParams.endDate)
                ? (mapParams.startDate + '–' + mapParams.endDate) : '—';
            const scaleRange = switchDebugScaleFields(mapParams, urlStr);
            return {
                contours: switchDebugFmtVal(mapParams ? effectiveContour(mapParams) : urlP.contours),
                pixelSize: switchDebugFmtVal(mapParams && mapParams.pixelSize != null
                    ? mapParams.pixelSize : urlP.pixelSize),
                background: switchDebugFmtVal(mapParams && mapParams.background != null
                    ? mapParams.background : urlP.background),
                opacity: switchDebugFmtVal(mapParams && mapParams.opacity != null
                    ? mapParams.opacity : urlP.opacity),
                colorscale: switchDebugFmtVal(colorscale),
                autoColorScale: switchDebugFmtAutoScale(mapParams, urlStr, urlP),
                scaleRange: scaleRange,
                point: switchDebugFmtCoord(pointLat, pointLon),
                refPoint: switchDebugFmtCoord(refLat, refLon),
                charts: chartsVisible == null ? '—' : switchDebugFmtVal(chartsVisible),
                dates: dates
            };
        }

        function switchDebugSentLabel(sentPost, urlBuilt) {
            const parts = [];
            if (sentPost) {
                parts.push('PM c=' + switchDebugFmtVal(sentPost.contour) +
                    ' ps=' + switchDebugFmtVal(sentPost.pixelSize));
            }
            if (urlBuilt) {
                parts.push('URL c=' + urlBuilt.contours + ' ps=' + urlBuilt.pixelSize);
            }
            return parts.length ? parts.join(' · ') : '—';
        }

        function switchDebugMatch(expected, actual) {
            const expNorm = switchDebugFmtVal(expected);
            const actNorm = switchDebugFmtVal(actual);
            if (expNorm === '—') return 'na';
            if (actNorm === '—') return 'pending';
            // Wildcard when leaving iframe state was not queried (fast-path cache).
            if (expNorm === '?' && actNorm === 'true') return 'ok';
            if (expNorm === actNorm) return 'ok';
            const expNum = parseFloat(expNorm);
            const actNum = parseFloat(actNorm);
            if (!isNaN(expNum) && !isNaN(actNum) && formatUrlNumber(expNum) === formatUrlNumber(actNum)) {
                return 'ok';
            }
            if (expNorm.includes(',') && actNorm.includes(',')) {
                const e = expNorm.split(',');
                const a = actNorm.split(',');
                if (e.length === 2 && a.length === 2) {
                    if (formatUrlNumber(e[0]) === formatUrlNumber(a[0]) &&
                            formatUrlNumber(e[1]) === formatUrlNumber(a[1])) {
                        return 'ok';
                    }
                    if (Math.abs(parseFloat(e[0]) - parseFloat(a[0])) < 0.001 &&
                            Math.abs(parseFloat(e[1]) - parseFloat(a[1])) < 0.001) {
                        return 'ok';
                    }
                }
            }
            return 'bad';
        }

        function switchDebugBestActual(displayRow, defKey) {
            const sources = [displayRow.finalLate, displayRow.final, displayRow.receivedLatest];
            for (let i = 0; i < sources.length; i++) {
                const snap = sources[i];
                if (!snap) continue;
                const v = snap[defKey];
                if (v != null && v !== '—' && v !== '') return v;
            }
            return null;
        }

        // chartsVisible can be false while Highcharts is on screen (#charts minimized / no map layer).
        function switchDebugChartsMatch(expectedCharts, actualCharts, expectedPoint, actualPoint) {
            const base = switchDebugMatch(expectedCharts, actualCharts);
            if (base === 'ok' || base === 'na' || base === 'pending') return base;
            const expPt = expectedPoint == null ? '—' : String(expectedPoint);
            const actPt = actualPoint == null ? '—' : String(actualPoint);
            const expCharts = switchDebugFmtVal(expectedCharts);
            if ((expCharts === 'true' || expCharts === '?') &&
                    switchDebugFmtVal(actualCharts) === 'false' &&
                    expPt !== '—' && actPt !== '—' &&
                    switchDebugMatch(expPt, actPt) === 'ok') {
                return 'ok';
            }
            return base;
        }

        function switchDebugCellClass(kind) {
            if (kind === 'ok') return 'ok';
            if (kind === 'bad') return 'bad';
            if (kind === 'pending') return 'pending';
            return 'na';
        }

        function flushIncompleteSwitchDebugRow() {
            if (!switchDebugActive) return;
            switchDebugActive.incomplete = true;
            switchDebugHistory.unshift(switchDebugActive);
            if (switchDebugHistory.length > SWITCH_DEBUG_MAX_HISTORY) {
                switchDebugHistory.length = SWITCH_DEBUG_MAX_HISTORY;
            }
            switchDebugActive = null;
        }

        function beginSwitchDebugRow(fromIdx, toIdx, fromState, switchPath, switchReloaded, targetUrlBefore) {
            flushIncompleteSwitchDebugRow();
            switchDebugFinalizeTimers.forEach((t) => clearTimeout(t));
            switchDebugFinalizeTimers = [];
            const expectedParams = mapParamsWithOverlayUserDisplay(currentMapParams);
            if (fromState && fromState.pointLat && fromState.pointLon) {
                expectedParams.pointLat = String(fromState.pointLat);
                expectedParams.pointLon = String(fromState.pointLon);
            } else if (hasPointSelection(expectedParams)) {
                // already in currentMapParams from syncPointFromSwitchState
            } else if (fromIdx >= 0) {
                const cached = lastKnownPointByIndex.get(fromIdx);
                if (cached && cached.pointLat && cached.pointLon) {
                    expectedParams.pointLat = cached.pointLat;
                    expectedParams.pointLon = cached.pointLon;
                }
            }
            let expectedCharts = '—';
            if (fromState && fromState.chartsVisible != null) {
                expectedCharts = switchDebugFmtVal(fromState.chartsVisible);
            } else if (hasPointSelection(expectedParams)) {
                expectedCharts = 'true';
            } else if (fromState && fromState.chartsVisible) {
                expectedCharts = 'true';
            }
            if (expectedCharts === '—' && hasPointSelection(expectedParams)) {
                expectedCharts = 'true';
            }
            switchDebugActive = {
                ts: new Date().toLocaleTimeString(),
                fromIdx, toIdx,
                fromLabel: iframeLabelForLog(fromIdx),
                toLabel: iframeLabelForLog(toIdx),
                path: switchPath || '—',
                reloaded: !!switchReloaded,
                expected: switchDebugParamsFromMapAndUrl(expectedParams, null, expectedCharts),
                urlAtSwitch: switchDebugParamsFromMapAndUrl(null, targetUrlBefore || '', null),
                urlBuilt: null,
                sentPost: null,
                receivedLatest: null,
                receivedCount: 0,
                final: null,
                finalLate: null
            };
            renderSwitchDebugPanel();
        }

        function recordSwitchDebugReloadUrl(url) {
            if (!switchDebugActive || !url) return;
            switchDebugActive.urlBuilt = switchDebugParamsFromMapAndUrl(null, url, null);
            renderSwitchDebugPanel();
        }

        function recordSwitchDebugSentPost(contourOn, pixelSize, onlyIndex) {
            if (!switchDebugActive || onlyIndex !== switchDebugActive.toIdx) return;
            switchDebugActive.sentPost = { contour: contourOn, pixelSize: pixelSize };
            renderSwitchDebugPanel();
        }

        function recordSwitchDebugReceived(senderIndex, rawMerged, eventData) {
            if (!switchDebugActive || senderIndex !== switchDebugActive.toIdx || !rawMerged) return;
            let charts = eventData && eventData.chartsVisible != null
                ? eventData.chartsVisible : null;
            if (charts == null && rawMerged.pointLat && rawMerged.pointLon) {
                charts = true;
            }
            switchDebugActive.receivedLatest = switchDebugParamsFromMapAndUrl(rawMerged, eventData && eventData.url, charts);
            switchDebugActive.receivedCount += 1;
            renderSwitchDebugPanel();
        }

        function scheduleSwitchDebugFinalize(index) {
            if (!switchDebugActive || switchDebugActive.toIdx !== index) return;
            switchDebugFinalizeTimers.forEach((t) => clearTimeout(t));
            switchDebugFinalizeTimers = [];
            switchDebugFinalizeTimers.push(setTimeout(() => finalizeSwitchDebugQuery(index, 'final'), 400));
            switchDebugFinalizeTimers.push(setTimeout(() => finalizeSwitchDebugQuery(index, 'finalLate', true), 1500));
        }

        function finalizeSwitchDebugQuery(index, field, archive) {
            if (!switchDebugActive || switchDebugActive.toIdx !== index) return;
            queryActiveIframeSwitchState(index, (state) => {
                if (!switchDebugActive || switchDebugActive.toIdx !== index) return;
                switchDebugActive[field] = switchDebugSnapFromIframeQuery(index, state);
                if (archive) {
                    switchDebugHistory.unshift(switchDebugActive);
                    if (switchDebugHistory.length > SWITCH_DEBUG_MAX_HISTORY) {
                        switchDebugHistory.length = SWITCH_DEBUG_MAX_HISTORY;
                    }
                    switchDebugActive = null;
                }
                renderSwitchDebugPanel();
            });
        }

        function renderSwitchDebugPanel() {
            const metaEl = document.getElementById('switch-debug-meta');
            const latestEl = document.getElementById('switch-debug-latest');
            const histWrap = document.getElementById('switch-debug-history-wrap');
            const panel = document.getElementById('switch-debug-panel');
            if (!metaEl || !latestEl || !histWrap || !panel) return;
            const h3 = panel.querySelector('h3');
            if (h3) h3.textContent = 'Switch parameter debug (' + OVERLAY_DEBUG_BUILD + ')';
            const row = switchDebugActive;
            if (!row && switchDebugHistory.length === 0) {
                metaEl.textContent = 'Waiting for first dataset switch — change dataset in the dropdown above.';
                latestEl.innerHTML = '<table><thead><tr><th>Parameter</th><th>Expected</th><th>Sent</th>' +
                    '<th>URL@switch</th><th>Received</th><th>UI 0.4s</th><th>UI 1.5s</th><th>✓</th></tr></thead>' +
                    '<tbody><tr><td colspan="8" class="pending">Switch datasets to populate this table.</td></tr></tbody></table>';
                histWrap.innerHTML = '';
                return;
            }
            const displayRow = row || switchDebugHistory[0];
            if (row) {
                metaEl.textContent = 'Latest (in progress): ' + row.fromLabel + ' → ' + row.toLabel +
                    ' | path=' + row.path + (row.reloaded ? ' (reload)' : '') +
                    ' | ' + row.ts + ' | received msgs=' + row.receivedCount;
            } else {
                metaEl.textContent = 'Latest completed: ' + displayRow.fromLabel + ' → ' + displayRow.toLabel +
                    ' | path=' + displayRow.path + ' | ' + displayRow.ts;
            }
            const paramDefs = [
                { key: 'contours', label: 'contours' },
                { key: 'pixelSize', label: 'pixelSize' },
                { key: 'background', label: 'background' },
                { key: 'opacity', label: 'opacity' },
                { key: 'autoColorScale', label: 'autoColorScale' },
                { key: 'colorscale', label: 'colorscale' },
                { key: 'scaleRange', label: 'minScale,maxScale' },
                { key: 'point', label: 'point (lat,lon)' },
                { key: 'refPoint', label: 'ref point' },
                { key: 'charts', label: 'timeseries chart' },
                { key: 'dates', label: 'date range' }
            ];
            const sentStr = switchDebugSentLabel(displayRow.sentPost, displayRow.urlBuilt);
            let html = '<table><thead><tr>' +
                '<th>Parameter</th><th>Expected</th><th>Sent</th><th>URL@switch</th>' +
                '<th>Received</th><th>UI 0.4s</th><th>UI 1.5s</th><th>✓</th></tr></thead><tbody>';
            paramDefs.forEach((def) => {
                const exp = displayRow.expected[def.key];
                const urlSw = displayRow.urlAtSwitch[def.key];
                const rec = displayRow.receivedLatest ? displayRow.receivedLatest[def.key] : '—';
                const fin = displayRow.final ? displayRow.final[def.key] : '—';
                const finL = displayRow.finalLate ? displayRow.finalLate[def.key] : '—';
                const sentCell = (def.key === 'contours' || def.key === 'pixelSize')
                    ? sentStr
                    : ((def.key === 'autoColorScale' && displayRow.urlBuilt)
                        ? displayRow.urlBuilt.autoColorScale
                        : (displayRow.urlBuilt ? displayRow.urlBuilt[def.key] : '—'));
                const bestActual = switchDebugBestActual(displayRow, def.key);
                const matchFn = def.key === 'charts' ? switchDebugChartsMatch : switchDebugMatch;
                const expPoint = displayRow.expected.point;
                const actPoint = switchDebugBestActual(displayRow, 'point');
                const ptFin = (displayRow.final && displayRow.final.point !== '—')
                    ? displayRow.final.point : actPoint;
                const ptFinL = (displayRow.finalLate && displayRow.finalLate.point !== '—')
                    ? displayRow.finalLate.point : actPoint;
                const match = def.key === 'charts'
                    ? matchFn(exp, bestActual, expPoint, actPoint)
                    : matchFn(exp, bestActual);
                const cellMatchFn = def.key === 'charts' ? switchDebugChartsMatch : switchDebugMatch;
                html += '<tr><td>' + def.label + '</td>' +
                    '<td>' + exp + '</td>' +
                    '<td>' + sentCell + '</td>' +
                    '<td>' + urlSw + '</td>' +
                    '<td>' + rec + '</td>' +
                    '<td class="' + switchDebugCellClass(
                        def.key === 'charts' ? cellMatchFn(exp, fin, expPoint, ptFin) :
                            cellMatchFn(exp, fin)) + '">' + fin + '</td>' +
                    '<td class="' + switchDebugCellClass(
                        def.key === 'charts' ? cellMatchFn(exp, finL, expPoint, ptFinL) :
                            cellMatchFn(exp, finL)) + '">' + finL + '</td>' +
                    '<td class="' + switchDebugCellClass(match) + '">' +
                    (match === 'ok' ? '✓' : (match === 'bad' ? '✗' : (match === 'pending' ? '…' : '—'))) +
                    '</td></tr>';
            });
            html += '</tbody></table>';
            latestEl.innerHTML = html;
            if (switchDebugHistory.length > 0) {
                let hhtml = '<table class="switch-debug-history"><thead><tr>' +
                    '<th>When</th><th>Switch</th><th>Path</th><th>contour</th><th>pixelSize</th>' +
                    '<th>point</th><th>ref</th><th>chart</th><th>OK</th></tr></thead><tbody>';
                switchDebugHistory.forEach((h) => {
                    const cmp = h.finalLate || h.final || h.receivedLatest || {};
                    const keys = ['contours', 'pixelSize', 'point', 'refPoint', 'charts'];
                    let okCount = 0;
                    let checkCount = 0;
                    keys.forEach((k) => {
                        const m = k === 'charts'
                            ? switchDebugChartsMatch(h.expected[k], switchDebugBestActual(h, k),
                                h.expected.point, switchDebugBestActual(h, 'point'))
                            : switchDebugMatch(h.expected[k], switchDebugBestActual(h, k));
                        if (m === 'ok') okCount++;
                        if (m === 'ok' || m === 'bad') checkCount++;
                    });
                    const mark = checkCount === 0 ? '…' : (okCount === checkCount ? '✓' : okCount + '/' + checkCount);
                    hhtml += '<tr><td>' + h.ts + '</td><td>' + h.fromLabel + '→' + h.toLabel + '</td><td>' + h.path +
                        '</td><td>' + (cmp.contours || '—') + '</td><td>' + (cmp.pixelSize || '—') + '</td>' +
                        '<td>' + (cmp.point || '—') + '</td><td>' + (cmp.refPoint || '—') + '</td>' +
                        '<td>' + (cmp.charts || '—') + '</td><td class="' +
                        (mark === '✓' ? 'ok' : (mark === '…' ? 'pending' : 'bad')) + '">' + mark + '</td></tr>';
                });
                hhtml += '</tbody></table>';
                histWrap.innerHTML = '<h3 style="font-size:11px;margin:8px 0 4px;color:#9cdcfe;">Recent switches</h3>' + hhtml;
            } else {
                histWrap.innerHTML = '';
            }
        }
        function dbgDisplayLog(location, message, data, hypothesisId) {
            const entry = {
                sessionId: 'b4a2c9', location, message, data,
                timestamp: Date.now(), hypothesisId
            };
            if (!window.__overlayDisplayDebugLog) window.__overlayDisplayDebugLog = [];
            window.__overlayDisplayDebugLog.push(entry);
            if (window.__overlayDisplayDebugLog.length > 80) window.__overlayDisplayDebugLog.shift();
        }

        function dbgSwitchLog(location, message, data, hypothesisId) {
            // Local debug table only; no external telemetry.
        }

        function overlayDebugSnapshot() {
            const panelStates = [];
            iframeDatasets.forEach((_, i) => {
                const panel = document.getElementById(`panel${i}`);
                const iframe = document.getElementById(`iframe${i}`);
                panelStates.push({
                    index: i,
                    label: iframeLabels.get(i) || `iframe${i}`,
                    visible: panel ? panel.style.visibility : null,
                    pointerEvents: panel ? panel.style.pointerEvents : null,
                    active: panel ? panel.classList.contains('active') : false,
                    warmInFlight: iframeWarmInFlight.has(i),
                    pendingDates: pendingDateSyncByIndex.has(i),
                    pointAfterRef: pointAfterRefInFlightByIndex.has(i)
                });
            });
            return {
                activeDatasetIdx,
                switchOpInFlight,
                switchOpStartedAt,
                switchOpAgeMs: switchOpStartedAt ? Date.now() - switchOpStartedAt : 0,
                pendingSelectIndex,
                pendingRevealIndex,
                pendingRevealAgeMs: pendingRevealSince ? Date.now() - pendingRevealSince : 0,
                iframeWarmInFlight: [...iframeWarmInFlight.keys()],
                activeSwitchTracking,
                datasetSwitchSuppressUntil,
                suppressRemainingMs: Math.max(0, datasetSwitchSuppressUntil - Date.now()),
                build: OVERLAY_DEBUG_BUILD,
                overlayUserDisplay: { ...overlayUserDisplay },
                displayDebugLog: (window.__overlayDisplayDebugLog || []).slice(-20),
                panelStates
            };
        }

        window.__overlayDebugHooks = {
            dbgDisplayLog,
            dbgSwitchLog,
            beginSwitchDebugRow,
            recordSwitchDebugReloadUrl,
            recordSwitchDebugSentPost,
            recordSwitchDebugReceived,
            scheduleSwitchDebugFinalize
        };
        window.__overlayDebugState = overlayDebugSnapshot;
        window.__overlayDisplayDebugLog = window.__overlayDisplayDebugLog || [];

        setInterval(() => {
            const snap = overlayDebugSnapshot();
            if (snap.switchOpInFlight && snap.switchOpAgeMs > 10000) {
                dbgSwitchLog('overlay.html:stuck-watchdog', 'switchOpInFlight > 10s', snap, 'A');
            }
            if (snap.pendingRevealIndex !== null && snap.pendingRevealAgeMs > 15000) {
                dbgSwitchLog('overlay.html:stuck-watchdog', 'panel reveal pending > 15s', snap, 'B');
            }
            if (snap.iframeWarmInFlight.length >= 3) {
                dbgSwitchLog('overlay.html:stuck-watchdog', 'multiple iframes warm in flight', snap, 'C');
            }
        }, 5000);
