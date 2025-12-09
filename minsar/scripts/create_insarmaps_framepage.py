#!/usr/bin/env python3
"""
Create a webpage with 4 iframes in a 2x2 grid layout.

Layout:
- Top Left: FILE1
- Top Right: FILE2
- Bottom Left: FILE3
- Bottom Right: FILE4
"""
import os
import re
import json
import argparse
from pathlib import Path
from urllib.parse import urlparse, parse_qs


def read_insarmaps_log(log_path):
    """Read URLs from insarmaps.log file and return them sorted by startDataset."""
    if not os.path.exists(log_path):
        raise FileNotFoundError(f"insarmaps.log file not found: {log_path}")
    
    urls = []
    with open(log_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and (line.startswith('http://') or line.startswith('https://')):
                urls.append(line)
    
    if not urls:
        raise ValueError(f"No valid URLs found in {log_path}")
    
    # Extract startDataset from each URL and sort
    def get_sort_key(url):
        try:
            parsed = urlparse(url)
            query_params = parse_qs(parsed.query)
            start_dataset = query_params.get('startDataset', [''])[0].lower()
            
            # Priority: desc (0), asc (1), vert (2), horz (3), others (4)
            if 'desc' in start_dataset:
                return (0, start_dataset)
            elif 'asc' in start_dataset:
                return (1, start_dataset)
            elif 'vert' in start_dataset:
                return (2, start_dataset)
            elif 'horz' in start_dataset:
                return (3, start_dataset)
            else:
                return (4, start_dataset)
        except Exception:
            return (5, '')  # Put unparseable URLs last
    
    urls.sort(key=get_sort_key)
    return urls


def get_label_from_url(url):
    """Extract label from URL based on startDataset parameter."""
    try:
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        start_dataset = query_params.get('startDataset', [''])[0].lower()
        
        if 'desc' in start_dataset:
            return 'Descending'
        elif 'asc' in start_dataset:
            return 'Ascending'
        elif 'vert' in start_dataset:
            return 'Vertical'
        elif 'horz' in start_dataset:
            return 'Horizontal'
        else:
            # Fallback: use the dataset name or a generic label
            return start_dataset if start_dataset else 'Dataset'
    except Exception:
        return 'Dataset'


def apply_zoom_factor(url, zoom_factor):
    """Apply zoom factor to URL if provided."""
    if zoom_factor is None:
        return url
    
    from urllib.parse import urlunparse
    try:
        parsed = urlparse(url)
        path_parts = parsed.path.strip('/').split('/')
        
        # Check if URL has the format /start/{lat}/{lon}/{zoom}
        if len(path_parts) >= 4 and path_parts[0] == 'start':
            # Replace the zoom value (4th element, index 3)
            path_parts[3] = str(zoom_factor)
            parsed = parsed._replace(path='/' + '/'.join(path_parts))
            url = urlunparse(parsed)
    except (IndexError, ValueError) as e:
        print(f"Warning: Could not modify zoom in URL {url}: {e}")
    
    return url


def extract_iframe_src(html_file_or_url, add_cache_bust=True, zoom_factor=None):
    """Extract the src URL from an iframe HTML file, or return the URL if it's already a URL."""
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    import time
    
    # Check if it's already a URL (starts with http:// or https://)
    if html_file_or_url.startswith('http://') or html_file_or_url.startswith('https://'):
        url = html_file_or_url
    else:
        # Otherwise, treat it as a file path
        if not os.path.exists(html_file_or_url):
            raise FileNotFoundError(f"File not found: {html_file_or_url}")
        
        with open(html_file_or_url, 'r') as f:
            content = f.read()
        
        # Look for iframe src attribute
        match = re.search(r'<iframe[^>]*src=["\']([^"\']+)["\']', content, re.IGNORECASE)
        if match:
            url = match.group(1)
        else:
            # Alternative: look for src= without quotes
            match = re.search(r'<iframe[^>]*src=([^\s>]+)', content, re.IGNORECASE)
            if match:
                url = match.group(1).strip('"\'')
            else:
                raise ValueError(f"Could not find iframe src in {html_file_or_url}")
    
    # Parse URL to modify zoom factor if provided
    parsed = urlparse(url)
    path_parts = parsed.path.strip('/').split('/')
    
    # Check if URL has the format /start/{lat}/{lon}/{zoom}
    if len(path_parts) >= 4 and path_parts[0] == 'start' and zoom_factor is not None:
        try:
            # Replace the zoom value (4th element, index 3)
            path_parts[3] = str(zoom_factor)
            parsed = parsed._replace(path='/' + '/'.join(path_parts))
            url = urlunparse(parsed)
        except (IndexError, ValueError) as e:
            print(f"Warning: Could not modify zoom in URL {url}: {e}")
    
    # Add cache-busting parameter to force fresh loads (prevents Safari caching issue)
    if add_cache_bust:
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        # Add timestamp to prevent caching
        query_params['_t'] = [str(int(time.time() * 1000))]  # milliseconds timestamp
        new_query = urlencode(query_params, doseq=True)
        url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
    
    return url


def create_webpage_2frames(urls, labels, output_path='page.html', zoom_factor=None, layout='matrix'):
    """Create a webpage with 2 iframes in specified layout.
    
    Args:
        urls: List of 2 URLs
        labels: List of 2 labels
        output_path: Output HTML file path
        zoom_factor: Optional zoom factor to apply
        layout: 'matrix' (2 columns), 'column' (2 rows), or 'row' (2 columns, same as matrix)
    """
    
    if len(urls) < 2:
        raise ValueError(f"Need at least 2 URLs, got {len(urls)}")
    
    # Use first 2 URLs and apply zoom factor if provided
    src_file1 = apply_zoom_factor(urls[0], zoom_factor)
    src_file2 = apply_zoom_factor(urls[1], zoom_factor)
    
    # Use extracted labels from URLs (which derive from dataset names)
    label1 = labels[0] if len(labels) > 0 else 'Dataset'
    label2 = labels[1] if len(labels) > 1 else 'Dataset'
    
    # Determine grid layout based on layout parameter
    if layout == 'column':
        # Single column, 2 rows with fixed 700px height each
        grid_columns = '1fr'
        grid_rows = '700px 700px'
        container_height = 'auto'
        container_class = 'container-column'
        panel_class1 = 'panel-top'
        panel_class2 = 'panel-bottom'
    else:
        # matrix or row: 2 columns, 1 row
        grid_columns = '1fr 1fr'
        grid_rows = '1fr'
        container_height = 'calc(100vh - 40px)'
        container_class = ''
        panel_class1 = 'panel-top-left'
        panel_class2 = 'panel-top-right'
    
    # Create HTML content with JavaScript to ensure iframes are fully loaded and interactive
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>Insarmaps - 2 Panel View</title>
    <style>
        body {{
            margin: 0;
            padding: 10px;
            font-family: Arial, sans-serif;
            background-color: #f5f5f5;
        }}
        .container {{
            display: grid;
            grid-template-columns: {grid_columns};
            grid-template-rows: {grid_rows};
            gap: 10px;
            height: {container_height};
            max-width: 100%;
        }}
        .container-column {{
            margin-left: 16px;
            margin-right: 16px;
            background-color: #e0e0e0;
        }}
        .panel {{
            background-color: white;
            border: 2px solid #ddd;
            border-radius: 4px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            position: relative;
            cursor: pointer;
            transition: box-shadow 0.2s;
        }}
        .panel:hover {{
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        }}
        .panel.active {{
            box-shadow: 0 0 0 3px rgba(74, 144, 226, 0.5);
        }}
        .panel-header {{
            background-color: #4a90e2;
            color: white;
            padding: 8px 12px;
            font-size: 14px;
            font-weight: bold;
            margin: 0;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: relative;
            height: 38px;
            box-sizing: border-box;
        }}
        .panel-header-title {{
            flex: 1;
        }}
        .panel iframe {{
            width: 100%;
            height: calc(100% - 38px);
            border: none;
            display: block;
        }}
        .panel-top-left .panel-header {{
            background-color: #4a90e2;
        }}
        .panel-top-right .panel-header {{
            background-color: #50c878;
        }}
        .panel-top .panel-header {{
            background-color: #4a90e2;
        }}
        .panel-bottom .panel-header {{
            background-color: #50c878;
        }}
        .loading {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: #666;
            font-size: 14px;
        }}
        .url-control {{
            display: flex;
            flex-direction: row;
            align-items: center;
            gap: 6px;
            margin-left: auto;
            background-color: rgba(255, 255, 255, 0.2);
            padding: 1px 8px;
            border-radius: 4px;
            flex-shrink: 0;
            pointer-events: auto;
            height: 22px;
            box-sizing: border-box;
        }}
        .url-control:hover {{
            background-color: rgba(255, 255, 255, 0.3);
        }}
        .url-control label {{
            font-weight: bold;
            color: white;
            font-size: 11px;
            white-space: nowrap;
        }}
        .url-control input {{
            flex: 1;
            min-width: 150px;
            max-width: 300px;
            padding: 1px 8px;
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 3px;
            font-size: 11px;
            font-family: monospace;
            background-color: rgba(255, 255, 255, 0.9);
            color: #333;
            cursor: text;
            user-select: text;
            -webkit-user-select: text;
            -moz-user-select: text;
            -ms-user-select: text;
            pointer-events: auto !important;
            height: 18px;
            box-sizing: border-box;
            line-height: 16px;
        }}
        .url-control input:focus {{
            outline: none;
            border-color: rgba(255, 255, 255, 0.6);
            background-color: white;
        }}
        .url-control input::placeholder {{
            color: #999;
        }}
        .url-control button {{
            padding: 1px 10px;
            background-color: rgba(255, 255, 255, 0.9);
            color: #4a90e2;
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 3px;
            cursor: pointer;
            font-size: 11px;
            font-weight: bold;
            white-space: nowrap;
            pointer-events: auto;
            height: 18px;
            box-sizing: border-box;
            line-height: 16px;
        }}
        .url-control button:hover {{
            background-color: white;
            border-color: rgba(255, 255, 255, 0.6);
        }}
        .url-control button:disabled {{
            background-color: rgba(255, 255, 255, 0.5);
            cursor: not-allowed;
            color: #999;
        }}
        .url-control #url-open-btn {{
            background-color: #4a90e2;
            color: white;
            border: 1px solid #4a90e2;
            padding: 1px 8px;
            min-width: 20px;
        }}
        .url-control #url-open-btn:hover {{
            background-color: #357abd;
            border-color: #357abd;
        }}
        .frame-dimensions-info {{
            position: fixed;
            bottom: 10px;
            right: 10px;
            background-color: rgba(0, 0, 0, 0.7);
            color: white;
            padding: 6px 10px;
            border-radius: 4px;
            font-size: 11px;
            font-family: monospace;
            z-index: 999;
            pointer-events: none;
        }}
    </style>
