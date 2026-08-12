#!/usr/bin/env python3
"""Collect unfinished miaplpy unwrap tasks and write PVC launcher jobfiles."""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from pathlib import Path

try:
    import h5py
except ImportError:  # pragma: no cover
    h5py = None

RUN05_BASE = 'run_05_miaplpy_unwrap_ifgram'
UNFINISHED_BASE = f'{RUN05_BASE}_unfinished'
BYTES_PER_PIXEL = 420
PPN_SAFETY_MARGIN = 1
DEFAULT_QUEUE = 'pvc'
DEFAULT_WALLTIME = '12:00:00'


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            'Collect unfinished miaplpy unwrap tasks in new jobfile(s) '
            '(using run_05_miaplpy_unwrap_ifgram_*)'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Examples:\n'
            '  complete_unfinished_unwrap_tasks.py '
            'miaplpy_Big1_202001_202608/network_delaunay_4/run_files\n'
            '  complete_unfinished_unwrap_tasks.py '
            '/scratch/05861/tg851601/EtnaSenA44/miaplpy_Big1_202001_202608/network_delaunay_4/run_files'
        ),
    )
    parser.add_argument(
        'run_files_dir',
        help='Path to network*/run_files (absolute or relative to cwd / EtnaSenA44 on scratch)',
    )
    parser.add_argument(
        '--queue',
        default=DEFAULT_QUEUE,
        help=f'Slurm partition (default: {DEFAULT_QUEUE})',
    )
    parser.add_argument(
        '--walltime',
        default=DEFAULT_WALLTIME,
        help=f'SBATCH walltime (default: {DEFAULT_WALLTIME})',
    )
    parser.add_argument(
        '--bytes-per-pixel',
        type=float,
        default=BYTES_PER_PIXEL,
        help=f'Snaphu memory model in bytes/pixel (default: {BYTES_PER_PIXEL})',
    )
    return parser


def resolve_run_files_dir(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if path.is_dir():
        return path.resolve()

    candidates = [
        Path.cwd() / path,
        Path(os.environ.get('SCRATCH_DIR', '')) / path if os.environ.get('SCRATCH_DIR') else None,
    ]
    scratch = os.environ.get('SCRATCHDIR') or os.environ.get('SCRATCH')
    if scratch:
        candidates.append(Path(scratch) / path)
        candidates.append(Path(scratch) / 'EtnaSenA44' / path)

    for cand in candidates:
        if cand is not None and cand.is_dir():
            return cand.resolve()

    raise FileNotFoundError(f'run_files directory not found: {path_str}')


def load_queue_row(queue_name: str) -> dict:
    cfg_candidates = []
    minsar_home = os.getenv('MINSAR_HOME') or os.getenv('RSMASINSAR_HOME')
    if minsar_home:
        cfg_candidates.append(Path(minsar_home) / 'minsar' / 'defaults' / 'queues.cfg')
    cfg_candidates.append(Path(__file__).resolve().parent / 'queues.cfg')

    cfg = next((p for p in cfg_candidates if p.is_file()), None)
    if cfg is None:
        raise FileNotFoundError(
            'queues.cfg not found (set MINSAR_HOME or place queues.cfg next to this script)'
        )

    platform = os.getenv('PLATFORM_NAME', 'stampede3')
    with open(cfg, 'r', encoding='utf-8') as f:
        lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith('#')]
    header = lines[0].split()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < len(header):
            continue
        row = dict(zip(header, parts))
        if row.get('PLATFORM_NAME') == platform and row.get('QUEUENAME') == queue_name:
            return {
                'queue': queue_name,
                'cpus_per_node': int(row['CPUS_PER_NODE']),
                'mem_per_node_mb': int(row['MEM_PER_NODE']),
                'max_nodes_pj': int(row['MAX_NODES_PJ']),
            }
    raise RuntimeError(
        f'No queues.cfg row for PLATFORM_NAME={platform} QUEUENAME={queue_name} in {cfg}'
    )


