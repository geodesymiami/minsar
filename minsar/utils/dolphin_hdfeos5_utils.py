"""Library helpers for Dolphin/sweets GeoTIFF stacks → MintPy HDF-EOS5.

Used by ``dolphin2hdfeos5.py``. Independent of
``minsar.src.minsar.cli.create_dolphin_files``.
"""

from __future__ import annotations

import glob
import importlib.util
import inspect
import os
import re
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import xy as rasterio_xy
from mintpy.utils import writefile

from minsar.src.minsar.helper_functions import utm_to_lonlat

DATASET_NAME_RE = re.compile(
    r"(?P<project>.+?)(?P<sat>Sen|S1|TSX|ALOS2|CSK|RS2|ENV)(?P<pass>[AD])(?P<orbit>\d+)$",
    re.IGNORECASE,
)
SAT_TO_MISSION = {
    "SEN": "S1",
    "S1": "S1",
    "TSX": "TSX",
    "ALOS2": "ALOS2",
    "CSK": "CSK",
    "RS2": "RS2",
    "ENV": "ENV",
}
SKIP_DIR_NAMES = {
    "timeseries",
    "dolphin",
    "mintpy",
    "miaplpy",
    "geometry",
    "gslcs",
    "data",
    "JSON",
    "outputs",
    "interferograms",
    "unwrapped",
}
S1_WAVELENGTH = 0.05546576


def _iso_date(ymd):
    """Convert YYYYMMDD to YYYY-MM-DD."""
    s = str(ymd).strip()
    if isinstance(ymd, (bytes, np.bytes_)):
        s = ymd.decode("utf-8").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10]


def _load_save_hdfeos5():
    """Prefer MinSAR additions/mintpy save_hdfeos5 over upstream MintPy."""
    minsar_home = os.environ.get("MINSAR_HOME", "")
    if minsar_home:
        he5_path = Path(minsar_home) / "additions" / "mintpy" / "save_hdfeos5.py"
        if he5_path.is_file():
            spec = importlib.util.spec_from_file_location("minsar_save_hdfeos5", he5_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    import mintpy.save_hdfeos5 as mod
    return mod


def he5_output_filename(metadata, update_mode=True, subset_mode=True):
    """MintPy/MiaplPy HE5 name via save_hdfeos5.get_output_filename."""
    mod = _load_save_hdfeos5()
    kwargs = {"update_mode": update_mode, "subset_mode": subset_mode}
    if "template" in inspect.signature(mod.get_output_filename).parameters:
        return mod.get_output_filename(metadata, {}, **kwargs)
    return mod.get_output_filename(metadata, **kwargs)


def parse_dataset_name(name: str) -> dict:
    """Parse MinSAR dataset name like HawaiiPunaSweetsSenA124."""
    name = str(name).strip()
    match = DATASET_NAME_RE.search(name)
    if not match:
        return {"PROJECT_NAME": name}
    sat = match.group("sat").upper()
    if sat == "SEN":
        sat_key = "SEN"
        platform = "Sen"
    else:
        sat_key = sat
        platform = sat
    pass_code = match.group("pass").upper()
    orbit = int(match.group("orbit"))
    orbit_direction = "ASCENDING" if pass_code == "A" else "DESCENDING"
    return {
        "PROJECT_NAME": name,
        "mission": SAT_TO_MISSION.get(sat_key, sat_key),
        "PLATFORM": platform,
        "ORBIT_DIRECTION": orbit_direction,
        "flight_direction": pass_code,
        "relative_orbit": orbit,
    }


def infer_dataset_name(run_dir: Path) -> str:
    """Walk parents to the MinSAR dataset directory name."""
    for parent in [run_dir, *run_dir.parents]:
        if parent.name in SKIP_DIR_NAMES or not parent.name:
            continue
        if DATASET_NAME_RE.search(parent.name):
            return parent.name
    return run_dir.name if run_dir.name not in SKIP_DIR_NAMES else run_dir.resolve().name


def resolve_run_paths(input_path: Path) -> tuple[Path, Path, Path]:
    """Return (dataset_dir, dolphin_dir, timeseries_dir).

    ``input_path`` is typically ``dolphin`` or an absolute ``.../dolphin`` dir.
    Dataset name (HawaiiPunaSweetsSenA124) is taken from the parent folder.
    """
    path = input_path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input path does not exist: {path}")
    if path.is_file():
        path = path.parent
    if path.name == "timeseries":
        ts_dir = path
        dolphin_dir = path.parent if path.parent.name == "dolphin" else path.parent
        dataset_dir = dolphin_dir.parent if dolphin_dir.name == "dolphin" else dolphin_dir
        return dataset_dir, dolphin_dir, ts_dir
    if (path / "timeseries").is_dir() and path.name == "dolphin":
        return path.parent, path, path / "timeseries"
    if (path / "dolphin" / "timeseries").is_dir():
        return path, path / "dolphin", path / "dolphin" / "timeseries"
    if (path / "timeseries").is_dir():
        return path, path, path / "timeseries"
    raise FileNotFoundError(
        f"No timeseries/ directory in {path} (pass the dolphin dir, e.g. dolphin2hdfeos5.py dolphin)"
    )


def find_geometry_path(path=None):
    """Return a geometry directory next to ``path`` or a parent."""
    path = Path(path) if path else Path.cwd()
    for candidate in (path / "geometry", path.parent / "geometry", path.parent.parent / "geometry"):
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"No geometry directory found near {path}")


