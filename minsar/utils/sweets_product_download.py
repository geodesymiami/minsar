"""Download missing SWEETS SAFE or OPERA CSLC products without re-fetching valid files."""

from __future__ import annotations

import re
from pathlib import Path

SAFE_KEY_RE = re.compile(r"_(\d{8})T\d{6}_.*_(\d{6})_[0-9A-F]{6}_")


def safe_acquisition_key(path: Path) -> tuple[int, str] | None:
    """Return (absolute_orbit, yyyymmdd) parsed from a burst2safe SAFE name."""
    match = SAFE_KEY_RE.search(path.name)
    if not match:
        return None
    return int(match.group(2)), match.group(1)


def _safe_is_readable(path: Path) -> tuple[bool, str]:
    """Return whether a burst2safe SAFE has the files COMPASS needs."""
    import xml.etree.ElementTree as ET

    import rasterio

    required = [path / "manifest.safe", path / "preview/map-overlay.kml"]
    missing = [item.relative_to(path) for item in required if not item.is_file()]
    annotations = sorted((path / "annotation").glob("*.xml"))
    measurements = sorted((path / "measurement").glob("*.tiff"))
    if missing:
        return False, f"missing {', '.join(map(str, missing))}"
    if not annotations:
        return False, "no annotation XML files"
    if not measurements:
        return False, "no measurement TIFF files"
    try:
        ET.parse(path / "manifest.safe")
        for annotation in annotations:
            ET.parse(annotation)
        for measurement in measurements:
            with rasterio.open(measurement) as dataset:
                if dataset.width < 1 or dataset.height < 1 or dataset.count < 1:
                    return False, f"empty raster {measurement.name}"
    except Exception as exc:
        return False, str(exc)
    return True, ""


def _hdf5_has_datasets(path: Path, datasets: tuple[str, ...]) -> tuple[bool, str]:
    """Return whether an HDF5 file opens and contains required datasets."""
    import h5py

    if path.stat().st_size < 1024 * 1024:
        return False, "file is smaller than 1 MiB"
    try:
        with h5py.File(path, "r") as handle:
            missing = [dataset for dataset in datasets if dataset not in handle]
            if missing:
                return False, f"missing {', '.join(missing)}"
            for dataset in datasets:
                value = handle[dataset]
                if value.size < 1:
                    return False, f"empty {dataset}"
                if value.ndim >= 2:
                    _ = value[0, 0]
    except Exception as exc:
        return False, str(exc)
    return True, ""


def expected_safe_keys(search) -> set[tuple[int, str]]:
    """Return expected (absolute_orbit, yyyymmdd) keys for a BurstSearch config."""
    from burst2safe import utils as burst_utils
    from burst2safe.search import find_group

    results = find_group(
        search.track,
        search.aoi,
        search.polarizations,
        search.swaths,
        "IW",
        search.min_bursts,
        use_relative_orbit=True,
        start_date=search.start,
        end_date=search.end,
    )
    infos = burst_utils.get_burst_infos(results, search.out_dir)
    if search.flight_direction:
        infos = [info for info in infos if info.direction.upper() == search.flight_direction.upper()]
    expected = {
        (int(info.absolute_orbit), info.date.strftime("%Y%m%d"))
        for info in infos
        if info.date is not None
    }
    if not expected:
        raise RuntimeError("SAFE search found no expected acquisitions")
    return expected


def valid_safe_keys(out_dir: Path) -> set[tuple[int, str]]:
    """Return acquisition keys for readable SAFE directories already on disk."""
    valid: set[tuple[int, str]] = set()
    for path in sorted(out_dir.glob("S1[ABCD]_*.SAFE")):
        key = safe_acquisition_key(path)
        readable, _ = _safe_is_readable(path)
        if key and readable:
            valid.add(key)
    return valid