def parse_job_template(run_files_dir: Path) -> dict:
    jobs = sorted(run_files_dir.glob(f'{RUN05_BASE}_*.job'))
    jobs = [j for j in jobs if 'unfinished' not in j.name]
    if not jobs:
        raise FileNotFoundError(f'No {RUN05_BASE}_*.job template in {run_files_dir}')

    text = jobs[0].read_text(errors='replace')

    def grab(pattern: str, default=None):
        match = re.search(pattern, text, re.M)
        return match.group(1) if match else default

    return {
        'account': grab(r'^#SBATCH\s+-A\s+(\S+)'),
        'mail_user': grab(r'^#SBATCH\s+--mail-user=(\S+)'),
        'mail_type': grab(r'^#SBATCH\s+--mail-type=(\S+)', 'fail'),
        'omp_num_threads': int(grab(r'^export OMP_NUM_THREADS=(\d+)', '1')),
    }


def extract_unwrap_command(line: str) -> str:
    match = re.search(r'(unwrap_ifgram\.py\b.*)', line)
    if not match:
        return ''
    cmd = match.group(1)
    cmd = re.split(r'\s+2>', cmd, maxsplit=1)[0]
    cmd = re.split(r'\s+>', cmd, maxsplit=1)[0]
    return cmd.strip()


def parse_unwrapped_ifg(cmd: str) -> str | None:
    match = re.search(r'--unwrapped_ifg\s+(\S+)', cmd)
    return match.group(1) if match else None


def parse_num_tiles_from_command(cmd: str) -> int:
    match = re.search(r'--num_tiles\s+(\d+)', cmd)
    return max(1, int(match.group(1))) if match else 1


def parse_length_width_from_command(cmd: str) -> tuple[int | None, int | None]:
    length_match = re.search(r'--length\s+(\d+)', cmd)
    width_match = re.search(r'--width\s+(\d+)', cmd)
    length = int(length_match.group(1)) if length_match else None
    width = int(width_match.group(1)) if width_match else None
    return length, width


def read_slc_stack_size(miaplpy_dir: Path) -> tuple[int, int]:
    if h5py is None:
        raise RuntimeError(
            'h5py is required to read slcStack.h5 when --length/--width are absent from tasks'
        )
    h5_path = miaplpy_dir / 'inputs' / 'slcStack.h5'
    if not h5_path.is_file():
        raise FileNotFoundError(f'Missing {h5_path}')
    with h5py.File(h5_path, 'r') as f:
        shape = f['/slc'].shape
        if len(shape) < 3:
            raise RuntimeError(f'Unexpected /slc shape {shape} in {h5_path}')
        return int(shape[1]), int(shape[2])


def infer_scene_size(run_files_dir: Path, tasks: list[str]) -> tuple[int, int]:
    for cmd in tasks:
        length, width = parse_length_width_from_command(cmd)
        if length and width:
            return length, width

    miaplpy_dir = run_files_dir.parent.parent
    return read_slc_stack_size(miaplpy_dir)


def mem_per_task_mib(length: int, width: int, bytes_per_pixel: float, num_tiles: int = 1) -> float:
    full = length * width * bytes_per_pixel / (1024.0 ** 2)
    ntiles = max(1, int(num_tiles))
    return full if ntiles <= 1 else full / float(ntiles)


