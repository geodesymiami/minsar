"""Lat/lon extraction from Insarmaps/SARvey CSV; column names match hdfeos5_or_csv_2json_mbtiles.py."""
import csv
import math
from statistics import mean

# Same order as insarmaps_scripts/hdfeos5_or_csv_2json_mbtiles.py read_from_csv_file
LAT_CANDIDATES = ["Y_geocorr", "Latitude", "Y", "ycoord"]
LON_CANDIDATES = ["X_geocorr", "Longitude", "X", "xcoord"]


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
        colmap = {name.strip(): name for name in reader.fieldnames}
        lat_col = next((colmap[c] for c in LAT_CANDIDATES if c in colmap), None)
        lon_col = next((colmap[c] for c in LON_CANDIDATES if c in colmap), None)
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