def download_safes(search, *, skip_existing: bool = True) -> list[Path]:
    """Download burst SLCs and build SAFE directories, optionally skipping valid products."""
    from burst2safe import utils as burst_utils
    from burst2safe.download import download_bursts
    from burst2safe.safe import Safe
    from burst2safe.search import find_group

    search.out_dir.mkdir(parents=True, exist_ok=True)
    results = find_group(
        search.track,
        search.aoi,
        search.polarizations,
        search.swaths,
        "IW",
        search.min_bursts,
        use_relative_orbit=True,
        start_date=search.start,
        end_date=search.end,
    )
    burst_infos = burst_utils.get_burst_infos(results, search.out_dir)
    if search.flight_direction:
        burst_infos = [info for info in burst_infos if info.direction.upper() == search.flight_direction.upper()]

    if skip_existing:
        valid = valid_safe_keys(search.out_dir)
        burst_infos = [
            info
            for info in burst_infos
            if info.date is not None
            and (int(info.absolute_orbit), info.date.strftime("%Y%m%d")) not in valid
        ]
        if not burst_infos:
            return sorted(search.out_dir.glob("S1[ABCD]_*.SAFE"))

    abs_orbits = burst_utils.drop_duplicates([info.absolute_orbit for info in burst_infos])
    burst_sets = [[info for info in burst_infos if info.absolute_orbit == orbit] for orbit in abs_orbits]
    for burst_set in burst_sets:
        Safe.check_group_validity(burst_set)

    download_bursts(burst_infos)
    safe_paths: list[Path] = []
    for burst_set in burst_sets:
        for info in burst_set:
            info.add_shape_info()
            info.add_start_stop_utc()
        safe = Safe(burst_set, search.all_anns, search.out_dir)
        safe_paths.append(safe.create_safe())
        safe.cleanup()
    return safe_paths


def _result_name(result: object) -> str:
    properties = result.properties  # type: ignore[attr-defined]
    return str(properties.get("fileName") or Path(properties["url"]).name)


def _download_missing_cslc_files(
    search,
    *,
    directory: Path,
    expected_names: set[str],
    datasets: tuple[str, ...],
    product,
) -> list[Path]:
    """Download only CSLC or static-layer files that are missing or unreadable."""
    from opera_utils.bursts import normalize_burst_id
    from opera_utils.download import _get_auth_session, filter_results_by_date_and_version, get_urls

    import asf_search as asf

    burst_ids = search._resolve_burst_ids()
    results = asf.search(
        operaBurstID=list(map(normalize_burst_id, burst_ids)),
        processingLevel=product.value,
        start=search.start if product.value == "CSLC" else None,
        end=search.end if product.value == "CSLC" else None,
        dataset=asf.DATASET.OPERA_S1,
    )
    if product.value == "CSLC":
        results = filter_results_by_date_and_version(results)

    existing = {path.name: path for path in directory.glob("*.h5")}
    missing_names = set(expected_names)
    for name in sorted(expected_names & existing.keys()):
        readable, _ = _hdf5_has_datasets(existing[name], datasets)
        if readable:
            missing_names.discard(name)

    if not missing_names:
        return [existing[name] for name in sorted(expected_names) if name in existing]

    directory.mkdir(parents=True, exist_ok=True)
    selected = [result for result in results if _result_name(result) in missing_names]
    if not selected:
        raise RuntimeError(f"ASF search returned no files for missing products in {directory}")

    urls = get_urls(selected)
    asf.download_urls(
        urls=urls,
        path=str(directory),
        session=_get_auth_session(),
        processes=search.max_jobs,
    )
    return [directory / _result_name(result) for result in selected]


def download_cslcs(search, *, skip_existing: bool = True) -> list[Path]:
    """Download OPERA CSLC and static-layer HDF5s, optionally skipping valid files."""
    from opera_utils.download import L2Product, search_cslcs

    search.out_dir.mkdir(parents=True, exist_ok=True)
    burst_ids = search._resolve_burst_ids()
    cslc_results = search_cslcs(start=search.start, end=search.end, track=search.track, burst_ids=burst_ids)
    static_results = search_cslcs(burst_ids=burst_ids, product=L2Product.CSLC_STATIC)
    expected_cslc = {_result_name(result) for result in cslc_results}
    expected_static = {_result_name(result) for result in static_results}
    if not expected_cslc or not expected_static:
        raise RuntimeError("CSLC search found no expected products")

    if not skip_existing:
        files = search.download()
        files.extend(search.download_static_layers())
        return files

    cslc_paths = _download_missing_cslc_files(
        search,
        directory=search.out_dir,
        expected_names=expected_cslc,
        datasets=("/data/VV", "/data/x_coordinates", "/data/y_coordinates", "/data/projection"),
        product=L2Product.CSLC,
    )
    static_paths = _download_missing_cslc_files(
        search,
        directory=search.static_layers_dir,
        expected_names=expected_static,
        datasets=(
            "/data/los_east",
            "/data/los_north",
            "/data/local_incidence_angle",
            "/data/layover_shadow_mask",
        ),
        product=L2Product.CSLC_STATIC,
    )
    return sorted(set(cslc_paths + static_paths))