</head>
<body>
    <div id="frame-dimensions-info" class="frame-dimensions-info"></div>
    <div class="container {container_class}">
        <div class="panel {panel_class1}" id="panel1">
            <div class="panel-header">
                <span class="panel-header-title">{label1}</span>
                <div class="url-control">
                    <label for="url-input">URL:</label>
                    <input type="text" id="url-input" placeholder="Paste full URL here">
                    <button id="url-apply-btn">Apply</button>
                    <button id="url-open-btn" title="Open URL in new window">O</button>
                </div>
            </div>
            <iframe id="iframe1" title="{label1}" allowfullscreen></iframe>
        </div>
        <div class="panel {panel_class2}" id="panel2">
            <div class="panel-header">{label2}</div>
            <iframe id="iframe2" title="{label2}" allowfullscreen></iframe>
        </div>
    </div>
    
    <script>
        // Track iframe load states
        const iframeStates = {{
            'iframe1': {{ loaded: false, processed: false, focused: false }},
            'iframe2': {{ loaded: false, processed: false, focused: false }}
        }};
        
        // Queue for processing iframes sequentially
        const iframeQueue = [
            {{ id: 'iframe1', panelId: 'panel1', name: '{label1}' }},
            {{ id: 'iframe2', panelId: 'panel2', name: '{label2}' }}
        ];
        
        let currentProcessingIndex = 0;
        let currentFocusIndex = -1; // Track which iframe should be focused next
        
        // Function to trigger colorscale adjustment for a specific iframe
        function triggerColorscaleAdjustment(iframeId, panelId) {{
            const iframe = document.getElementById(iframeId);
            const panel = document.getElementById(panelId);
            const state = iframeStates[iframeId];
            
            if (!iframe || state.processed) {{
                return false;
            }}
            
            try {{
                // Mark as processed to avoid duplicate processing
                state.processed = true;
                
                // Make this panel active and ensure it's visible
                document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
                panel.classList.add('active');
                
                // Scroll iframe into view and center it
                iframe.scrollIntoView({{ behavior: 'smooth', block: 'center', inline: 'center' }});
                
                // Wait for scroll to complete, then focus exclusively on this iframe
                setTimeout(() => {{
                    console.log(`Starting colorscale adjustment for ${{iframeId}}`);
                    
                    // CRITICAL: Focus this iframe and keep it focused
                    // The AJAX call to /preLoad needs the iframe to be active
                    iframe.focus();
                    
                    // Try multiple focus attempts to ensure it sticks
                    const focusInterval = setInterval(() => {{
                        iframe.focus();
                        try {{
                            iframe.contentWindow.focus();
                        }} catch (e) {{
                            // Cross-origin
                        }}
                    }}, 200);
                    
                    // Stop focusing after 5 seconds
                    setTimeout(() => {{
                        clearInterval(focusInterval);
                    }}, 5000);
                    
                    // Trigger resize events immediately
                    try {{
                        iframe.contentWindow.postMessage('resize', '*');
                        iframe.contentWindow.dispatchEvent(new Event('resize'));
                    }} catch (e) {{
                        // Cross-origin
                    }}
                    
                    // Wait 2 seconds for the /preLoad AJAX call to complete
                    // This is when colorscale adjusts to data-derived values
                    setTimeout(() => {{
                        console.log(`Colorscale should have adjusted for ${{iframeId}}`);
                        
                        // Send refresh messages
                        try {{
                            iframe.contentWindow.postMessage({{type: 'refresh'}}, '*');
                            iframe.contentWindow.postMessage({{type: 'init'}}, '*');
                        }} catch (e) {{
                            // Cross-origin
                        }}
                        
                        // Minimize attributes window
                        setTimeout(() => {{
                            try {{
                                iframe.contentWindow.postMessage({{type: 'minimizeAttributes'}}, '*');
                            }} catch (e) {{
                                // Cross-origin
                            }}
                        }}, 500);
                    }}, 2000);
                    
                }}, 500);
                
                return true;
            }} catch (e) {{
                console.error(`Error processing ${{iframeId}}:`, e);
                state.processed = false; // Allow retry
                return false;
            }}
        }}
        
        // Process next iframe in queue
        function processNextIframe() {{
            if (currentProcessingIndex >= iframeQueue.length) {{
                console.log('All iframes processed');
                return;
            }}
            
            const item = iframeQueue[currentProcessingIndex];
            const state = iframeStates[item.id];
            
            // Check if iframe is loaded
            if (!state.loaded) {{
                // Wait a bit and try again
                setTimeout(() => processNextIframe(), 200);
                return;
            }}
            
            // Process this iframe
            if (triggerColorscaleAdjustment(item.id, item.panelId)) {{
                console.log(`Processing ${{item.name}} (${{item.id}})`);
                currentProcessingIndex++;
                
                // Wait 5 seconds to ensure colorscale adjustment completes
                // The /preLoad AJAX call takes 1-2 seconds, then colorscale adjusts
                // We need to keep the iframe focused during this time
                setTimeout(() => {{
                    console.log(`Finished processing ${{item.name}}, moving to next iframe`);
                    processNextIframe();
                }}, 5000);
            }} else {{
                // Retry after a delay
                setTimeout(() => processNextIframe(), 500);
            }}
        }}
        
        // Setup iframe load listeners
        function setupIframe(iframeId, panelId) {{
            const iframe = document.getElementById(iframeId);
            const panel = document.getElementById(panelId);
            const state = iframeStates[iframeId];
            
            function onIframeLoad() {{
                // Reset state for reloads (e.g., after zoom change)
                const wasLoaded = state.loaded;
                state.loaded = true;
                console.log(`Iframe loaded: ${{iframeId}} (reload: ${{wasLoaded}})`);
                
                // If this is a reload (was already loaded), just focus it for colorscale adjustment
                if (wasLoaded) {{
                    // This is a reload after zoom change - focus it to trigger colorscale adjustment
                    setTimeout(() => {{
                        const iframe = document.getElementById(iframeId);
                        const panel = document.getElementById(panelId);
                        if (iframe && panel) {{
                            iframe.focus();
                            try {{
                                iframe.contentWindow.focus();
                            }} catch (e) {{
                                // Cross-origin
                            }}
                            // Try to minimize attributes
                            setTimeout(() => {{
                                try {{
                                    iframe.contentWindow.postMessage({{type: 'minimizeAttributes'}}, '*');
                                }} catch (e) {{
                                    // Cross-origin
                                }}
                            }}, 500);
                        }}
                    }}, 500);
                    return;
                }}
                
                // Original load logic for initial page load
                // Find which iframe this is in the queue
                const queueIndex = iframeQueue.findIndex(item => item.id === iframeId);
                
                // Focus this iframe immediately when it loads to ensure AJAX call completes
                // But do it sequentially - only focus the next one in queue
                if (queueIndex === currentFocusIndex + 1) {{
                    currentFocusIndex = queueIndex;
                    focusIframeForColorscale(iframeId, panelId, queueIndex);
                }} else if (queueIndex === 0 && currentFocusIndex === -1) {{
                    // First iframe - start the sequence
                    currentFocusIndex = 0;
                    focusIframeForColorscale(iframeId, panelId, 0);
                }}
                
                // If all iframes are loaded, start the sequential processing queue
                const allLoaded = Object.values(iframeStates).every(s => s.loaded);
                if (allLoaded && currentProcessingIndex === 0) {{
                    console.log('All iframes loaded, starting sequential processing...');
                    setTimeout(() => {{
                        processNextIframe();
                    }}, 1000);
                }}
            }}
            
            // Function to focus iframe and maintain focus during AJAX call
            function focusIframeForColorscale(iframeId, panelId, queueIndex) {{
                const iframe = document.getElementById(iframeId);
                const panel = document.getElementById(panelId);
                
                console.log(`Focusing ${{iframeId}} for colorscale adjustment (queue index: ${{queueIndex}})`);
                
                // Make this panel active
                document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
                panel.classList.add('active');
                
                // Scroll into view
                iframe.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                
                setTimeout(() => {{
                    // Focus the iframe continuously for 3 seconds to ensure AJAX completes
                    iframe.focus();
                    
                    const focusInterval = setInterval(() => {{
                        iframe.focus();
                        try {{
                            iframe.contentWindow.focus();
                        }} catch (e) {{
                            // Cross-origin
                        }}
                    }}, 100);
                    
                    // Stop focusing after 3 seconds (AJAX should complete by then)
                    setTimeout(() => {{
                        clearInterval(focusInterval);
                        console.log(`Finished focusing ${{iframeId}}`);
                    }}, 3000);
                    
                    // Try to minimize attributes window
                    setTimeout(() => {{
                        try {{
                            iframe.contentWindow.postMessage({{type: 'minimizeAttributes'}}, '*');
                        }} catch (e) {{
                            // Cross-origin
                        }}
                    }}, 2500);
                }}, 300);
            }}
            
            // Listen for load event
            iframe.addEventListener('load', onIframeLoad);
            
            // Force reload iframe to bypass Safari cache on subsequent page loads
            // This ensures fresh AJAX calls to /preLoad for colorscale adjustment
            let reloadAttempted = false;
            const forceReload = () => {{
                if (!reloadAttempted && iframe.src) {{
                    reloadAttempted = true;
                    const currentSrc = iframe.src;
                    // Clear and reload to force fresh content
                    iframe.src = '';
                    setTimeout(() => {{
                        iframe.src = currentSrc + (currentSrc.includes('?') ? '&' : '?') + '_reload=' + Date.now();
                    }}, 50);
                }}
            }};
            
            // Try to reload after a short delay if iframe seems cached
            setTimeout(() => {{
                // If iframe loaded very quickly (< 100ms), it's likely from cache
                if (iframe.complete && state.loaded) {{
                    forceReload();
                }}
            }}, 200);
            
            // Also check if already loaded (in case load event fired before listener was added)
            if (iframe.complete) {{
                // Small delay to ensure setup is complete
                setTimeout(onIframeLoad, 50);
            }}
            
            // Make panel clickable for manual interaction
            panel.addEventListener('click', (e) => {{
                // Don't interfere with URL control clicks or input field
                if (e.target.closest('.url-control')) {{
                    return;
                }}
                // Don't interfere if clicking on input field
                if (e.target.id === 'url-input' || e.target.closest('#url-input')) {{
                    return;
                }}
                document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
                panel.classList.add('active');
                iframe.focus();
                try {{
                    iframe.contentWindow.focus();
                }} catch (e) {{
                    // Cross-origin - ignore
                }}
            }}, false);
        }}
        
        // Store original iframe URLs for sequential loading
        const originalIframeUrls = {{
            'iframe1': '{src_file1}',
            'iframe2': '{src_file2}'
        }};
        
        // Store current iframe URLs (will be modified by URL template)
        const iframeUrls = {{...originalIframeUrls}};
        
        // Function to parse URL and extract parameters
        function parseUrlParameters(urlString) {{
            try {{
                const urlObj = new URL(urlString);
                const result = {{
                    // Path parameters
                    pathname: urlObj.pathname,
                    pathParts: urlObj.pathname.split('/').filter(p => p),
                    // Query parameters
                    queryParams: {{}},
                    // Base URL (protocol + host)
                    origin: urlObj.origin
                }};
                
                // Parse query parameters
                urlObj.searchParams.forEach((value, key) => {{
                    result.queryParams[key] = value;
                }});
                
                return result;
            }} catch (e) {{
                console.error('Error parsing URL:', e);
                return null;
            }}
        }}
        
        // Function to merge URL parameters from template URL into target URL
        // Preserves startDataset from target URL (keeps original data file)
        // Uses template's zoom, lat, lon from path, and query parameters
        function mergeUrlParameters(templateUrl, targetUrl) {{
            try {{
                const template = parseUrlParameters(templateUrl);
                const target = parseUrlParameters(targetUrl);
                
                if (!template || !target) {{
                    return targetUrl; // Return original if can't parse
                }}
                
                // Use template's origin and path (includes zoom, lat, lon, etc. from path)
                // This preserves the zoom level from the template URL
                const newOrigin = template.origin;
                const newPath = template.pathname;
                
                // Merge query parameters
                const newParams = new URLSearchParams();
                
                // First, copy all parameters from template (zoom level, center coords, pointLon, startDate, pixel_size, etc.)
                for (const [key, value] of Object.entries(template.queryParams)) {{
                    newParams.set(key, value);
                }}
                
                // Preserve startDataset from target URL (keep original data file)
                if (target.queryParams.startDataset) {{
                    newParams.set('startDataset', target.queryParams.startDataset);
                }}
                
                // Always add hideAttributes
                newParams.set('hideAttributes', 'true');
                
                // Build new URL using template's origin and path, but preserve target's startDataset
                const newUrl = newOrigin + newPath + '?' + newParams.toString();
                
                return newUrl;
            }} catch (e) {{
                console.error('Error merging URL parameters:', e);
                return targetUrl; // Return original if error
            }}
        }}
        
        // Function to apply URL template to all iframes sequentially
        let isApplyingUrl = false;
        
        function applyUrlToAllFrames(templateUrlString) {{
            if (!templateUrlString || templateUrlString.trim() === '') {{
                alert('Please enter a valid URL');
                return;
            }}
            
            if (isApplyingUrl) {{
                console.log('Already applying URL changes, please wait...');
                return;
            }}
            
            isApplyingUrl = true;
            const urlApplyBtn = document.getElementById('url-apply-btn');
            if (urlApplyBtn) {{
                urlApplyBtn.disabled = true;
                urlApplyBtn.textContent = 'Applying...';
            }}
            
            console.log(`Applying URL template to all iframes: ${{templateUrlString}}`);
            
            const iframeIds = ['iframe1', 'iframe2'];
            let currentIndex = 0;
            
            function applyToNextIframe() {{
                if (currentIndex >= iframeIds.length) {{
                    // All done
                    isApplyingUrl = false;
                    const urlApplyBtn = document.getElementById('url-apply-btn');
                    if (urlApplyBtn) {{
                        urlApplyBtn.disabled = false;
                        urlApplyBtn.textContent = 'Apply';
                    }}
                    // Keep the template URL in the input box so user can see/copy what was applied
                    // Don't modify the input - it should show the exact URL the user pasted
                    console.log('Finished applying URL to all iframes');
                    console.log('Template URL that was applied:', templateUrlString);
                    return;
                }}
                
                const iframeId = iframeIds[currentIndex];
                const iframe = document.getElementById(iframeId);
                
                if (iframe) {{
                    // Get original URL for this iframe
                    const originalUrl = originalIframeUrls[iframeId];
                    
                    // Merge template URL with original URL (preserving startDataset)
                    let newUrl = mergeUrlParameters(templateUrlString, originalUrl);
                    
                    // Add cache-busting to force reload
                    const separator = newUrl.includes('?') ? '&' : '?';
                    newUrl = newUrl + separator + '_nocache=' + Date.now() + '_' + currentIndex;
                    
                    console.log(`Updating ${{iframeId}} ({{currentIndex + 1}}/2): ${{newUrl}}`);
                    
                    // Update original URL (without cache-busting) for future changes
                    const cleanNewUrl = newUrl.split('&_nocache')[0].split('?_nocache')[0];
                    originalIframeUrls[iframeId] = cleanNewUrl;
                    
                    // Reset load state so it can reload properly
                    const state = iframeStates[iframeId];
                    if (state) {{
                        state.loaded = false;
                        state.processed = false;
                    }}
                    
                    // Update iframe src - this will trigger a reload
                    iframe.src = newUrl;
                    
                    // Wait 1 second before applying to next iframe
                    currentIndex++;
                    setTimeout(() => {{
                        applyToNextIframe();
                    }}, 1000);
                }} else {{
                    // Iframe not found, skip it
                    currentIndex++;
                    applyToNextIframe();
                }}
            }}
            
            // Start applying to first iframe
            applyToNextIframe();
        }}
        
        // Set up URL control
        const urlInput = document.getElementById('url-input');
        const urlApplyBtn = document.getElementById('url-apply-btn');
        const urlOpenBtn = document.getElementById('url-open-btn');
        const urlControl = document.querySelector('.url-control');
        
        // Ensure input is editable and stop all event propagation
        if (urlInput) {{
            urlInput.readOnly = false;
            urlInput.disabled = false;
            
            // Track click count for triple-click detection (only for triple-click)
            let clickCount = 0;
            let clickTimer = null;
            let lastClickTime = 0;
            
            // Handle triple-click to select all - minimal interference
            urlInput.addEventListener('mousedown', (e) => {{
                // Only stop propagation to panel, don't prevent default
                e.stopPropagation();
                
                const now = Date.now();
                // Reset counter if more than 500ms since last click
                if (now - lastClickTime > 500) {{
                    clickCount = 0;
                }}
                lastClickTime = now;
                clickCount++;
                
                // Reset counter after 500ms
                if (clickTimer) {{
                    clearTimeout(clickTimer);
                }}
                clickTimer = setTimeout(() => {{
                    clickCount = 0;
                }}, 500);
                
                // On third click, select all (but only after browser handles the click)
                if (clickCount === 3) {{
                    // Don't prevent default - let browser handle mousedown normally
                    // This allows normal cursor placement for single/double clicks
                    setTimeout(() => {{
                        if (urlInput && document.activeElement === urlInput) {{
                            urlInput.select();
                        }}
                        clickCount = 0;
                    }}, 100); // Longer delay to ensure browser handled the click first
                }}
                // For single and double clicks, do nothing - let browser handle normally
            }}, false); // Use bubble phase - browser handles first
            
            // Don't interfere with focus at all - let browser handle it completely
            urlInput.addEventListener('focus', (e) => {{
                // Only stop propagation to panel, don't do anything else
                e.stopPropagation();
                // Don't select, don't move cursor - let user's click determine cursor position
            }}, false);
            
            // Don't interfere with click at all - let browser handle cursor placement
            urlInput.addEventListener('click', (e) => {{
                // Only stop propagation to panel
                e.stopPropagation();
                // Don't do anything else - browser will place cursor where user clicked
            }}, false);
            
            // Stop mouseup from bubbling to panel, but don't interfere with selection
            urlInput.addEventListener('mouseup', (e) => {{
                e.stopPropagation();
                // Don't interfere - let browser handle text selection normally
            }}, false);
            
            // Don't interfere with any other events - let browser handle everything normally
        }}
        
        // Stop events on the entire URL control from bubbling to panel
        // But only for the control container itself, not for input/button inside it
        if (urlControl) {{
            ['click', 'mousedown', 'mouseup'].forEach(eventType => {{
                urlControl.addEventListener(eventType, (e) => {{
                    // Only stop propagation if clicking on the control container itself or label
                    // Don't interfere with input or button events at all
                    const target = e.target;
                    if (target === urlControl || 
                        target === urlControl.querySelector('label') ||
                        (target.tagName && target.tagName.toLowerCase() === 'label')) {{
                        e.stopPropagation();
                    }}
                    // For input and button, don't stop propagation - let them work normally
                }}, false);
            }});
        }}
        
        // Extract initial URL from first iframe to populate input
        // This shows the original URL, but user can paste a different URL to use as template
        // Set this after a small delay to ensure input is fully ready and doesn't interfere
        setTimeout(() => {{
            try {{
                if (urlInput && originalIframeUrls['iframe1']) {{
                    // Store current selection/cursor position if any
                    const hadFocus = document.activeElement === urlInput;
                    const selectionStart = urlInput.selectionStart;
                    const selectionEnd = urlInput.selectionEnd;
                    
                    urlInput.value = originalIframeUrls['iframe1'];
                    
                    // Ensure input is fully interactive after setting value
                    urlInput.readOnly = false;
                    urlInput.disabled = false;
                    
                    // If it had focus, restore cursor position (or set to end if no position)
                    if (hadFocus && selectionStart !== null && selectionEnd !== null) {{
                        urlInput.setSelectionRange(selectionStart, selectionEnd);
                    }}
                    // Don't auto-focus or auto-select - let user click where they want
                }}
            }} catch (e) {{
                // Ignore if can't parse
            }}
        }}, 200); // Longer delay to ensure page is fully loaded
        
        // Function to calculate and display frame dimensions
        function getFrameDimensions() {{
            const container = document.querySelector('.container');
            const panel1 = document.getElementById('panel1');
            const iframe1 = document.getElementById('iframe1');
            const iframe2 = document.getElementById('iframe2');
            
            if (!container || !panel1 || !iframe1 || !iframe2) {{
                return null;
            }}
            
            const containerRect = container.getBoundingClientRect();
            const panel1Rect = panel1.getBoundingClientRect();
            const iframe1Rect = iframe1.getBoundingClientRect();
            const iframe2Rect = iframe2.getBoundingClientRect();
            
            // Panel dimensions (all panels are the same size)
            const panelWidth = Math.round(panel1Rect.width);
            const panelHeight = Math.round(panel1Rect.height);
            
            // Iframe dimensions
            // Panel 1 (top-left) has URL control, so iframe is smaller
            const iframe1Width = Math.round(iframe1Rect.width);
            const iframe1Height = Math.round(iframe1Rect.height);
            
            // Panel 2 has same iframe size (no URL control)
            const iframe2Width = Math.round(iframe2Rect.width);
            const iframe2Height = Math.round(iframe2Rect.height);
            
            return {{
                panel: {{ width: panelWidth, height: panelHeight }},
                iframe1: {{ width: iframe1Width, height: iframe1Height }}, // With URL control
                iframe2: {{ width: iframe2Width, height: iframe2Height }} // Without URL control
            }};
        }}
        
        // Display frame dimensions in console and add to page
        function displayFrameDimensions() {{
            const dims = getFrameDimensions();
            if (dims) {{
                console.log('Frame Dimensions:');
                console.log('  Panel size (all panels):', dims.panel.width + 'x' + dims.panel.height + ' pixels');
                console.log('  Iframe 1 (left, with URL control):', dims.iframe1.width + 'x' + dims.iframe1.height + ' pixels');
                console.log('  Iframe 2 (right panel):', dims.iframe2.width + 'x' + dims.iframe2.height + ' pixels');
                console.log('  Recommended browser window size:', dims.iframe2.width + 'x' + dims.iframe2.height + ' pixels');
                
                // Also display in a small info box (optional - can be removed if not needed)
                const infoBox = document.getElementById('frame-dimensions-info');
                if (infoBox) {{
                    infoBox.textContent = `Frame: ${{dims.iframe2.width}}x${{dims.iframe2.height}}px`;
                }}
            }}
        }}
        
        // Calculate dimensions when page loads and on resize
        window.addEventListener('load', () => {{
            setTimeout(displayFrameDimensions, 500);
        }});
        
        window.addEventListener('resize', () => {{
            setTimeout(displayFrameDimensions, 100);
        }});
        
        // Store the original template URL when user pastes/edits
        let templateUrl = '';
        if (urlInput) {{
            urlInput.addEventListener('input', (e) => {{
                // Store the current value as template when user types/pastes
                templateUrl = urlInput.value.trim();
            }});
            
            urlInput.addEventListener('paste', (e) => {{
                // After paste, update template URL
                setTimeout(() => {{
                    templateUrl = urlInput.value.trim();
                    console.log('Template URL updated after paste:', templateUrl);
                }}, 0);
            }});
        }}
        
        // Common function to apply URL (used by both button and Enter key)
        // Define this as a window function so it's accessible everywhere
        // Make sure it's defined before the button handlers
        function applyUrlFromInputFunction() {{
            const urlInput = document.getElementById('url-input');
            if (!urlInput) {{
                console.error('URL input not found');
                return;
            }}
            
            const urlValue = urlInput.value.trim();
            console.log('Applying URL from input:', urlValue);
            
            if (urlValue) {{
                // Call the applyUrlToAllFrames function - it should be defined above
                try {{
                    if (typeof applyUrlToAllFrames === 'function') {{
                        applyUrlToAllFrames(urlValue);
                    }} else {{
                        console.error('applyUrlToAllFrames is not a function');
                        alert('Error: URL application function not available. Please refresh the page.');
                    }}
                }} catch (error) {{
                    console.error('Error calling applyUrlToAllFrames:', error);
                    alert('Error applying URL: ' + error.message);
                }}
            }} else {{
                alert('Please enter a URL');
            }}
        }}
        
        // Also assign to window for global access
        window.applyUrlFromInput = applyUrlFromInputFunction;
        
        // Apply URL on button click
        if (urlApplyBtn) {{
            console.log('Setting up Apply button handler');
            
            // Stop propagation on button to prevent panel from handling it
            urlApplyBtn.addEventListener('mousedown', (e) => {{
                e.stopPropagation();
                e.stopImmediatePropagation();
            }}, true);
            
            // Main click handler
            urlApplyBtn.addEventListener('click', (e) => {{
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
                console.log('Apply button clicked - calling applyUrlFromInputFunction');
                
                // Try multiple ways to call the function
                if (typeof applyUrlFromInputFunction === 'function') {{
                    applyUrlFromInputFunction();
                }} else if (window.applyUrlFromInput) {{
                    window.applyUrlFromInput();
                }} else {{
                    console.error('applyUrlFromInput not available, trying direct call');
                    // Last resort - try to get input and call applyUrlToAllFrames directly
                    const urlInput = document.getElementById('url-input');
                    if (urlInput && typeof applyUrlToAllFrames === 'function') {{
                        const urlValue = urlInput.value.trim();
                        if (urlValue) {{
                            applyUrlToAllFrames(urlValue);
                        }} else {{
                            alert('Please enter a URL');
                        }}
                    }} else {{
                        alert('Error: Unable to apply URL. Please refresh the page.');
                    }}
                }}
                return false;
            }}, false); // Use bubble phase instead of capture
            
            // Also try mouseup as backup
            urlApplyBtn.addEventListener('mouseup', (e) => {{
                e.stopPropagation();
                e.stopImmediatePropagation();
            }}, true);
        }}
        
        // Set up Open button handler
        if (urlOpenBtn) {{
            console.log('Setting up Open button handler');
            
            // Stop propagation on button to prevent panel from handling it
            urlOpenBtn.addEventListener('mousedown', (e) => {{
                e.stopPropagation();
                e.stopImmediatePropagation();
            }}, true);
            
            // Main click handler
            urlOpenBtn.addEventListener('click', (e) => {{
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
                console.log('Open button clicked');
                
                // Get URL from input field
                const urlValue = urlInput ? urlInput.value.trim() : '';
                if (urlValue) {{
                    // Open URL in new window
                    window.open(urlValue, '_blank', 'noopener,noreferrer');
                }} else {{
                    alert('Please enter a URL first');
                }}
                return false;
            }}, false);
            
            // Also try mouseup as backup
            urlOpenBtn.addEventListener('mouseup', (e) => {{
                e.stopPropagation();
                e.stopImmediatePropagation();
            }}, true);
        }}
        
        // Apply URL on Enter key
        if (urlInput) {{
            urlInput.addEventListener('keypress', (e) => {{
                e.stopPropagation();
                if (e.key === 'Enter' || e.keyCode === 13) {{
                    e.preventDefault();
                    // Only apply if button is not disabled (or doesn't exist)
                    const canApply = !urlApplyBtn || !urlApplyBtn.disabled;
                    if (canApply) {{
                        if (typeof applyUrlFromInputFunction === 'function') {{
                            applyUrlFromInputFunction();
                        }} else if (window.applyUrlFromInput) {{
                            window.applyUrlFromInput();
                        }} else {{
                            console.error("applyUrlFromInput not available");
                        }}
                    }}
                }}
            }}, true);
            
            // Also handle keydown for better compatibility
            urlInput.addEventListener('keydown', (e) => {{
                if (e.key === 'Enter' || e.keyCode === 13) {{
                    e.stopPropagation();
                    // Let keypress handle it, but stop propagation here too
                }}
            }}, true);
            
            // Ensure paste works
            urlInput.addEventListener('paste', (e) => {{
                e.stopPropagation();
                // Allow paste to work normally - browser will handle it
            }}, true);
            
            // Ensure all keyboard events work
            urlInput.addEventListener('keydown', (e) => {{
                e.stopPropagation();
            }}, true);
            
            urlInput.addEventListener('keyup', (e) => {{
                e.stopPropagation();
            }}, true);
        }}
        
        let currentLoadIndex = 0;
        const loadOrder = ['iframe1', 'iframe2'];
        
        // Load iframes sequentially to prevent Safari from blocking AJAX calls
        function loadNextIframe() {{
            if (currentLoadIndex >= loadOrder.length) {{
                console.log('All iframes loaded sequentially');
                return;
            }}
            
            const iframeId = loadOrder[currentLoadIndex];
            const iframe = document.getElementById(iframeId);
            const panelId = 'panel' + (currentLoadIndex + 1);
            const state = iframeStates[iframeId];
            
            console.log(`Loading ${{iframeId}} ({{currentLoadIndex + 1}}/2)`);
            
            // Set up the iframe first
            setupIframe(iframeId, panelId);
            
            // Add cache-busting parameter and hideAttributes parameter
            // Use original URL to avoid zoom modifications during initial load
            const url = originalIframeUrls[iframeId];
            const separator = url.includes('?') ? '&' : '?';
            const cacheBustUrl = url + separator + 'hideAttributes=true&_nocache=' + Date.now() + '_' + currentLoadIndex + '_' + Math.random().toString(36).substr(2, 9);
            
            // Focus this iframe before loading to ensure it's active
            const panel = document.getElementById(panelId);
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            panel.classList.add('active');
            iframe.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
            
            // Focus continuously during load
            const focusInterval = setInterval(() => {{
                iframe.focus();
                try {{
                    iframe.contentWindow.focus();
                }} catch (e) {{
                    // Cross-origin
                }}
            }}, 100);
            
            // Load the iframe
            iframe.src = cacheBustUrl;
            
            // Wait for iframe to load, then wait for AJAX call to complete
            const checkLoaded = setInterval(() => {{
                if (state.loaded) {{
                    clearInterval(checkLoaded);
                    clearInterval(focusInterval);
                    
                    console.log(`${{iframeId}} loaded, waiting for colorscale adjustment...`);
                    
                    // Wait 1 second after load for AJAX call to /preLoad to complete
                    // and colorscale to adjust to data-derived values
                    setTimeout(() => {{
                        console.log(`Finished processing ${{iframeId}}, moving to next`);
                        currentLoadIndex++;
                        
                        // Load next iframe
                        if (currentLoadIndex < loadOrder.length) {{
                            loadNextIframe();
                        }}
                    }}, 1000);
                }}
            }}, 100);
            
            // Timeout fallback - if iframe doesn't load within 10 seconds, move on
            setTimeout(() => {{
                clearInterval(checkLoaded);
                clearInterval(focusInterval);
                if (!state.loaded) {{
                    console.warn(`${{iframeId}} did not load within timeout, moving to next`);
                    currentLoadIndex++;
                    if (currentLoadIndex < loadOrder.length) {{
                        loadNextIframe();
                    }}
                }}
            }}, 10000);
        }}
        
        // Initialize and load iframes sequentially when DOM is ready
        window.addEventListener('DOMContentLoaded', () => {{
            // Start loading first iframe after a short delay
            setTimeout(() => {{
                loadNextIframe();
            }}, 100);
        }});
        
        // Fallback: if not all iframes loaded after 5 seconds, process what we have
        window.addEventListener('load', () => {{
            setTimeout(() => {{
                const loadedCount = Object.values(iframeStates).filter(s => s.loaded).length;
                if (loadedCount > 0 && currentProcessingIndex === 0) {{
                    console.log(`Starting processing with ${{loadedCount}} loaded iframes`);
                    processNextIframe();
                }}
            }}, 5000);
        }});
    </script>
