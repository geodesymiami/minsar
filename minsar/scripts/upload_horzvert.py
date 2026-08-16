#!/usr/bin/env python3
########################
# Author:  Falk Amelung
#######################

import argparse
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime

##############################################################################
EXAMPLE = """Examples:
    upload_horzvert.py LaPalmaRecent
    upload_horzvert.py LaPalmaRecent/miaplpy_202501_202606
    upload_horzvert.py Fernandina
    upload_horzvert.py Karkeh/miaplpy_201410_202608
"""

DESCRIPTION = (
    "Uploads horzvert data products to jetstream server"
)


def create_parser():
    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE,
                 formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('data_dirs', nargs='+', metavar="DIRECTORY", help='upload horzvert site or product directory')
    parser.add_argument('--sleep', type=int, metavar="SECS", default=None, help='sleep seconds before running')
    parser.add_argument('--quiet-summary', dest='quiet_summary', action='store_true', default=False,
                        help='suppress final Data at: URL summary (logs are still written)')

    return parser


def cmd_line_parse(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    if inps.sleep is not None and inps.sleep < 0:
        parser.error("--sleep must be a non-negative integer")
    return inps


###################################################
WGET_URL_RE = re.compile(r"^wget\s+(https?://\S+)\s*$")
RUN_HORZVERT_NAME = "run_horzvert2timeseries"
VOLCDEF_WEB_FILES = (
    "insarmaps.log",
    "overlay.html",
    "index.html",
    "data_files.txt",
    "download_commands.txt",
    "urls.log",
)


def parse_data_files_paths(data_files_txt):
    """Return non-comment paths from data_files.txt."""
    paths = []
    with open(data_files_txt, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            paths.append(line)
    return paths


def _remote_dir_prefix(REMOTE_DIR=None):
    REMOTE_DIR = REMOTE_DIR if REMOTE_DIR is not None else os.getenv("REMOTE_DIR", "/data/HDF5EOS/")
    if not REMOTE_DIR.startswith("/"):
        REMOTE_DIR = "/" + REMOTE_DIR
    if not REMOTE_DIR.endswith("/"):
        REMOTE_DIR += "/"
    return REMOTE_DIR


def parse_download_commands_relpaths(text, REMOTE_DIR=None):
    """Return work_dir-relative paths from wget lines in download_commands.txt."""
    prefix = _remote_dir_prefix(REMOTE_DIR)
    rels = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = WGET_URL_RE.match(line)
        if not match:
            continue
        url = match.group(1)
        host_and_path = re.match(r"^https?://[^/]+(/.*)$", url)
        if not host_and_path:
            continue
        url_path = host_and_path.group(1)
        if not url_path.startswith(prefix):
            continue
        rel = url_path[len(prefix):]
        if rel:
            rels.append(rel)
    return rels


def _is_radar_los_he5(path):
    stem = os.path.basename(path).lower()
    if not stem.endswith(".he5"):
        return False
    if stem.startswith("geo_"):
        return False
    if "vert" in stem or "horz" in stem:
        return False
    return True


def _is_geo_los_he5(path):
    """True for geo_* asc/desc LOS .he5 (not vert/horz products)."""
    stem = os.path.basename(path).lower()
    if not stem.endswith(".he5"):
        return False
    if not stem.startswith("geo_"):
        return False
    if "vert" in stem or "horz" in stem:
        return False
    return True


def _is_product_dir(path):
    name = os.path.basename(path.rstrip("/"))
    return name.startswith("mintpy") or name.startswith("miaplpy")


def normalize_data_dir(data_dir, work_dir):
    """Relative path from work_dir: site (LaPalmaRecent) or product (LaPalmaRecent/miaplpy_...)."""
    raw = (data_dir or "").rstrip("/")
    if not raw:
        return raw
    if os.path.isabs(raw):
        rel = os.path.relpath(os.path.realpath(raw), os.path.abspath(work_dir))
    else:
        rel = raw
    return rel.replace("\\", "/")


def iter_product_dirs(site_dir):
    """Yield mintpy*/miaplpy* directories under site_dir."""
    if not os.path.isdir(site_dir):
        return
    for name in sorted(os.listdir(site_dir)):
        path = os.path.join(site_dir, name)
        if os.path.isdir(path) and _is_product_dir(path):
            yield path


def iter_upload_product_dirs(work_dir, data_dir):
    """Yield product dirs to upload: one dated dir, or all under the site."""
    parts = [p for p in data_dir.split("/") if p]
    if not parts:
        return
    site_dir = os.path.join(work_dir, parts[0])
    if len(parts) >= 2 and _is_product_dir(parts[1]):
        product_dir = os.path.join(work_dir, parts[0], parts[1])
        if os.path.isdir(product_dir):
            yield product_dir
        return
    yield from iter_product_dirs(site_dir)


def overlay_page_url(REMOTEHOST_DATA, REMOTE_DIR, data_dir):
    """Public overlay.html URL for a product dir under REMOTE_DIR."""
    if not REMOTE_DIR.endswith("/"):
        REMOTE_DIR += "/"
    rel = (data_dir or "").replace("\\", "/").strip("/")
    return f"http://{REMOTEHOST_DATA}{REMOTE_DIR}{rel}/overlay.html"


def ssh_mkdir_p_command(REMOTE_CONNECTION, REMOTE_DIR, unique_dirs):
    """SSH mkdir -p for destination dirs, including parents (upload_data_products quoting)."""
    prefix = REMOTE_DIR if REMOTE_DIR.endswith('/') else REMOTE_DIR + '/'
    remote_paths = []
    seen = set()
    for d in sorted(unique_dirs):
        d = (d or '').replace('\\', '/').strip('/')
        if not d:
            continue
        parts = d.split('/')
        for i in range(1, len(parts) + 1):
            path = prefix + '/'.join(parts[:i])
            if path not in seen:
                seen.add(path)
                remote_paths.append(path)
    if not remote_paths:
        return None
    all_dirs = ' '.join(remote_paths)
    return f'ssh {REMOTE_CONNECTION} "mkdir -p {all_dirs}"'


def collect_upload_relpaths(work_dir, data_dir):
    """Relative paths: download products, run file, radar LOS HE5s, and volcdef_web files."""
    work_dir = os.path.abspath(work_dir)
    data_dir = normalize_data_dir(data_dir, work_dir)
    scp_list = []
    seen = set()

    def add(path):
        if not path:
            return
        full = path if os.path.isabs(path) else os.path.join(work_dir, path)
        if not os.path.isfile(full):
            return
        rel = os.path.relpath(os.path.realpath(full), work_dir)
        if rel.startswith(".."):
            return
        if rel not in seen:
            seen.add(rel)
            scp_list.append(rel)

    for product_dir in iter_upload_product_dirs(work_dir, data_dir):
        download_commands = os.path.join(product_dir, "download_commands.txt")
        data_files = os.path.join(product_dir, "data_files.txt")
        if os.path.isfile(download_commands):
            with open(download_commands, encoding="utf-8") as handle:
                for rel in parse_download_commands_relpaths(handle.read()):
                    add(os.path.join(work_dir, rel))
        elif os.path.isfile(data_files):
            for entry in parse_data_files_paths(data_files):
                add(entry)
        if os.path.isfile(data_files):
            for entry in parse_data_files_paths(data_files):
                if _is_radar_los_he5(entry):
                    add(entry)
                elif _is_geo_los_he5(entry):
                    add(entry)
        add(os.path.join(product_dir, RUN_HORZVERT_NAME))
        for name in VOLCDEF_WEB_FILES:
            add(os.path.join(product_dir, name))

    return scp_list


def add_log_remote_hdfeos5(scp_list, work_dir):
    # add uploaded he5 files to remote log file

    REMOTEHOST_DATA = os.getenv('REMOTEHOST_DATA')
    REMOTEUSER = os.getenv('REMOTEUSER')
    REMOTELOGFILE = os.getenv('REMOTELOGFILE')
    if not REMOTEHOST_DATA or not REMOTEUSER or not REMOTELOGFILE:
        return

    he5_files = []
    for rel in scp_list:
        if not rel.endswith('.he5'):
            continue
        full_path = os.path.join(work_dir, rel)
        if os.path.isfile(full_path):
            he5_files.append(full_path)
    if not he5_files:
        return

    from mintpy.utils import readfile

    metadata = readfile.read_attribute(he5_files[0])
    if 'data_footprint' not in metadata:
        raise Exception('ERROR: data_footprint not found in metadata')
    data_footprint = metadata['data_footprint']
    current_date = datetime.now().strftime('%Y%m%d')

    for full_path in he5_files:
        relative_file = os.path.relpath(full_path, start=work_dir)
        escaped_data_footprint = shlex.quote(data_footprint)
        command = f"""ssh {REMOTEUSER}@{REMOTEHOST_DATA} "echo {current_date} {relative_file} {escaped_data_footprint} >> {REMOTELOGFILE}" """
        status = subprocess.Popen(command, shell=True).wait()
        if status != 0:
            raise Exception('ERROR appending to remote log file in upload_horzvert.py')


##############################################################################

def main(iargs=None):

    inps = cmd_line_parse(iargs)

    inps.work_dir = os.getcwd()

    os.chdir(inps.work_dir)

    if not iargs is None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1::]

    from minsar.objects import message_rsmas
    message_rsmas.log(inps.work_dir, os.path.basename(__file__) + ' ' + ' '.join(input_arguments))

    if inps.sleep:
        print(f'sleeping {inps.sleep} secs before starting ...')
        time.sleep(inps.sleep)

    REMOTEHOST_DATA = os.getenv('REMOTEHOST_DATA')
    REMOTEUSER = os.getenv('REMOTEUSER')
    REMOTE_DIR = os.getenv('REMOTE_DIR', '/data/HDF5EOS/')
    if not REMOTE_DIR.endswith('/'):
        REMOTE_DIR += '/'
    REMOTE_CONNECTION = REMOTEUSER + '@' + REMOTEHOST_DATA
    REMOTE_CONNECTION_DIR = REMOTE_CONNECTION + ':' + REMOTE_DIR

    scp_list = []
    seen = set()
    for data_dir in inps.data_dirs:
        data_dir = data_dir.rstrip('/')
        for element in collect_upload_relpaths(inps.work_dir, data_dir):
            if element not in seen:
                seen.add(element)
                scp_list.append(element)

    print('################')
    print('Data to upload: ')
    for element in scp_list:
        print(element)
    print('################')
    time.sleep(2)

    remote_urls = []
    for data_dir in inps.data_dirs:
        data_dir = normalize_data_dir(data_dir.rstrip('/'), inps.work_dir)
        printed = False
        for product_dir in iter_upload_product_dirs(inps.work_dir, data_dir):
            rel = os.path.relpath(os.path.realpath(product_dir), inps.work_dir).replace('\\', '/')
            remote_urls.append(overlay_page_url(REMOTEHOST_DATA, REMOTE_DIR, rel))
            printed = True
        if not printed:
            remote_urls.append(overlay_page_url(REMOTEHOST_DATA, REMOTE_DIR, data_dir))

    print('\n################')
    print('Uploading listed files (rsync replaces existing copies, including updated radar LOS HE5s)')
    print('################\n')

    unique_dirs = set()
    upload_commands = []
    for element in scp_list:
        full_path = os.path.join(inps.work_dir, element)
        if not os.path.isfile(full_path):
            print(f'Warning: Path does not exist, skipping: {full_path}')
            continue
        dir_name = os.path.dirname(element)
        unique_dirs.add(dir_name)
        upload_cmd = (
            f'rsync -avz --progress --mkpath {shlex.quote(full_path)} '
            f'{REMOTE_CONNECTION_DIR}{dir_name}/'
        )
        upload_commands.append(upload_cmd)

    mkdir_cmd = ssh_mkdir_p_command(REMOTE_CONNECTION, REMOTE_DIR, unique_dirs)
    if mkdir_cmd:
        print('\nCreating all remote directories with one SSH command...')
        print(mkdir_cmd)
        status = subprocess.Popen(mkdir_cmd, shell=True).wait()
        if status != 0:
            raise Exception('ERROR creating remote directories in upload_horzvert.py')

    for command in upload_commands:
        print('\nUploading data:')
        print(command)
        status = subprocess.Popen(command, shell=True).wait()
        if status != 0:
            raise Exception('ERROR uploading using rsync in upload_horzvert.py')

    print('\nAdjusting permissions for all uploaded directories...')
    unique_top_dirs = set()
    for element in scp_list:
        top_dir = element.split('/')[0]
        if top_dir:
            unique_top_dirs.add(top_dir)
    if unique_top_dirs:
        all_paths = ' '.join([f'{REMOTE_DIR}{d}' for d in sorted(unique_top_dirs)])
        command = f'ssh {REMOTEUSER}@{REMOTEHOST_DATA} "chmod -R u=rwX,go=rX {all_paths}"'
        print(command)
        status = subprocess.Popen(command, shell=True).wait()
        if status != 0:
            raise Exception('ERROR adjusting permissions in upload_horzvert.py')

##########################################
    add_log_remote_hdfeos5(scp_list, inps.work_dir)
##########################################
    if not inps.quiet_summary:
        print('\nData at:')
        for url in remote_urls:
            print(url)

    return None


if __name__ == "__main__":
    main()
