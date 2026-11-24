#!/usr/bin/env python3
"""
Per-granule download -> verify -> post-download command (e.g. unpack), restartable.

The state of a granule is read from the file system, never from a status file:

    <dir>/ARCHIVED_FILES/X.zip   downloaded and post-processed      -> skip
    <dir>/X.zip                  download complete                  -> post-download command only
    <dir>/X.zip.part             download interrupted               -> resume at its current size
    nothing                      not started                        -> download

A download is written to X.zip.part and renamed to X.zip only once its size matches the
catalog and the zip opens, so a file named X.zip is always complete.

Timing is appended to <dir>/download_timing.csv (one row per attempt) and, while a
download runs, to <dir>/X.download.log (one line per PROGRESS_INTERVAL seconds).
"""

import csv
import datetime
import os
import shlex
import signal
import socket
import subprocess
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

TIMING_FILE = 'download_timing.csv'
ARCHIVE_DIR = 'ARCHIVED_FILES'
PROGRESS_INTERVAL = 60        # seconds between lines in X.download.log
CHUNK_SIZE = 1024 * 1024
MAX_ATTEMPTS = 3
TIMING_FIELDS = [
    'granule', 'step', 'attempt', 'status', 'start', 'end', 'seconds', 'bytes_this_attempt',
    'resumed_from_byte', 'mean_MB_per_s', 'seconds_to_first_byte', 'http_status', 'final_host',
    'slurm_job_id', 'node', 'message',
]
MB = 1024 * 1024
GB = 1024 * MB


class Interrupted(Exception):
    """Raised inside a worker when the run was asked to stop (SIGTERM / SIGINT)."""


def _now():
    return datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def product_name_url_bytes(product):
    """Return (file name, url, expected size in bytes or None) for an asf_search product."""
    props = getattr(product, 'properties', None) or {}
    url = props.get('url')
    name = props.get('fileName') or os.path.basename(urlparse(url).path)
    size = props.get('bytes')
    if isinstance(size, dict):
        entry = size.get(name)
        size = entry.get('bytes') if isinstance(entry, dict) else entry
    try:
        size = int(size)
    except (TypeError, ValueError):
        size = None
    return name, url, size if size and size > 0 else None


def is_valid_zip(path, name=None):
    """True if name (default: path) is not a zip file name, or path opens as a zip (central directory present)."""
    if not (name or path).lower().endswith('.zip'):
        return True
    try:
        with zipfile.ZipFile(path):
            return True
    except (zipfile.BadZipFile, OSError):
        return False


def classify(directory, name, expected_bytes):
    """
    Return (state, bytes_on_disk); state is 'done', 'post', 'resume' or 'download'.

    A file X.zip that is incomplete (left by a downloader that writes to the final name)
    is renamed to X.zip.part so that it is resumed instead of downloaded again.
    """
    final = os.path.join(directory, name)
    part = final + '.part'

    if os.path.isfile(os.path.join(directory, ARCHIVE_DIR, name)):
        return 'done', 0

    if os.path.isfile(final):
        size = os.path.getsize(final)
        size_ok = expected_bytes is None or size == expected_bytes
        if size_ok and is_valid_zip(final):
            if os.path.isfile(part):
                os.remove(part)
            return 'post', size
        too_big = expected_bytes is not None and size >= expected_bytes
        if too_big or os.path.isfile(part):
            os.remove(final)
        else:
            os.replace(final, part)

    if os.path.isfile(part):
        size = os.path.getsize(part)
        if expected_bytes is not None and size > expected_bytes:
            os.remove(part)
            return 'download', 0
        return ('resume', size) if size > 0 else ('download', 0)

    return 'download', 0


class TimingLog:
    """Appends rows to <dir>/download_timing.csv; safe to use from several threads."""

    def __init__(self, directory):
        self.path = os.path.join(directory, TIMING_FILE)
        self.lock = threading.Lock()
        self.rows = []
        self.job_id = os.environ.get('SLURM_JOB_ID', '')
        self.node = socket.gethostname()

    def write(self, **row):
        row.setdefault('slurm_job_id', self.job_id)
        row.setdefault('node', self.node)
        with self.lock:
            self.rows.append(row)
            new = not os.path.isfile(self.path) or os.path.getsize(self.path) == 0
            with open(self.path, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=TIMING_FIELDS, extrasaction='ignore')
                if new:
                    writer.writeheader()
                writer.writerow(row)


def _open_stream(session, url, offset):
    headers = {'Range': f'bytes={offset}-'} if offset > 0 else {}
    kwargs = {'stream': True, 'headers': headers, 'timeout': (60, 300)}
    try:
        from asf_search.download.download import strip_auth_if_aws
        kwargs['hooks'] = {'response': strip_auth_if_aws}
    except Exception:
        pass
    return session.get(url, **kwargs)