</body>
</html>"""
    
    # Write to output file
    with open(output_path, 'w') as f:
        f.write(html_content)
    
    print(f"Webpage created: {os.path.abspath(output_path)}")
    return output_path


def create_webpage_4frames(urls, labels, output_path='page.html', zoom_factor=None, layout='matrix'):
    """Create a webpage with 4 iframes in specified layout.
    
    Args:
        urls: List of 4 URLs
        labels: List of 4 labels
        output_path: Output HTML file path
        zoom_factor: Optional zoom factor to apply
        layout: 'matrix' (2x2 grid) or 'column' (4 rows)
    """
    
    if len(urls) < 4:
        raise ValueError(f"Need at least 4 URLs, got {len(urls)}")
    
    # Use first 4 URLs and apply zoom factor if provided
    src_file1 = apply_zoom_factor(urls[0], zoom_factor)
    src_file2 = apply_zoom_factor(urls[1], zoom_factor)
    src_file3 = apply_zoom_factor(urls[2], zoom_factor)
    src_file4 = apply_zoom_factor(urls[3], zoom_factor)
    
    # Use extracted labels from URLs (which derive from dataset names)
    label1 = labels[0] if len(labels) > 0 else 'Dataset'
    label2 = labels[1] if len(labels) > 1 else 'Dataset'
    label3 = labels[2] if len(labels) > 2 else 'Dataset'
    label4 = labels[3] if len(labels) > 3 else 'Dataset'
    
    # Determine grid layout based on layout parameter
    if layout == 'column':
        # Single column, 4 rows with fixed 700px height each
        grid_columns = '1fr'
        grid_rows = '700px 700px 700px 700px'
        container_height = 'auto'
        container_class = 'container-column'
        panel_class1 = 'panel-row1'
        panel_class2 = 'panel-row2'
        panel_class3 = 'panel-row3'
        panel_class4 = 'panel-row4'
    else:
        # matrix: 2x2 grid
        grid_columns = '1fr 1fr'
        grid_rows = '1fr 1fr'
        container_height = 'calc(100vh - 40px)'
        container_class = ''
        panel_class1 = 'panel-top-left'
        panel_class2 = 'panel-top-right'
        panel_class3 = 'panel-bottom-left'
        panel_class4 = 'panel-bottom-right'
    
    # Create HTML content with JavaScript to ensure iframes are fully loaded and interactive
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>Insarmaps - 4 Panel View</title>
    <style>
        body {{
            margin: 0;
            padding: 10px;
            font-family: Arial, sans-serif;
            background-color: #f5f5f5;
        }}
        .container {{
            display: grid;
            grid-template-columns: {grid_columns};
            grid-template-rows: {grid_rows};
            gap: 10px;
            height: {container_height};
            max-width: 100%;
        }}
        .container-column {{
            margin-left: 16px;
            margin-right: 16px;
            background-color: #e0e0e0;
        }}
        .panel {{
            background-color: white;
            border: 2px solid #ddd;
            border-radius: 4px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            position: relative;
            cursor: pointer;
            transition: box-shadow 0.2s;
        }}
        .panel:hover {{
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        }}
        .panel.active {{
            box-shadow: 0 0 0 3px rgba(74, 144, 226, 0.5);
        }}
        .panel-header {{
            background-color: #4a90e2;
            color: white;
            padding: 8px 12px;
            font-size: 14px;
            font-weight: bold;
            margin: 0;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: relative;
            height: 38px;
            box-sizing: border-box;
        }}
        .panel-header-title {{
            flex: 1;
        }}
        .panel iframe {{
            width: 100%;
            height: calc(100% - 38px);
            border: none;
            display: block;
        }}
        .panel-top-left .panel-header {{
            background-color: #4a90e2;
        }}
        .panel-top-right .panel-header {{
            background-color: #50c878;
        }}
        .panel-bottom-left .panel-header {{
            background-color: #ff6b6b;
        }}
        .panel-bottom-right .panel-header {{
            background-color: #ffa500;
        }}
        .panel-row1 .panel-header {{
            background-color: #4a90e2;
        }}
        .panel-row2 .panel-header {{
            background-color: #50c878;
        }}
        .panel-row3 .panel-header {{
            background-color: #ff6b6b;
        }}
        .panel-row4 .panel-header {{
            background-color: #ffa500;
        }}
        .loading {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: #666;
            font-size: 14px;
        }}
        .url-control {{
            display: flex;
            flex-direction: row;
            align-items: center;
            gap: 6px;
            margin-left: auto;
            background-color: rgba(255, 255, 255, 0.2);
            padding: 1px 8px;
            border-radius: 4px;
            flex-shrink: 0;
            pointer-events: auto;
            height: 22px;
            box-sizing: border-box;
        }}
        .url-control:hover {{
            background-color: rgba(255, 255, 255, 0.3);
        }}
        .url-control label {{
            font-weight: bold;
            color: white;
            font-size: 11px;
            white-space: nowrap;
        }}
        .url-control input {{
            flex: 1;
            min-width: 150px;
            max-width: 300px;
            padding: 1px 8px;
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 3px;
            font-size: 11px;
            font-family: monospace;
            background-color: rgba(255, 255, 255, 0.9);
            color: #333;
            cursor: text;
            user-select: text;
            -webkit-user-select: text;
            -moz-user-select: text;
            -ms-user-select: text;
            pointer-events: auto !important;
            height: 18px;
            box-sizing: border-box;
            line-height: 16px;
        }}
        .url-control input:focus {{
            outline: none;
            border-color: rgba(255, 255, 255, 0.6);
            background-color: white;
        }}
        .url-control input::placeholder {{
            color: #999;
        }}
        .url-control button {{
            padding: 1px 10px;
            background-color: rgba(255, 255, 255, 0.9);
            color: #4a90e2;
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 3px;
            cursor: pointer;
            font-size: 11px;
            font-weight: bold;
            white-space: nowrap;
            pointer-events: auto;
            height: 18px;
            box-sizing: border-box;
            line-height: 16px;
        }}
        .url-control button:hover {{
            background-color: white;
            border-color: rgba(255, 255, 255, 0.6);
        }}
        .url-control button:disabled {{
            background-color: rgba(255, 255, 255, 0.5);
            cursor: not-allowed;
            color: #999;
        }}
        .url-control #url-open-btn {{
            background-color: #4a90e2;
            color: white;
            border: 1px solid #4a90e2;
            padding: 1px 8px;
            min-width: 20px;
        }}
        .url-control #url-open-btn:hover {{
            background-color: #357abd;
            border-color: #357abd;
        }}
        .frame-dimensions-info {{
            position: fixed;
            bottom: 10px;
            right: 10px;
            background-color: rgba(0, 0, 0, 0.7);
            color: white;
            padding: 6px 10px;
            border-radius: 4px;
            font-size: 11px;
            font-family: monospace;
            z-index: 999;
            pointer-events: none;
        }}
    </style>
</head>
<body>
    <div id="frame-dimensions-info" class="frame-dimensions-info"></div>
    <div class="container {container_class}">
        <div class="panel {panel_class1}" id="panel1">
            <div class="panel-header">
                <span class="panel-header-title">{label1}</span>
                <div class="url-control">
                    <label for="url-input">URL:</label>
                    <input type="text" id="url-input" placeholder="Paste full URL here">
                    <button id="url-apply-btn">Apply</button>
                    <button id="url-open-btn" title="Open URL in new window">O</button>
                </div>
            </div>
            <iframe id="iframe1" title="{label1}" allowfullscreen></iframe>
        </div>
        <div class="panel {panel_class2}" id="panel2">
            <div class="panel-header">{label2}</div>
            <iframe id="iframe2" title="{label2}" allowfullscreen></iframe>
        </div>
        <div class="panel {panel_class3}" id="panel3">
            <div class="panel-header">{label3}</div>
            <iframe id="iframe3" title="{label3}" allowfullscreen></iframe>
        </div>
        <div class="panel {panel_class4}" id="panel4">
            <div class="panel-header">{label4}</div>
            <iframe id="iframe4" title="{label4}" allowfullscreen></iframe>
        </div>
    </div>
    
    <script>
        // Track iframe load states
        const iframeStates = {{
            'iframe1': {{ loaded: false, processed: false, focused: false }},
            'iframe2': {{ loaded: false, processed: false, focused: false }},
            'iframe3': {{ loaded: false, processed: false, focused: false }},
            'iframe4': {{ loaded: false, processed: false, focused: false }}
        }};
        
        // Queue for processing iframes sequentially
        const iframeQueue = [
            {{ id: 'iframe1', panelId: 'panel1', name: '{label1}' }},
            {{ id: 'iframe2', panelId: 'panel2', name: '{label2}' }},
            {{ id: 'iframe3', panelId: 'panel3', name: '{label3}' }},
            {{ id: 'iframe4', panelId: 'panel4', name: '{label4}' }}
        ];
        
        let currentProcessingIndex = 0;
        let currentFocusIndex = -1; // Track which iframe should be focused next
        
        // Function to trigger colorscale adjustment for a specific iframe
        function triggerColorscaleAdjustment(iframeId, panelId) {{
            const iframe = document.getElementById(iframeId);
            const panel = document.getElementById(panelId);
            const state = iframeStates[iframeId];
            
            if (!iframe || state.processed) {{
                return false;
            }}
            
            try {{
                // Mark as processed to avoid duplicate processing
                state.processed = true;
                
                // Make this panel active and ensure it's visible
                document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
                panel.classList.add('active');
                
                // Scroll iframe into view and center it
                iframe.scrollIntoView({{ behavior: 'smooth', block: 'center', inline: 'center' }});
                
                // Wait for scroll to complete, then focus exclusively on this iframe
                setTimeout(() => {{
                    console.log(`Starting colorscale adjustment for ${{iframeId}}`);
                    
                    // CRITICAL: Focus this iframe and keep it focused
                    // The AJAX call to /preLoad needs the iframe to be active
                    iframe.focus();
                    
                    // Try multiple focus attempts to ensure it sticks
                    const focusInterval = setInterval(() => {{
                        iframe.focus();
                        try {{
                            iframe.contentWindow.focus();
                        }} catch (e) {{
                            // Cross-origin
                        }}
                    }}, 200);
                    
                    // Stop focusing after 5 seconds
                    setTimeout(() => {{
                        clearInterval(focusInterval);
                    }}, 5000);
                    
                    // Trigger resize events immediately
                    try {{
                        iframe.contentWindow.postMessage('resize', '*');
                        iframe.contentWindow.dispatchEvent(new Event('resize'));
                    }} catch (e) {{
                        // Cross-origin
                    }}
                    
                    // Wait 2 seconds for the /preLoad AJAX call to complete
                    // This is when colorscale adjusts to data-derived values
                    setTimeout(() => {{
                        console.log(`Colorscale should have adjusted for ${{iframeId}}`);
                        
                        // Send refresh messages
                        try {{
                            iframe.contentWindow.postMessage({{type: 'refresh'}}, '*');
                            iframe.contentWindow.postMessage({{type: 'init'}}, '*');
                        }} catch (e) {{
                            // Cross-origin
                        }}
                        
                        // Minimize attributes window
                        setTimeout(() => {{
                            try {{
                                iframe.contentWindow.postMessage({{type: 'minimizeAttributes'}}, '*');
                            }} catch (e) {{
                                // Cross-origin
                            }}
                        }}, 500);
                    }}, 2000);
                    
                }}, 500);
                
                return true;
            }} catch (e) {{
                console.error(`Error processing ${{iframeId}}:`, e);
                state.processed = false; // Allow retry
                return false;
            }}
        }}
        
        // Process next iframe in queue
        function processNextIframe() {{
            if (currentProcessingIndex >= iframeQueue.length) {{
                console.log('All iframes processed');
                return;
            }}
            
            const item = iframeQueue[currentProcessingIndex];
            const state = iframeStates[item.id];
            
            // Check if iframe is loaded
            if (!state.loaded) {{
                // Wait a bit and try again
                setTimeout(() => processNextIframe(), 200);
                return;
            }}
            
            // Process this iframe
            if (triggerColorscaleAdjustment(item.id, item.panelId)) {{
                console.log(`Processing ${{item.name}} (${{item.id}})`);
                currentProcessingIndex++;
                
                // Wait 5 seconds to ensure colorscale adjustment completes
                // The /preLoad AJAX call takes 1-2 seconds, then colorscale adjusts
                // We need to keep the iframe focused during this time
                setTimeout(() => {{
                    console.log(`Finished processing ${{item.name}}, moving to next iframe`);
                    processNextIframe();
                }}, 5000);
            }} else {{
                // Retry after a delay
                setTimeout(() => processNextIframe(), 500);
            }}
        }}
        
        // Setup iframe load listeners
        function setupIframe(iframeId, panelId) {{
            const iframe = document.getElementById(iframeId);
            const panel = document.getElementById(panelId);
            const state = iframeStates[iframeId];
            
            function onIframeLoad() {{
                // Reset state for reloads (e.g., after zoom change)
                const wasLoaded = state.loaded;
                state.loaded = true;
                console.log(`Iframe loaded: ${{iframeId}} (reload: ${{wasLoaded}})`);
                
                // If this is a reload (was already loaded), just focus it for colorscale adjustment
                if (wasLoaded) {{
                    // This is a reload after zoom change - focus it to trigger colorscale adjustment
                    setTimeout(() => {{
                        const iframe = document.getElementById(iframeId);
                        const panel = document.getElementById(panelId);
                        if (iframe && panel) {{
                            iframe.focus();
                            try {{
                                iframe.contentWindow.focus();
                            }} catch (e) {{
                                // Cross-origin
                            }}
                            // Try to minimize attributes
                            setTimeout(() => {{
                                try {{
                                    iframe.contentWindow.postMessage({{type: 'minimizeAttributes'}}, '*');
                                }} catch (e) {{
                                    // Cross-origin
                                }}
                            }}, 500);
                        }}
                    }}, 500);
                    return;
                }}
                
                // Original load logic for initial page load
                // Find which iframe this is in the queue
                const queueIndex = iframeQueue.findIndex(item => item.id === iframeId);
                
                // Focus this iframe immediately when it loads to ensure AJAX call completes
                // But do it sequentially - only focus the next one in queue
                if (queueIndex === currentFocusIndex + 1) {{
                    currentFocusIndex = queueIndex;
                    focusIframeForColorscale(iframeId, panelId, queueIndex);
                }} else if (queueIndex === 0 && currentFocusIndex === -1) {{
                    // First iframe - start the sequence
                    currentFocusIndex = 0;
                    focusIframeForColorscale(iframeId, panelId, 0);
                }}
                
                // If all iframes are loaded, start the sequential processing queue
                const allLoaded = Object.values(iframeStates).every(s => s.loaded);
                if (allLoaded && currentProcessingIndex === 0) {{
                    console.log('All iframes loaded, starting sequential processing...');
                    setTimeout(() => {{
                        processNextIframe();
                    }}, 1000);
                }}
            }}
            
            // Function to focus iframe and maintain focus during AJAX call
            function focusIframeForColorscale(iframeId, panelId, queueIndex) {{
                const iframe = document.getElementById(iframeId);
                const panel = document.getElementById(panelId);
                
                console.log(`Focusing ${{iframeId}} for colorscale adjustment (queue index: ${{queueIndex}})`);
                
                // Make this panel active
                document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
                panel.classList.add('active');
                
                // Scroll into view
                iframe.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                
                setTimeout(() => {{
                    // Focus the iframe continuously for 3 seconds to ensure AJAX completes
                    iframe.focus();
                    
                    const focusInterval = setInterval(() => {{
                        iframe.focus();
                        try {{
                            iframe.contentWindow.focus();
                        }} catch (e) {{
                            // Cross-origin
                        }}
                    }}, 100);
                    
                    // Stop focusing after 3 seconds (AJAX should complete by then)
                    setTimeout(() => {{
                        clearInterval(focusInterval);
                        console.log(`Finished focusing ${{iframeId}}`);
                    }}, 3000);
                    
                    // Try to minimize attributes window
                    setTimeout(() => {{
                        try {{
                            iframe.contentWindow.postMessage({{type: 'minimizeAttributes'}}, '*');
                        }} catch (e) {{
                            // Cross-origin
                        }}
                    }}, 2500);
                }}, 300);
            }}
            
            // Listen for load event
            iframe.addEventListener('load', onIframeLoad);
            
            // Force reload iframe to bypass Safari cache on subsequent page loads
            // This ensures fresh AJAX calls to /preLoad for colorscale adjustment
            let reloadAttempted = false;
            const forceReload = () => {{
                if (!reloadAttempted && iframe.src) {{
                    reloadAttempted = true;
                    const currentSrc = iframe.src;
                    // Clear and reload to force fresh content
                    iframe.src = '';
                    setTimeout(() => {{
                        iframe.src = currentSrc + (currentSrc.includes('?') ? '&' : '?') + '_reload=' + Date.now();
                    }}, 50);
                }}
            }};
            
            // Try to reload after a short delay if iframe seems cached
            setTimeout(() => {{
                // If iframe loaded very quickly (< 100ms), it's likely from cache
                if (iframe.complete && state.loaded) {{
                    forceReload();
                }}
            }}, 200);
            
            // Also check if already loaded (in case load event fired before listener was added)
            if (iframe.complete) {{
                // Small delay to ensure setup is complete
                setTimeout(onIframeLoad, 50);
            }}
            
            // Make panel clickable for manual interaction
            panel.addEventListener('click', (e) => {{
                // Don't interfere with URL control clicks or input field
                if (e.target.closest('.url-control')) {{
                    return;
                }}
                // Don't interfere if clicking on input field
                if (e.target.id === 'url-input' || e.target.closest('#url-input')) {{
                    return;
                }}
                document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
                panel.classList.add('active');
                iframe.focus();
                try {{
                    iframe.contentWindow.focus();
                }} catch (e) {{
                    // Cross-origin - ignore
                }}
            }}, false);
        }}
        
        // Store original iframe URLs for sequential loading
        const originalIframeUrls = {{
            'iframe1': '{src_file1}',
            'iframe2': '{src_file2}',
            'iframe3': '{src_file3}',
            'iframe4': '{src_file4}'
        }};
        
        // Store current iframe URLs (will be modified by URL template)
        const iframeUrls = {{...originalIframeUrls}};
        
        // Function to parse URL and extract parameters
        function parseUrlParameters(urlString) {{
            try {{
                const urlObj = new URL(urlString);
                const result = {{
                    // Path parameters
                    pathname: urlObj.pathname,
                    pathParts: urlObj.pathname.split('/').filter(p => p),
                    // Query parameters
                    queryParams: {{}},
                    // Base URL (protocol + host)
                    origin: urlObj.origin
                }};
                
                // Parse query parameters
                urlObj.searchParams.forEach((value, key) => {{
                    result.queryParams[key] = value;
                }});
                
                return result;
            }} catch (e) {{
                console.error('Error parsing URL:', e);
                return null;
            }}
        }}
        
        // Function to merge URL parameters from template URL into target URL
        // Preserves startDataset from target URL (keeps original data file)
        // Uses template's zoom, lat, lon from path, and query parameters
        function mergeUrlParameters(templateUrl, targetUrl) {{
            try {{
                const template = parseUrlParameters(templateUrl);
                const target = parseUrlParameters(targetUrl);
                
                if (!template || !target) {{
                    return targetUrl; // Return original if can't parse
                }}
                
                // Use template's origin and path (includes zoom, lat, lon, etc. from path)
                // This preserves the zoom level from the template URL
                const newOrigin = template.origin;
                const newPath = template.pathname;
                
                // Merge query parameters
                const newParams = new URLSearchParams();
                
                // First, copy all parameters from template (zoom level, center coords, pointLon, startDate, pixel_size, etc.)
                for (const [key, value] of Object.entries(template.queryParams)) {{
                    newParams.set(key, value);
                }}
                
                // Preserve startDataset from target URL (keep original data file)
                if (target.queryParams.startDataset) {{
                    newParams.set('startDataset', target.queryParams.startDataset);
                }}
                
                // Always add hideAttributes
                newParams.set('hideAttributes', 'true');
                
                // Build new URL using template's origin and path, but preserve target's startDataset
                const newUrl = newOrigin + newPath + '?' + newParams.toString();
                
                return newUrl;
            }} catch (e) {{
                console.error('Error merging URL parameters:', e);
                return targetUrl; // Return original if error
            }}
        }}
        
        // Function to apply URL template to all iframes sequentially
        let isApplyingUrl = false;
        
        function applyUrlToAllFrames(templateUrlString) {{
            if (!templateUrlString || templateUrlString.trim() === '') {{
                alert('Please enter a valid URL');
                return;
            }}
            
            if (isApplyingUrl) {{
                console.log('Already applying URL changes, please wait...');
                return;
            }}
            
            isApplyingUrl = true;
            const urlApplyBtn = document.getElementById('url-apply-btn');
            if (urlApplyBtn) {{
                urlApplyBtn.disabled = true;
                urlApplyBtn.textContent = 'Applying...';
            }}
            
            console.log(`Applying URL template to all iframes: ${{templateUrlString}}`);
            
            const iframeIds = ['iframe1', 'iframe2', 'iframe3', 'iframe4'];
            let currentIndex = 0;
            
            function applyToNextIframe() {{
                if (currentIndex >= iframeIds.length) {{
                    // All done
                    isApplyingUrl = false;
                    const urlApplyBtn = document.getElementById('url-apply-btn');
                    if (urlApplyBtn) {{
                        urlApplyBtn.disabled = false;
                        urlApplyBtn.textContent = 'Apply';
                    }}
                    // Keep the template URL in the input box so user can see/copy what was applied
                    // Don't modify the input - it should show the exact URL the user pasted
                    console.log('Finished applying URL to all iframes');
                    console.log('Template URL that was applied:', templateUrlString);
                    return;
                }}
                
                const iframeId = iframeIds[currentIndex];
                const iframe = document.getElementById(iframeId);
                
                if (iframe) {{
                    // Get original URL for this iframe
                    const originalUrl = originalIframeUrls[iframeId];
                    
                    // Merge template URL with original URL (preserving startDataset)
                    let newUrl = mergeUrlParameters(templateUrlString, originalUrl);
                    
                    // Add cache-busting to force reload
                    const separator = newUrl.includes('?') ? '&' : '?';
                    newUrl = newUrl + separator + '_nocache=' + Date.now() + '_' + currentIndex;
                    
                    console.log(`Updating ${{iframeId}} ({{currentIndex + 1}}/4): ${{newUrl}}`);
                    
                    // Update original URL (without cache-busting) for future changes
                    const cleanNewUrl = newUrl.split('&_nocache')[0].split('?_nocache')[0];
                    originalIframeUrls[iframeId] = cleanNewUrl;
                    
                    // Reset load state so it can reload properly
                    const state = iframeStates[iframeId];
                    if (state) {{
                        state.loaded = false;
                        state.processed = false;
                    }}
                    
                    // Update iframe src - this will trigger a reload
                    iframe.src = newUrl;
                    
                    // Wait 1 second before applying to next iframe
                    currentIndex++;
                    setTimeout(() => {{
                        applyToNextIframe();
                    }}, 1000);
                }} else {{
                    // Iframe not found, skip it
                    currentIndex++;
                    applyToNextIframe();
                }}
            }}
            
            // Start applying to first iframe
            applyToNextIframe();
        }}
        
        // Set up URL control
        const urlInput = document.getElementById('url-input');
        const urlApplyBtn = document.getElementById('url-apply-btn');
        const urlOpenBtn = document.getElementById('url-open-btn');
        const urlControl = document.querySelector('.url-control');
        
        // Ensure input is editable and stop all event propagation
        if (urlInput) {{
            urlInput.readOnly = false;
            urlInput.disabled = false;
            
            // Track click count for triple-click detection (only for triple-click)
            let clickCount = 0;
            let clickTimer = null;
            let lastClickTime = 0;
            
            // Handle triple-click to select all - minimal interference
            urlInput.addEventListener('mousedown', (e) => {{
                // Only stop propagation to panel, don't prevent default
                e.stopPropagation();
                
                const now = Date.now();
                // Reset counter if more than 500ms since last click
                if (now - lastClickTime > 500) {{
                    clickCount = 0;
                }}
                lastClickTime = now;
                clickCount++;
                
                // Reset counter after 500ms
                if (clickTimer) {{
                    clearTimeout(clickTimer);
                }}
                clickTimer = setTimeout(() => {{
                    clickCount = 0;
                }}, 500);
                
                // On third click, select all (but only after browser handles the click)
                if (clickCount === 3) {{
                    // Don't prevent default - let browser handle mousedown normally
                    // This allows normal cursor placement for single/double clicks
                    setTimeout(() => {{
                        if (urlInput && document.activeElement === urlInput) {{
                            urlInput.select();
                        }}
                        clickCount = 0;
                    }}, 100); // Longer delay to ensure browser handled the click first
                }}
                // For single and double clicks, do nothing - let browser handle normally
            }}, false); // Use bubble phase - browser handles first
            
            // Don't interfere with focus at all - let browser handle it completely
            urlInput.addEventListener('focus', (e) => {{
                // Only stop propagation to panel, don't do anything else
                e.stopPropagation();
                // Don't select, don't move cursor - let user's click determine cursor position
            }}, false);
            
            // Don't interfere with click at all - let browser handle cursor placement
            urlInput.addEventListener('click', (e) => {{
                // Only stop propagation to panel
                e.stopPropagation();
                // Don't do anything else - browser will place cursor where user clicked
            }}, false);
            
            // Stop mouseup from bubbling to panel, but don't interfere with selection
            urlInput.addEventListener('mouseup', (e) => {{
                e.stopPropagation();
                // Don't interfere - let browser handle text selection normally
            }}, false);
            
            // Don't interfere with any other events - let browser handle everything normally
        }}
        
        // Stop events on the entire URL control from bubbling to panel
        // But only for the control container itself, not for input/button inside it
        if (urlControl) {{
            ['click', 'mousedown', 'mouseup'].forEach(eventType => {{
                urlControl.addEventListener(eventType, (e) => {{
                    // Only stop propagation if clicking on the control container itself or label
                    // Don't interfere with input or button events at all
                    const target = e.target;
                    if (target === urlControl || 
                        target === urlControl.querySelector('label') ||
                        (target.tagName && target.tagName.toLowerCase() === 'label')) {{
                        e.stopPropagation();
                    }}
                    // For input and button, don't stop propagation - let them work normally
                }}, false);
            }});
        }}
        
        // Extract initial URL from first iframe to populate input
        // This shows the original URL, but user can paste a different URL to use as template
        // Set this after a small delay to ensure input is fully ready and doesn't interfere
        setTimeout(() => {{
            try {{
                if (urlInput && originalIframeUrls['iframe1']) {{
                    // Store current selection/cursor position if any
                    const hadFocus = document.activeElement === urlInput;
                    const selectionStart = urlInput.selectionStart;
                    const selectionEnd = urlInput.selectionEnd;
                    
                    urlInput.value = originalIframeUrls['iframe1'];
                    
                    // Ensure input is fully interactive after setting value
                    urlInput.readOnly = false;
                    urlInput.disabled = false;
                    
                    // If it had focus, restore cursor position (or set to end if no position)
                    if (hadFocus && selectionStart !== null && selectionEnd !== null) {{
                        urlInput.setSelectionRange(selectionStart, selectionEnd);
                    }}
                    // Don't auto-focus or auto-select - let user click where they want
                }}
            }} catch (e) {{
                // Ignore if can't parse
            }}
        }}, 200); // Longer delay to ensure page is fully loaded
        
        // Function to calculate and display frame dimensions
        function getFrameDimensions() {{
            const container = document.querySelector('.container');
            const panel1 = document.getElementById('panel1');
            const iframe1 = document.getElementById('iframe1');
            const iframe2 = document.getElementById('iframe2');
            
            if (!container || !panel1 || !iframe1 || !iframe2) {{
                return null;
            }}
            
            const containerRect = container.getBoundingClientRect();
            const panel1Rect = panel1.getBoundingClientRect();
            const iframe1Rect = iframe1.getBoundingClientRect();
            const iframe2Rect = iframe2.getBoundingClientRect();
            
            // Panel dimensions (all panels are the same size)
            const panelWidth = Math.round(panel1Rect.width);
            const panelHeight = Math.round(panel1Rect.height);
            
            // Iframe dimensions
            // Panel 1 (top-left) has URL control, so iframe is smaller
            const iframe1Width = Math.round(iframe1Rect.width);
            const iframe1Height = Math.round(iframe1Rect.height);
            
            // Panels 2, 3, 4 have same iframe size (no URL control)
            const iframe2Width = Math.round(iframe2Rect.width);
            const iframe2Height = Math.round(iframe2Rect.height);
            
            return {{
                panel: {{ width: panelWidth, height: panelHeight }},
                iframe1: {{ width: iframe1Width, height: iframe1Height }}, // With URL control
                iframe2_3_4: {{ width: iframe2Width, height: iframe2Height }} // Without URL control
            }};
        }}
        
        // Display frame dimensions in console and add to page
        function displayFrameDimensions() {{
            const dims = getFrameDimensions();
            if (dims) {{
                console.log('Frame Dimensions:');
                console.log('  Panel size (all panels):', dims.panel.width + 'x' + dims.panel.height + ' pixels');
                console.log('  Iframe 1 (top-left, with URL control):', dims.iframe1.width + 'x' + dims.iframe1.height + ' pixels');
                console.log('  Iframes 2,3,4 (other panels):', dims.iframe2_3_4.width + 'x' + dims.iframe2_3_4.height + ' pixels');
                console.log('  Recommended browser window size:', dims.iframe2_3_4.width + 'x' + dims.iframe2_3_4.height + ' pixels');
                
                // Also display in a small info box (optional - can be removed if not needed)
                const infoBox = document.getElementById('frame-dimensions-info');
                if (infoBox) {{
                    infoBox.textContent = `Frame: ${{dims.iframe2_3_4.width}}x${{dims.iframe2_3_4.height}}px`;
                }}
            }}
        }}
        
        // Calculate dimensions when page loads and on resize
        window.addEventListener('load', () => {{
            setTimeout(displayFrameDimensions, 500);
        }});
        
        window.addEventListener('resize', () => {{
            setTimeout(displayFrameDimensions, 100);
        }});
        
        // Store the original template URL when user pastes/edits
        let templateUrl = '';
        if (urlInput) {{
            urlInput.addEventListener('input', (e) => {{
                // Store the current value as template when user types/pastes
                templateUrl = urlInput.value.trim();
            }});
            
            urlInput.addEventListener('paste', (e) => {{
                // After paste, update template URL
                setTimeout(() => {{
                    templateUrl = urlInput.value.trim();
                    console.log('Template URL updated after paste:', templateUrl);
                }}, 0);
            }});
        }}
        
        // Common function to apply URL (used by both button and Enter key)
        // Define this as a window function so it's accessible everywhere
        // Make sure it's defined before the button handlers
        function applyUrlFromInputFunction() {{
            const urlInput = document.getElementById('url-input');
            if (!urlInput) {{
                console.error('URL input not found');
                return;
            }}
            
            const urlValue = urlInput.value.trim();
            console.log('Applying URL from input:', urlValue);
            
            if (urlValue) {{
                // Call the applyUrlToAllFrames function - it should be defined above
                try {{
                    if (typeof applyUrlToAllFrames === 'function') {{
                        applyUrlToAllFrames(urlValue);
                    }} else {{
                        console.error('applyUrlToAllFrames is not a function');
                        alert('Error: URL application function not available. Please refresh the page.');
                    }}
                }} catch (error) {{
                    console.error('Error calling applyUrlToAllFrames:', error);
                    alert('Error applying URL: ' + error.message);
                }}
            }} else {{
                alert('Please enter a URL');
            }}
        }}
        
        // Also assign to window for global access
        window.applyUrlFromInput = applyUrlFromInputFunction;
        
        // Apply URL on button click
        if (urlApplyBtn) {{
            console.log('Setting up Apply button handler');
            
            // Stop propagation on button to prevent panel from handling it
            urlApplyBtn.addEventListener('mousedown', (e) => {{
                e.stopPropagation();
                e.stopImmediatePropagation();
            }}, true);
            
            // Main click handler
            urlApplyBtn.addEventListener('click', (e) => {{
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
                console.log('Apply button clicked - calling applyUrlFromInputFunction');
                
                // Try multiple ways to call the function
                if (typeof applyUrlFromInputFunction === 'function') {{
                    applyUrlFromInputFunction();
                }} else if (window.applyUrlFromInput) {{
                    window.applyUrlFromInput();
                }} else {{
                    console.error('applyUrlFromInput not available, trying direct call');
                    // Last resort - try to get input and call applyUrlToAllFrames directly
                    const urlInput = document.getElementById('url-input');
                    if (urlInput && typeof applyUrlToAllFrames === 'function') {{
                        const urlValue = urlInput.value.trim();
                        if (urlValue) {{
                            applyUrlToAllFrames(urlValue);
                        }} else {{
                            alert('Please enter a URL');
                        }}
                    }} else {{
                        alert('Error: Unable to apply URL. Please refresh the page.');
                    }}
                }}
                return false;
            }}, false); // Use bubble phase instead of capture
            
            // Also try mouseup as backup
            urlApplyBtn.addEventListener('mouseup', (e) => {{
                e.stopPropagation();
                e.stopImmediatePropagation();
            }}, true);
        }}
        
        // Set up Open button handler
        if (urlOpenBtn) {{
            console.log('Setting up Open button handler');
            
            // Stop propagation on button to prevent panel from handling it
            urlOpenBtn.addEventListener('mousedown', (e) => {{
                e.stopPropagation();
                e.stopImmediatePropagation();
            }}, true);
            
            // Main click handler
            urlOpenBtn.addEventListener('click', (e) => {{
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
                console.log('Open button clicked');
                
                // Get URL from input field
                const urlValue = urlInput ? urlInput.value.trim() : '';
                if (urlValue) {{
                    // Open URL in new window
                    window.open(urlValue, '_blank', 'noopener,noreferrer');
                }} else {{
                    alert('Please enter a URL first');
                }}
                return false;
            }}, false);
            
            // Also try mouseup as backup
            urlOpenBtn.addEventListener('mouseup', (e) => {{
                e.stopPropagation();
                e.stopImmediatePropagation();
            }}, true);
        }}
        
        // Apply URL on Enter key
        if (urlInput) {{
            urlInput.addEventListener('keypress', (e) => {{
                e.stopPropagation();
                if (e.key === 'Enter' || e.keyCode === 13) {{
                    e.preventDefault();
                    // Only apply if button is not disabled (or doesn't exist)
                    const canApply = !urlApplyBtn || !urlApplyBtn.disabled;
                    if (canApply) {{
                        if (typeof applyUrlFromInputFunction === 'function') {{
                            applyUrlFromInputFunction();
                        }} else if (window.applyUrlFromInput) {{
                            window.applyUrlFromInput();
                        }} else {{
                            console.error("applyUrlFromInput not available");
                        }}
                    }}
                }}
            }}, true);
            
            // Also handle keydown for better compatibility
            urlInput.addEventListener('keydown', (e) => {{
                if (e.key === 'Enter' || e.keyCode === 13) {{
                    e.stopPropagation();
                    // Let keypress handle it, but stop propagation here too
                }}
            }}, true);
            
            // Ensure paste works
            urlInput.addEventListener('paste', (e) => {{
                e.stopPropagation();
                // Allow paste to work normally - browser will handle it
            }}, true);
            
            // Ensure all keyboard events work
            urlInput.addEventListener('keydown', (e) => {{
                e.stopPropagation();
            }}, true);
            
            urlInput.addEventListener('keyup', (e) => {{
                e.stopPropagation();
            }}, true);
        }}
        
        let currentLoadIndex = 0;
        const loadOrder = ['iframe1', 'iframe2', 'iframe3', 'iframe4'];
        
        // Load iframes sequentially to prevent Safari from blocking AJAX calls
        function loadNextIframe() {{
            if (currentLoadIndex >= loadOrder.length) {{
                console.log('All iframes loaded sequentially');
                return;
            }}
            
            const iframeId = loadOrder[currentLoadIndex];
            const iframe = document.getElementById(iframeId);
            const panelId = 'panel' + (currentLoadIndex + 1);
            const state = iframeStates[iframeId];
            
            console.log(`Loading ${{iframeId}} ({{currentLoadIndex + 1}}/4)`);
            
            // Set up the iframe first
            setupIframe(iframeId, panelId);
            
            // Add cache-busting parameter and hideAttributes parameter
            // Use original URL to avoid zoom modifications during initial load
            const url = originalIframeUrls[iframeId];
            const separator = url.includes('?') ? '&' : '?';
            const cacheBustUrl = url + separator + 'hideAttributes=true&_nocache=' + Date.now() + '_' + currentLoadIndex + '_' + Math.random().toString(36).substr(2, 9);
            
            // Focus this iframe before loading to ensure it's active
            const panel = document.getElementById(panelId);
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            panel.classList.add('active');
            iframe.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
            
            // Focus continuously during load
            const focusInterval = setInterval(() => {{
                iframe.focus();
                try {{
                    iframe.contentWindow.focus();
                }} catch (e) {{
                    // Cross-origin
                }}
            }}, 100);
            
            // Load the iframe
            iframe.src = cacheBustUrl;
            
            // Wait for iframe to load, then wait for AJAX call to complete
            const checkLoaded = setInterval(() => {{
                if (state.loaded) {{
                    clearInterval(checkLoaded);
                    clearInterval(focusInterval);
                    
                    console.log(`${{iframeId}} loaded, waiting for colorscale adjustment...`);
                    
                    // Wait 1 second after load for AJAX call to /preLoad to complete
                    // and colorscale to adjust to data-derived values
                    setTimeout(() => {{
                        console.log(`Finished processing ${{iframeId}}, moving to next`);
                        currentLoadIndex++;
                        
                        // Load next iframe
                        if (currentLoadIndex < loadOrder.length) {{
                            loadNextIframe();
                        }}
                    }}, 1000);
                }}
            }}, 100);
            
            // Timeout fallback - if iframe doesn't load within 10 seconds, move on
            setTimeout(() => {{
                clearInterval(checkLoaded);
                clearInterval(focusInterval);
                if (!state.loaded) {{
                    console.warn(`${{iframeId}} did not load within timeout, moving to next`);
                    currentLoadIndex++;
                    if (currentLoadIndex < loadOrder.length) {{
                        loadNextIframe();
                    }}
                }}
            }}, 10000);
        }}
        
        // Initialize and load iframes sequentially when DOM is ready
        window.addEventListener('DOMContentLoaded', () => {{
            // Start loading first iframe after a short delay
            setTimeout(() => {{
                loadNextIframe();
            }}, 100);
        }});
        
        // Fallback: if not all iframes loaded after 5 seconds, process what we have
        window.addEventListener('load', () => {{
            setTimeout(() => {{
                const loadedCount = Object.values(iframeStates).filter(s => s.loaded).length;
                if (loadedCount > 0 && currentProcessingIndex === 0) {{
                    console.log(`Starting processing with ${{loadedCount}} loaded iframes`);
                    processNextIframe();
                }}
            }}, 5000);
        }});
    </script>
</body>
</html>"""
    
    # Write to output file
    with open(output_path, 'w') as f:
        f.write(html_content)
    
    print(f"Webpage created: {os.path.abspath(output_path)}")
    return output_path


