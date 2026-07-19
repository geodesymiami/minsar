#!/usr/bin/env python3
"""Resize miaplpy unwrap (run_05) launcher jobfiles from slcStack.h5 dimensions.

Estimates snaphu memory from LENGTH x WIDTH (420 bytes/pixel), sets LAUNCHER_PPN,
and by default increases the node number so the job finishes as quickly as possible.
If the required node count exceeds MAX_NODES_PJ (16 on skx-dev), splits into multiple
run_05_miaplpy_unwrap_ifgram_*.job files.

Requires miaplpy step 1 (load_data) so that inputs/slcStack.h5 exists.

Phase 2 recipe (manual; automate later in minsarApp / run_workflow)::

    # 1) Run only load_data
    run_workflow.bash $TE/<site>.template --dir <miaplpy_dir> --start 1 --stop 1
    #    or: --start load_data --stop load_data

    # 2) Resize unwrap jobfiles
    resize_miaplpy_unwrap_jobfiles.py <miaplpy_dir>

    # 3) Continue from step 2
    run_workflow.bash $TE/<site>.template --dir <miaplpy_dir> --start 2
    #    or: --start phase_linking

Examples::

    resize_miaplpy_unwrap_jobfiles.py miaplpy_202001_202412
    resize_miaplpy_unwrap_jobfiles.py miaplpy_202001_202412 --dry-run
    resize_miaplpy_unwrap_jobfiles.py miaplpy_202001_202412 --no-scale-node-number
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from pathlib import Path

try:
    import h5py
except ImportError as exc:  # pragma: no cover
    print(f'Error: h5py is required ({exc})', file=sys.stderr)
    sys.exit(1)

BYTES_PER_PIXEL = 420
RUN05_BASE = 'run_05_miaplpy_unwrap_ifgram'


def create_parser():
    parser = argparse.ArgumentParser(
        description='Resize miaplpy run_05 unwrap jobfiles from slcStack.h5 size.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        'miaplpy_dir',
        type=str,
        help='MiaplPy directory (e.g. miaplpy_202001_202412) containing inputs/slcStack.h5',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print planned changes without modifying files',
    )
    parser.add_argument(
        '--no-scale-node-number',
        action='store_true',
        help='Keep existing node number / jobfile count; only update LAUNCHER_PPN',
    )
    parser.add_argument(
        '--queue',
        type=str,
        default=None,
        help='Queue name (default: from existing run_05*.job #SBATCH -p, else QUEUENAME env)',
    )
    parser.add_argument(
        '--bytes-per-pixel',
        type=float,
        default=BYTES_PER_PIXEL,
        help=f'Snaphu memory model in bytes/pixel (default: {BYTES_PER_PIXEL})',
    )
    return parser


def resolve_miaplpy_dir(path_str: str) -> Path:
    path = Path(path_str).expanduser().resolve()
    if not path.is_dir():
        raise FileNotFoundError(f'miaplpy directory not found: {path}')
    return path


def find_run_files_dir(miaplpy_dir: Path) -> Path:
    candidates = sorted(miaplpy_dir.glob('network*/run_files'))
    if not candidates:
        raise FileNotFoundError(f'No network*/run_files under {miaplpy_dir}')
    # Prefer a directory that already has run_05 files
    for cand in candidates:
        if list(cand.glob(f'{RUN05_BASE}*')):
            return cand
    return candidates[0]


def read_slc_stack_size(miaplpy_dir: Path) -> tuple[int, int]:
    h5_path = miaplpy_dir / 'inputs' / 'slcStack.h5'
    if not h5_path.is_file():
        raise FileNotFoundError(
            f'Missing {h5_path}. Run miaplpy load_data (step 1) first.'
        )
    with h5py.File(h5_path, 'r') as f:
        if '/slc' not in f:
            raise RuntimeError(f'No /slc dataset in {h5_path}')
        shape = f['/slc'].shape
        if len(shape) < 3:
            raise RuntimeError(f'Unexpected /slc shape {shape} in {h5_path}')
        length, width = int(shape[1]), int(shape[2])
    return length, width


def load_queue_row(queue_name: str) -> dict:
    minsar_home = os.getenv('MINSAR_HOME') or os.getenv('RSMASINSAR_HOME')
    if minsar_home:
        cfg = Path(minsar_home) / 'minsar' / 'defaults' / 'queues.cfg'
    else:
        cfg = Path(__file__).resolve().parents[1] / 'defaults' / 'queues.cfg'
    if not cfg.is_file():
        raise FileNotFoundError(f'queues.cfg not found: {cfg}')

    platform = os.getenv('PLATFORM_NAME', 'stampede3')
    with open(cfg, 'r') as f:
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
                'max_walltime': row.get('MAX_WALLTIME', 'n/a'),
            }
    raise RuntimeError(
        f'No queues.cfg row for PLATFORM_NAME={platform} QUEUENAME={queue_name} in {cfg}'
    )


def infer_queue_from_jobfiles(run_files_dir: Path) -> str | None:
    jobs = sorted(run_files_dir.glob(f'{RUN05_BASE}_*.job'))
    if not jobs:
        jobs = sorted(run_files_dir.glob(f'{RUN05_BASE}*.job'))
    for job in jobs:
        text = job.read_text(errors='replace')
        m = re.search(r'^#SBATCH\s+-p\s+(\S+)', text, re.M)
        if m:
            return m.group(1)
    return None


def parse_job_template(job_path: Path) -> dict:
    """Extract reusable SBATCH fields from an existing unwrap jobfile."""
    text = job_path.read_text(errors='replace')
    def grab(pattern, default=None):
        m = re.search(pattern, text, re.M)
        return m.group(1) if m else default

    return {
        'account': grab(r'^#SBATCH\s+-A\s+(\S+)'),
        'mail_user': grab(r'^#SBATCH\s+--mail-user=(\S+)'),
        'mail_type': grab(r'^#SBATCH\s+--mail-type=(\S+)', 'fail'),
        'queue': grab(r'^#SBATCH\s+-p\s+(\S+)'),
        'walltime': grab(r'^#SBATCH\s+-t\s+(\S+)', '2:00:00'),
        'omp_num_threads': int(grab(r'^export OMP_NUM_THREADS=(\d+)', '1')),
        'n_nodes': int(grab(r'^#SBATCH\s+-N\s+(\d+)', '1')),
        'launcher_ppn': int(grab(r'^export LAUNCHER_PPN=(\d+)', '1')),
        'text': text,
    }


def read_unwrap_tasks(run_files_dir: Path) -> list[str]:
    """Return bare unwrap_ifgram.py command lines (no time wrapper / redirects)."""
    master = run_files_dir / RUN05_BASE
    tasks: list[str] = []
    if master.is_file():
        for line in master.read_text(errors='replace').splitlines():
            s = line.strip()
            if not s or s.startswith('wait') or s.startswith('#'):
                continue
            if 'unwrap_ifgram.py' in s:
                # master may already be bare commands
                cmd = s
                if cmd.startswith('/usr/bin/time'):
                    cmd = extract_unwrap_command(cmd)
                tasks.append(cmd if cmd.endswith('\n') else cmd + '\n')
    if tasks:
        return tasks

    # Fall back: strip wrappers from existing launcher files (_0, _1, ...)
    for launcher in sorted(run_files_dir.iterdir()):
        if not launcher.is_file():
            continue
        if re.fullmatch(rf'{RUN05_BASE}_\d+', launcher.name) is None:
            continue
        for line in launcher.read_text(errors='replace').splitlines():
            if 'unwrap_ifgram.py' not in line:
                continue
            cmd = extract_unwrap_command(line.strip())
            if cmd:
                tasks.append(cmd + '\n')
    if not tasks:
        raise FileNotFoundError(
            f'No unwrap tasks found in {run_files_dir}/{RUN05_BASE} or {RUN05_BASE}_*'
        )
    return tasks


def extract_unwrap_command(line: str) -> str:
    m = re.search(r'(unwrap_ifgram\.py\b.*)', line)
    if not m:
        return ''
    cmd = m.group(1)
    # drop stdout/stderr redirections
    cmd = re.split(r'\s+2>', cmd, maxsplit=1)[0]
    cmd = re.split(r'\s+>', cmd, maxsplit=1)[0]
    return cmd.strip()


def mem_per_task_mib(length: int, width: int, bytes_per_pixel: float) -> float:
    return length * width * bytes_per_pixel / (1024.0 ** 2)


def compute_ppn(mem_mib: float, mem_per_node_mb: int, cpus_per_node: int) -> int:
    if mem_mib <= 0:
        return cpus_per_node
    return min(cpus_per_node, max(1, int(math.floor(mem_per_node_mb / mem_mib))))


def max_width_for_ppn48(length: int, mem_per_node_mb: int, bytes_per_pixel: float,
                        cpus_for_ref: int = 48) -> int:
    max_mem_per_task = mem_per_node_mb / float(cpus_for_ref)
    max_pixels = max_mem_per_task * (1024.0 ** 2) / bytes_per_pixel
    return max(1, int(math.floor(max_pixels / length)))


def plan_job_split(n_tasks: int, ppn: int, max_nodes_pj: int,
                   scale_node_number: bool, existing_nodes: int) -> list[tuple[int, int, int, int]]:
    """Return list of (start, end, n_nodes, job_index) for task slices [start:end]."""
    if n_tasks <= 0:
        return []

    if not scale_node_number:
        n_nodes = max(1, existing_nodes)
        return [(0, n_tasks, n_nodes, 0)]

    nodes_needed = int(math.ceil(n_tasks / float(ppn)))
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
    """Match existing minsar launcher wrapping with /usr/bin/time and LAUNCHER_JID."""
    base = str(batch_path.resolve())
    bare = cmd.strip()
    return (
        f'/usr/bin/time -v -o {base}__$LAUNCHER_JID.time_log {bare} '
        f'> {base}__$LAUNCHER_JID.o 2>{base}__$LAUNCHER_JID.e\n'
    )


def write_jobfile(job_path: Path, batch_path: Path, template: dict, queue_info: dict,
                  n_nodes: int, ppn: int) -> None:
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
    lines.append(f"#SBATCH -t {template.get('walltime', '2:00:00')}\n")
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


def remove_stale_run05_splits(run_files_dir: Path, keep_indices: set[int]) -> list[str]:
    """Remove old run_05_* launcher/job files whose index is not in keep_indices."""
    removed = []
    for path in run_files_dir.glob(f'{RUN05_BASE}_*'):
        m = re.match(rf'{RUN05_BASE}_(\d+)(\.job)?$', path.name)
        if not m:
            continue
        idx = int(m.group(1))
        if idx not in keep_indices:
            path.unlink(missing_ok=True)
            removed.append(path.name)
    return removed


def main(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(args=iargs)

    miaplpy_dir = resolve_miaplpy_dir(inps.miaplpy_dir)
    run_files_dir = find_run_files_dir(miaplpy_dir)
    length, width = read_slc_stack_size(miaplpy_dir)

    existing_jobs = sorted(run_files_dir.glob(f'{RUN05_BASE}_*.job'))
    if not existing_jobs:
        raise FileNotFoundError(
            f'No {RUN05_BASE}_*.job in {run_files_dir}. Create miaplpy jobfiles first.'
        )
    template = parse_job_template(existing_jobs[0])

    queue_name = (
        inps.queue
        or template.get('queue')
        or infer_queue_from_jobfiles(run_files_dir)
        or os.getenv('QUEUENAME')
        or 'skx-dev'
    )
    queue_info = load_queue_row(queue_name)
    queue_info['queue'] = queue_name

    tasks = read_unwrap_tasks(run_files_dir)
    n_tasks = len(tasks)
    mem_mib = mem_per_task_mib(length, width, inps.bytes_per_pixel)
    ppn = compute_ppn(mem_mib, queue_info['mem_per_node_mb'], queue_info['cpus_per_node'])
    www = max_width_for_ppn48(
        length, queue_info['mem_per_node_mb'], inps.bytes_per_pixel,
        cpus_for_ref=queue_info['cpus_per_node'],
    )

    # queues.cfg MEM_PER_NODE is in MB; SKX 192000 -> 192 GB
    mem_gb = int(round(queue_info['mem_per_node_mb'] / 1000.0))

    print(
        f"Queue {queue_name} with node memory {mem_gb} GB, file size {length}x{width}. "
        f"For {queue_info['cpus_per_node']} simultaneous jobs max file size is {length}x{www}"
    )

    scale = not inps.no_scale_node_number
    plans = plan_job_split(
        n_tasks, ppn, queue_info['max_nodes_pj'], scale, template['n_nodes']
    )
    total_nodes = sum(p[2] for p in plans)
    concurrent = sum(p[2] * ppn for p in plans)
    waves = int(math.ceil(n_tasks / float(concurrent))) if concurrent else 0

    print(f'bytes_per_pixel={inps.bytes_per_pixel:g}  mem_per_task={mem_mib:.1f} MiB  '
          f'LAUNCHER_PPN={ppn}  n_tasks={n_tasks}')
    print(f'scale_node_number={scale}  jobfiles={len(plans)}  total_nodes={total_nodes}  '
          f'MAX_NODES_PJ={queue_info["max_nodes_pj"]}  estimated_waves={waves}')
    for start, end, n_nodes, job_index in plans:
        print(f'  {RUN05_BASE}_{job_index}.job: tasks[{start}:{end}] '
              f'n_tasks={end-start}  N={n_nodes}  LAUNCHER_NHOSTS={n_nodes}  '
              f'LAUNCHER_PPN={ppn}')

    if queue_info.get('max_walltime') and queue_info['max_walltime'] not in ('n/a', None):
        if waves > 1 and queue_name.endswith('dev'):
            print(
                f'Warning: estimated {waves} waves on {queue_name} '
                f'(MAX_WALLTIME={queue_info["max_walltime"]}); check walltime if unwraps are slow.'
            )

    if inps.dry_run:
        print('Dry run: no files modified.')
        return 0

    keep = {p[3] for p in plans}
    removed = remove_stale_run05_splits(run_files_dir, keep)
    if removed:
        print('Removed stale files: ' + ', '.join(sorted(removed)))

    for start, end, n_nodes, job_index in plans:
        batch_path = run_files_dir / f'{RUN05_BASE}_{job_index}'
        job_path = run_files_dir / f'{RUN05_BASE}_{job_index}.job'
        chunk = tasks[start:end]
        wrapped = [wrap_launcher_task(cmd, batch_path) for cmd in chunk]
        batch_path.write_text(''.join(wrapped))
        write_jobfile(job_path, batch_path, template, queue_info, n_nodes, ppn)
        print(f'Wrote {job_path.name} and {batch_path.name} ({end-start} tasks, N={n_nodes}, PPN={ppn})')

    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