def _read_geotiff(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        return src.read(1)


def _timeseries_tifs(ts_dir: Path) -> tuple[list[Path], list[Path]]:
    pair_files = sorted(
        p for p in ts_dir.iterdir()
        if p.suffix.lower() in {".tif", ".tiff"} and re.fullmatch(r"\d{8}_\d{8}", p.stem)
    )
    date_files = sorted(
        p for p in ts_dir.iterdir()
        if p.suffix.lower() in {".tif", ".tiff"} and re.fullmatch(r"\d{8}", p.stem)
    )
    return pair_files, date_files


def collect_timeseries(ts_dir: Path):
    """Stack Dolphin timeseries GeoTIFFs. Pair names get a zero reference slice."""
    pair_files, date_files = _timeseries_tifs(ts_dir)
    first = date_files or pair_files
    if not first:
        raise FileNotFoundError(f"No YYYYMMDD.tif or YYYYMMDD_YYYYMMDD.tif in {ts_dir}")

    with rasterio.open(first[0]) as src:
        height, width = src.height, src.width
        transform = src.transform
        crs = src.crs
        bounds = src.bounds

    slices = []
    if date_files:
        for path in date_files:
            slices.append((path.stem, _read_geotiff(path)))
    else:
        ref_dates = {p.stem.split("_")[0] for p in pair_files}
        if len(ref_dates) != 1:
            print(
                f"Warning: pair rasters do not share one reference date: {sorted(ref_dates)}"
            )
        ref_date = sorted(ref_dates)[0]
        slices.append((ref_date, np.zeros((height, width), dtype=np.float32)))
        for path in pair_files:
            _ref, sec = path.stem.split("_")
            slices.append((sec, _read_geotiff(path)))

    slices.sort(key=lambda item: item[0])
    date_list = np.array([item[0] for item in slices])
    stack = np.stack([np.asarray(item[1], dtype=np.float32) for item in slices])
    grid = {
        "LENGTH": height,
        "WIDTH": width,
        "transform": transform,
        "crs": crs,
        "bbox": bounds,
    }
    return stack, date_list, grid


def _first_existing_file(candidates) -> Path | None:
    for path in candidates:
        if Path(path).is_file():
            return Path(path)
    return None


def _missing_looked_for(candidates) -> str:
    paths = [str(path) for path in candidates]
    if len(paths) == 1:
        return paths[0]
    return f"{paths[0]} (also looked for: {', '.join(paths[1:])})"


def _geometry_dir(dataset_dir: Path, dolphin_dir: Path, ts_dir: Path) -> Path | None:
    for candidate in (
        dolphin_dir / "geometry",
        ts_dir / "geometry",
        dataset_dir / "geometry",
    ):
        if candidate.is_dir():
            return candidate
    try:
        return Path(find_geometry_path(ts_dir))
    except FileNotFoundError:
        return None


def _temporal_coherence_candidates(dolphin_dir: Path, ts_dir: Path) -> list[Path]:
    ifg_dir = dolphin_dir / "interferograms"
    return [
        ts_dir / "temporal_coherence_average.tif",
        ts_dir / "temporal_coherence.tif",
        ifg_dir / "*temporal*coherence*average*",
        ifg_dir / "temporal_coherence_*.tif",
    ]


def _watermask_candidates(dataset_dir: Path, dolphin_dir: Path, ts_dir: Path) -> list[Path]:
    return [
        ts_dir / "warped_watermask.tif",
        dolphin_dir / "warped_watermask.tif",
        dataset_dir / "watermask.tif",
    ]


def _glob_existing(pattern: Path) -> list[Path]:
    return [Path(path) for path in sorted(glob.glob(str(pattern)))]


def resolve_required_files(dataset_dir: Path, dolphin_dir: Path, ts_dir: Path) -> dict:
    """Locate required Dolphin rasters. Raise FileNotFoundError listing missing paths."""
    missing = []
    files = {}

    pair_files, date_files = _timeseries_tifs(ts_dir)
    ts_files = date_files or pair_files
    if ts_files:
        files["timeseries"] = ts_files
    else:
        missing.append(str(ts_dir / "YYYYMMDD*.tif"))

    temp_files = []
    for candidate in (
        ts_dir / "temporal_coherence_average.tif",
        ts_dir / "temporal_coherence.tif",
    ):
        if candidate.is_file():
            temp_files = [candidate]
            break
    if not temp_files:
        ifg_dir = dolphin_dir / "interferograms"
        temp_files = _glob_existing(ifg_dir / "*temporal*coherence*average*")
        if not temp_files:
            temp_files = _glob_existing(ifg_dir / "temporal_coherence_*.tif")
    if temp_files:
        files["temporal_coherence"] = temp_files
    else:
        missing.append(_missing_looked_for(_temporal_coherence_candidates(dolphin_dir, ts_dir)))

    watermask = _first_existing_file(_watermask_candidates(dataset_dir, dolphin_dir, ts_dir))
    if watermask is not None:
        files["watermask"] = watermask
    else:
        missing.append(_missing_looked_for(_watermask_candidates(dataset_dir, dolphin_dir, ts_dir)))

    conn_path = ts_dir / "conncomp_intersection.tif"
    if conn_path.is_file():
        files["conncomp"] = conn_path
    else:
        missing.append(str(conn_path))

    geom_dir = _geometry_dir(dataset_dir, dolphin_dir, ts_dir)
    geom_expected = geom_dir if geom_dir is not None else dolphin_dir / "geometry"
    files["geometry_dir"] = geom_dir
    for key, name in (
        ("height", "height.tif"),
        ("incidence", "local_incidence_angle.tif"),
        ("los_east", "los_east.tif"),
        ("los_north", "los_north.tif"),
    ):
        path = geom_expected / name
        if path.is_file():
            files[key] = path
        else:
            missing.append(str(path))

    shadow_path = geom_expected / "layover_shadow_mask.tif"
    files["shadow"] = shadow_path if shadow_path.is_file() else None
    avg_paths = _glob_existing(dolphin_dir / "interferograms" / "*.int.cor.tif")
    files["avg_spatial"] = avg_paths or None
    ref_path = ts_dir / "reference_point.txt"
    files["reference_point"] = ref_path if ref_path.is_file() else None

    if missing:
        raise FileNotFoundError("missing required files:\n  " + "\n  ".join(missing))
    return files


def _read_required_tif(path: Path, shape: tuple[int, int]) -> np.ndarray:
    data = _read_geotiff(path)
    if data.shape != tuple(shape):
        raise ValueError(f"{path} has shape {data.shape}, expected {shape}")
    return data.astype(np.float32, copy=False)


def _mean_matching_tif(paths, shape: tuple[int, int], required: bool) -> np.ndarray | None:
    arrays = []
    first_bad = None
    for path in paths:
        data = _read_geotiff(Path(path))
        if data.shape == shape:
            arrays.append(data.astype(np.float32))
        elif first_bad is None:
            first_bad = (Path(path), data.shape)
    if arrays:
        return np.nanmean(np.stack(arrays), axis=0)
    if required:
        if first_bad is not None:
            path, got = first_bad
            raise ValueError(f"{path} has shape {got}, expected {shape}")
        raise ValueError(f"no rasters matched expected shape {shape}")
    return None


def load_quality_layers(
    dataset_dir: Path,
    dolphin_dir: Path,
    ts_dir: Path,
    shape: tuple[int, int],
    files: dict | None = None,
):
    """Load required mask/geometry layers. Missing required files raise FileNotFoundError."""
    if files is None:
        files = resolve_required_files(dataset_dir, dolphin_dir, ts_dir)

    temp_paths = files["temporal_coherence"]
    if len(temp_paths) == 1:
        temp_coh = _read_required_tif(temp_paths[0], shape)
    else:
        temp_coh = _mean_matching_tif(temp_paths, shape, required=True)

    watermask = _read_required_tif(files["watermask"], shape)
    conncomp = _read_required_tif(files["conncomp"], shape)
    height = _read_required_tif(files["height"], shape)
    incidence = _read_required_tif(files["incidence"], shape)
    los_east = _read_required_tif(files["los_east"], shape)
    los_north = _read_required_tif(files["los_north"], shape)
    azimuth = np.rad2deg(np.arctan2(los_east, los_north)).astype(np.float32)

    shadow = None
    if files["shadow"] is not None:
        shadow = same_shape(_read_geotiff(files["shadow"]), shape)
    avg_coh = None
    if files["avg_spatial"]:
        avg_coh = _mean_matching_tif(files["avg_spatial"], shape, required=False)

    return {
        "temporal_coherence": temp_coh,
        "avg_spatial_coherence": avg_coh,
        "watermask": watermask,
        "conncomp": conncomp,
        "shadow": shadow,
        "height": height,
        "incidence": incidence,
        "azimuth": azimuth,
        "geometry_dir": files["geometry_dir"],
        "files": files,
    }


def same_shape(arr, shape):
    if arr is None:
        return None
    if np.asarray(arr).shape != tuple(shape):
        print(f"Warning: skip raster with shape {np.asarray(arr).shape}, expected {shape}")
        return None
    return arr


def build_mask(shape, stack, quality, temp_coh_thresh=0.65) -> np.ndarray:
    mask = np.ones(shape, dtype=bool)
    watermask = quality.get("watermask")
    if watermask is not None and watermask.shape == shape:
        mask &= watermask != 0
    conncomp = quality.get("conncomp")
    if conncomp is not None and conncomp.shape == shape:
        mask &= conncomp != 0
    temp_coh = quality.get("temporal_coherence")
    if temp_coh is not None and temp_coh.shape == shape:
        mask &= np.isfinite(temp_coh) & (temp_coh > temp_coh_thresh)
    if stack.shape[0] > 1:
        mask &= np.isfinite(stack[1])
    else:
        mask &= np.isfinite(stack[0])
    return mask


def read_reference_point(ts_dir: Path, shape: tuple[int, int]) -> tuple[int, int] | None:
    ref_file = ts_dir / "reference_point.txt"
    if not ref_file.is_file():
        return None
    text = ref_file.read_text().strip().replace(" ", "")
    if "," not in text:
        return None
    row_s, col_s = text.split(",", 1)
    row, col = int(float(row_s)), int(float(col_s))
    if not (0 <= row < shape[0] and 0 <= col < shape[1]):
        raise ValueError(
            f"reference_point.txt ({row},{col}) outside grid {shape} in {ref_file}"
        )
    return row, col


def latlon_grids(grid: dict) -> tuple[np.ndarray, np.ndarray]:
    """2D WGS84 lat/lon for each pixel center from the native GeoTIFF CRS."""
    length, width = int(grid["LENGTH"]), int(grid["WIDTH"])
    transform = grid["transform"]
    rows, cols = np.meshgrid(np.arange(length), np.arange(width), indexing="ij")
    xs, ys = rasterio_xy(transform, rows, cols, offset="center")
    # rasterio 1.4+ and pyproj flatten 2-D inputs; restore (length, width)
    xs = np.asarray(xs, dtype=np.float64).reshape(length, width)
    ys = np.asarray(ys, dtype=np.float64).reshape(length, width)
    crs = grid["crs"]
    if crs is None or crs.to_epsg() == 4326 or (crs.is_geographic if hasattr(crs, "is_geographic") else False):
        return ys.astype(np.float32), xs.astype(np.float32)
    lon, lat = utm_to_lonlat(xs, ys, crs)
    return np.asarray(lat, dtype=np.float32).reshape(length, width), np.asarray(lon, dtype=np.float32).reshape(length, width)


def snwe_wkt(south, north, west, east) -> str:
    return (
        f"POLYGON(({west} {south},{west} {north},{east} {north},"
        f"{east} {south},{west} {south}))"
    )


def degree_geotransform(latitude: np.ndarray, longitude: np.ndarray) -> dict:
    """UL-pixel lon/lat and adjacent-pixel steps (MintPy Y_FIRST/X_FIRST)."""
    lat0 = float(latitude[0, 0])
    lon0 = float(longitude[0, 0])
    x_step = float(longitude[0, 1] - longitude[0, 0]) if longitude.shape[1] > 1 else 0.0
    y_step = float(latitude[1, 0] - latitude[0, 0]) if latitude.shape[0] > 1 else 0.0
    return {
        "X_FIRST": str(lon0),
        "Y_FIRST": str(lat0),
        "X_STEP": str(x_step),
        "Y_STEP": str(y_step),
        "X_UNIT": "degrees",
        "Y_UNIT": "degrees",
    }


def corner_attrs(latitude: np.ndarray, longitude: np.ndarray) -> dict:
    """LAT/LON_REF1..4: first-line near/far, last-line near/far."""
    return {
        "LAT_REF1": str(float(latitude[0, 0])),
        "LON_REF1": str(float(longitude[0, 0])),
        "LAT_REF2": str(float(latitude[0, -1])),
        "LON_REF2": str(float(longitude[0, -1])),
        "LAT_REF3": str(float(latitude[-1, 0])),
        "LON_REF3": str(float(longitude[-1, 0])),
        "LAT_REF4": str(float(latitude[-1, -1])),
        "LON_REF4": str(float(longitude[-1, -1])),
    }


def read_dolphin_wavelength(dataset_dir: Path, dolphin_dir: Path, ts_dir: Path) -> float | None:
    for cfg in (
        dolphin_dir / "dolphin_config.yaml",
        ts_dir / "dolphin_config.yaml",
        dataset_dir / "dolphin_config.yaml",
    ):
        if not cfg.is_file():
            continue
        text = cfg.read_text(errors="replace")
        match = re.search(r"^\s*wavelength:\s*([0-9.eE+-]+)", text, re.MULTILINE)
        if match:
            return float(match.group(1))
    return None


def populate_insarmaps_metadata(metadata, date_list, latitude, longitude, ref_row, ref_col):
    """Fill insarmaps-essential UNAVCO attributes without overwriting existing values."""
    dates_str = [
        d.decode("utf-8") if isinstance(d, (bytes, np.bytes_)) else str(d)
        for d in date_list
    ]
    lat_arr = np.asarray(latitude)
    lon_arr = np.asarray(longitude)
    if lat_arr.ndim == 2 and lon_arr.ndim == 2:
        ref_lat, ref_lon = float(lat_arr[ref_row, ref_col]), float(lon_arr[ref_row, ref_col])
    elif lat_arr.ndim == 1 and lon_arr.ndim == 1:
        ref_lat, ref_lon = float(lat_arr[ref_row]), float(lon_arr[ref_col])
    else:
        ref_lat, ref_lon = float(np.nanmean(lat_arr)), float(np.nanmean(lon_arr))

    rel_orbit = metadata.get("relative_orbit", metadata.get("track_number"))
    if rel_orbit is None:
        proj = str(metadata.get("PROJECT_NAME", ""))
        match = DATASET_NAME_RE.search(proj)
        if match:
            rel_orbit = int(match.group("orbit"))
        else:
            match = re.search(r"[ADad](\d+)$", proj)
            if match:
                rel_orbit = int(match.group(1))

    defaults = {
        "processing_type": "LOS_TIMESERIES",
        "first_date": _iso_date(dates_str[0]),
        "last_date": _iso_date(dates_str[-1]),
        "history": date.today().isoformat(),
        "atmos_correct_method": "None",
        "first_frame": 0,
        "last_frame": 0,
        "REF_LAT": ref_lat,
        "REF_LON": ref_lon,
        "look_direction": metadata.get("look_direction") or "R",
        "data_footprint": metadata.get("data_footprint") or metadata.get("scene_footprint") or "",
        "scene_footprint": metadata.get("scene_footprint") or metadata.get("data_footprint") or "",
    }
    if rel_orbit is not None:
        defaults["relative_orbit"] = int(rel_orbit)
    for key, value in defaults.items():
        if key not in metadata or metadata[key] in (None, ""):
            metadata[key] = value
    return metadata


def create_hdfeos_output(
    ts_data: np.ndarray,
    mask: np.ndarray,
    latitude: np.ndarray,
    longitude: np.ndarray,
    date_list: np.ndarray,
    output_path: str,
    temporal_coherence: np.ndarray = None,
    height: np.ndarray = None,
    azimuth: np.ndarray = None,
    incidence: np.ndarray = None,
    slant_range: np.ndarray = None,
    bperp: np.ndarray = None,
    shadow_mask: np.ndarray = None,
    avg_spatial_coherence: np.ndarray = None,
    metadata: dict = None,
):
    """Write a MintPy-style HDF-EOS5 file from Dolphin arrays."""
    if metadata is None:
        metadata = {}
    if not output_path.endswith(".he5"):
        output_path = output_path.replace(".h5", ".he5")

    if metadata:
        length, width = int(metadata["LENGTH"]), int(metadata["WIDTH"])
    else:
        length, width = ts_data.shape[1], ts_data.shape[2]

    if latitude.ndim == 1:
        lat_grid = np.tile(latitude[:, np.newaxis], (1, width))
    else:
        lat_grid = latitude
    if longitude.ndim == 1:
        lon_grid = np.tile(longitude, (length, 1))
    else:
        lon_grid = longitude

    if bperp is None:
        bperp = np.zeros(len(date_list))

    hdfeos_dict = {
        "HDFEOS/GRIDS/timeseries/geometry/latitude": lat_grid.astype("float32"),
        "HDFEOS/GRIDS/timeseries/geometry/longitude": lon_grid.astype("float32"),
        "HDFEOS/GRIDS/timeseries/geometry/shadowMask": (
            np.zeros((length, width), dtype="uint8")
            if shadow_mask is None
            else np.asarray(shadow_mask).astype("uint8")
        ),
        "HDFEOS/GRIDS/timeseries/geometry/height": (
            np.full((length, width), np.nan, dtype="float32")
            if height is None
            else height.astype("float32")
        ),
        "HDFEOS/GRIDS/timeseries/geometry/azimuthAngle": (
            np.full((length, width), np.nan, dtype="float32")
            if azimuth is None
            else azimuth.astype("float32")
        ),
        "HDFEOS/GRIDS/timeseries/geometry/incidenceAngle": (
            np.full((length, width), np.nan, dtype="float32")
            if incidence is None
            else incidence.astype("float32")
        ),
        "HDFEOS/GRIDS/timeseries/geometry/slantRangeDistance": (
            np.full((length, width), np.nan, dtype="float32")
            if slant_range is None
            else slant_range.astype("float32")
        ),
        "HDFEOS/GRIDS/timeseries/observation/bperp": bperp.astype("float32"),
        "HDFEOS/GRIDS/timeseries/observation/date": np.asarray(date_list).astype("S8"),
        "HDFEOS/GRIDS/timeseries/observation/displacement": ts_data.astype("float32"),
        "HDFEOS/GRIDS/timeseries/quality/avgSpatialCoherence": (
            np.full((length, width), np.nan, dtype="float32")
            if avg_spatial_coherence is None
            else np.asarray(avg_spatial_coherence).astype("float32")
        ),
        "HDFEOS/GRIDS/timeseries/quality/mask": mask.astype("bool"),
        "HDFEOS/GRIDS/timeseries/quality/temporalCoherence": (
            np.full((length, width), np.nan, dtype="float32")
            if temporal_coherence is None
            else temporal_coherence.astype("float32")
        ),
    }

    if "vert" in output_path:
        metadata["displacementType"] = "VERTICAL"
    elif "hor" in output_path:
        metadata["displacementType"] = "HORIZONTAL"
    metadata["FILE_TYPE"] = "HDFEOS"
    metadata["FILE_PATH"] = output_path
    metadata["WIDTH"] = str(width)
    metadata["LENGTH"] = str(length)
    if not metadata.get("PROCESSOR"):
        metadata["PROCESSOR"] = "dolphin"
    if not metadata.get("PROJECT_NAME"):
        parent = os.path.dirname(output_path)
        if os.path.basename(parent) in ("timeseries", "mintpy", "miaplpy", "dolphin"):
            metadata["PROJECT_NAME"] = os.path.basename(os.path.dirname(parent))
        else:
            metadata["PROJECT_NAME"] = os.path.basename(parent)
    metadata["REF_DATE"] = str(date_list[0])

    writefile.write(hdfeos_dict, out_file=output_path, metadata=metadata)
    print(f"\n HDFEOS file created: {output_path}")
    return output_path


def build_metadata(
    dataset_dir: Path,
    dolphin_dir: Path,
    ts_dir: Path,
    date_list,
    latitude,
    longitude,
    ref_y,
    ref_x,
) -> dict:
    """Build HE5 metadata from the dataset directory name and dolphin outputs."""
    dataset_name = infer_dataset_name(dataset_dir)
    parsed = parse_dataset_name(dataset_name)
    dates_str = [
        d.decode("utf-8") if isinstance(d, (bytes, np.bytes_)) else str(d)
        for d in date_list
    ]
    first_ymd = dates_str[0]
    last_ymd = dates_str[-1]
    first_iso = f"{first_ymd[0:4]}-{first_ymd[4:6]}-{first_ymd[6:8]}"
    last_iso = f"{last_ymd[0:4]}-{last_ymd[4:6]}-{last_ymd[6:8]}"

    geo = degree_geotransform(latitude, longitude)
    south = float(latitude[-1, 0])
    north = float(latitude[0, 0])
    west = float(longitude[0, 0])
    east = float(longitude[0, -1])
    if south > north:
        south, north = north, south
    if west > east:
        west, east = east, west
    footprint = snwe_wkt(south, north, west, east)

    wavelength = read_dolphin_wavelength(dataset_dir, dolphin_dir, ts_dir) or S1_WAVELENGTH
    relative_orbit = parsed.get("relative_orbit")
    if relative_orbit is None:
        relative_orbit = 0

    orbit_direction = parsed.get("ORBIT_DIRECTION")
    if not orbit_direction:
        raise ValueError(
            f"Cannot determine ORBIT_DIRECTION from dataset name {dataset_name!r} "
            "(expected e.g. HawaiiPunaSenA124)."
        )
    flight = parsed.get("flight_direction")
    if not flight and orbit_direction:
        flight = "A" if str(orbit_direction).upper().startswith("A") else "D"

    mission = parsed.get("mission") or "S1"
    platform = parsed.get("PLATFORM") or ("Sen" if mission == "S1" else mission)
    project_name = parsed.get("PROJECT_NAME") or dataset_name

    ref_lat = float(latitude[ref_y, ref_x])
    ref_lon = float(longitude[ref_y, ref_x])

    metadata = {
        "FILE_TYPE": "HDFEOS",
        "UNIT": "m",
        "PROCESSOR": "dolphin",
        "processing_software": "dolphin",
        "post_processing_method": "dolphin",
        "processing_type": "LOS_TIMESERIES",
        "PROJECT_NAME": project_name,
        "mission": mission,
        "PLATFORM": platform,
        "beam_mode": "IW",
        "beam_swath": 0,
        "relative_orbit": int(relative_orbit),
        "ORBIT_DIRECTION": orbit_direction,
        "flight_direction": flight or "Unknown",
        "look_direction": "R",
        "polarization": "VV",
        "WAVELENGTH": wavelength,
        "wavelength": wavelength,
        "LENGTH": str(latitude.shape[0]),
        "WIDTH": str(latitude.shape[1]),
        "REF_DATE": first_ymd,
        "START_DATE": first_ymd,
        "END_DATE": last_ymd,
        "first_date": first_iso,
        "last_date": last_iso,
        "REF_Y": str(ref_y),
        "REF_X": str(ref_x),
        "REF_LAT": ref_lat,
        "REF_LON": ref_lon,
        "data_footprint": footprint,
        "scene_footprint": footprint,
        "history": date.today().isoformat(),
        "atmos_correct_method": "None",
        "unwrap_method": "snaphu",
        "first_frame": 0,
        "last_frame": 0,
        "prf": 0,
        **geo,
        **corner_attrs(latitude, longitude),
    }
    populate_insarmaps_metadata(metadata, dates_str, latitude, longitude, ref_y, ref_x)
    metadata["PROJECT_NAME"] = project_name
    metadata["mission"] = mission
    metadata["relative_orbit"] = int(relative_orbit)
    metadata["post_processing_method"] = "dolphin"
    metadata["ORBIT_DIRECTION"] = orbit_direction
    metadata["flight_direction"] = metadata.get("flight_direction") or flight
    metadata["data_footprint"] = footprint
    metadata["scene_footprint"] = footprint
    return metadata
