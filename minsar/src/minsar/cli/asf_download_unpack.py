#!/usr/bin/env python3
"""
Download ASF archives and unpack each one as soon as its download completes.

Downloads and unpacks run at the same time: N downloads and N unpacks (--parallel N).
The script can be stopped at any time (e.g. SLURM walltime) and started again:
    finished archives (in ARCHIVED_FILES)   are skipped
    downloaded archives not yet unpacked    are unpacked
    interrupted downloads (*.part)          continue where they stopped
    interrupted unpacks                     are redone
"""

import os
import sys
import time
import argparse
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import asf_search as asf
from asf_search.download.download import strip_auth_if_aws

from minsar.src.minsar.cli import asf_search_args

EXAMPLE = """Examples:
    asf_download_unpack.py --processingLevel=1.1 --platform=ALOS-2 --relativeOrbit=89 --intersectsWith='POLYGON((9.16 4.20,9.18 4.20,9.18 4.22,9.16 4.22,9.16 4.20))' --start-date=2014-10-04 --end-date=2015-12-31 --parallel=6 --dir=SLC_ORIG
    asf_download_unpack.py ... --dir=SLC_ORIG --no-unpack        # download only (resumable)
    asf_download_unpack.py ... --dir=SLC_ORIG --unpack-dir=SLC

Search options are those of asf_search_args.py (see asf_search_args.py --help).
ALOS-2 archives are unpacked into the YYMMDD layout of alosStack.
"""

CHUNK_SIZE = 8 * 1024 * 1024
MAX_TRIES = 20          # per archive and run; every try continues the partial file
RETRY_WAIT = 30         # seconds

print_lock = threading.Lock()


def log(message):
    with print_lock:
        print(f"{datetime.now():%Y%m%d:%H-%M-%S} {message}", flush=True)


def create_parser():
    parser = argparse.ArgumentParser(description=__doc__, epilog=EXAMPLE,
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--unpack-dir', metavar='FOLDER', default=None,
                        help='directory for the unpacked data (default: SLC next to --dir)')
    parser.add_argument('--no-unpack', dest='unpack', action='store_false', help='download only')
    return parser


def expected_size(product):
    """Archive size in bytes from the ASF listing, or None if the listing has none."""
    size = product.properties.get('bytes')
    try:
        return int(size) if int(size) > 0 else None
    except (TypeError, ValueError):
        return None


def download(url, archive, size):
    """Download url to archive. An interrupted download continues from archive.part.

    Returns False if the complete archive was already there.
    """
    part = archive + '.part'

    # A file left by an interrupted asf_search download has the final name but is too short.
    if os.path.isfile(archive):
        if size is None or os.path.getsize(archive) == size:
            return False
        os.replace(archive, part)

    last_error = None
    for attempt in range(MAX_TRIES):
        if attempt:
            time.sleep(RETRY_WAIT)
        have = os.path.getsize(part) if os.path.isfile(part) else 0
        if size and have > size:
            os.remove(part)
            have = 0
        if not (size and have == size):
            try:
                total = fetch(url, part, have)
            except Exception as error:      # network errors: try again, continuing the partial file
                last_error = error
                log(f"retry {attempt + 1}/{MAX_TRIES} {os.path.basename(archive)}: {error}")
                continue
            size = size or total
        have = os.path.getsize(part)
        if size is None or have == size:
            os.replace(part, archive)
            return True
        last_error = f"incomplete: {have} of {size} bytes"

    raise RuntimeError(f"download failed after {MAX_TRIES} tries: {last_error}")


def fetch(url, part, have):
    """Append the bytes after position `have` to part. Returns the full size if the server gives it."""
    headers = {'Range': f'bytes={have}-'} if have else {}
    session = asf.ASFSession()
    with session.get(url, stream=True, headers=headers, timeout=(60, 600),
                     hooks={'response': strip_auth_if_aws}) as response:
        if response.status_code == 416:     # nothing after `have`: the partial file is not usable
            os.remove(part)
            raise RuntimeError('server rejected the resume position, starting over')
        response.raise_for_status()

        total = None
        if response.status_code == 206:
            mode = 'ab'
            content_range = response.headers.get('Content-Range', '')
            if '/' in content_range and content_range.rsplit('/', 1)[1].isdigit():
                total = int(content_range.rsplit('/', 1)[1])
        else:                               # server ignored the Range header: start over
            mode = 'wb'
            if response.headers.get('Content-Length', '').isdigit():
                total = int(response.headers['Content-Length'])

        with open(part, mode) as f:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                f.write(chunk)
    return total


def unpack(archive, unpack_dir, alos_stack):
    """Unpack one archive into unpack_dir. The archive is moved to ARCHIVED_FILES when done."""
    cmd = ['uncompress_and_rename_data.py', archive, '--output-dir', unpack_dir]
    if alos_stack:
        cmd.append('--alos-stack')
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"unpack failed:\n{result.stdout}")


def main(iargs=None):
    own, search_args = create_parser().parse_known_args(iargs)
    inps = asf_search_args.create_parser(search_args + ['--download'])
    download_dir = os.path.abspath(inps.dir)
    unpack_dir = os.path.abspath(own.unpack_dir or os.path.join(os.path.dirname(download_dir), 'SLC'))
    archived_dir = os.path.join(download_dir, 'ARCHIVED_FILES')
    alos_stack = inps.processing_level == asf.PRODUCT_TYPE.L1_1

    _, products = asf_search_args.find_products(inps)

    todo = []
    for product in products:
        name = product.properties['fileName']
        if os.path.isfile(os.path.join(archived_dir, name)):
            continue
        todo.append(product)
    log(f"{len(products)} archives: {len(products) - len(todo)} already done, {len(todo)} to do. "
        f"Parallel: {inps.parallel}  Download: {download_dir}  Unpack: {unpack_dir if own.unpack else 'no'}")
    if own.unpack:
        os.makedirs(unpack_dir, exist_ok=True)

    failed = []
    unpack_pool = ThreadPoolExecutor(max_workers=inps.parallel)
    unpack_jobs = []

    def unpack_one(archive):
        name = os.path.basename(archive)
        start = time.time()
        try:
            unpack(archive, unpack_dir, alos_stack)
            log(f"unpacked   {name} ({(time.time() - start) / 60:.0f} min)")
        except Exception as error:
            failed.append(name)
            log(f"ERROR {name}: {error}")

    def download_one(product):
        name = product.properties['fileName']
        archive = os.path.join(download_dir, name)
        start = time.time()
        try:
            if download(product.properties['url'], archive, expected_size(product)):
                minutes = (time.time() - start) / 60
                log(f"downloaded {name} ({os.path.getsize(archive) / 1e9:.1f} GB, {minutes:.0f} min)")
        except Exception as error:
            failed.append(name)
            log(f"ERROR {name}: {error}")
            return
        if own.unpack:
            unpack_jobs.append(unpack_pool.submit(unpack_one, archive))

    try:
        with ThreadPoolExecutor(max_workers=inps.parallel) as download_pool:
            list(download_pool.map(download_one, todo))
        unpack_pool.shutdown(wait=True)
    except KeyboardInterrupt:
        log("Interrupted. Run again to continue.")
        os._exit(130)

    if failed:
        log(f"FAILED: {len(failed)} of {len(todo)} archives: {' '.join(sorted(failed))}")
        return 1
    log("Done.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
