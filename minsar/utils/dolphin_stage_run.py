"""Split-stage Dolphin helpers: wrapped phase only, then stitch from burst products."""

from __future__ import annotations

import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from minsar.utils.sweets_import import hide_argv_from_pyre


def load_displacement_workflow(config_path: Path):
    """Load DisplacementWorkflow while hiding this process argv from pyre."""
    from dolphin.workflows.config import DisplacementWorkflow

    return DisplacementWorkflow.from_yaml(config_path)


def run_wrapped_phase_only(cfg, *, debug: bool = False) -> None:
    """Per-burst phase linking and burst interferograms. No stitch, unwrap, or timeseries."""
    import logging

    from dolphin import utils
    from dolphin._log import setup_logging
    from dolphin.workflows import displacement, wrapped_phase
    from dolphin.workflows._block_split import crop_to_central
    from dolphin.workflows._utils import _create_burst_cfg, _remove_dir_if_empty
    from tqdm.auto import tqdm

    logger = logging.getLogger("dolphin")
    if cfg.log_file is None:
        cfg.log_file = cfg.work_directory / "dolphin.log"
    setup_logging(logger_name="dolphin", debug=debug, filename=cfg.log_file)
    if not cfg.worker_settings.gpu_enabled:
        utils.disable_gpu()
    utils.set_num_threads(cfg.worker_settings.threads_per_worker)

    grouped = displacement._prepare_grouped_inputs(cfg)
    grouped_slc_files = grouped.grouped_slc_files
    block_bounds = grouped.block_bounds
    logger.info("Found SLC files from %s bursts", len(grouped_slc_files))
    logger.info("Wrapped stage: phase linking only (no stitch, unwrap, or timeseries)")

    wrapped_phase_cfgs = [
        (
            burst,
            _create_burst_cfg(
                cfg,
                burst,
                grouped_slc_files,
                grouped.grouped_amp_mean_files,
                grouped.grouped_amp_dispersion_files,
                grouped.grouped_layover_shadow_mask_files,
                bounds=block_bounds.get(burst),
            ),
        )
        for burst in grouped_slc_files
    ]
    for _, burst_cfg in wrapped_phase_cfgs:
        burst_cfg.create_dir_tree()
        _remove_dir_if_empty(burst_cfg.timeseries_options._directory)
        _remove_dir_if_empty(burst_cfg.unwrap_options._directory)

    num_parallel = min(cfg.worker_settings.n_parallel_bursts, len(grouped_slc_files))
    Executor = ProcessPoolExecutor if num_parallel > 1 else utils.DummyProcessPoolExecutor
    workers_per_burst = cfg.worker_settings.n_parallel_bursts // num_parallel
    ctx = mp.get_context("spawn")
    tqdm.set_lock(ctx.RLock())
    needs_hdf5_unlock = not grouped.is_opera_burst_mode and num_parallel > 1
    with Executor(
        max_workers=cfg.worker_settings.n_parallel_bursts,
        mp_context=ctx,
        initializer=displacement._worker_init,
        initargs=(tqdm.get_lock(), needs_hdf5_unlock),
    ) as exc:
        fut_to_burst = {
            exc.submit(
                wrapped_phase.run,
                burst_cfg,
                debug=debug,
                max_workers=workers_per_burst,
                raise_on_empty=True,
                tqdm_kwargs={"position": i},
            ): burst
            for i, (burst, burst_cfg) in enumerate(wrapped_phase_cfgs)
        }
        for fut, burst in fut_to_burst.items():
            wrapped_phase_output = fut.result()
            bb = block_bounds.get(burst)
            if bb is not None and bb.read_bounds != bb.central_bounds:
                cb = bb.central_bounds
                (
                    cur_ifg_list,
                    cur_crlb_files,
                    cur_closure_phase_files,
                    _comp_slcs,
                    temp_coh_files,
                    ps_file,
                    amp_disp_file,
                    shp_count_files,
                    similarity_files,
                ) = wrapped_phase_output
                [crop_to_central(f, cb) for f in cur_ifg_list]
                [crop_to_central(f, cb) for f in cur_crlb_files]
                [crop_to_central(f, cb) for f in cur_closure_phase_files]
                [crop_to_central(f, cb) for f in temp_coh_files]
                [crop_to_central(f, cb) for f in shp_count_files]
                [crop_to_central(f, cb) for f in similarity_files]
                crop_to_central(ps_file, cb)
                crop_to_central(amp_disp_file, cb)

    logger.info("Wrapped phase complete (stitch/unwrap left to later stages)")


