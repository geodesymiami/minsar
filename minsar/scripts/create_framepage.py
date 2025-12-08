#!/usr/bin/env python3
"""
Create a webpage with 4 iframes in a 2x2 grid layout.

Layout:
- Top Left: FILE1
- Top Right: FILE2
- Bottom Left: vert
- Bottom Right: horz
"""
import os
import re
import argparse
from pathlib import Path


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


def create_webpage(file1_path, file2_path, vert_path, horz_path, output_path='page.html', zoom_factor=None):
    """Create a webpage with 4 iframes in a 2x2 grid."""
    
    # Extract iframe sources
    try:
        src_file1 = extract_iframe_src(file1_path, zoom_factor=zoom_factor)
        src_file2 = extract_iframe_src(file2_path, zoom_factor=zoom_factor)
        src_vert = extract_iframe_src(vert_path, zoom_factor=zoom_factor)
        src_horz = extract_iframe_src(horz_path, zoom_factor=zoom_factor)
    except Exception as e:
        import traceback
        print(f"Error extracting iframe sources: {e}")
        traceback.print_exc()
        return None
    
    # Create HTML content with JavaScript to ensure iframes are fully loaded and interactive
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>InSAR Maps - 4 Panel View</title>
    <style>
        body {{
            margin: 0;
            padding: 10px;
            font-family: Arial, sans-serif;
            background-color: #f5f5f5;
        }}
        .container {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            grid-template-rows: 1fr 1fr;
            gap: 10px;
            height: calc(100vh - 40px);
            max-width: 100%;
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
        }}
        .panel iframe {{
            width: 100%;
            height: calc(100% - 36px);
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
        .loading {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: #666;
            font-size: 14px;
        }}
        .zoom-control {{
            position: fixed;
            top: 10px;
            right: 10px;
            background-color: white;
            padding: 15px 20px;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            z-index: 1000;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .zoom-control label {{
            font-weight: bold;
            color: #333;
            font-size: 14px;
        }}
        .zoom-control input {{
            width: 80px;
            padding: 6px 10px;
            border: 2px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
        }}
        .zoom-control input:focus {{
            outline: none;
            border-color: #4a90e2;
        }}
        .zoom-control button {{
            padding: 6px 15px;
            background-color: #4a90e2;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            font-weight: bold;
        }}
        .zoom-control button:hover {{
            background-color: #357abd;
        }}
    </style>
</head>
<body>
    <div class="zoom-control">
        <label for="zoom-input">Zoom:</label>
        <input type="number" id="zoom-input" step="0.1" min="1" max="20" placeholder="11.0">
        <button id="zoom-apply-btn">Apply</button>
    </div>
    <div class="container">
        <div class="panel panel-top-left" id="panel1">
            <div class="panel-header">FILE1</div>
            <iframe id="iframe1" title="FILE1" allowfullscreen></iframe>
        </div>
        <div class="panel panel-top-right" id="panel2">
            <div class="panel-header">FILE2</div>
            <iframe id="iframe2" title="FILE2" allowfullscreen></iframe>
        </div>
        <div class="panel panel-bottom-left" id="panel3">
            <div class="panel-header">Vertical</div>
            <iframe id="iframe3" title="Vertical" allowfullscreen></iframe>
        </div>
        <div class="panel panel-bottom-right" id="panel4">
            <div class="panel-header">Horizontal</div>
            <iframe id="iframe4" title="Horizontal" allowfullscreen></iframe>
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
            {{ id: 'iframe1', panelId: 'panel1', name: 'FILE1' }},
            {{ id: 'iframe2', panelId: 'panel2', name: 'FILE2' }},
            {{ id: 'iframe3', panelId: 'panel3', name: 'Vertical' }},
            {{ id: 'iframe4', panelId: 'panel4', name: 'Horizontal' }}
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
                document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
                panel.classList.add('active');
                iframe.focus();
                try {{
                    iframe.contentWindow.focus();
                }} catch (e) {{
                    // Cross-origin - ignore
                }}
            }});
        }}
        
        // Store original iframe URLs for sequential loading
        const originalIframeUrls = {{
            'iframe1': '{src_file1}',
            'iframe2': '{src_file2}',
            'iframe3': '{src_vert}',
            'iframe4': '{src_horz}'
        }};
        
        // Store current iframe URLs (will be modified by zoom)
        const iframeUrls = {{...originalIframeUrls}};
        
        // Function to update zoom in a URL
        function updateZoomInUrl(url, newZoom) {{
            try {{
                const urlObj = new URL(url);
                const pathParts = urlObj.pathname.split('/').filter(p => p);
                
                // Check if URL has format /start/{{lat}}/{{lon}}/{{zoom}}
                if (pathParts.length >= 4 && pathParts[0] === 'start') {{
                    // Replace zoom (index 3)
                    pathParts[3] = newZoom.toString();
                    urlObj.pathname = '/' + pathParts.join('/');
                    
                    // Preserve existing query parameters (except cache-busting ones)
                    const params = new URLSearchParams(urlObj.search);
                    params.delete('_nocache');
                    params.delete('_t');
                    params.set('hideAttributes', 'true');
                    urlObj.search = params.toString();
                    
                    return urlObj.toString();
                }}
            }} catch (e) {{
                console.error('Error updating zoom in URL:', e, url);
            }}
            return url; // Return original if can't parse
        }}
        
        // Function to apply zoom to all iframes
        function applyZoomToAllFrames(zoomValue) {{
            if (!zoomValue || isNaN(zoomValue) || zoomValue < 1 || zoomValue > 20) {{
                alert('Please enter a valid zoom value between 1 and 20');
                return;
            }}
            
            console.log(`Applying zoom ${{zoomValue}} to all iframes`);
            
            // Update URLs for all iframes
            const iframeIds = ['iframe1', 'iframe2', 'iframe3', 'iframe4'];
            
            iframeIds.forEach((iframeId, index) => {{
                const iframe = document.getElementById(iframeId);
                if (iframe) {{
                    // Get original URL
                    const originalUrl = originalIframeUrls[iframeId];
                    
                    // Update zoom in URL (this preserves query params and adds hideAttributes)
                    let newUrl = updateZoomInUrl(originalUrl, zoomValue);
                    
                    // Add cache-busting to force reload
                    const separator = newUrl.includes('?') ? '&' : '?';
                    newUrl = newUrl + separator + '_nocache=' + Date.now() + '_' + index;
                    
                    console.log(`Updating ${{iframeId}}: ${{newUrl}}`);
                    
                    // Update original URL so future zoom changes work correctly
                    // Remove cache-busting to store clean URL
                    const cleanNewUrl = newUrl.split('&_nocache')[0].split('?_nocache')[0];
                    originalIframeUrls[iframeId] = cleanNewUrl;
                    
                    // Update iframe src - this will trigger a reload
                    iframe.src = newUrl;
                    
                    // Reset load state so it can reload properly
                    const state = iframeStates[iframeId];
                    if (state) {{
                        state.loaded = false;
                        state.processed = false;
                    }}
                }}
            }});
        }}
        
        // Set up zoom control
        const zoomInput = document.getElementById('zoom-input');
        const zoomApplyBtn = document.getElementById('zoom-apply-btn');
        
        // Extract initial zoom from first iframe URL to populate input
        try {{
            const firstUrl = originalIframeUrls['iframe1'];
            const urlObj = new URL(firstUrl);
            const pathParts = urlObj.pathname.split('/').filter(p => p);
            if (pathParts.length >= 4 && pathParts[0] === 'start') {{
                zoomInput.value = pathParts[3];
            }}
        }} catch (e) {{
            // Ignore if can't parse
        }}
        
        // Apply zoom on button click
        zoomApplyBtn.addEventListener('click', () => {{
            const zoomValue = parseFloat(zoomInput.value);
            applyZoomToAllFrames(zoomValue);
        }});
        
        // Apply zoom on Enter key
        zoomInput.addEventListener('keypress', (e) => {{
            if (e.key === 'Enter') {{
                const zoomValue = parseFloat(zoomInput.value);
                applyZoomToAllFrames(zoomValue);
            }}
        }});
        
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


