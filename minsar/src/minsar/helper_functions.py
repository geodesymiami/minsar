import os
import glob
import h5py
import argparse
import datetime
import numpy as np

from pyproj import Transformer, CRS


def normalize_meta_value(value):
    """Normalize metadata values read from HDF5/netCDF objects.

    The function converts bytes to UTF-8 strings, NumPy scalar types to Python
    scalars, and collapses singleton lists/arrays where appropriate. For
    multi-element arrays or sequences it recursively normalizes members.

    Args:
        value: A value read from file attributes or datasets (bytes, numpy
            types, lists, tuples, numpy arrays, or Python scalars).

    Returns:
        A Python-native value suitable for use as metadata (str, int, float,
        bool, list, or dict-like nested structures). Singleton lists/arrays
        containing a single scalar are collapsed to that scalar.

    Examples:
        >>> normalize_meta_value(b"abc")
        'abc'
        >>> normalize_meta_value(np.array([42]))
        42
    """

    def _collapse_singleton(v):
        # Only collapse if not a scalar
        while isinstance(v, (list, tuple)) and len(v) == 1 and not isinstance(v[0], (float, int, str)):
            v = v[0]
        return v

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return normalize_meta_value(value.item())
        norm_list = [normalize_meta_value(item) for item in value.tolist()]
        return _collapse_singleton(norm_list)
    if isinstance(value, (list, tuple)):
        # If the list/tuple contains only one scalar, return the scalar
        if len(value) == 1 and isinstance(value[0], (float, int, str)):
            return value[0]
        norm_list = [normalize_meta_value(item) for item in value]
        return _collapse_singleton(norm_list)
    return value


def merge_metadata(metadata: list[argparse.Namespace | dict]) -> dict:
    """Merge a list of metadata mappings and return shared keys.

    This function accepts a list of mappings (either plain dictionaries or
    `argparse.Namespace` objects). It computes the intersection of keys
    present in all input dictionaries and returns a new dictionary that
    contains only those keys whose values are identical across all inputs.

    Special handling: if a value is a comma-separated string it is compared
    as a set of trimmed parts (so ordering differences do not prevent a
    match).

    Args:
        metadata: List of metadata items. Each item may be a `dict` or an
            `argparse.Namespace` (namespaces are converted to dicts via
            `vars()`).

    Returns:
        dict: A dictionary of shared metadata keys and their common values.

    Example:
        >>> merge_metadata([{'A':1,'B':2}, {'A':1,'B':3}])
        {'A': 1}
    """

    def _as_set(val):
        if isinstance(val, str) and ',' in val:
            return set(s.strip() for s in val.split(','))
        return val

    # Convert Namespace to dict if needed
    dicts = [vars(m) if isinstance(m, argparse.Namespace) else m for m in metadata]
    shared_keys = set(dicts[0]).intersection(*dicts[1:])
    shared = {}
    for k in shared_keys:
        v0 = dicts[0][k]
        if all(_as_set(d[k]) == _as_set(v0) for d in dicts[1:]):
            shared[k] = v0

    return shared


def extract_identification_metadata(opera):
    """Extract identification metadata from an opened HDF5/netCDF file.

    The function attempts to locate an "identification" group in either a
    netCDF4-style object (with `.groups` and `.variables`) or an `h5py`
    file-like object (with `.get` and `.attrs`). All attribute/dataset
    values are normalized via :func:`normalize_meta_value`.

    Args:
        opera: Opened file-like object (netCDF4 Dataset or h5py File/Group).

    Returns:
        dict: A mapping of identification variable/attribute names to
        normalized Python values. Returns an empty dict if no
        identification group is found.
    """

    # netCDF4
    identification_group = None
    if hasattr(opera, "groups") and hasattr(opera.groups, "get"):
        identification_group = opera.groups.get("identification")
    # h5py
    elif hasattr(opera, "get"):
        identification_group = opera.get("identification")

    identification_variables = {}

    if identification_group is None:
        return identification_variables

    # netCDF4 variables
    if hasattr(identification_group, "variables"):
        for var_name, var_obj in identification_group.variables.items():
            identification_variables[var_name] = normalize_meta_value(var_obj[...])

        if hasattr(identification_group, "ncattrs"):
            for attr_name in identification_group.ncattrs():
                identification_variables[attr_name] = normalize_meta_value(
                    getattr(identification_group, attr_name)
                )

    # h5py datasets / attrs
    else:
        if hasattr(identification_group, "attrs"):
            for attr_name, attr_val in identification_group.attrs.items():
                identification_variables[attr_name] = normalize_meta_value(attr_val)

    return identification_variables