def extract_coordinates_from_url(url):
    """Extract lat, lon, and zoom from URL path format /start/{lat}/{lon}/{zoom}."""
    try:
        parsed = urlparse(url)
        path_parts = parsed.path.strip('/').split('/')
        
        if len(path_parts) >= 4 and path_parts[0] == 'start':
            lat = float(path_parts[1])
            lon = float(path_parts[2])
            zoom = float(path_parts[3])
            return lat, lon, zoom
    except (ValueError, IndexError):
        pass
    
    # Try to get from query parameters as fallback
    try:
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        if 'lat' in query_params and 'lon' in query_params:
            lat = float(query_params['lat'][0])
            lon = float(query_params['lon'][0])
            zoom = float(query_params.get('zoom', ['10'])[0])
            return lat, lon, zoom
    except (ValueError, KeyError):
        pass
    
    return None, None, None


def create_overlay_html(urls, labels, output_path='overlay.html', zoom_factor=None):
    """Create an overlay HTML page with all frames overlain and a dropdown to select dataset."""
    
    if not urls:
        raise ValueError("No URLs provided")
    
    # Prepare data for each frame
    frames_data = []
    for i, url in enumerate(urls):
        label = labels[i] if i < len(labels) else f'Dataset {i+1}'
        frames_data.append({
            'url': apply_zoom_factor(url, zoom_factor),
            'label': label
        })
    
    # Generate JavaScript for frames data using JSON for proper escaping
    frames_js = json.dumps(frames_data, indent=8)
    
    # Generate options HTML for dropdown
    options_html = ''
    for i, frame in enumerate(frames_data):
        options_html += f'            <option value="{i}">{frame["label"]}</option>\n'
    
    # Create HTML content - similar to good_create_insarmaps_framepage.py
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>Insarmaps - Frame Overlay</title>
    <style>
        body {{
            margin: 0;
            padding: 10px;
            font-family: Arial, sans-serif;
            background-color: #f5f5f5;
        }}
        .frame-selector {{
            margin-bottom: 10px;
            padding: 10px;
            background-color: white;
            border: 2px solid #ddd;
            border-radius: 4px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .frame-selector label {{
            font-weight: bold;
            font-size: 14px;
            color: #333;
        }}
        .frame-selector select {{
            padding: 6px 12px;
            font-size: 14px;
            border: 1px solid #ddd;
            border-radius: 4px;
            background-color: white;
            cursor: pointer;
            flex: 1;
            max-width: 300px;
        }}
        .frame-selector select:focus {{
            outline: none;
            border-color: #4a90e2;
        }}
        .container {{
            width: 100%;
            height: calc(100vh - 80px);
            max-width: 100%;
            position: relative;
        }}
        .panel {{
            background-color: white;
            border: 2px solid #ddd;
            border-radius: 4px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            cursor: pointer;
            transition: box-shadow 0.2s;
            display: none;
        }}
        .panel.active {{
            display: block;
        }}
        .panel:hover {{
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        }}
        .panel.active {{
            box-shadow: 0 0 0 3px rgba(74, 144, 226, 0.5);
        }}
        .panel-header {{
            background-color: #4a90e2;
            color: white;
            padding: 8px 12px;
            font-size: 14px;
            font-weight: bold;
            margin: 0;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: relative;
            height: 38px;
            box-sizing: border-box;
        }}
        .panel-header-title {{
            flex: 1;
        }}
        .url-control {{
            display: flex;
            flex-direction: row;
            align-items: center;
            gap: 6px;
            margin-left: auto;
            background-color: rgba(255, 255, 255, 0.2);
            padding: 1px 8px;
            border-radius: 4px;
            flex-shrink: 0;
            pointer-events: auto;
            height: 22px;
            box-sizing: border-box;
        }}
        .url-control:hover {{
            background-color: rgba(255, 255, 255, 0.3);
        }}
        .url-control label {{
            font-weight: bold;
            color: white;
            font-size: 11px;
            white-space: nowrap;
        }}
        .url-control input {{
            flex: 1;
            min-width: 150px;
            max-width: 300px;
            padding: 1px 8px;
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 3px;
            font-size: 11px;
            font-family: monospace;
            background-color: rgba(255, 255, 255, 0.9);
            color: #333;
            cursor: text;
            user-select: text;
            -webkit-user-select: text;
            -moz-user-select: text;
            -ms-user-select: text;
            pointer-events: auto !important;
            height: 18px;
            box-sizing: border-box;
            line-height: 16px;
        }}
        .url-control input:focus {{
            outline: none;
            border-color: rgba(255, 255, 255, 0.6);
            background-color: white;
        }}
        .url-control input::placeholder {{
            color: #999;
        }}
        .url-control button {{
            padding: 1px 10px;
            background-color: rgba(255, 255, 255, 0.9);
            color: #4a90e2;
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 3px;
            cursor: pointer;
            font-size: 11px;
            font-weight: bold;
            white-space: nowrap;
            pointer-events: auto;
            height: 18px;
            box-sizing: border-box;
        }}
        .url-control button:hover {{
            background-color: white;
        }}
        .url-control button:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}
        .url-control #url-open-btn {{
            background-color: #4a90e2;
            color: white;
            border: 1px solid #4a90e2;
            padding: 1px 8px;
            min-width: 20px;
        }}
        .url-control #url-open-btn:hover {{
            background-color: #357abd;
            border-color: #357abd;
        }}
        .panel iframe {{
            width: 100%;
            height: calc(100% - 38px);
            border: none;
            display: block;
        }}
    </style>