def main():
    parser = argparse.ArgumentParser(
        description='Create a webpage with 4 iframes in a 2x2 grid layout.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    create_webpage.py
    create_webpage.py --file1 iframe_FILE1.html --file2 iframe_FILE2.html --vert iframe_vert.html --horz iframe_horz.html
    create_webpage.py --dir /path/to/directory --output combined.html
    create_webpage.py --zoom 12.5
    create_webpage.py --file1 iframe_FILE1.html --zoom 11.0 --output page.html
        """
    )
    
    parser.add_argument('--file1', default='iframe_FILE1.html',
                       help='Path to FILE1 iframe HTML file or direct URL (default: iframe_FILE1.html)')
    parser.add_argument('--file2', default='iframe_FILE2.html',
                       help='Path to FILE2 iframe HTML file or direct URL (default: iframe_FILE2.html)')
    parser.add_argument('--vert', default='iframe_vert.html',
                       help='Path to vertical iframe HTML file or direct URL (default: iframe_vert.html)')
    parser.add_argument('--horz', default='iframe_horz.html',
                       help='Path to horizontal iframe HTML file or direct URL (default: iframe_horz.html)')
    parser.add_argument('--dir', default=None,
                       help='Directory containing the iframe files (default: current directory)')
    parser.add_argument('--output', '-o', default='page.html',
                       help='Output HTML file name (default: page.html)')
    parser.add_argument('--zoom', '-z', type=float, default=None,
                       help='Zoom factor to apply to all iframe URLs (e.g., 11.0, 12.5). Only works with URLs in format /start/lat/lon/zoom')
    
    args = parser.parse_args()
    
    # Determine base directory
    base_dir = args.dir if args.dir else os.getcwd()
    base_dir = os.path.abspath(base_dir)
    
    # Construct full paths (only if they're not URLs)
    def get_path(arg_value):
        if arg_value.startswith('http://') or arg_value.startswith('https://'):
            return arg_value
        if os.path.isabs(arg_value):
            return arg_value
        return os.path.join(base_dir, arg_value)
    
    file1_path = get_path(args.file1)
    file2_path = get_path(args.file2)
    vert_path = get_path(args.vert)
    horz_path = get_path(args.horz)
    output_path = os.path.join(base_dir, args.output) if not os.path.isabs(args.output) else args.output
    
    # Create the webpage
    try:
        create_webpage(file1_path, file2_path, vert_path, horz_path, output_path, zoom_factor=args.zoom)
    except Exception as e:
        print(f"Error creating webpage: {e}")
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())
