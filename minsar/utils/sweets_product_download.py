"""Download missing SWEETS SAFE or OPERA CSLC products without re-fetching valid files."""

from __future__ import annotations

import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Callable

SAFE_KEY_RE = re.compile(r"_(\d{8})T\d{6}_.*_(\d{6})_[0-9A-F]{6}_")
MISSING_BURSTS_LOG = "missing_bursts.txt"
MISSING_BURSTS_HEADER = (
    "# ASF burst SLC acquisitions skipped (not downloaded; processing continues without them).\n"
    "# Columns: YYYYMMDD orbit swath pol  reason\n"
)
DEFAULT_BURST_DOWNLOAD_RETRIES = 10
BURST_DOWNLOAD_RETRY_SLEEP_SECS = 60


class MissingBurstsLog:
    """Append skipped SAFE acquisition records under the sweets data directory."""

    def __init__(self, out_dir: Path) -> None:
        self.path = Path(out_dir) / MISSING_BURSTS_LOG
        self._seen: set[tuple[str, int, str, str]] = set()
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0].isdigit() and len(parts[0]) == 8:
                    orbit_s = parts[1].removeprefix("orbit=")
                    if orbit_s.isdigit():
                        self._seen.add((parts[0], int(orbit_s), parts[2], parts[3]))

    def record(
        self,
        *,
        orbit: int | str,
        swath: str,
        pol: str,
        reason: str,
        yyyymmdd: str | None = None,
        search_results: list | None = None,
    ) -> None:
        """Record one skipped acquisition; dedupe by date, orbit, swath, pol."""
        orbit_int = int(orbit) if str(orbit).isdigit() else 0
        date = yyyymmdd or _acquisition_date_for_orbit(search_results or [], orbit_int)
        if not date:
            date = "00000000"
        key = (date, orbit_int, swath, pol)
        if key in self._seen:
            return
        self._seen.add(key)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.is_file() or self.path.stat().st_size == 0:
            self.path.write_text(MISSING_BURSTS_HEADER, encoding="utf-8")
        line = f"{date} orbit={orbit_int:06d} {swath} {pol}  {reason.strip()}\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
        print(
            f"Skipping acquisition {date} orbit {orbit_int:06d} {swath} {pol}: {reason}",
            file=sys.stderr,
        )


def skipped_safe_keys(out_dir: Path) -> set[tuple[int, str]]:
    """Return (absolute_orbit, yyyymmdd) keys listed in data/missing_bursts.txt."""
    path = Path(out_dir) / MISSING_BURSTS_LOG
    keys: set[tuple[int, str]] = set()
    if not path.is_file():
        return keys
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit() and len(parts[0]) == 8:
            orbit_s = parts[1].removeprefix("orbit=")
            if orbit_s.isdigit():
                keys.add((int(orbit_s), parts[0]))
    return keys


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


def _burst_group_key(result) -> tuple[int, str, str]:
    """Return (absolute_orbit, swath, polarization) for an ASF burst hit."""
    props = result.properties
    return int(props["orbit"]), str(props["burst"]["subswath"]), str(props["polarization"])


def _relative_burst_ids(bursts: list) -> list[int]:
    """Sorted unique relative burst IDs in an ASF burst group."""
    return sorted({int(burst.properties["burst"]["relativeBurstID"]) for burst in bursts})


def _dedupe_bursts(bursts: list) -> list:
    """Keep one ASF hit per granule fileID."""
    seen: set[str] = set()
    unique: list = []
    for burst in bursts:
        file_id = str(burst.properties.get("fileID") or burst.properties.get("fileName") or id(burst))
        if file_id in seen:
            continue
        seen.add(file_id)
        unique.append(burst)
    return unique