def compute_ppn(
    mem_mib: float,
    mem_per_node_mb: int,
    cpus_per_node: int,
    num_tiles: int = 1,
) -> int:
    if mem_mib <= 0:
        mem_ppn = cpus_per_node
    else:
        raw_ppn = int(math.floor(mem_per_node_mb / mem_mib))
        mem_ppn = min(cpus_per_node, max(1, raw_ppn - PPN_SAFETY_MARGIN))

    ntiles = max(1, int(num_tiles))
    if ntiles <= 1:
        return mem_ppn
    cpu_ppn = max(1, int(cpus_per_node // ntiles))
    return min(mem_ppn, cpu_ppn)


def list_source_launcher_files(run_files_dir: Path) -> list[Path]:
    files = []
    for path in sorted(run_files_dir.iterdir()):
        if not path.is_file():
            continue
        if re.fullmatch(rf'{RUN05_BASE}_\d+', path.name):
            files.append(path)
    if not files and (run_files_dir / RUN05_BASE).is_file():
        files.append(run_files_dir / RUN05_BASE)
    if not files:
        raise FileNotFoundError(
            f'No launcher files matching {RUN05_BASE}_N or {RUN05_BASE} in {run_files_dir}'
        )
    return files


def collect_unfinished_tasks(run_files_dir: Path) -> tuple[list[str], dict[str, int]]:
    seen_unw: set[str] = set()
    unfinished: list[str] = []
    stats = {'total': 0, 'finished': 0, 'unfinished': 0, 'duplicate': 0}

    for launcher in list_source_launcher_files(run_files_dir):
        for line in launcher.read_text(errors='replace').splitlines():
            if 'unwrap_ifgram.py' not in line:
                continue
            cmd = extract_unwrap_command(line.strip())
            if not cmd:
                continue
            stats['total'] += 1
            unw = parse_unwrapped_ifg(cmd)
            if not unw:
                continue
            if unw in seen_unw:
                stats['duplicate'] += 1
                continue
            seen_unw.add(unw)
            if Path(unw).is_file():
                stats['finished'] += 1
                continue
            stats['unfinished'] += 1
            unfinished.append(cmd + '\n')

    return unfinished, stats


def plan_jobs(
    n_tasks: int,
    ppn: int,
    max_nodes_pj: int,
) -> list[tuple[int, int, int, int]]:
    """Return (start, end, n_nodes, job_index) slices for unfinished tasks."""
    if n_tasks <= 0:
        return []

    nodes_needed = int(math.ceil(n_tasks / float(ppn)))
    nodes_for_all = min(max_nodes_pj, max(1, nodes_needed))
    if nodes_for_all >= nodes_needed:
        return [(0, n_tasks, nodes_for_all, 0)]

    n_jobfiles = int(math.ceil(nodes_needed / float(max_nodes_pj)))
    tasks_per_job = int(math.ceil(n_tasks / float(n_jobfiles)))

    plans = []
    for job_index in range(n_jobfiles):
        start = job_index * tasks_per_job
        end = min(n_tasks, start + tasks_per_job)
        if start >= end:
            break
        n_chunk = end - start
        n_nodes = min(max_nodes_pj, max(1, int(math.ceil(n_chunk / float(ppn)))))
        plans.append((start, end, n_nodes, job_index))
    return plans


def wrap_launcher_task(cmd: str, batch_path: Path) -> str:
    base = str(batch_path.resolve())
    bare = cmd.strip()
    return (
        f'/usr/bin/time -v -o {base}__$LAUNCHER_JID.time_log {bare} '
        f'> {base}__$LAUNCHER_JID.o 2>{base}__$LAUNCHER_JID.e\n'
    )


def write_jobfile(
    job_path: Path,
    batch_path: Path,
    template: dict,
    queue_info: dict,
    n_nodes: int,
    ppn: int,
    walltime: str,
) -> None:
    n_tasks_slurm = n_nodes * queue_info['cpus_per_node']
    job_name = batch_path.name
    out_dir = str(batch_path.parent.resolve())
    lines = ['#! /bin/bash\n']
    lines.append(f'#SBATCH -J {job_name}\n')
    if template.get('account'):
        lines.append(f"#SBATCH -A {template['account']}\n")
    if template.get('mail_user'):
        lines.append(f"#SBATCH --mail-user={template['mail_user']}\n")
        lines.append(f"#SBATCH --mail-type={template.get('mail_type', 'fail')}\n")
    lines.append(f'#SBATCH -N {n_nodes}\n')
    lines.append(f'#SBATCH -n {n_tasks_slurm}\n')
    lines.append(f'#SBATCH -o {out_dir}/{job_name}_%J.o\n')
    lines.append(f'#SBATCH -e {out_dir}/{job_name}_%J.e\n')
    lines.append(f"#SBATCH -p {queue_info['queue']}\n")
    lines.append(f'#SBATCH -t {walltime}\n')
    lines.append('################################################\n')
    lines.append('# execute tasks with launcher\n')
    lines.append('################################################\n')
    lines.append(f"export OMP_NUM_THREADS={template.get('omp_num_threads', 1)}\n")
    lines.append(f'export LAUNCHER_PPN={ppn}\n')
    lines.append(f'export LAUNCHER_NHOSTS={n_nodes}\n')
    lines.append(f'export LAUNCHER_JOB_FILE={batch_path.resolve()}\n')
    lines.append('export LAUNCHER_WORKDIR=/dev/shm\n')
    lines.append('cd /dev/shm\n')
    lines.append('$LAUNCHER_DIR/paramrun\n')
    job_path.write_text(''.join(lines))


def main(iargs: list[str] | None = None) -> int:
    parser = create_parser()
    inps = parser.parse_args(args=iargs)

    run_files_dir = resolve_run_files_dir(inps.run_files_dir)
    template = parse_job_template(run_files_dir)
    queue_info = load_queue_row(inps.queue)

    unfinished, stats = collect_unfinished_tasks(run_files_dir)
    if not unfinished:
        print(f'All unwrap tasks finished in {run_files_dir}')
        print(
            f"Scanned {stats['total']} command lines: "
            f"{stats['finished']} finished, {stats['duplicate']} duplicates skipped"
        )
        return 0

    num_tiles = max(parse_num_tiles_from_command(cmd) for cmd in unfinished)
    length, width = infer_scene_size(run_files_dir, unfinished)
    mem_mib = mem_per_task_mib(length, width, inps.bytes_per_pixel, num_tiles=num_tiles)
    ppn = compute_ppn(
        mem_mib,
        queue_info['mem_per_node_mb'],
        queue_info['cpus_per_node'],
        num_tiles=num_tiles,
    )

    n_tasks = len(unfinished)
    plans = plan_jobs(n_tasks, ppn, queue_info['max_nodes_pj'])
    total_nodes = sum(p[2] for p in plans)
    concurrent = sum(p[2] * ppn for p in plans)
    waves = int(math.ceil(n_tasks / float(concurrent))) if concurrent else 0
    mem_gb = queue_info['mem_per_node_mb'] / 1000.0

    print(f'run_files: {run_files_dir}')
    print(
        f"tasks: {stats['unfinished']} unfinished / {stats['finished']} finished "
        f"({stats['total']} lines, {stats['duplicate']} duplicates ignored)"
    )
    print(
        f"queue={inps.queue}  nodes={queue_info['cpus_per_node']} cpus, "
        f"{mem_gb:.0f} GB RAM, MAX_NODES_PJ={queue_info['max_nodes_pj']}"
    )
    print(
        f'scene={length}x{width}  num_tiles={num_tiles}  '
        f'mem_per_task={mem_mib:.1f} MiB  LAUNCHER_PPN={ppn}'
    )
    print(
        f'jobfiles={len(plans)}  total_nodes={total_nodes}  '
        f'concurrent_slots={concurrent}  estimated_waves={waves}  walltime={inps.walltime}'
    )
    for start, end, n_nodes, job_index in plans:
        print(
            f'  {UNFINISHED_BASE}_{job_index}: tasks[{start}:{end}] '
            f'n={end - start}  N={n_nodes}  LAUNCHER_PPN={ppn}'
        )

    for start, end, n_nodes, job_index in plans:
        batch_path = run_files_dir / f'{UNFINISHED_BASE}_{job_index}'
        job_path = run_files_dir / f'{UNFINISHED_BASE}_{job_index}.job'
        chunk = unfinished[start:end]
        wrapped = [wrap_launcher_task(cmd, batch_path) for cmd in chunk]
        batch_path.write_text(''.join(wrapped))
        write_jobfile(job_path, batch_path, template, queue_info, n_nodes, ppn, inps.walltime)
        print(f'Wrote {job_path.name} and {batch_path.name} ({len(chunk)} tasks)')

    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