def parse_polygon(polygon):
    """
    Parses a polygon string retreive from ASF vertex tool and extracts the latitude and longitude coordinates.

    Args:
        polygon (str): The polygon string in the format "POLYGON((lon1 lat1, lon2 lat2, ...))".

    Returns:
        tuple: A tuple containing the latitude and longitude coordinates as lists.
               The latitude list contains the minimum and maximum latitude values.
               The longitude list contains the minimum and maximum longitude values.
    """
    latitude = []
    longitude = []
    pol = polygon.replace("POLYGON((", "").replace("))", "")

    # Split the string into a list of coordinates
    for word in pol.split(','):
        if (float(word.split(' ')[1])) not in latitude:
            latitude.append(float(word.split(' ')[1]))
        if (float(word.split(' ')[0])) not in longitude:
            longitude.append(float(word.split(' ')[0]))

    longitude = [round(min(longitude), 2), round(max(longitude), 2)]
    latitude = [round(min(latitude), 2), round(max(latitude), 2)]
    region = [longitude[0], longitude[1], latitude[0], latitude[1]]

    return region


def convert_to_coord(x, y, centroid):
    """Convert UTM grid coordinates to longitude/latitude.

    The function computes a UTM CRS from the provided centroid and converts
    meshgrid arrays `x`, `y` from UTM to (lon, lat) using :func:`utm_to_lonlat`.

    Args:
        x: 1-D or 2-D array of UTM easting coordinates (or X grid).
        y: 1-D or 2-D array of UTM northing coordinates (or Y grid).
        centroid: Sequence (lon, lat) used to determine UTM zone and
            hemisphere.

    Returns:
        tuple: (lon, lat) arrays with the same shape as the broadcasted
        `x`/`y` inputs.
    """

    print("Converting utm to lat/lon ...\n")

    xx, yy = np.meshgrid(x, y)
    lon, lat = centroid
    zone = int((lon + 180) // 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    utm_crs = CRS.from_epsg(epsg)
    return utm_to_lonlat(xx, yy, utm_crs)


def utm_to_lonlat(x, y, utm_crs):
    """Transform coordinates from UTM CRS to WGS84 (lon, lat).

    Args:
        x: Array of UTM eastings.
        y: Array of UTM northings.
        utm_crs: pyproj CRS object describing the UTM CRS.

    Returns:
        tuple: Arrays (lon, lat) transformed to EPSG:4326.
    """

    wgs84 = CRS.from_epsg(4326)
    transformer = Transformer.from_crs(utm_crs, wgs84, always_xy=True)
    lon, lat = transformer.transform(x, y)
    return lon, lat


def get_utm_crs_from_bbox(lon, lat):
    """Return a UTM CRS for a point defined by longitude and latitude.

    Args:
        lon: Longitude in degrees.
        lat: Latitude in degrees.

    Returns:
        pyproj.CRS: The EPSG CRS for the appropriate UTM zone/hemisphere.
    """

    zone = int((lon + 180) // 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return CRS.from_epsg(epsg)


def convert_to_utm(longitude, latitude):
    """
    Converts latitude and longitude to UTM coordinates.

    Parameters:
        longitude (array-like): Array of longitude values.
        latitude (array-like): Array of latitude values.

    Returns:
        tuple: Arrays of UTM Eastings (x) and Northings (y).
    """
    """Convert latitude/longitude arrays to UTM Eastings/Northings.

    The function determines a representative UTM zone from the mean
    longitude and chooses EPSG:326## or 327## depending on hemisphere.

    Args:
        longitude: array-like of longitudes (degrees).
        latitude: array-like of latitudes (degrees).

    Returns:
        tuple: Arrays (x, y) in UTM coordinates.
    """

    # Calculate the UTM zone based on the longitude
    utm_zone = int((np.nanmean(longitude) + 180) // 6) + 1

    # Determine the hemisphere based on latitude
    hemisphere = 'north' if np.nanmean(latitude) >= 0 else 'south'

    # Determine the EPSG code based on the UTM zone and hemisphere
    epsg_code = f"326{utm_zone:02d}" if hemisphere == 'north' else f"327{utm_zone:02d}"

    # Create a Transformer object for WGS84 to UTM
    transformer = Transformer.from_crs("epsg:4326", f"epsg:{epsg_code}", always_xy=True)

    # Convert to UTM coordinates (Eastings, Northings)
    x, y = transformer.transform(longitude, latitude)

    return x, y


def get_flight_direction(fname):
    """Extract flight direction from HDF5/HDFEOS file.

    Based on MintPy's info.py approach for reading attributes.

    Parameters:
    -----------
    fname : str
        Path to HDF5/HDFEOS file (.h5 or .he5)

    Returns:
    --------
    str
        Flight direction: 'asc' for ascending or 'desc' for descending
        Returns None if neither ORBIT_DIRECTION nor flight_direction is found

    Notes:
    ------
    - First tries to read ORBIT_DIRECTION attribute
    - Falls back to flight_direction attribute if ORBIT_DIRECTION not found
    - Maps: ASCENDING/A -> 'asc', DESCENDING/D -> 'desc'
    """
    """Determine flight direction ('asc' or 'desc') from HDF5/HDFEOS file.

    The function reads attributes from an HDF5/HE5 file (root-level first,
    then group/dataset attributes) and looks for either `ORBIT_DIRECTION`
    or `flight_direction`. It maps common values to the canonical
    strings `'asc'` and `'desc'`.

    Args:
        fname: Path to an HDF5/HDFEOS file (str or PathLike).

    Returns:
        'asc' | 'desc' | None: The detected flight direction, or `None` if
        no matching attribute was found.
    """

    fname = os.fspath(fname)  # Convert from possible pathlib.Path

    if not os.path.isfile(fname):
        raise FileNotFoundError(f'Input file does not exist: {fname}')

    fext = os.path.splitext(fname)[1].lower()
    if fext not in ['.h5', '.he5']:
        raise ValueError(f'Input file must be HDF5/HDFEOS format (.h5 or .he5): {fname}')

    # Read attributes from file (similar to MintPy's read_attribute)
    # Try root level first, then check groups/datasets if needed
    with h5py.File(fname, 'r') as f:
        # Check root level attributes first
        root_atr = dict(f.attrs)

        # Decode string format (like MintPy does)
        for key, value in root_atr.items():
            try:
                root_atr[key] = value.decode('utf8')
            except:
                root_atr[key] = value

        # Try to find ORBIT_DIRECTION or flight_direction in root attributes first
        if 'ORBIT_DIRECTION' in root_atr or 'flight_direction' in root_atr:
            atr = root_atr
        # If not in root and WIDTH exists, use root attributes
        elif len(root_atr) > 0 and 'WIDTH' in root_atr.keys():
            atr = root_atr
        else:
            # Look for attributes in groups/datasets (HDFEOS structure)
            global atr_list

            def get_hdf5_attrs(name, obj):
                global atr_list
                if len(obj.attrs) > 0:
                    # Prefer attributes with WIDTH, but also collect any with our target attributes
                    if 'WIDTH' in obj.attrs.keys() or 'ORBIT_DIRECTION' in obj.attrs.keys() or 'flight_direction' in obj.attrs.keys():
                        atr_list.append(dict(obj.attrs))

            atr_list = []
            f.visititems(get_hdf5_attrs)

            # Prioritize attributes with ORBIT_DIRECTION or flight_direction
            priority_atr = None
            for a in atr_list:
                if 'ORBIT_DIRECTION' in a or 'flight_direction' in a:
                    priority_atr = a
                    break

            if priority_atr:
                atr = priority_atr
            # Otherwise, use the attrs with most items
            elif atr_list:
                num_list = [len(i) for i in atr_list]
                atr = atr_list[np.argmax(num_list)]
            else:
                # Fall back to root attributes even if empty
                atr = root_atr

        # Decode string format for all attributes
        for key, value in atr.items():
            try:
                atr[key] = value.decode('utf8')
            except:
                atr[key] = value

    # Try ORBIT_DIRECTION first
    orbit_dir = atr.get('ORBIT_DIRECTION', None)
    if orbit_dir:
        orbit_dir = str(orbit_dir).strip().upper()
        if orbit_dir == 'ASCENDING':
            return 'asc'
        elif orbit_dir == 'DESCENDING':
            return 'desc'

    # Fall back to flight_direction
    flight_dir = atr.get('flight_direction', None)
    if flight_dir:
        flight_dir = str(flight_dir).strip().upper()
        if flight_dir in ['A', 'ASCENDING']:
            return 'asc'
        elif flight_dir in ['D', 'DESCENDING']:
            return 'desc'

    # Not found
    return None


def get_he5_files(dir, dataset=None):
    """Collect HE5 files in a directory, grouped by dataset type.

    This utility scans `dir` for `.he5` files and classifies them into
    groups used by downstream processing: geometric (geo), persistent
    scatterer (PS), difference stack (DS), and filtered DS (`filtDS`). The
    function returns the list matching the requested `dataset` kind and a
    representative suffix.

    Args:
        dir (str): Directory to search for `.he5` files.
        dataset (str, optional): One of: "geo", "PS", "DS", "filt*DS",
            "DSfilt*DS", "PSDS", "all". If omitted, behaviour is to
            collect and return the default 'geo' group.

    Returns:
        tuple: (list_of_files, suffix) where `list_of_files` is the list of
        matching files (may be empty) and `suffix` is the suffix string to
        append when constructing related filenames.

    Raises:
        ValueError: If no files matching the requested dataset type are
        found.
    """

    all_files = glob.glob(dir + '/*.he5')

    file_geo = [file for file in all_files if 'DS' not in file and 'PS' not in file]
    file_PS = [file for file in all_files if 'PS' in file]
    file_DS = [file for file in all_files if 'DS' in file and 'filt' not in file]
    file_filtDS = [file for file in all_files if 'DS' in file and 'filt' in file]

    files = []
    suffixes = []
    if dataset == "geo":
        files.append(file_geo)
        suffixes.append("")
    if dataset == "PS":
        files.append(file_PS)
        suffixes.append("_PS")
    if dataset == "DS":
        files.append(file_DS)
        suffixes.append("_DS")
    if dataset == "filt*DS" or dataset == "filtDS":
        files.append(file_filtDS)
        suffixes.append("_filtDS")
    if dataset == "DSfilt*DS" or dataset == "DSfiltDS":
        files.append(file_DS)
        files.append(file_filtDS)
        suffixes.append("_DS")
        suffixes.append("_filtDS")
    if dataset == "PSDS" or dataset == "DSPS":
        files.append(file_PS)
        files.append(file_DS)
        suffixes.append("_PS")
        suffixes.append("_DS")
    if dataset == "all":
        files.append(file_geo)
        files.append(file_PS)
        files.append(file_DS)
        suffixes.append("")
        suffixes.append("_PS")
        suffixes.append("_DS")

    if not any(files):
        raise ValueError(f"USER ERROR: no files {dataset} found.")

    return files[0], suffixes[0]


def get_output_filename(metadata,):
    """Build output filename from OPERA identification metadata."""
    def mget(key, default=None):
        # supports dict metadata and argparse.Namespace(attrs=..., variables=...)
        if isinstance(metadata, dict):
            return metadata.get(key, default)
        if hasattr(metadata, "attrs") and key in metadata.attrs:
            return metadata.attrs.get(key, default)
        if hasattr(metadata, "variables") and key in metadata.variables:
            return metadata.variables.get(key, default)
        if hasattr(metadata, key):
            return getattr(metadata, key)
        return default

    def parse_ymd(value):
        if not value:
            return "00000000"
        s = str(value).strip()
        for fmt in (
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
        ):
            try:
                return datetime.datetime.strptime(s, fmt).strftime("%Y%m%d")
            except ValueError:
                pass
        # fallback for strings like "2017-01-07T04:30:28.815125Z"
        return s[:10].replace("-", "")

    direction = mget("orbit_pass_direction", mget("ORBIT_DIRECTION", None))
    if direction is not None:
        direction = str(direction).strip().upper()

    sat_raw = mget("source_data_satellite_names", mget("mission", mget("PLATFORM", None)))
    sat_str = str(sat_raw).upper().replace(" ", "") if sat_raw is not None else ""

    if "S1" in sat_str or 'SEN' in sat_str:
        sat = "S1"
    else:
        sat = str(sat_raw).split(",")[0].strip() if sat_raw else "OPERA"

    relorb = f"{int(mget('relative_orbit', mget('track_number', 0))):03d}"
    relorb2 = f"{int(mget('relative_orbit_second', mget('frame_id', 0))):05d}"

    method_str = str(mget("post_processing_method", "opera")).lower()

    date1 = parse_ymd(
        mget("first_date", mget("reference_datetime", mget("reference_zero_doppler_start_time")))
    )
    date2 = parse_ymd(
        mget("last_date", mget("secondary_datetime", mget("secondary_zero_doppler_start_time")))
    )

    update_flag = str(mget("cfg.mintpy.save.hdfEos5.update", "")).lower() == "yes"
    if update_flag:
        date2 = "XXXXXXXX"

    direction_val = direction or mget("orbit_pass_direction", mget('orbit_direction', None))
    if direction_val:
        direction_upper = str(direction_val).strip().upper()
        if "ASC" in direction_upper:
            direction_val = "asc"
        elif "DES" in direction_upper:
            direction_val = "desc"
        else:
            direction_val = str(direction_val).strip().lower()

    if direction_val:
        out_name = f"{sat}_{direction_val}_{relorb}_{relorb2}_{method_str}_{date1}_{date2}.he5"
    else:
        out_name = f"{sat}_{relorb}_{relorb2}_{method_str}_{date1}_{date2}.he5"

    fbase, fext = os.path.splitext(out_name)
    polygon_str = mget("data_footprint", mget("bounding_polygon", None))

    if polygon_str:
        try:
            sub = corners_string(polygon_str)
            out_name = f"{fbase}_{sub}{fext}"
        except Exception:
            pass
    return out_name


def corners_string(string) -> str:
    """
    Return corners from the polygon as S0081W09112_S0081W09130_S0100W09130_S0100W09112
    """

    def fmt_lat(lat: float) -> str:
        val = int(round(abs(lat) * 100))              # keep 2 decimals
        return f"{'N' if lat >= 0 else 'S'}{val:04d}" # 2 deg digits + 2 decimals

    def fmt_lon(lon: float) -> str:
        val = int(round(abs(lon) * 100))
        return f"{'E' if lon >= 0 else 'W'}{val:05d}" # 3 deg digits + 2 decimals

    if 'POLYGON' in string:
        lon_min, lon_max, lat_min, lat_max = parse_polygon(string)
    else:
        lat_min, lat_max, lon_min, lon_max = min(string[1]), max(string[1]), min(string[0]), max(string[0])
    # CCW starting at SW: SW, NW, NE, SE
    corners = [
        (lat_min, lon_min),  # SW
        (lat_max, lon_min),  # NW
        (lat_max, lon_max),  # NE
        (lat_min, lon_max),  # SE
    ]
    parts = [f"{fmt_lat(lat)}{fmt_lon(lon)}" for (lat, lon) in corners]
    return "_".join(parts)