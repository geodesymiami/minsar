"""Lat/lon extraction from Insarmaps/SARvey CSV; column names match insarmaps_ingester.py."""
import csv
import math
from statistics import mean

# Same order as insarmaps_scripts/insarmaps_ingester.py (case-insensitive match)
LAT_CANDIDATES = ["latitude_corrected", "Y_geocorr", "Latitude", "latitude", "Y", "ycoord"]
LON_CANDIDATES = ["longitude_corrected", "X_geocorr", "Longitude", "longitude", "X", "xcoord"]


def _parse_float_cell(val):
    if val is None or (isinstance(val, str) and not val.strip()):
        return None
    try:
        x = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(x):
        return None
    return x


def _detect_lat_lon_fieldnames(fieldnames):
    """Return (lat_col, lon_col) using LAT/LON_CANDIDATES (case-insensitive)."""
    lower_map = {name.strip().lower(): name.strip() for name in fieldnames if name is not None}
    lat_col = next((lower_map[c.lower()] for c in LAT_CANDIDATES if c.lower() in lower_map), None)
    lon_col = next((lower_map[c.lower()] for c in LON_CANDIDATES if c.lower() in lower_map), None)
    return lat_col, lon_col


def load_csv_lat_lon_arrays(csv_path):
    """
    Return parallel lists of latitude and longitude (finite floats only).

    Raises
    ------
    ValueError
        If no recognized lat/lon columns are found or no valid points.
    """
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        lat_col, lon_col = _detect_lat_lon_fieldnames(reader.fieldnames)
        if lat_col is None or lon_col is None:
            raise ValueError(
                "Could not find latitude/longitude columns. Supported names: "
                f"{LAT_CANDIDATES} and {LON_CANDIDATES}."
            )
        lats, lons = [], []
        for row in reader:
            la = _parse_float_cell(row.get(lat_col))
            lo = _parse_float_cell(row.get(lon_col))
            if la is not None and lo is not None:
                lats.append(la)
                lons.append(lo)
    if not lats:
        raise ValueError("No valid lat/lon rows in CSV")
    return lats, lons


def csv_mean_lat_lon(csv_path):
    """Mean latitude and longitude as floats."""
    lats, lons = load_csv_lat_lon_arrays(csv_path)
    return mean(lats), mean(lons)


def csv_lat_lon_spans(csv_path):
    """Latitude and longitude span (max - min) in degrees."""
    lats, lons = load_csv_lat_lon_arrays(csv_path)
    return max(lats) - min(lats), max(lons) - min(lons)


def csv_lat_lon_bounds(csv_path):
    """Bounding box (min_lat, max_lat, min_lon, max_lon) in degrees."""
    lats, lons = load_csv_lat_lon_arrays(csv_path)
    return min(lats), max(lats), min(lons), max(lons)


# Typical browser window, from `open_insarmaps.py --print-bounds` -> --bounds 304 55 1452 947
# (left top right bottom), i.e. 1148 x 892 px. The tab/address bars take ~90 px of the height.
TYPICAL_WINDOW_BOUNDS = (304, 55, 1452, 947)
BROWSER_CHROME_HEIGHT = 90
VIEWPORT_WIDTH = TYPICAL_WINDOW_BOUNDS[2] - TYPICAL_WINDOW_BOUNDS[0]
VIEWPORT_HEIGHT = TYPICAL_WINDOW_BOUNDS[3] - TYPICAL_WINDOW_BOUNDS[1] - BROWSER_CHROME_HEIGHT
VIEWPORT_FILL = 0.75      # fraction of the map view the data should cover (limiting dimension)
WORLD_SIZE_ZOOM0 = 512.0  # Mapbox GL: the world is 512 * 2**zoom CSS pixels wide
MIN_ZOOM = 3.0
MAX_ZOOM = 18.0
DEFAULT_ZOOM = 11.0


def _mercator_y(lat):
    """Web Mercator y as a fraction of the world size (0 at the equator, grows northward)."""
    lat = max(-85.0, min(85.0, lat))
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / (2 * math.pi)


def zoom_for_bounds(
    min_lat, max_lat, min_lon, max_lon,
    viewport_fill=VIEWPORT_FILL, width=VIEWPORT_WIDTH, height=VIEWPORT_HEIGHT,
    min_zoom=MIN_ZOOM, max_zoom=MAX_ZOOM,
):
    """
    Insarmaps (Mapbox GL) zoom at which the bounding box covers `viewport_fill` of a
    width x height px map view, along whichever of width/height is limiting.

    Returns the mid zoom if the box is degenerate; otherwise clamped to [min_zoom, max_zoom].
    """
    x_frac = abs(max_lon - min_lon) / 360.0
    y_frac = abs(_mercator_y(max_lat) - _mercator_y(min_lat))
    if viewport_fill <= 0 or (x_frac <= 0 and y_frac <= 0):
        return (min_zoom + max_zoom) / 2.0
    zooms = []
    if x_frac > 0:
        zooms.append(math.log2(viewport_fill * width / (WORLD_SIZE_ZOOM0 * x_frac)))
    if y_frac > 0:
        zooms.append(math.log2(viewport_fill * height / (WORLD_SIZE_ZOOM0 * y_frac)))
    return max(min_zoom, min(min(zooms), max_zoom))


def wkt_polygon_bounds(wkt):
    """(min_lat, max_lat, min_lon, max_lon) of a 'POLYGON((lon lat,lon lat,...))' string, or None."""
    if not isinstance(wkt, str):
        return None
    start, end = wkt.find("(("), wkt.find("))")
    if not wkt.strip().upper().startswith("POLYGON") or start < 0 or end < 0:
        return None
    lats, lons = [], []
    for pair in wkt[start + 2:end].replace("(", "").replace(")", "").split(","):
        parts = pair.split()
        if len(parts) >= 2:
            try:
                lon, lat = float(parts[0]), float(parts[1])
            except ValueError:
                return None
            lons.append(lon)
            lats.append(lat)
    if not lats:
        return None
    return min(lats), max(lats), min(lons), max(lons)