def download_once(session, url, directory, name, expected_bytes, stop_event, timing, attempt):
    """
    One download attempt into X.part, resuming at its current size.
    Returns True when X is complete and in place; False if the attempt has to be repeated.
    """
    final = os.path.join(directory, name)
    part = final + '.part'
    progress_log = os.path.join(directory, os.path.splitext(name)[0] + '.download.log')

    offset = os.path.getsize(part) if os.path.isfile(part) else 0
    row = dict(granule=name, step='download', attempt=attempt, start=_now(), resumed_from_byte=offset,
               bytes_this_attempt=0, status='failed', message='')
    t0 = time.time()
    received = 0
    response = None

    def finish(status, message=''):
        seconds = time.time() - t0
        row.update(status=status, end=_now(), seconds=f'{seconds:.1f}', bytes_this_attempt=received,
                   mean_MB_per_s=f'{received / MB / seconds:.2f}' if seconds > 0 else '', message=message)
        timing.write(**row)

    try:
        if not (expected_bytes is not None and offset == expected_bytes):
            response = _open_stream(session, url, offset)
            row['seconds_to_first_byte'] = f'{time.time() - t0:.1f}'
            row['http_status'] = response.status_code
            row['final_host'] = urlparse(response.url).netloc

            if response.status_code == 416:
                # range not satisfiable: the .part is not a prefix of the file on the server
                response.close()
                os.remove(part)
                finish('failed', 'HTTP 416, restarting file from zero')
                return False
            if response.status_code == 200:
                if offset > 0:
                    row['message'] = 'server ignored Range, restarted from zero'
                offset = 0
                row['resumed_from_byte'] = 0
                mode = 'wb'
            elif response.status_code == 206:
                mode = 'ab'
            else:
                response.raise_for_status()
                raise RuntimeError(f'unexpected HTTP status {response.status_code}')

            last_time, last_bytes = t0, 0
            with open(part, mode) as f, open(progress_log, 'a') as plog:
                plog.write(f'# {_now()} attempt {attempt} start at byte {offset} of {expected_bytes} host {row["final_host"]}\n')
                plog.flush()
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if stop_event.is_set():
                        raise Interrupted()
                    f.write(chunk)
                    received += len(chunk)
                    now = time.time()
                    if now - last_time >= PROGRESS_INTERVAL:
                        rate = (received - last_bytes) / MB / (now - last_time)
                        plog.write(f'{_now()} {offset + received} {rate:.2f}\n')
                        plog.flush()
                        last_time, last_bytes = now, received
                now = time.time()
                rate = (received - last_bytes) / MB / (now - last_time) if now > last_time else 0
                plog.write(f'{_now()} {offset + received} {rate:.2f}\n')

        size = os.path.getsize(part)
        if expected_bytes is not None and size < expected_bytes:
            finish('failed', f'connection closed at {size} of {expected_bytes} bytes')
            return False
        if (expected_bytes is not None and size > expected_bytes) or not is_valid_zip(part, name):
            os.remove(part)
            finish('failed', f'bad file ({size} bytes, expected {expected_bytes}), removed')
            return False
        os.replace(part, final)
        finish('ok', row['message'])
        return True
    except Interrupted:
        finish('interrupted')
        raise
    except Exception as e:
        finish('failed', f'{type(e).__name__}: {e}'[:300])
        return False
    finally:
        if response is not None:
            response.close()


