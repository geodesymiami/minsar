#!/usr/bin/env python3
"""
plot_mintpy_summary_pngs.py — Generate MintPy/MiaplPy summary PNGs (no per-ifgram plots).

Creates overview figures such as velocity.png, temporalCoherence.png, network.png,
and geo_velocity.png. Skips per-interferogram plots (unwrapPhase_N.png,
coherence_N.png, connectComponent_N.png, etc.) that make mintpy.plot slow on
large networks.

Example:
    plot_mintpy_summary_pngs.py --dir miaplpy_201411_202606/network_delaunay_4
    plot_mintpy_summary_pngs.py --dir /scratch/05861/tg851601/MyvatnSenD9/miaplpy_201411_202606/network_delaunay_4 -t smallbaselineApp.cfg --dpi 100
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
import time
from pathlib import Path

from mintpy.utils import readfile, utils as ut


DESCRIPTION = (
    "Generate MintPy/MiaplPy summary PNG figures only (no per-ifgram/date plots). "
    "Output PNGs are moved to pic/ by default."
)

EXAMPLES = """Examples:
plot_mintpy_summary_pngs.py --dir miaplpy_201411_202606/network_delaunay_4
plot_mintpy_summary_pngs.py --dir /scratch/05861/tg851601/MyvatnSenD9/miaplpy_201411_202606/network_delaunay_4 -t smallbaselineApp.cfg --dpi 100 --memory 0.2
plot_mintpy_summary_pngs.py --dir mintpy --no-network --outdir pic
"""

# ifgramStack dataset prefixes that expand to one PNG per interferogram
PER_IFGRAM_DATASETS = frozenset({
    'unwrapPhase-',
    'coherence-',
    'connectComponent-',
    'unwrapPhase_bridging-',
    'unwrapPhase_phaseClosure-',
    'unwrapPhase_bridging_phaseClosure-',
})


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=EXAMPLES,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        '--dir', dest='work_dir', metavar='DIR', default='.',
        help='MintPy/MiaplPy processing directory (default: current directory)',
    )
    parser.add_argument(
        '-t', '--template', dest='template_file', metavar='FILE', default='smallbaselineApp.cfg',
        help='MintPy template for plot options and tropo model (default: smallbaselineApp.cfg)',
    )
    parser.add_argument(
        '--dpi', dest='dpi', metavar='INT', type=int, default=None,
        help='Figure DPI for view.py (default: mintpy.plot.dpi from template, else 150)',
    )
    parser.add_argument(
        '--memory', dest='max_memory', metavar='GB', type=float, default=None,
        help='Max memory per view.py call in GB (default: mintpy.plot.maxMemory from template, else 4)',
    )
    parser.add_argument(
        '--num-workers', dest='num_workers', metavar='N', type=int, default=None,
        help='Parallel view.py jobs (default: mintpy.compute.numWorker from template, else 4)',
    )
    parser.add_argument(
        '--outdir', dest='out_dir', metavar='DIR', default='pic',
        help='Directory for PNG output (default: pic)',
    )
    parser.add_argument(
        '--no-network', dest='plot_network', action='store_false',
        help='Skip plot_network.py (network.png, coherenceMatrix.png, etc.)',
    )
    parser.add_argument(
        '--no-move', dest='move_pngs', action='store_false',
        help='Leave PNG files in the processing directory instead of moving to --outdir',
    )
    parser.set_defaults(plot_network=True, move_pngs=True)
    return parser


def _read_plot_settings(template_file: str | None) -> dict:
    """Read plot-related template values with MintPy auto defaults."""
    settings = {
        'dpi': 150,
        'max_plot_memory': 4.0,
        'max_memory': 4.0,
        'num_workers': 4,
        'tropo_model': 'ERA5',
        'cluster': 'local',
    }
    if not template_file or not os.path.isfile(template_file):
        return settings

    template = readfile.read_template(template_file)
    template = ut.check_template_auto_value(template)

    for key, attr in (
        ('mintpy.plot.dpi', 'dpi'),
        ('mintpy.plot.maxMemory', 'max_plot_memory'),
        ('mintpy.compute.maxMemory', 'max_memory'),
        ('mintpy.compute.numWorker', 'num_workers'),
    ):
        if key in template and template[key] not in (None, 'auto', 'none', 'None', ''):
            settings[attr] = template[key]

    if 'mintpy.troposphericDelay.weatherModel' in template:
        val = template['mintpy.troposphericDelay.weatherModel']
        if val and str(val).lower() not in ('auto', 'none', 'no'):
            settings['tropo_model'] = str(val).upper()

    if 'mintpy.compute.cluster' in template:
        settings['cluster'] = template['mintpy.compute.cluster']

    for attr in ('dpi', 'max_plot_memory', 'max_memory', 'num_workers'):
        settings[attr] = abs(float(settings[attr]))
    settings['dpi'] = int(settings['dpi'])
    settings['num_workers'] = int(settings['num_workers'])
    return settings


def _expand_glob_paths(pattern: str) -> list[str]:
    if '*' not in pattern:
        return [pattern] if os.path.isfile(pattern) else []
    return sorted(glob.glob(pattern))


def _build_view_jobs(work_dir: str, template_file: str | None, dpi: int, max_plot_memory: float) -> list[list[str]]:
    """Build view.py argument lists for summary figures only."""
    stack_file, geom_file, lookup_file, _ion_file = ut.check_loaded_dataset(work_dir, print_msg=False)[:4]
    mask_file = os.path.join(work_dir, 'maskTempCoh.h5')
    geo_dir = os.path.join(work_dir, 'geo')

    rel = lambda p: os.path.relpath(p, work_dir) if p else p
    stack_file = rel(stack_file)
    geom_file = rel(geom_file)
    lookup_file = rel(lookup_file)
    mask_file = rel(mask_file)
    geo_dir = rel(geo_dir)

    settings = _read_plot_settings(template_file)
    tropo_model = settings['tropo_model']

    opt4ts = ['--noaxis', '-u', 'cm', '--wrap', '--wrap-range', '-5', '5']
    opt_common = [
        '--dpi', str(dpi),
        '--noverbose', '--nodisplay', '--update',
        '--memory', str(max_plot_memory),
    ]

    iargs_list0: list[list[str]] = [
        ['velocity.h5', '--dem', geom_file, '--mask', mask_file],
        ['temporalCoherence.h5', '-c', 'gray', '-v', '0', '1'],
        ['temporalCoherence_lowpass_gaussian.h5', '-c', 'gray', '-v', '0', '1'],
        ['maskTempCoh.h5', '-c', 'gray', '-v', '0', '1'],
        ['maskTempCoh_lowpass_gaussian.h5', '-c', 'gray', '-v', '0', '1'],
        [geom_file],
        [lookup_file] if lookup_file else [],
        ['avgPhaseVelocity.h5'],
        ['avgSpatialCoh.h5', '-c', 'gray', '-v', '0', '1'],
        ['maskConnComp.h5', '-c', 'gray', '-v', '0', '1'],
        ['numTriNonzeroIntAmbiguity.h5', '--mask', 'no'],
        ['numInvIfgram.h5', '--mask', 'no'],
        ['timeseries.h5'] + opt4ts,
        ['timeseries_*.h5'] + opt4ts,
        [os.path.join(geo_dir, 'geo_maskTempCoh.h5'), '-c', 'gray', '-v', '0', '1'],
        [os.path.join(geo_dir, 'geo_maskTempCoh_lowpass_gaussian.h5'), '-c', 'gray', '-v', '0', '1'],
        [os.path.join(geo_dir, 'geo_temporalCoherence.h5'), '-c', 'gray', '-v', '0', '1'],
        [os.path.join(geo_dir, 'geo_temporalCoherence_lowpass_gaussian.h5'), '-c', 'gray', '-v', '0', '1'],
        [os.path.join(geo_dir, 'geo_avgSpatialCoh.h5'), '-c', 'gray', '-v', '0', '1'],
        [os.path.join(geo_dir, 'geo_velocity.h5'), 'velocity'],
        [os.path.join(geo_dir, 'geo_timeseries*.h5')] + opt4ts,
        [f'velocity{tropo_model}.h5', '--mask', 'no'],
    ]

    # MiaplPy PS mask (parent dir) and geocoded PS mask
    for mask_ps in ('../maskPS.h5', 'maskPS.h5', os.path.join(geo_dir, 'geo_maskPS.h5')):
        iargs_list0.append([mask_ps, '-c', 'gray', '-v', '0', '1'])

    iargs_list: list[list[str]] = []
    for iargs in iargs_list0:
        if not iargs:
            continue
        fname, args = iargs[0], iargs[1:]
        if stack_file and fname == stack_file and args and args[0] in PER_IFGRAM_DATASETS:
            continue
        if '*' in fname:
            for path in _expand_glob_paths(fname):
                iargs_list.append([path] + args)
        elif os.path.isfile(fname):
            iargs_list.append([fname] + args)

    return [opt_common + iargs for iargs in iargs_list]


def _run_plot_network(work_dir: str, template_file: str | None) -> None:
    stack_file, _, _, _ = ut.check_loaded_dataset(work_dir, print_msg=False)[:4]
    if not stack_file:
        print('Warning: ifgramStack not found; skip plot_network.py')
        return

    iargs = [stack_file, '--nodisplay']
    if template_file and os.path.isfile(template_file):
        iargs += ['-t', template_file]

    ds_names = readfile.get_dataset_list(stack_file)
    if any('phase' in name.lower() for name in ds_names):
        iargs += ['-d', 'coherence', '-v', '0.2', '1.0']
    elif any('offset' in name.lower() for name in ds_names):
        iargs += ['-d', 'offsetSNR', '-v', '0', '20']

    print('plot_network.py', ' '.join(iargs))
    import mintpy.cli.plot_network
    mintpy.cli.plot_network.main(iargs)


def _run_timeseries_rms(template_file: str | None) -> None:
    res_file = 'timeseriesResidual.h5'
    if not os.path.isfile(res_file):
        print(f'No {res_file}; skip timeseries_rms.py')
        return
    iargs = [res_file]
    if template_file and os.path.isfile(template_file):
        iargs += ['-t', template_file]
    print('timeseries_rms.py', ' '.join(iargs))
    import mintpy.cli.timeseries_rms
    mintpy.cli.timeseries_rms.main(iargs)


def _run_view_jobs(
    iargs_list: list[list[str]],
    max_memory: float,
    max_plot_memory: float,
    num_workers: int,
    cluster: str,
) -> None:
    import mintpy.cli.view

    if not iargs_list:
        print('No summary datasets found to plot.')
        return

    run_parallel = False
    num_cores = 1
    if cluster:
        from mintpy.utils import cluster as mintpy_cluster
        num_workers_fmt = mintpy_cluster.DaskCluster.format_num_worker(cluster, num_workers)
        num_cores, run_parallel, Parallel, delayed = ut.check_parallel(
            len(iargs_list),
            print_msg=False,
            maxParallelNum=num_workers_fmt,
        )
        plot_memory = 1.5 if 2.0 < max_plot_memory <= 4.0 else 1.5 * (max_plot_memory / 4.0)
        num_cores = min(num_cores, max(int(max_memory / plot_memory), 1))

    if run_parallel and num_cores > 1:
        print(f'parallel view.py using {num_cores} workers for {len(iargs_list)} summary figure(s) ...')
        Parallel(n_jobs=num_cores)(delayed(mintpy.cli.view.main)(iargs) for iargs in iargs_list)
    else:
        for iargs in iargs_list:
            mintpy.cli.view.main(iargs)


def _collect_pngs(work_dir: str, out_dir: str) -> list[str]:
    out_path = Path(work_dir) / out_dir
    out_path.mkdir(parents=True, exist_ok=True)

    png_files: list[str] = []
    for pattern in ('*.png', 'geo/*.png'):
        png_files.extend(glob.glob(os.path.join(work_dir, pattern)))

    moved: list[str] = []
    for png in sorted(set(png_files)):
        dest = out_path / os.path.basename(png)
        if os.path.abspath(png) == os.path.abspath(dest):
            moved.append(str(dest))
            continue
        shutil.move(png, dest)
        moved.append(str(dest))
    return moved


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    work_dir = os.path.abspath(args.work_dir)
    if not os.path.isdir(work_dir):
        print(f'Error: directory not found: {work_dir}', file=sys.stderr)
        return 1

    template_file = args.template_file
    if template_file and not os.path.isabs(template_file):
        template_file = os.path.join(work_dir, template_file)
    if template_file and not os.path.isfile(template_file):
        print(f'Warning: template not found: {template_file}; using defaults')
        template_file = None

    settings = _read_plot_settings(template_file)
    dpi = args.dpi if args.dpi is not None else settings['dpi']
    max_plot_memory = args.max_memory if args.max_memory is not None else settings['max_plot_memory']
    max_memory = settings['max_memory']
    num_workers = args.num_workers if args.num_workers is not None else settings['num_workers']

    cwd = os.getcwd()
    os.chdir(work_dir)
    start = time.time()

    try:
        if args.plot_network:
            _run_plot_network(work_dir, template_file)

        iargs_list = _build_view_jobs(work_dir, template_file, dpi, max_plot_memory)
        print(f'plotting {len(iargs_list)} summary dataset(s) with view.py ...')
        _run_view_jobs(iargs_list, max_memory, max_plot_memory, num_workers, settings['cluster'])
        _run_timeseries_rms(template_file)

        if args.move_pngs:
            moved = _collect_pngs(work_dir, args.out_dir)
            print(f'moved {len(moved)} PNG file(s) to {args.out_dir}/')
        else:
            print('PNG files left in processing directory (--no-move).')
    finally:
        os.chdir(cwd)

    mins, secs = divmod(time.time() - start, 60)
    print(f'time used: {int(mins):02d} mins {secs:.1f} secs.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