def _glob_burst(work_dir: Path, pattern: str) -> list[Path]:
    return sorted(p for p in work_dir.glob(pattern) if p.is_file())


def collect_burst_stitch_inputs(work_dir: Path) -> dict[str, list[Path]]:
    """Burst-level products under DIR/*/ (not the stitched DIR/interferograms tree)."""
    ifgs = _glob_burst(work_dir, "*/interferograms/*.int.vrt")
    ifgs += _glob_burst(work_dir, "*/interferograms/*.int.tif")
    crlb_file_list: list[Path] = []
    closure_phase_file_list: list[Path] = []
    for linked_phase in sorted(work_dir.glob("*/linked_phase")):
        crlb_file_list.extend(sorted(linked_phase.rglob("crlb*.tif")))
        closure_phase_file_list.extend(sorted(linked_phase.rglob("closure_phase*.tif")))
    return {
        "ifg_file_list": ifgs,
        "temp_coh_file_list": _glob_burst(work_dir, "*/linked_phase/temporal_coherence*.tif"),
        "ps_file_list": _glob_burst(work_dir, "*/PS/ps_pixels_looked.tif"),
        "amp_dispersion_list": _glob_burst(work_dir, "*/PS/amp_dispersion_looked.tif"),
        "shp_count_file_list": _glob_burst(work_dir, "*/linked_phase/shp_count*.tif"),
        "similarity_file_list": _glob_burst(work_dir, "*/linked_phase/*similarity*.tif"),
        "crlb_file_list": crlb_file_list,
        "closure_phase_file_list": closure_phase_file_list,
    }


def run_stitch(cfg) -> None:
    """Stitch burst interferograms into DIR/interferograms (no unwrap)."""
    import logging

    from dolphin._log import setup_logging
    from dolphin.workflows import stitching_bursts

    logger = logging.getLogger("dolphin")
    if cfg.log_file is None:
        cfg.log_file = cfg.work_directory / "dolphin.log"
    setup_logging(logger_name="dolphin", debug=False, filename=cfg.log_file)

    products = collect_burst_stitch_inputs(cfg.work_directory)
    if not products["ifg_file_list"]:
        raise FileNotFoundError(
            f"No burst interferograms under {cfg.work_directory}/*/interferograms. "
            "Run dolphin_wrapped first."
        )
    logger.info("Stitching %s burst interferograms (no unwrap)", len(products["ifg_file_list"]))
    stitching_bursts.run(
        ifg_file_list=products["ifg_file_list"],
        temp_coh_file_list=products["temp_coh_file_list"],
        ps_file_list=products["ps_file_list"],
        crlb_file_list=products["crlb_file_list"],
        closure_phase_file_list=products["closure_phase_file_list"],
        amp_dispersion_list=products["amp_dispersion_list"],
        shp_count_file_list=products["shp_count_file_list"],
        similarity_file_list=products["similarity_file_list"],
        stitched_ifg_dir=cfg.interferogram_network._directory,
        output_options=cfg.output_options,
        file_date_fmt=cfg.input_options.cslc_date_fmt,
        corr_window_size=(11, 11),
    )


def with_hidden_argv(func, *args, **kwargs):
    """Run func with sys.argv stripped so spawned workers do not feed flags to pyre."""
    with hide_argv_from_pyre():
        return func(*args, **kwargs)