def run_post_command(post_cmd, directory, name, stop_event, timing):
    """Run the post-download command for one completed file. Returns True on success."""
    final = os.path.join(directory, name)
    log_file = os.path.join(directory, os.path.splitext(name)[0] + '.unpack.log')
    quoted = shlex.quote(os.path.abspath(final))
    cmd = post_cmd.replace('{}', quoted) if '{}' in post_cmd else f'{post_cmd} {quoted}'
    row = dict(granule=name, step='unpack', attempt=1, start=_now())
    t0 = time.time()
    with open(log_file, 'a') as log:
        log.write(f'# {_now()} {cmd}\n')
        log.flush()
        proc = subprocess.Popen(cmd, shell=True, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        while proc.poll() is None:
            if stop_event.wait(1):
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                proc.wait()
                timing.write(**row, status='interrupted', end=_now(), seconds=f'{time.time() - t0:.1f}')
                raise Interrupted()
    ok = proc.returncode == 0
    timing.write(**row, status='ok' if ok else 'failed', end=_now(), seconds=f'{time.time() - t0:.1f}',
                 message='' if ok else f'exit code {proc.returncode}, see {os.path.basename(log_file)}')
    return ok


def process_granule(product, directory, post_cmd, session_factory, stop_event, timing):
    """Take one granule as far as it can go. Returns 'done', 'failed' or 'interrupted'."""
    name, url, expected = product_name_url_bytes(product)
    try:
        state, _ = classify(directory, name, expected)
        if state == 'done':
            return 'done'
        if state in ('download', 'resume'):
            session = session_factory()
            for attempt in range(1, MAX_ATTEMPTS + 1):
                if stop_event.is_set():
                    raise Interrupted()
                if download_once(session, url, directory, name, expected, stop_event, timing, attempt):
                    break
                if stop_event.wait(10):
                    raise Interrupted()
            else:
                print(f'FAILED download: {name}', flush=True)
                return 'failed'
            print(f'{_now()} downloaded: {name}', flush=True)
        if post_cmd:
            if stop_event.is_set():
                raise Interrupted()
            if not run_post_command(post_cmd, directory, name, stop_event, timing):
                print(f'FAILED post-download command: {name}', flush=True)
                return 'failed'
            print(f'{_now()} unpacked: {name}', flush=True)
        return 'done'
    except Interrupted:
        return 'interrupted'
    except Exception as e:
        print(f'FAILED {name}: {type(e).__name__}: {e}', flush=True)
        return 'failed'


def _print_plan(products, directory):
    counts = {'done': 0, 'post': 0, 'resume': 0, 'download': 0}
    for product in products:
        name, _, expected = product_name_url_bytes(product)
        state, size = classify(directory, name, expected)
        counts[state] += 1
        detail = ''
        if state == 'resume':
            total = f'{expected / GB:.1f}' if expected else '?'
            detail = f' at {size / GB:.1f}/{total} GB'
        elif expected:
            detail = f' ({expected / GB:.1f} GB)'
        label = {'done': 'done', 'post': 'to unpack', 'resume': 'to resume', 'download': 'to download'}[state]
        print(f'  {name}: {label}{detail}')
    print(f"{counts['done']} done, {counts['post']} to unpack, {counts['resume']} to resume, "
          f"{counts['download']} to download", flush=True)


def _print_summary(products, results, timing):
    print('\nSummary of this run (seconds):')
    print(f"  {'granule':<45} {'result':<12} {'download':>9} {'MB/s':>7} {'unpack':>8}")
    for product, result in zip(products, results):
        name = product_name_url_bytes(product)[0]
        rows = [r for r in timing.rows if r['granule'] == name]
        dl = [r for r in rows if r['step'] == 'download']
        dl_sec = sum(float(r.get('seconds') or 0) for r in dl)
        dl_bytes = sum(int(r.get('bytes_this_attempt') or 0) for r in dl)
        rate = f'{dl_bytes / MB / dl_sec:.1f}' if dl_sec > 0 else '-'
        up_sec = sum(float(r.get('seconds') or 0) for r in rows if r['step'] == 'unpack')
        print(f"  {name:<45} {result:<12} {dl_sec:>9.0f} {rate:>7} {up_sec:>8.0f}")
    print(f'Timing of every attempt: {timing.path}', flush=True)


def run_pipeline(products, directory, post_cmd, parallel, session_factory):
    """
    Download every product and run post_cmd on each as soon as it is complete.
    Returns the number of granules that are not finished (0 = all done).
    """
    directory = os.path.abspath(directory)
    os.makedirs(directory, exist_ok=True)
    products = list(products)
    timing = TimingLog(directory)
    stop_event = threading.Event()

    print(f'State of {len(products)} granules in {directory}:')
    _print_plan(products, directory)

    def handler(signum, frame):
        print(f'\nReceived signal {signum}: stopping; restart the same command to continue.', flush=True)
        stop_event.set()

    old_handlers = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            old_handlers[sig] = signal.signal(sig, handler)
    try:
        with ThreadPoolExecutor(max_workers=max(int(parallel), 1)) as pool:
            futures = [pool.submit(process_granule, p, directory, post_cmd, session_factory, stop_event, timing)
                       for p in products]
            while not all(f.done() for f in futures):
                time.sleep(0.5)
                if stop_event.is_set():
                    for f in futures:
                        f.cancel()
            results = ['interrupted' if f.cancelled() else f.result() for f in futures]
    finally:
        for sig, old in old_handlers.items():
            signal.signal(sig, old)

    _print_summary(products, results, timing)
    unfinished = sum(1 for r in results if r != 'done')
    if unfinished:
        print(f'{unfinished} of {len(products)} granules are NOT finished; run the same command again.', flush=True)
    else:
        print(f'All {len(products)} granules are finished.', flush=True)
    return unfinished