def _dedupe_search_bursts(bursts: list) -> list:
    """Keep one ASF hit per orbit, swath, polarization, and relative burst ID."""
    seen: set[tuple[int, str, str, int]] = set()
    unique: list = []
    for burst in bursts:
        props = burst.properties
        key = (
            int(props["orbit"]),
            str(props["burst"]["subswath"]),
            str(props["polarization"]),
            int(props["burst"]["relativeBurstID"]),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(burst)
    return unique


def _dedupe_burst_infos(burst_infos: list) -> list:
    """Keep one BurstInfo per orbit, swath, polarization, and burst ID."""
    seen: set[tuple[int, str, str, int]] = set()
    unique: list = []
    for info in burst_infos:
        burst_id = int(info.burst_id) if info.burst_id is not None else -1
        key = (int(info.absolute_orbit), str(info.swath), str(info.polarization), burst_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(info)
    return unique


def _partition_valid_burst_sets(
    burst_infos: list,
    missing_log: MissingBurstsLog,
    *,
    drop_duplicates: Callable[[list], list] | None = None,
) -> list[list]:
    """Split burst infos into per-orbit groups that pass burst2safe validity checks."""
    from burst2safe import utils as burst_utils
    from burst2safe.safe import Safe

    dedupe = drop_duplicates or _dedupe_burst_infos
    abs_orbits = burst_utils.drop_duplicates([info.absolute_orbit for info in burst_infos])
    valid_sets: list[list] = []
    for orbit in abs_orbits:
        burst_set = dedupe([info for info in burst_infos if info.absolute_orbit == orbit])
        if not burst_set:
            continue
        try:
            Safe.check_group_validity(burst_set)
        except ValueError as exc:
            info = burst_set[0]
            missing_log.record(
                orbit=info.absolute_orbit,
                swath=str(info.swath),
                pol=str(info.polarization),
                reason=str(exc),
                yyyymmdd=info.date.strftime("%Y%m%d") if info.date is not None else None,
            )
            continue
        valid_sets.append(burst_set)
    return valid_sets


def _parse_burst_start_date(result) -> str | None:
    """Return YYYYMMDD from an ASF S1 burst search hit."""
    props = result.properties
    raw = props.get("startTime") or props.get("start") or props.get("processingDate")
    if not raw:
        return None
    text = str(raw).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).strftime("%Y%m%d")
    except ValueError:
        match = re.search(r"(\d{8})", str(raw))
        return match.group(1) if match else None


def _acquisition_date_for_orbit(search_results: list, orbit: int) -> str | None:
    """Best-effort acquisition date for an absolute orbit from ASF search hits."""
    for result in search_results:
        if int(result.properties["orbit"]) == orbit:
            date = _parse_burst_start_date(result)
            if date:
                return date
    return None


def _find_group_skip_missing(
    orbit: int | None,
    footprint,
    polarizations: list[str] | None,
    swaths: list[str] | None,
    mode: str,
    min_bursts: int,
    start_date: datetime | None,
    end_date: datetime | None,
    use_relative_orbit: bool,
    missing_log: MissingBurstsLog,
) -> list:
    """Like burst2safe.find_group, but skip orbit/swath/pol groups missing on Vertex."""
    import asf_search
    from burst2safe.search import get_burst_group, sanitize_group_search_inputs

    if use_relative_orbit and not (start_date and end_date):
        raise ValueError("You must provide start and end dates when using relative orbit number.")

    polarizations, swaths = sanitize_group_search_inputs(polarizations, swaths, mode)
    opts = dict(
        dataset=asf_search.constants.DATASET.SLC_BURST,
        intersectsWith=footprint.wkt,
        beamMode=mode,
    )
    if use_relative_orbit:
        assert start_date is not None
        assert end_date is not None
        opts["relativeOrbit"] = orbit
        opts["start"] = (f"{start_date.strftime('%Y-%m-%d')}T00:00:00Z",)
        opts["end"] = (f"{end_date.strftime('%Y-%m-%d')}T23:59:59Z",)
    else:
        opts["absoluteOrbit"] = orbit
    search_results = list(asf_search.geo_search(**opts))

    grouped: list = []
    if use_relative_orbit:
        absolute_orbits = sorted({int(result.properties["orbit"]) for result in search_results})
        group_definitions = product(polarizations, swaths, absolute_orbits)
    else:
        group_definitions = product(polarizations, swaths)

    for group_definition in group_definitions:
        try:
            sub_results = get_burst_group(search_results, *group_definition, min_bursts=min_bursts)
        except ValueError as exc:
            pol, swath, *rest = group_definition
            abs_orbit = rest[0] if rest else None
            missing_log.record(
                orbit=abs_orbit if abs_orbit is not None else "?",
                swath=str(swath),
                pol=str(pol),
                reason=str(exc),
                search_results=search_results,
            )
            continue
        grouped.extend(sub_results)
    return grouped


def _fetch_burst_id_range(template_bursts: list, needed: list[int]) -> list:
    """Search ASF for needed relative burst IDs on the template group's orbit/swath/pol."""
    import asf_search

    relative_orbit, _, swath = template_bursts[0].properties["burst"]["fullBurstID"].split("_")
    polarization = template_bursts[0].properties["polarization"]
    absolute_orbit = int(template_bursts[0].properties["orbit"])
    full_burst_ids = [f"{relative_orbit}_{burst_id:06}_{swath}" for burst_id in needed]
    return list(
        asf_search.search(
            dataset=asf_search.constants.DATASET.SLC_BURST,
            absoluteOrbit=absolute_orbit,
            polarization=polarization,
            fullBurstID=full_burst_ids,
        )
    )


def fill_consecutive_burst_ids(results: list, *, missing_log: MissingBurstsLog | None = None) -> list:
    """Add skipped burst IDs so each orbit/swath/pol group is consecutive.

    burst2safe will not pack a SAFE unless relative burst IDs are consecutive.
    ASF ``intersectsWith`` can hit the first and last burst covering an AOI and
    miss a middle burst whose footprint does not quite intersect the rectangle.
    Fetch ``min_id..max_id`` for that group. If a date still lacks a burst in the
    ASF catalog, skip that acquisition instead of failing the whole stack.
    """
    groups: dict[tuple[int, str, str], list] = defaultdict(list)
    for result in results:
        groups[_burst_group_key(result)].append(result)

    if not groups:
        return []

    filled: list = []
    for key, bursts in groups.items():
        orbit, swath, pol = key
        bursts = _dedupe_search_bursts(bursts)
        have = _relative_burst_ids(bursts)
        if not have:
            continue
        # Per acquisition: fill only gaps between bursts ASF returned for this pass.
        # Do not require every date to share the same burst-ID span across the stack.
        needed = list(range(have[0], have[-1] + 1))
        if have != needed:
            missing = [burst_id for burst_id in needed if burst_id not in have]
            print(
                f"Filling burst ID gap {missing} for orbit {orbit} {swath} {pol} "
                f"(ASF intersected {have}, need {needed})",
                file=sys.stderr,
            )
            bursts = _dedupe_search_bursts(_fetch_burst_id_range(bursts, needed))
            have = _relative_burst_ids(bursts)
        if have != needed:
            missing = [burst_id for burst_id in needed if burst_id not in have]
            reason = f"missing relative burst IDs {missing} after ASF search (need {needed})"
            if missing_log is not None:
                missing_log.record(
                    orbit=orbit,
                    swath=swath,
                    pol=pol,
                    reason=reason,
                    search_results=bursts,
                )
            else:
                print(f"Skipping orbit {orbit} {swath} {pol}: {reason}", file=sys.stderr)
            continue
        filled.extend(_dedupe_search_bursts(_dedupe_bursts(bursts)))
    if not filled:
        raise RuntimeError(
            "SAFE search found no acquisition with consecutive burst IDs after gap fill. "
            "ASF did not return the middle burst(s) for any date in the range."
        )
    return filled


def search_safe_bursts(search, *, missing_log: MissingBurstsLog | None = None) -> list:
    """ASF burst hits for a BurstSearch, with consecutive burst-ID gaps filled."""
    log = missing_log or MissingBurstsLog(search.out_dir)
    results = _find_group_skip_missing(
        search.track,
        search.aoi,
        search.polarizations,
        search.swaths,
        "IW",
        search.min_bursts,
        use_relative_orbit=True,
        start_date=search.start,
        end_date=search.end,
        missing_log=log,
    )
    return fill_consecutive_burst_ids(list(results), missing_log=log)


def expected_safe_keys(search) -> set[tuple[int, str]]:
    """Return expected (absolute_orbit, yyyymmdd) keys for a BurstSearch config."""
    from burst2safe import utils as burst_utils

    missing_log = MissingBurstsLog(search.out_dir)
    results = search_safe_bursts(search, missing_log=missing_log)
    infos = burst_utils.get_burst_infos(results, search.out_dir)
    if search.flight_direction:
        infos = [info for info in infos if info.direction.upper() == search.flight_direction.upper()]
    valid_sets = _partition_valid_burst_sets(infos, missing_log)
    expected = {
        (int(info.absolute_orbit), info.date.strftime("%Y%m%d"))
        for burst_set in valid_sets
        for info in burst_set
        if info.date is not None
    }
    expected -= skipped_safe_keys(search.out_dir)
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


def _format_exc(exc: BaseException) -> str:
    """Return a non-empty error string (GDAL RuntimeError can have blank str())."""
    text = str(exc).strip()
    if text:
        return text
    return f"{type(exc).__name__} (no message)"


def _download_bursts_with_retries(burst_infos, *, retries: int = DEFAULT_BURST_DOWNLOAD_RETRIES) -> None:
    """Call burst2safe.download_bursts, retrying ASF HTTP 202 RetryError."""
    from burst2safe.download import download_bursts
    from tenacity import RetryError

    attempts = max(1, retries)
    for attempt in range(1, attempts + 1):
        try:
            download_bursts(burst_infos)
            return
        except RetryError as exc:
            if attempt == attempts:
                raise RuntimeError(f"Burst download failed after {attempts} attempts (ASF RetryError)") from exc
            print(
                f"Burst download retry {attempt}/{attempts} after ASF RetryError; sleeping {BURST_DOWNLOAD_RETRY_SLEEP_SECS}s",
                file=sys.stderr,
            )
            time.sleep(BURST_DOWNLOAD_RETRY_SLEEP_SECS)


def download_safes(search, *, skip_existing: bool = True, retries: int = DEFAULT_BURST_DOWNLOAD_RETRIES) -> list[Path]:
    """Download burst SLCs and build SAFE directories, optionally skipping valid products."""
    from burst2safe import utils as burst_utils
    from burst2safe.safe import Safe

    search.out_dir.mkdir(parents=True, exist_ok=True)
    missing_log = MissingBurstsLog(search.out_dir)
    on_disk = sorted(search.out_dir.glob("S1[ABCD]_*.SAFE"))
    results = search_safe_bursts(search, missing_log=missing_log)
    burst_infos = burst_utils.get_burst_infos(results, search.out_dir)
    if search.flight_direction:
        burst_infos = [info for info in burst_infos if info.direction.upper() == search.flight_direction.upper()]

    skipped_keys = skipped_safe_keys(search.out_dir)
    if skip_existing:
        valid = valid_safe_keys(search.out_dir)
        burst_infos = [
            info
            for info in burst_infos
            if info.date is not None
            and (int(info.absolute_orbit), info.date.strftime("%Y%m%d")) not in valid
            and (int(info.absolute_orbit), info.date.strftime("%Y%m%d")) not in skipped_keys
        ]
        if not burst_infos:
            return on_disk

    valid_sets = _partition_valid_burst_sets(burst_infos, missing_log)
    if not valid_sets:
        if skip_existing and on_disk:
            print(
                f"No new downloadable SAFE acquisitions ({len(on_disk)} already on disk; "
                f"see {missing_log.path})",
                file=sys.stderr,
            )
            return on_disk
        raise RuntimeError("No SAFE acquisition has a valid consecutive burst group")
    safe_paths: list[Path] = list(on_disk)
    for burst_set in valid_sets:
        info = burst_set[0]
        try:
            _download_bursts_with_retries(burst_set, retries=retries)
            for item in burst_set:
                item.add_shape_info()
                item.add_start_stop_utc()
            safe = Safe(burst_set, search.all_anns, search.out_dir)
            safe_paths.append(safe.create_safe())
            safe.cleanup()
        except (OSError, RuntimeError, ValueError) as exc:
            missing_log.record(
                orbit=info.absolute_orbit,
                swath=str(info.swath),
                pol=str(info.polarization),
                reason=_format_exc(exc),
                yyyymmdd=info.date.strftime("%Y%m%d") if info.date is not None else None,
            )
            continue
    if not safe_paths:
        raise RuntimeError(
            "No SAFE acquisition could be downloaded and assembled; see missing_bursts.txt"
        )
    if missing_log.path.is_file() and missing_log.path.stat().st_size > len(MISSING_BURSTS_HEADER):
        print(
            f"Skipped acquisitions logged to {missing_log.path} ({len(missing_log._seen)} date(s))",
            file=sys.stderr,
        )
    return sorted(set(safe_paths))


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
