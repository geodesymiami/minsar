#!/usr/bin/env python3
"""Apply SARvey-style atmospheric (APS) kriging to an existing p1 time-series HDF5.

Estimates APS from a sparse stable subset of points (same logic as SARvey step 3),
interpolates to every point in the input file, subtracts it, and writes a new HDF5
with identical point_id / coord_xy (no network or densification changes).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import numpy as np


def _get_minsar_home() -> Path:
    """Return MINSAR_HOME or infer from this script's location."""
    for env in ("MINSAR_HOME", "RSMASINSAR_HOME"):
        home = os.environ.get(env)
        if home:
            return Path(home).resolve()
    return Path(__file__).resolve().parent.parent.parent


def _sarvey_search_roots() -> list[str]:
    """SARvey install roots to try, in priority order (matches setup/environment.bash)."""
    minsar_home = _get_minsar_home()
    candidates = [
        os.environ.get("SARVEY_HOME", ""),
        str(minsar_home / "tools" / "sarvey"),
    ]
    roots: list[str] = []
    seen: set[str] = set()
    for root in candidates:
        if root and root not in seen:
            seen.add(root)
            roots.append(root)
    return roots


def _ensure_sarvey_import_path() -> None:
    for root in _sarvey_search_roots():
        if os.path.isdir(root) and root not in sys.path:
            sys.path.insert(0, root)

    try:
        import sarvey  # noqa: F401
        return
    except ImportError:
        pass

    raise EnvironmentError(
        "Cannot find SARvey. Set SARVEY_HOME or MINSAR_HOME, or install under "
        f"{_get_minsar_home() / 'tools' / 'sarvey'}."
    )


def _estimate_residuals(point_obj, *, ifg_space: bool = False) -> np.ndarray:
    """Acquisition-space phase residuals (v_hat) for APS; works with sarvey and sarvey_erik."""
    import sarvey.utils as ut

    if hasattr(ut, "estimateParameters_t"):
        return ut.estimateParameters_t(obj=point_obj, ifg_space=ifg_space)[-1]
    return ut.estimateParameters(obj=point_obj, ifg_space=ifg_space)[-1]


def _resolve_config_path(filepath: str | Path, workdir: Path) -> Path:
    config_path = Path(filepath)
    if not config_path.is_absolute():
        config_path = workdir / config_path
    return config_path.resolve()


def _read_config_dict(config_path: Path) -> dict:
    """Parse SARvey config.json without pydantic (works with sarvey and sarvey_erik keys)."""
    text = config_path.read_text()
    try:
        import json5

        data = json5.loads(text)
    except ImportError:
        import json
        import re

        text = re.sub(r"(?<![\w\"])(\w+) *:", r'"\1":', text)
        text = re.sub(r",\s*([\]}])", r"\1", text)
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be an object: {config_path}")
    return data


def _config_section(cfg: dict, name: str) -> dict:
    section = cfg.get(name, {})
    return section if isinstance(section, dict) else {}


def _resolve_workdir_path(workdir: Path, path_value: str | None, default: str) -> Path:
    rel = path_value if path_value not in (None, "") else default
    path = Path(rel)
    if not path.is_absolute():
        path = workdir / path
    return path.resolve()


def load_aps_filter_config(filepath: str | Path, workdir: Path) -> dict:
    """Read only APS-filter settings from config.json (sarvey and sarvey_erik compatible)."""
    config_path = _resolve_config_path(filepath, workdir)
    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    cfg = _read_config_dict(config_path)
    general = _config_section(cfg, "general")
    filtering = _config_section(cfg, "filtering")

    interpolation_method = str(filtering.get("interpolation_method", "kriging")).lower()
    if interpolation_method not in ("kriging", "linear", "cubic"):
        raise ValueError(
            f"filtering.interpolation_method must be kriging, linear, or cubic: "
            f"{interpolation_method!r}"
        )

    return {
        "config_path": config_path,
        "input_dir": _resolve_workdir_path(workdir, general.get("input_path"), "inputs/"),
        "output_dir": _resolve_workdir_path(workdir, general.get("output_path"), "outputs/"),
        "num_cores": int(general.get("num_cores", 16)),
        "log_level": str(general.get("logging_level", "INFO")).upper(),
        "apply_aps_filtering": bool(filtering.get("apply_aps_filtering", True)),
        "grid_size": int(filtering.get("grid_size", 1000)),
        "max_auto_corr": float(filtering.get("max_temporal_autocorrelation", 0.3)),
        "interpolation_method": interpolation_method,
    }