</head>
<body>
    <div class="frame-selector">
        <label for="frame-select">Select dataset:</label>
        <select id="frame-select">
{options_html}        </select>
    </div>
    <div class="container">
        <!-- Panels will be created dynamically for each frame -->
    </div>
    
    <script>
        // Frames data
        const frames = {frames_js};
        
        // Track iframe load states
        const iframeStates = {{}};
        const panels = [];
        let currentLoadIndex = 0;
        
        // Create panels for each frame (but don't load iframes yet)
        const container = document.querySelector('.container');
        
        frames.forEach((frame, index) => {{
            const panel = document.createElement('div');
            panel.className = 'panel';
            panel.id = `panel${{index}}`;
            if (index === 0) {{
                panel.classList.add('active');
            }}
            
            const header = document.createElement('div');
            header.className = 'panel-header';
            
            const title = document.createElement('span');
            title.className = 'panel-header-title';
            title.textContent = frame.label;
            header.appendChild(title);
            
            // Add URL control to all panels
            const urlControl = document.createElement('div');
            urlControl.className = 'url-control';
            
            const urlLabel = document.createElement('label');
            urlLabel.setAttribute('for', `url-input-${{index}}`);
            urlLabel.textContent = 'URL:';
            
            const urlInput = document.createElement('input');
            urlInput.type = 'text';
            urlInput.id = `url-input-${{index}}`;
            urlInput.className = 'url-input-frame';
            urlInput.placeholder = 'Paste full URL here';
            
            // Add Apply button to all panels
            const urlApplyBtn = document.createElement('button');
            urlApplyBtn.className = 'url-apply-btn-frame';
            urlApplyBtn.id = `url-apply-btn-${{index}}`;
            urlApplyBtn.textContent = 'Apply';
            
            // Add "O" button to all panels
            const urlOpenBtn = document.createElement('button');
            urlOpenBtn.className = 'url-open-btn-frame';
            urlOpenBtn.id = `url-open-btn-${{index}}`;
            urlOpenBtn.textContent = 'O';
            urlOpenBtn.title = 'Open URL in new window';
            
            // Order: URL label, URL input, Apply button, "O" button
            urlControl.appendChild(urlLabel);
            urlControl.appendChild(urlInput);
            urlControl.appendChild(urlApplyBtn);
            urlControl.appendChild(urlOpenBtn);
            header.appendChild(urlControl);
            
            const iframe = document.createElement('iframe');
            iframe.id = `iframe${{index}}`;
            iframe.title = frame.label;
            iframe.setAttribute('allowfullscreen', '');
            // Don't set src yet - will load sequentially
            
            // Track state
            iframeStates[iframe.id] = {{ loaded: false }};
            
            panel.appendChild(header);
            panel.appendChild(iframe);
            container.appendChild(panel);
            panels.push(panel);
        }});
        
        // Store original iframe URLs
        const originalIframeUrls = {{}};
        
        // Sequential loading function
        function loadNextIframe() {{
            if (currentLoadIndex >= frames.length) {{
                console.log('All iframes loaded');
                return;
            }}
            
            const iframe = document.getElementById(`iframe${{currentLoadIndex}}`);
            const panel = panels[currentLoadIndex];
            const frame = frames[currentLoadIndex];
            const state = iframeStates[iframe.id];
            
            if (!iframe || !panel) {{
                console.error(`Could not find iframe or panel at index ${{currentLoadIndex}}`);
                currentLoadIndex++;
                loadNextIframe();
                return;
            }}
            
            console.log(`Loading iframe ${{currentLoadIndex + 1}}/${{frames.length}}: ${{frame.label}}`);
            
            // Make this panel active and visible
            panels.forEach(p => p.classList.remove('active'));
            panel.classList.add('active');
            
            // Set iframe source
            iframe.src = frame.url;
            
            // Store original URL
            originalIframeUrls[iframe.id] = frame.url;
            
            // Use load event to detect when iframe is loaded
            const onIframeLoad = () => {{
                if (state.loaded) return; // Already processed
                
                state.loaded = true;
                console.log(`Iframe ${{currentLoadIndex + 1}} loaded, waiting for colorscale adjustment...`);
                
                // Update URL input for this frame
                const urlInput = document.getElementById(`url-input-${{currentLoadIndex}}`);
                if (urlInput && frame.url) {{
                    urlInput.value = frame.url;
                }}
                
                // Wait 1 second after load for AJAX call to /preLoad to complete
                // and colorscale to adjust to data-derived values
                setTimeout(() => {{
                    console.log(`Finished processing iframe ${{currentLoadIndex + 1}}, moving to next`);
                    currentLoadIndex++;
                    
                    // Load next iframe
                    loadNextIframe();
                }}, 1000);
            }};
            
            // Add load event listener
            iframe.addEventListener('load', onIframeLoad);
            
            // Timeout fallback - if iframe doesn't load within 10 seconds, move on
            setTimeout(() => {{
                if (!state.loaded) {{
                    console.warn(`Iframe ${{currentLoadIndex + 1}} did not load within timeout, moving to next`);
                    iframe.removeEventListener('load', onIframeLoad);
                    state.loaded = true; // Mark as loaded to prevent infinite loop
                    currentLoadIndex++;
                    loadNextIframe();
                }}
            }}, 10000);
        }}
        
        // Frame selector functionality - switch between datasets
        const frameSelect = document.getElementById('frame-select');
        if (frameSelect) {{
            frameSelect.addEventListener('change', (e) => {{
                const selectedIndex = parseInt(e.target.value);
                
                // Hide all panels
                panels.forEach(panel => {{
                    panel.classList.remove('active');
                }});
                
                // Show selected panel
                if (selectedIndex >= 0 && selectedIndex < panels.length) {{
                    const selectedPanel = panels[selectedIndex];
                    selectedPanel.classList.add('active');
                }}
            }});
            
            // Initialize: first panel active by default
            if (panels.length > 0) {{
                frameSelect.value = '0';
            }}
        }}
        
        // Function to apply URL template to all iframes sequentially
        let isApplyingUrl = false;
        
        function applyUrlToAllFrames(templateUrlString) {{
            if (!templateUrlString || templateUrlString.trim() === '') {{
                console.warn('Empty URL provided');
                return;
            }}
            
            if (isApplyingUrl) {{
                console.log('Already applying URL changes, please wait...');
                return;
            }}
            
            isApplyingUrl = true;
            // Disable all Apply buttons
            frames.forEach((frame, idx) => {{
                const urlApplyBtn = document.getElementById(`url-apply-btn-${{idx}}`);
                if (urlApplyBtn) {{
                    urlApplyBtn.disabled = true;
                    urlApplyBtn.textContent = 'Applying...';
                }}
            }});
            
            console.log(`Applying URL template to all iframes: ${{templateUrlString}}`);
            
            let applyIndex = 0;
            
            function applyToNextIframe() {{
                if (applyIndex >= frames.length) {{
                    isApplyingUrl = false;
                    // Re-enable all Apply buttons
                    frames.forEach((frame, idx) => {{
                        const urlApplyBtn = document.getElementById(`url-apply-btn-${{idx}}`);
                        if (urlApplyBtn) {{
                            urlApplyBtn.disabled = false;
                            urlApplyBtn.textContent = 'Apply';
                        }}
                    }});
                    console.log('Finished applying URL to all iframes');
                    return;
                }}
                
                const iframe = document.getElementById(`iframe${{applyIndex}}`);
                const panel = panels[applyIndex];
                
                if (iframe && panel) {{
                    // Make panel active
                    panels.forEach(p => p.classList.remove('active'));
                    panel.classList.add('active');
                    
                    // Merge URL parameters (preserve startDataset from target, use template for others)
                    try {{
                        const targetUrl = originalIframeUrls[iframe.id] || frames[applyIndex].url;
                        const mergedUrl = mergeUrlParameters(templateUrlString, targetUrl);
                        iframe.src = mergedUrl;
                        
                        // Update the URL input for this frame
                        const urlInput = document.getElementById(`url-input-${{applyIndex}}`);
                        if (urlInput) {{
                            urlInput.value = mergedUrl;
                        }}
                        
                        console.log(`Applied URL to iframe ${{applyIndex + 1}}/${{frames.length}}`);
                        
                        // Wait 1 second before applying to next iframe
                        setTimeout(() => {{
                            applyIndex++;
                            applyToNextIframe();
                        }}, 1000);
                    }} catch (error) {{
                        console.error(`Error applying URL to iframe ${{applyIndex + 1}}:`, error);
                        applyIndex++;
                        applyToNextIframe();
                    }}
                }} else {{
                    applyIndex++;
                    applyToNextIframe();
                }}
            }}
            
            // Start applying to first iframe
            applyToNextIframe();
        }}
        
        // Function to merge URL parameters from template URL into target URL
        function mergeUrlParameters(templateUrl, targetUrl) {{
            try {{
                const template = parseUrlParameters(templateUrl);
                const target = parseUrlParameters(targetUrl);
                
                if (!template || !target) {{
                    return templateUrl; // Fallback to template
                }}
                
                // Use template's origin and path (includes zoom, lat, lon, etc. from path)
                const newOrigin = template.origin;
                const newPath = template.pathname;
                
                // Merge query parameters
                const mergedParams = {{}};
                
                // First, copy all parameters from template (zoom level, center coords, pointLon, startDate, pixel_size, etc.)
                for (const [key, value] of Object.entries(template.queryParams)) {{
                    mergedParams[key] = value;
                }}
                
                // Preserve startDataset from target URL (keep original data file)
                if (target.queryParams.startDataset) {{
                    mergedParams.startDataset = target.queryParams.startDataset;
                }}
                
                // Build new URL
                const queryString = Object.entries(mergedParams)
                    .map(([key, value]) => `${{key}}=${{encodeURIComponent(value)}}`)
                    .join('&');
                
                return `${{newOrigin}}${{newPath}}?${{queryString}}`;
            }} catch (error) {{
                console.error('Error merging URLs:', error);
                return templateUrl;
            }}
        }}
        
        // Function to parse URL parameters
        function parseUrlParameters(url) {{
            try {{
                const urlObj = new URL(url);
                const params = {{}};
                urlObj.searchParams.forEach((value, key) => {{
                    params[key] = value;
                }});
                
                return {{
                    origin: urlObj.origin,
                    pathname: urlObj.pathname,
                    queryParams: params
                }};
            }} catch (error) {{
                console.error('Error parsing URL:', error);
                return null;
            }}
        }}
        
        // URL input and button handlers - handle all frames
        // Common function to apply URL from a specific frame's input
        function applyUrlFromInputFunction(frameIndex) {{
            const urlInput = document.getElementById(`url-input-${{frameIndex}}`);
            if (!urlInput) return;
            
            const urlValue = urlInput.value.trim();
            if (!urlValue) {{
                alert('Please enter a URL');
                return;
            }}
            
            console.log(`Applying URL from frame ${{frameIndex}} input:`, urlValue);
            
            try {{
                // Call the applyUrlToAllFrames function
                if (typeof applyUrlToAllFrames === 'function') {{
                    applyUrlToAllFrames(urlValue);
                }} else {{
                    console.error('applyUrlToAllFrames is not a function');
                    alert('Error: Unable to apply URL. Please refresh the page.');
                }}
            }} catch (error) {{
                console.error('Error calling applyUrlToAllFrames:', error);
                alert('Error applying URL: ' + error.message);
            }}
        }}
        
        // Also assign to window for global access (uses first frame by default)
        window.applyUrlFromInput = function() {{
            applyUrlFromInputFunction(0);
        }};
        
        // Set up Apply button handlers for all frames
        frames.forEach((frame, index) => {{
            const urlApplyBtn = document.getElementById(`url-apply-btn-${{index}}`);
            
            if (urlApplyBtn) {{
                urlApplyBtn.addEventListener('mousedown', (e) => {{
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                }}, true);
                
                urlApplyBtn.addEventListener('click', (e) => {{
                    e.preventDefault();
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                    console.log(`Apply button clicked for frame ${{index}}`);
                    
                    applyUrlFromInputFunction(index);
                    return false;
                }}, false);
                
                urlApplyBtn.addEventListener('mouseup', (e) => {{
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                }}, true);
            }}
        }});
        
        // Set up "O" button handlers for all frames
        frames.forEach((frame, index) => {{
            const urlOpenBtn = document.getElementById(`url-open-btn-${{index}}`);
            const urlInput = document.getElementById(`url-input-${{index}}`);
            
            if (urlOpenBtn) {{
                urlOpenBtn.addEventListener('mousedown', (e) => {{
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                }}, true);
                
                urlOpenBtn.addEventListener('click', (e) => {{
                    e.preventDefault();
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                    console.log(`Open button clicked for frame ${{index}}`);
                    
                    // Get URL from this frame's input field
                    const urlValue = urlInput ? urlInput.value.trim() : '';
                    if (urlValue) {{
                        // Open URL in new window
                        window.open(urlValue, '_blank', 'noopener,noreferrer');
                    }} else {{
                        alert('Please enter a URL first');
                    }}
                    return false;
                }}, false);
                
                urlOpenBtn.addEventListener('mouseup', (e) => {{
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                }}, true);
            }}
            
            // Set up event handlers for each URL input
            if (urlInput) {{
                // Apply URL on Enter key (applies to all frames using this frame's URL)
                urlInput.addEventListener('keypress', (e) => {{
                    e.stopPropagation();
                    if (e.key === 'Enter' || e.keyCode === 13) {{
                        e.preventDefault();
                        const frameApplyBtn = document.getElementById(`url-apply-btn-${{index}}`);
                        const canApply = !frameApplyBtn || !frameApplyBtn.disabled;
                        if (canApply) {{
                            applyUrlFromInputFunction(index);
                        }}
                    }}
                }}, true);
                
                // Stop events from bubbling to panel
                urlInput.addEventListener('click', (e) => {{
                    e.stopPropagation();
                }}, false);
                
                urlInput.addEventListener('mousedown', (e) => {{
                    e.stopPropagation();
                }}, false);
                
                urlInput.addEventListener('mouseup', (e) => {{
                    e.stopPropagation();
                }}, false);
                
                urlInput.addEventListener('paste', (e) => {{
                    e.stopPropagation();
                }}, true);
                
                urlInput.addEventListener('keydown', (e) => {{
                    e.stopPropagation();
                }}, true);
                
                urlInput.addEventListener('keyup', (e) => {{
                    e.stopPropagation();
                }}, true);
            }}
        }});
        
        // Stop events on URL controls from bubbling to panels
        document.querySelectorAll('.url-control').forEach(urlControl => {{
            ['click', 'mousedown', 'mouseup'].forEach(eventType => {{
                urlControl.addEventListener(eventType, (e) => {{
                    const target = e.target;
                    if (target === urlControl || 
                        target === urlControl.querySelector('label') ||
                        (target.tagName && target.tagName.toLowerCase() === 'label')) {{
                        e.stopPropagation();
                    }}
                }}, false);
            }});
        }});
        
        // Update URL inputs when iframes load
        function updateUrlInputs() {{
            frames.forEach((frame, index) => {{
                const urlInput = document.getElementById(`url-input-${{index}}`);
                const iframeId = `iframe${{index}}`;
                if (urlInput && originalIframeUrls[iframeId]) {{
                    urlInput.value = originalIframeUrls[iframeId];
                    urlInput.readOnly = false;
                    urlInput.disabled = false;
                }}
            }});
        }}
        
        // Extract initial URLs from iframes to populate inputs
        setTimeout(() => {{
            try {{
                updateUrlInputs();
            }} catch (error) {{
                console.error('Error setting initial URLs:', error);
            }}
        }}, 500);
        
        // Start loading iframes sequentially when page loads
        window.addEventListener('DOMContentLoaded', () => {{
            setTimeout(() => {{
                loadNextIframe();
            }}, 100);
        }});
    </script>
