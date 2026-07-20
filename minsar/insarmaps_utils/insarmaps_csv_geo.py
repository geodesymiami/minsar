"""Lat/lon extraction from Insarmaps/SARvey CSV; column names match hdfeos5_or_csv_2json_mbtiles.py."""
import csv
import math
from statistics import mean

# Same order as insarmaps_scripts/hdfeos5_or_csv_2json_mbtiles.py (case-insensitive match)
LAT_CANDIDATES = ["Y_geocorr", "Latitude", "latitude", "Y", "ycoord"]
LON_CANDIDATES = ["X_geocorr", "Longitude", "longitude", "X", "xcoord"]


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