def resolve_filter_settings(args, workdir: Path) -> dict:
    """Merge SARvey config (-f) with CLI overrides (CLI wins)."""
    settings = {
        "grid_size": None,
        "max_auto_corr": None,
        "interpolation_method": None,
        "num_cores": None,
        "log_level": None,
        "input_dir": None,
        "config_path": None,
        "apply_aps_filtering": True,
    }

    if args.filepath:
        cfg = load_aps_filter_config(args.filepath, workdir)
        settings["config_path"] = cfg["config_path"]
        settings["apply_aps_filtering"] = cfg["apply_aps_filtering"]
        settings["grid_size"] = cfg["grid_size"]
        settings["max_auto_corr"] = cfg["max_auto_corr"]
        settings["interpolation_method"] = cfg["interpolation_method"]
        settings["num_cores"] = cfg["num_cores"]
        settings["log_level"] = cfg["log_level"]
        settings["input_dir"] = cfg["input_dir"]

    if args.grid_size is not None:
        settings["grid_size"] = args.grid_size
    if args.max_temporal_autocorrelation is not None:
        settings["max_auto_corr"] = args.max_temporal_autocorrelation
    if args.interpolation_method is not None:
        settings["interpolation_method"] = args.interpolation_method
    if args.num_cores is not None:
        settings["num_cores"] = args.num_cores
    if args.log_level is not None:
        settings["log_level"] = args.log_level.upper()
    if args.input_dir is not None:
        settings["input_dir"] = Path(args.input_dir)

    settings["grid_size"] = settings["grid_size"] if settings["grid_size"] is not None else 1000
    settings["max_auto_corr"] = (
        settings["max_auto_corr"] if settings["max_auto_corr"] is not None else 0.3
    )
    settings["interpolation_method"] = (
        settings["interpolation_method"]
        if settings["interpolation_method"] is not None
        else "kriging"
    )
    settings["num_cores"] = settings["num_cores"] if settings["num_cores"] is not None else 16
    settings["log_level"] = settings["log_level"] if settings["log_level"] is not None else "INFO"
    return settings


def default_output_path(input_path: Path, suffix: str = "_noAPS") -> Path:
    stem = input_path.stem
    if stem.endswith(suffix):
        return input_path
    return input_path.with_name(f"{stem}{suffix}{input_path.suffix}")


def resolve_input_dir(output_dir: Path, input_dir: Path | None) -> Path:
    if input_dir is not None:
        return input_dir.resolve()
    candidate = output_dir.parent / "inputs"
    if candidate.is_dir():
        return candidate.resolve()
    raise FileNotFoundError(
        f"inputs directory not found at {candidate}; pass --input-dir"
    )


def _scene_extent_m(coord_utm_img: np.ndarray) -> tuple[float, float]:
    p0 = coord_utm_img[:, 0, 0]
    p1 = coord_utm_img[:, 0, -1]
    p2 = coord_utm_img[:, -1, 0]
    dist_width = float(np.linalg.norm(p0 - p1))
    dist_length = float(np.linalg.norm(p0 - p2))
    return dist_width, dist_length


def _effective_grid_size(
    dist_width: float,
    dist_length: float,
    grid_size: int,
    logger: logging.Logger,
    target_cells_per_axis: int = 4,
) -> int:
    """Shrink grid cells for small AOIs so APS conditioning uses multiple stable points."""
    min_extent = min(dist_width, dist_length)
    cells_rng = max(1, int(round(dist_width / grid_size)))
    cells_az = max(1, int(round(dist_length / grid_size)))
    if cells_rng >= 2 and cells_az >= 2 and grid_size < min_extent:
        return grid_size

    new_size = max(int(min_extent / target_cells_per_axis), 50)
    logger.warning(
        "Grid size %sm too large for AOI (%.0fm x %.0fm); using %sm (~%sx%s cells).",
        grid_size,
        dist_width,
        dist_length,
        new_size,
        max(1, int(round(dist_width / new_size))),
        max(1, int(round(dist_length / new_size))),
    )
    return new_size


def _stable_mask_from_grid(
    auto_corr: np.ndarray,
    mask: np.ndarray,
    box_list: list,
    max_auto_corr: float,
) -> np.ndarray:
    import sarvey.utils as ut

    auto_corr_img = np.full(mask.shape, np.inf, dtype=np.float64)
    auto_corr_img[mask] = auto_corr
    auto_corr_img[auto_corr_img > max_auto_corr] = np.inf
    return ut.selectBestPointsInGrid(box_list=box_list, quality=auto_corr_img, sel_min=True)