</body>
</html>"""
    
    # Write to output file
    with open(output_path, 'w') as f:
        f.write(html_content)
    
    print(f"Overlay webpage created: {os.path.abspath(output_path)}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description='Create a webpage with 2 or 4 iframes from a log file containing URLs.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    create_insarmaps_framepage.py
    create_insarmaps_framepage.py insarmaps.log
    create_insarmaps_framepage.py /path/to/insarmaps.log --outfile combined.html
    create_insarmaps_framepage.py insarmaps.log --zoom 12.5
    create_insarmaps_framepage.py insarmaps.log --outdir /path/to/output --outfile combined.html
        """
    )
    
    parser.add_argument('log_file', nargs='?', default='insarmaps.log',
                       help='Path to file containing URLs (default: insarmaps.log)')
    parser.add_argument('--outdir', default=None,
                       help='Output directory (default: current directory)')
    parser.add_argument('--outfile', default='multi_frame_page.html',
                       help='Output HTML file name (default: multi_frame_page.html)')
    parser.add_argument('--zoom', '-z', type=float, default=None,
                       help='Zoom factor to apply to all iframe URLs (e.g., 11.0, 12.5). Only works with URLs in format /start/lat/lon/zoom')
    
    args = parser.parse_args()
    
    # Determine output directory
    out_dir = args.outdir if args.outdir else os.getcwd()
    out_dir = os.path.abspath(out_dir)
    
    # Construct full path to log file (use current directory or absolute path)
    if os.path.isabs(args.log_file):
        log_path = args.log_file
    else:
        log_path = os.path.join(os.getcwd(), args.log_file)
    
    # Read URLs from insarmaps.log
    try:
        urls = read_insarmaps_log(log_path)
        num_urls = len(urls)
        print(f"Found {num_urls} URLs in {log_path}")
        
        # Extract labels from all URLs
        labels = [get_label_from_url(url) for url in urls]
        
        # Create overlay.html with all frames (works for any number of URLs)
        overlay_path = os.path.join(out_dir, 'overlay.html')
        try:
            create_overlay_html(urls, labels, overlay_path, zoom_factor=args.zoom)
        except Exception as e:
            print(f"Warning: Could not create overlay.html: {e}")
        
        # Count entries and call appropriate function
        if num_urls == 2:
            # Create multiple layout files for 2 frames
            base_path = os.path.splitext(args.outfile)[0] if args.outfile else 'multi_frame_page'
            
            # Create matrix.html (2 columns)
            matrix_path = os.path.join(out_dir, 'matrix.html')
            create_webpage_2frames(urls[:2], labels[:2], matrix_path, zoom_factor=args.zoom, layout='matrix')
            
            # Create column.html (2 rows)
            column_path = os.path.join(out_dir, 'column.html')
            create_webpage_2frames(urls[:2], labels[:2], column_path, zoom_factor=args.zoom, layout='column')
            
            # Create row.html (same as matrix - 2 columns)
            row_path = os.path.join(out_dir, 'row.html')
            create_webpage_2frames(urls[:2], labels[:2], row_path, zoom_factor=args.zoom, layout='row')
            
            print(f"Created 4 layout files: overlay.html, matrix.html, column.html, row.html")
            
        elif num_urls >= 4:
            # Create multiple layout files for 4 frames
            base_path = os.path.splitext(args.outfile)[0] if args.outfile else 'multi_frame_page'
            
            # Create matrix.html (2x2 grid)
            matrix_path = os.path.join(out_dir, 'matrix.html')
            create_webpage_4frames(urls[:4], labels[:4], matrix_path, zoom_factor=args.zoom, layout='matrix')
            
            # Create column.html (4 rows)
            column_path = os.path.join(out_dir, 'column.html')
            create_webpage_4frames(urls[:4], labels[:4], column_path, zoom_factor=args.zoom, layout='column')
            
            print(f"Created 3 layout files: overlay.html, matrix.html, column.html")
        else:
            # Invalid number of entries for 2/4 frame layouts, but overlay.html was created
            print(f"Note: Found {num_urls} URLs. Need exactly 2 or at least 4 URLs for matrix/column layouts.")
            print(f"Created overlay.html with all {num_urls} frames.")
            return 0
    except Exception as e:
        import traceback
        print(f"Error creating webpage: {e}")
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())