def select_stable_point_ids(
    point_obj,
    output_dir: Path,
    *,
    grid_size: int,
    max_auto_corr: float,
    logger: logging.Logger,
    min_stable: int = 10,
):
    """Return point_id values used to condition APS kriging (SARvey step 3 logic)."""
    import sarvey.utils as ut
    from sarvey.objects import CoordinatesUTM

    mask = point_obj.createMask()
    residuals = _estimate_residuals(point_obj, ifg_space=False)
    auto_corr = ut.temporalAutoCorrelation(residuals=residuals, lag=1).reshape(-1)

    coord_utm_obj = CoordinatesUTM(
        file_path=str(output_dir / "coordinates_utm.h5"),
        logger=logger,
    )
    coord_utm_obj.open()
    dist_width, dist_length = _scene_extent_m(coord_utm_obj.coord_utm)
    grid_size = _effective_grid_size(dist_width, dist_length, grid_size, logger)

    box_list, _ = ut.createSpatialGrid(
        coord_utm_img=coord_utm_obj.coord_utm,
        length=point_obj.length,
        width=point_obj.width,
        grid_size=grid_size,
        logger=logger,
    )

    cand_mask_sparse = np.zeros_like(mask, dtype=bool)
    corr_threshold = max_auto_corr
    for attempt in range(6):
        cand_mask_sparse = _stable_mask_from_grid(
            auto_corr, mask, box_list, max_auto_corr=corr_threshold
        )
        num_stable = int(cand_mask_sparse.sum())
        if num_stable >= min_stable:
            if attempt:
                logger.warning(
                    "Using %s stable points with relaxed max temporal autocorrelation %.2f (requested %.2f).",
                    num_stable,
                    corr_threshold,
                    max_auto_corr,
                )
            break
        if num_stable > 0 and attempt == 5:
            logger.warning(
                "Only %s stable points selected (<%s); continuing with sparse APS conditioning.",
                num_stable,
                min_stable,
            )
            break
        logger.warning(
            "Only %s stable points at max temporal autocorrelation %.2f; relaxing threshold.",
            num_stable,
            corr_threshold,
        )
        corr_threshold = min(1.0, corr_threshold + 0.15)

    if not cand_mask_sparse.any():
        logger.warning(
            "No points passed autocorrelation threshold; using lowest-autocorr points per grid cell."
        )
        auto_corr_img = np.full(mask.shape, np.inf, dtype=np.float64)
        auto_corr_img[mask] = auto_corr
        cand_mask_sparse = ut.selectBestPointsInGrid(
            box_list=box_list, quality=auto_corr_img, sel_min=True
        )

    num_stable = int(cand_mask_sparse.sum())
    if num_stable == 0:
        raise ValueError(
            "No stable points selected for APS estimation; try --grid-size 200 or "
            "--max-temporal-autocorrelation 0.5"
        )
    if num_stable < min_stable:
        logger.warning(
            "Only %s stable points selected for APS; results may be unreliable.",
            num_stable,
        )

    point_id_img = np.arange(point_obj.length * point_obj.width).reshape(
        (point_obj.length, point_obj.width)
    )
    return point_id_img[cand_mask_sparse]


def apply_aps_filter(
    input_path: Path,
    output_path: Path,
    input_dir: Path,
    *,
    interpolation_method: str = "kriging",
    grid_size: int = 1000,
    max_auto_corr: float = 0.3,
    num_cores: int = 16,
    logger: logging.Logger,
) -> Path:
    _ensure_sarvey_import_path()
    import sarvey.utils as ut
    from sarvey.filtering import estimateAtmosphericPhaseScreen, simpleInterpolation
    from sarvey.objects import Points

    input_path = input_path.resolve()
    output_dir = input_path.parent
    for required in ("ifg_network.h5", "coordinates_utm.h5"):
        req = output_dir / required
        if not req.is_file():
            raise FileNotFoundError(f"Required SARvey output missing: {req}")

    slc_stack = input_dir / "slcStack.h5"
    if not slc_stack.is_file():
        raise FileNotFoundError(f"slcStack.h5 not found under {input_dir}")

    point_obj = Points(file_path=str(output_path), logger=logger)
    point_obj.open(other_file_path=str(input_path), input_path=str(input_dir))

    keep_id = select_stable_point_ids(
        point_obj,
        output_dir,
        grid_size=grid_size,
        max_auto_corr=max_auto_corr,
        logger=logger,
    )

    stable_obj = Points(file_path=str(output_path), logger=logger)
    stable_obj.open(other_file_path=str(input_path), input_path=str(input_dir))
    stable_obj.removePoints(keep_id=keep_id, input_path=str(input_dir))
    phase_for_aps = _estimate_residuals(stable_obj, ifg_space=False)

    logger.info(
        "Estimating APS with %s (%s stable / %s total points).",
        interpolation_method,
        stable_obj.num_points,
        point_obj.num_points,
    )

    if interpolation_method == "kriging":
        _, aps_all = estimateAtmosphericPhaseScreen(
            residuals=phase_for_aps,
            coord_utm1=stable_obj.coord_utm,
            coord_utm2=point_obj.coord_utm,
            num_cores=num_cores,
            bool_plot=False,
            logger=logger,
        )
    elif interpolation_method in ("linear", "cubic"):
        _, aps_all = simpleInterpolation(
            residuals=phase_for_aps,
            coord_utm1=stable_obj.coord_utm,
            coord_utm2=point_obj.coord_utm,
            interp_method=interpolation_method,
        )
    else:
        raise ValueError(f"Unknown interpolation method: {interpolation_method}")

    point_obj.phase = (point_obj.phase - aps_all).astype(np.float32)
    point_obj.writeToFile()
    logger.info("Wrote APS-corrected time series: %s", output_path)
    return output_path


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Subtract a SARvey-style atmospheric phase screen from an existing p1 "
            "time-series HDF5 without changing points or the IFG network."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""\
Examples:
  sarvey_APS_filter.py -f config.json outputs/p1_ts.h5
  sarvey_APS_filter.py -f config.json outputs/p1_ts_thermal_filtered.h5
  sarvey_APS_filter.py -f config.json outputs/p1_ts.h5 -o outputs/p1_ts_aps_corrected.h5
  sarvey_APS_filter.py -f config.json -w /path/to/project outputs/p1_ts.h5
""",
    )
    parser.add_argument(
        "input_file",
        help="SARvey p1 time-series HDF5 to filter (e.g. p1_ts.h5 or p1_ts_thermal_filtered.h5)",
    )
    parser.add_argument(
        "-f", "--filepath", metavar="FILE",
        help="Path to SARvey config.json (sarvey -f; reads general/ filtering only, any SARvey version)",
    )
    parser.add_argument(
        "-w", "--workdir", default=None,
        help="Working directory for relative paths (default: current directory, same as sarvey -w)",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output HDF5 path (default: <input_stem>_noAPS.h5 beside input)",
    )
    parser.add_argument(
        "--input-dir",
        help="Path to SARvey inputs/ with slcStack.h5 (overrides general.input_path from config)",
    )
    parser.add_argument(
        "--interpolation-method",
        choices=("kriging", "linear", "cubic"),
        help="Spatial APS interpolation (overrides filtering.interpolation_method in config)",
    )
    parser.add_argument(
        "--grid-size", type=int,
        help="Stable-point grid size in metres (overrides filtering.grid_size in config)",
    )
    parser.add_argument(
        "--max-temporal-autocorrelation", type=float,
        help="Max lag-1 temporal autocorrelation for stable points (overrides config)",
    )
    parser.add_argument(
        "--num-cores", type=int,
        help="Worker cores for kriging (overrides general.num_cores in config)",
    )
    parser.add_argument(
        "--log-level", default=None,
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Logging level (overrides general.logging_level in config)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    workdir = Path(args.workdir).resolve() if args.workdir else Path.cwd().resolve()
    settings = resolve_filter_settings(args, workdir)

    logging.basicConfig(
        level=getattr(logging, settings["log_level"]),
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True,
    )
    logger = logging.getLogger("sarvey_APS_filter")
    logger.info("Working directory: %s", workdir)
    if settings["config_path"] is not None:
        logger.info("Configuration file: %s", settings["config_path"])
        if not settings["apply_aps_filtering"]:
            logger.warning(
                "filtering.apply_aps_filtering is false in %s; running APS filter anyway.",
                settings["config_path"].name,
            )

    input_path = Path(args.input_file)
    if not input_path.is_absolute():
        input_path = (workdir / input_path).resolve()
    if not input_path.is_file():
        parser.error(f"input file not found: {input_path}")

    output_path = Path(args.output).resolve() if args.output else default_output_path(input_path)
    if settings["input_dir"] is not None:
        input_dir = settings["input_dir"].resolve()
        if not input_dir.is_dir():
            parser.error(f"input directory not found: {input_dir}")
    else:
        input_dir = resolve_input_dir(input_path.parent, None)

    apply_aps_filter(
        input_path,
        output_path,
        input_dir,
        interpolation_method=settings["interpolation_method"],
        grid_size=settings["grid_size"],
        max_auto_corr=settings["max_auto_corr"],
        num_cores=settings["num_cores"],
        logger=logger,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
