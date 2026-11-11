#!/usr/bin/env python3
########################
# Author:  Falk Amelung
#######################


import os
import re
import subprocess
import sys
import glob
import shutil
import shlex
import time
from datetime import datetime
import argparse
from pathlib import Path
from minsar.objects.rsmas_logging import loglevel
from minsar.objects import message_rsmas
import minsar.utils.process_utilities as putils
import minsar.job_submission as js
from minsar.src.minsar.create_html import create_html
from minsar.src.minsar.add_missing_attributes import add_missing_attributes_for_upload

sys.path.insert(0, os.getenv('SSARAHOME'))
import password_config as password

##############################################################################
EXAMPLE = """Examples:
    upload_data_products.py mintpy
    upload_data_products.py miaplpy
    upload_data_products.py miaplpy/network_single_reference
    upload_data_products.py miaplpy/inputs
    upload_data_products.py S1_desc_115_20160803_20260612.he5
    upload_data_products.py qqCerroAzul/miaplpy_202501_202610_filtDS
    upload_data_products.py qqCerroAzul
"""

DESCRIPTION = (
    "Uploads mintpy/miaplpy directories, files, or horzvert site/product directories to jetstream"
)

def create_parser():
    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE,
                 formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('data_dirs', nargs='+', metavar="PATH", help='mintpy/miaplpy path, or a horzvert site or product directory')
    parser.add_argument('--geo', dest='geo_flag', action='store_true', default=False, help='uploads geo  directory')
    parser.add_argument('--all', dest='all_flag', action='store_true', default=False, help='uploads full directory')
    parser.add_argument('--pic', dest='piconly_flag', action='store_true', default=False, help='uploads only pic directory')
    #parser.add_argument('--triplets', dest='triplets_flag', action='store_true', default=False, help='uploads numTriNonzeroIntAmbiguity.h5')
    parser.add_argument('--triplets', dest='triplets_flag', action='store_true', default=True, help='uploads numTriNonzeroIntAmbiguity.h5')
    parser.add_argument('--quiet-summary', dest='quiet_summary', action='store_true', default=False,
                        help='suppress final Data at: URL summary (logs are still written)')
    parser.add_argument('--sleep', type=int, metavar="SECS", default=None, help='sleep seconds before a horzvert upload')

    return parser

def cmd_line_parse(iargs=None):

    parser = create_parser()
    inps = parser.parse_args(args=iargs)
    if inps.sleep is not None and inps.sleep < 0:
        parser.error("--sleep must be a non-negative integer")

    inps.mintpy_flag = False
    inps.miaplpy_flag = False
    if inps.data_dirs:
        if 'mintpy' in inps.data_dirs[0]:
            inps.mintpy_flag = True
        elif 'miaplpy' in inps.data_dirs[0]:
            inps.miaplpy_flag = True

    print('inps: ',inps)
    return inps

###################################################
class Inps:
    def __init__(self, dir):
        self.dir = dir

def create_html_if_needed(dir):
    if not os.path.isfile(dir + '/index.html'):
        # Create an instance of Inps with the directory
        inps = Inps(dir)
        create_html(inps)

def _is_insarmaps_log(path):
    """True for an insarmaps.log sidecar, not a product directory."""
    return os.path.basename(str(path).rstrip("/")) == "insarmaps.log"


def _is_pic_dir(path):
    """True when path is a pic output directory."""
    return os.path.basename(str(path).rstrip("/")) == "pic"


def _is_dolphin_dir(path):
    """True for ISCE3 dolphin work tree root (dolphin or dolphin_*)."""
    base = os.path.basename(str(path).rstrip("/"))
    return base == "dolphin" or base.startswith("dolphin_")


def _ensure_minsar_log(work_dir):
    """Ensure project minsar_log exists (last minsarIsce3App command line)."""
    src = os.path.join(work_dir, "minsar_log")
    if os.path.isfile(src):
        return src
    log_path = os.path.join(work_dir, "log")
    if os.path.isfile(log_path):
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            matches = [ln for ln in fh if "minsarIsce3App" in ln]
        if matches:
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(matches[-1].rstrip("\n") + "\n")
    return src if os.path.isfile(src) else None


def _copy_minsar_log_to_pic(pic_dir, work_dir):
    """Copy project minsar_log into pic/ for Jetstream gallery."""
    src = _ensure_minsar_log(work_dir)
    if src:
        shutil.copy2(src, os.path.join(pic_dir, "minsar_log"))


def _ensure_insarmaps_log(work_dir):
    """Ensure insarmaps.log exists at project root (copy from pic/ or timeseries/ if needed)."""
    root_log = os.path.join(work_dir, "insarmaps.log")
    if os.path.isfile(root_log):
        return root_log
    for rel in (
        "pic/insarmaps.log",
        "dolphin/pic/insarmaps.log",
        "dolphin/timeseries/insarmaps.log",
    ):
        candidate = os.path.join(work_dir, rel)
        if os.path.isfile(candidate):
            shutil.copy2(candidate, root_log)
            return root_log
    return None


def _is_isce3_upload(inps):
    """True for ISCE3 dolphin/he5/pic uploads (not mintpy/miaplpy)."""
    if inps.mintpy_flag or inps.miaplpy_flag:
        return False
    for data_dir in inps.data_dirs:
        data_dir = str(data_dir).rstrip("/")
        if _is_insarmaps_log(data_dir):
            return True
        if _is_dolphin_dir(data_dir) or _is_pic_dir(data_dir):
            return True
        if data_dir.endswith(".he5") or glob.has_magic(data_dir):
            return True
        if os.path.basename(data_dir) == "pic" and os.path.isdir(data_dir):
            return True
    return False


def _append_isce3_project_logs(scp_list, work_dir):
    """Add project-root log sidecars for rsync to Jetstream project dir."""
    _ensure_minsar_log(work_dir)
    _ensure_insarmaps_log(work_dir)
    for log_name in ("upload.log", "insarmaps.log", "minsar_log"):
        path = os.path.join(work_dir, log_name)
        if os.path.isfile(path):
            pattern = f"/{log_name}"
            if pattern not in scp_list:
                scp_list.append(pattern)


def _pic_dir_for_upload(data_dir):
    """Return local pic directory for upload.log URL, or None."""
    data_dir = data_dir.rstrip("/")
    if _is_pic_dir(data_dir) and os.path.isdir(data_dir):
        return data_dir
    pic_dir = data_dir + "/pic"
    if os.path.isdir(pic_dir):
        return pic_dir
    return None


def add_log_remote_he5(scp_list, work_dir):
    # add uploaded he5 files to remote log file

    REMOTEHOST_DATA = os.getenv('REMOTEHOST_DATA')
    REMOTEUSER = os.getenv('REMOTEUSER')
    REMOTELOGFILE = os.getenv('REMOTELOGFILE')

    try:
        he5_pattern = [item for item in scp_list if item.endswith('.he5')][0]
    except:
        return  # No .he5 pattern found in scp_list

    # Check if any .he5 files were actually found
    he5_files = glob.glob(work_dir + he5_pattern)

    if not he5_files:
        print(f"No .he5 files found: {work_dir + he5_pattern}, skipping remote log update")
        return

    relative_he5_files = [os.path.relpath(item, start=os.path.dirname(work_dir)) for item in he5_files]
    current_date = datetime.now().strftime('%Y%m%d')

    file_path = he5_files[0]

    from mintpy.utils import readfile
    metadata = readfile.read_attribute(file_path)
    if 'data_footprint' not in metadata:
        raise Exception('ERROR: data_footprint not found in metadata')
    data_footprint = metadata['data_footprint']

    for relative_file in relative_he5_files:
        # command = f"echo {current_date} {relative_file} | ssh {REMOTEUSER}@{REMOTEHOST_DATA} 'cat >> {REMOTELOGFILE}'"
        escaped_data_footprint = shlex.quote(data_footprint)

        command = f"""ssh {REMOTEUSER}@{REMOTEHOST_DATA} "echo {current_date} {relative_file} {escaped_data_footprint} >> {REMOTELOGFILE}" """

        status = subprocess.Popen(command, shell=True).wait()
        if status != 0:
            raise Exception('ERROR appending to remote log file in upload_data_products.py')

##############################################################################
WGET_URL_RE = re.compile(r"^wget\s+(https?://\S+)\s*$")
RUN_HORZVERT_NAME = "run_horzvert2timeseries"
VOLCDEF_WEB_FILES = (
    "insarmaps.log",
    "overlay.html",
    "matrix.html",
    "index.html",
    "data_files.txt",
    "download_commands.txt",
    "urls.log",
    "commands.bash",
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


def _scratchdir_relpath(path, work_dir):
    """Return work_dir-relative path for absolute SCRATCHDIR paths."""
    if not path:
        return path
    full = path if os.path.isabs(path) else os.path.join(work_dir, path)
    try:
        rel = os.path.relpath(os.path.realpath(full), os.path.abspath(work_dir))
    except ValueError:
        return path
    if rel.startswith(".."):
        return path
    return rel.replace("\\", "/")


def rewrite_data_files_txt(data_files_txt, work_dir):
    """Rewrite absolute scratch paths in data_files.txt to work_dir-relative."""
    work_dir = os.path.abspath(work_dir)
    if not os.path.isfile(data_files_txt):
        return False
    with open(data_files_txt, encoding="utf-8") as handle:
        lines = handle.readlines()
    changed = False
    out = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            out.append(raw if raw.endswith("\n") else raw + "\n")
            continue
        rel = _scratchdir_relpath(line, work_dir)
        if rel != line:
            changed = True
        out.append(rel + "\n")
    if changed:
        with open(data_files_txt, "w", encoding="utf-8") as handle:
            handle.writelines(out)
        print(f"Rewrote paths in {data_files_txt} to be relative to {work_dir}")
    return changed


def rewrite_download_commands_txt(download_commands_txt, work_dir, remote_host=None, remote_dir=None):
    """Rebuild download_commands.txt from sibling data_files.txt (Jetstream URLs)."""
    product_dir = os.path.dirname(os.path.abspath(download_commands_txt))
    data_files = os.path.join(product_dir, "data_files.txt")
    if not os.path.isfile(data_files):
        return False
    rewrite_data_files_txt(data_files, work_dir)
    remote_host = remote_host or os.getenv("REMOTEHOST_DATA")
    remote_dir = remote_dir or os.getenv("REMOTE_DIR", "/data/HDF5EOS/")
    if not remote_dir.endswith("/"):
        remote_dir += "/"
    if not remote_host:
        return False
    try:
        status = subprocess.Popen(
            ["create_data_download_commands.py", data_files],
            cwd=work_dir,
        ).wait()
        if status == 0:
            print(f"Regenerated {download_commands_txt} for Jetstream URLs")
            return True
    except OSError:
        pass
    return False


def prepare_product_dir_for_upload(product_dir, work_dir, remote_host=None, remote_dir=None):
    """Rewrite data_files.txt / download_commands.txt paths before rsync."""
    data_files = os.path.join(product_dir, "data_files.txt")
    download_commands = os.path.join(product_dir, "download_commands.txt")
    if os.path.isfile(data_files):
        rewrite_data_files_txt(data_files, work_dir)
    if os.path.isfile(download_commands):
        rewrite_download_commands_txt(
            download_commands, work_dir, remote_host=remote_host, remote_dir=remote_dir,
        )
    elif os.path.isfile(data_files):
        try:
            subprocess.Popen(
                ["create_data_download_commands.py", data_files],
                cwd=work_dir,
            ).wait()
        except OSError:
            pass


def _remote_dir_prefix(remote_dir=None):
    remote_dir = remote_dir if remote_dir is not None else os.getenv("REMOTE_DIR", "/data/HDF5EOS/")
    if not remote_dir.startswith("/"):
        remote_dir = "/" + remote_dir
    if not remote_dir.endswith("/"):
        remote_dir += "/"
    return remote_dir


def parse_download_commands_relpaths(text, remote_dir=None):
    """Return work_dir-relative paths from wget lines in download_commands.txt."""
    prefix = _remote_dir_prefix(remote_dir)
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


def _is_hv_product_dir(path):
    name = os.path.basename(path.rstrip("/"))
    return name.startswith("mintpy") or name.startswith("miaplpy")


def normalize_data_dir(data_dir, work_dir):
    """Relative path from work_dir: site or site/product."""
    raw = (data_dir or "").rstrip("/")
    if not raw:
        return raw
    if os.path.isabs(raw):
        rel = os.path.relpath(os.path.realpath(raw), os.path.abspath(work_dir))
    else:
        rel = raw
    return rel.replace("\\", "/")


def iter_hv_product_dirs(site_dir):
    """Yield mintpy*/miaplpy* directories under site_dir."""
    if not os.path.isdir(site_dir):
        return
    for name in sorted(os.listdir(site_dir)):
        path = os.path.join(site_dir, name)
        if os.path.isdir(path) and _is_hv_product_dir(path):
            yield path


def iter_upload_product_dirs(work_dir, data_dir):
    """Yield product dirs to upload: one dated dir, or all under the site."""
    parts = [p for p in data_dir.split("/") if p]
    if not parts:
        return
    site_dir = os.path.join(work_dir, parts[0])
    if len(parts) >= 2 and _is_hv_product_dir(parts[1]):
        product_dir = os.path.join(work_dir, parts[0], parts[1])
        if os.path.isdir(product_dir):
            yield product_dir
        return
    yield from iter_hv_product_dirs(site_dir)


def _dir_has_horzvert_marker(product_dir):
    return (
        os.path.isfile(os.path.join(product_dir, RUN_HORZVERT_NAME))
        or os.path.isfile(os.path.join(product_dir, "data_files.txt"))
    )


def _is_horzvert_arg(work_dir, data_dir):
    products = list(iter_upload_product_dirs(work_dir, normalize_data_dir(data_dir, work_dir)))
    return any(_dir_has_horzvert_marker(p) for p in products)


def _is_horzvert_request(inps):
    """True when every argument is a horzvert site or product directory."""
    flags = [_is_horzvert_arg(inps.work_dir, data_dir) for data_dir in inps.data_dirs]
    if any(flags) and not all(flags):
        raise Exception('ERROR: mixed horzvert and non-horzvert paths in upload_data_products.py')
    return bool(flags) and all(flags)


def horzvert_replace_target(work_dir, data_dir):
    """('product', site/product) or ('site', site)."""
    rel = normalize_data_dir(data_dir, work_dir)
    parts = [p for p in rel.split("/") if p]
    if len(parts) >= 2 and _is_hv_product_dir(parts[1]):
        return "product", "/".join(parts[:2])
    if parts:
        return "site", parts[0]
    return "site", ""


def _ssh_remote(remote_connection, remote_script):
    command = "ssh " + shlex.quote(remote_connection) + " " + shlex.quote(remote_script)
    print(command)
    return subprocess.Popen(command, shell=True).wait()


def remove_remote_horzvert_dirs(remote_connection, remote_dir, work_dir, data_dirs):
    """Remove one named product dir, or every remote miaplpy* dir under a site."""
    exact = []
    sites = []
    seen_exact = set()
    seen_sites = set()
    prefix = _remote_dir_prefix(remote_dir)
    for data_dir in data_dirs:
        kind, rel = horzvert_replace_target(work_dir, data_dir)
        if not rel:
            continue
        path = prefix + rel
        if kind == "product":
            if path not in seen_exact:
                seen_exact.add(path)
                exact.append(path)
        elif path not in seen_sites:
            seen_sites.add(path)
            sites.append(path)
    if not exact and not sites:
        return
    print('\nReplacing remote horzvert directories ...')
    if exact:
        remote_script = "rm -rf " + " ".join(shlex.quote(path) for path in exact)
        status = _ssh_remote(remote_connection, remote_script)
        if status != 0:
            raise Exception('ERROR removing remote product directory in upload_data_products.py')
    for site_remote in sites:
        quoted = shlex.quote(site_remote)
        remote_script = (
            f"if [ -d {quoted} ]; then "
            f"find {quoted} -mindepth 1 -maxdepth 1 -type d -name 'miaplpy*' -exec rm -rf {{}} +; "
            f"fi"
        )
        status = _ssh_remote(remote_connection, remote_script)
        if status != 0:
            raise Exception('ERROR removing remote miaplpy directories in upload_data_products.py')


def overlay_page_url(remote_host, remote_dir, data_dir):
    """Public overlay.html URL for a product dir under remote_dir."""
    if not remote_dir.endswith("/"):
        remote_dir += "/"
    rel = (data_dir or "").replace("\\", "/").strip("/")
    return f"http://{remote_host}{remote_dir}{rel}/overlay.html"


def ssh_mkdir_p_command(remote_connection, remote_dir, unique_dirs):
    """SSH mkdir -p for destination dirs, including parents."""
    prefix = remote_dir if remote_dir.endswith('/') else remote_dir + '/'
    remote_paths = []
    seen = set()
    for directory in sorted(unique_dirs):
        directory = (directory or '').replace('\\', '/').strip('/')
        if not directory:
            continue
        parts = directory.split('/')
        for i in range(1, len(parts) + 1):
            path = prefix + '/'.join(parts[:i])
            if path not in seen:
                seen.add(path)
                remote_paths.append(path)
    if not remote_paths:
        return None
    all_dirs = ' '.join(shlex.quote(path) for path in remote_paths)
    return f'ssh {shlex.quote(remote_connection)} {shlex.quote("mkdir -p " + all_dirs)}'


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
    """Append each uploaded .he5 to the remote HDF5EOS log."""
    remote_host = os.getenv('REMOTEHOST_DATA')
    remote_user = os.getenv('REMOTEUSER')
    remote_log = os.getenv('REMOTELOGFILE')
    if not remote_host or not remote_user or not remote_log:
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
        command = f"""ssh {remote_user}@{remote_host} "echo {current_date} {relative_file} {escaped_data_footprint} >> {remote_log}" """
        status = subprocess.Popen(command, shell=True).wait()
        if status != 0:
            raise Exception('ERROR appending to remote log file in upload_data_products.py')


def upload_horzvert_products(inps):
    """Upload horzvert site or product dirs to /data/HDF5EOS/<site>/..."""
    if inps.sleep:
        print(f'sleeping {inps.sleep} secs before starting ...')
        time.sleep(inps.sleep)

    remote_host = os.getenv('REMOTEHOST_DATA')
    remote_user = os.getenv('REMOTEUSER')
    remote_dir = _remote_dir_prefix(os.getenv('REMOTE_DIR', '/data/HDF5EOS/'))
    remote_connection = remote_user + '@' + remote_host
    remote_connection_dir = remote_connection + ':' + remote_dir

    scp_list = []
    seen = set()
    for data_dir in inps.data_dirs:
        data_dir = data_dir.rstrip('/')
        for product_dir in iter_upload_product_dirs(inps.work_dir, normalize_data_dir(data_dir, inps.work_dir)):
            prepare_product_dir_for_upload(
                product_dir, inps.work_dir,
                remote_host=remote_host, remote_dir=remote_dir,
            )
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
        for product_dir in iter_upload_product_dirs(inps.work_dir, data_dir):
            overlay = os.path.join(product_dir, 'overlay.html')
            if not os.path.isfile(overlay):
                continue
            rel = os.path.relpath(os.path.realpath(product_dir), inps.work_dir).replace('\\', '/')
            remote_urls.append(overlay_page_url(remote_host, remote_dir, rel))

    print('\n################')
    print('Replacing remote miaplpy or named product directories, then uploading files')
    print('################\n')

    remove_remote_horzvert_dirs(remote_connection, remote_dir, inps.work_dir, inps.data_dirs)

    unique_dirs = set()
    upload_commands = []
    for element in scp_list:
        full_path = os.path.join(inps.work_dir, element)
        if not os.path.isfile(full_path):
            print(f'Warning: Path does not exist, skipping: {full_path}')
            continue
        dir_name = os.path.dirname(element)
        unique_dirs.add(dir_name)
        dest = f'{remote_connection_dir}{dir_name}/'
        upload_cmd = (
            f'rsync -avz --progress --mkpath {shlex.quote(full_path)} {shlex.quote(dest)}'
        )
        upload_commands.append(upload_cmd)

    mkdir_cmd = ssh_mkdir_p_command(remote_connection, remote_dir, unique_dirs)
    if mkdir_cmd:
        print('\nCreating all remote directories with one SSH command...')
        print(mkdir_cmd)
        status = subprocess.Popen(mkdir_cmd, shell=True).wait()
        if status != 0:
            raise Exception('ERROR creating remote directories in upload_data_products.py')

    for command in upload_commands:
        print('\nUploading data:')
        print(command)
        status = subprocess.Popen(command, shell=True).wait()
        if status != 0:
            raise Exception('ERROR uploading using rsync in upload_data_products.py')

    print('\nAdjusting permissions for all uploaded directories...')
    unique_top_dirs = set()
    for element in scp_list:
        top_dir = element.split('/')[0]
        if top_dir:
            unique_top_dirs.add(top_dir)
    if unique_top_dirs:
        all_paths = ' '.join(shlex.quote(f'{remote_dir}{directory}') for directory in sorted(unique_top_dirs))
        command = f'ssh {shlex.quote(remote_connection)} {shlex.quote("chmod -R u=rwX,go=rX " + all_paths)}'
        print(command)
        status = subprocess.Popen(command, shell=True).wait()
        if status != 0:
            raise Exception('ERROR adjusting permissions in upload_data_products.py')

    add_log_remote_hdfeos5(scp_list, inps.work_dir)
    if not inps.quiet_summary and remote_urls:
        print('\nData at:')
        for url in remote_urls:
            print(url)
    return None


##############################################################################

def main(iargs=None):

    inps = cmd_line_parse()

    inps.work_dir = os.getcwd()
    inps.project_name = os.path.basename(inps.work_dir)

    project_name = inps.project_name

    os.chdir(inps.work_dir)

    if not iargs is None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1::]

    message_rsmas.log(inps.work_dir, os.path.basename(__file__) + ' ' + ' '.join(input_arguments))

    if _is_horzvert_request(inps):
        return upload_horzvert_products(inps)

    REMOTEHOST_DATA = os.getenv('REMOTEHOST_DATA')
    REMOTEUSER = os.getenv('REMOTEUSER')
    REMOTE_DIR = '/data/HDF5EOS/'
    REMOTE_CONNECTION = REMOTEUSER + '@' + REMOTEHOST_DATA
    REMOTE_CONNECTION_DIR = REMOTE_CONNECTION + ':' + REMOTE_DIR

    scp_list = []
    for data_dir in inps.data_dirs:
        data_dir = data_dir.rstrip('/')

        # If path is a subdirectory (contains '/'), determine if it should upload all contents
        # Upload all for: mintpy/inputs, test1/EnvD140, miaplpy_*/network_*/pic, etc.
        # Use standard processing for: miaplpy_*/network_single_reference (network dirs themselves)
        if '/' in data_dir and os.path.isdir(data_dir):
            basename = os.path.basename(data_dir)
            # If it's a network directory itself (ends with network_*), use standard processing
            # Otherwise, if it's a subdirectory (like pic, inputs, geo), upload all contents
            if not basename.startswith('network_'):
                print(f"Uploading all contents of directory: {data_dir}")
                if os.path.isdir(data_dir + '/pic'):
                    create_html_if_needed(data_dir + '/pic')
                scp_list.extend(['/' + data_dir])
                continue

        # Main directory processing (mintpy, miaplpy, etc.)
        if 'mintpy' in data_dir:
            # Handle --all flag: upload entire directory
            if inps.all_flag:
                if os.path.isdir(data_dir + '/pic'):
                    create_html_if_needed(data_dir + '/pic')
                scp_list.extend(['/' + data_dir])
                continue  # Skip specific file patterns

            if os.path.isdir(data_dir + '/pic'):
               create_html_if_needed(data_dir + '/pic')

            scp_list.extend([ '/'+ data_dir +'/pic', ])

            if not inps.piconly_flag:
               scp_list.extend([
               '/'+ data_dir +'/*.he5',
               '/'+ data_dir +'/inputs/geometryRadar.h5',
               '/'+ data_dir +'/inputs/smallbaselineApp.cfg',
               '/'+ data_dir +'/inputs/*.template',
               '/'+ data_dir +'/geo/geo_velocity.h5'
               ])

               if inps.triplets_flag:
                  scp_list.extend([
                  '/'+ data_dir +'/numTriNonzeroIntAmbiguity.h5',
                  ])
               if inps.geo_flag:
                  scp_list.extend([
                  '/'+ data_dir +'/geo/geo_*.h5',
                  '/'+ data_dir +'/geo/geo_*.dbf',
                  '/'+ data_dir +'/geo/geo_*.prj',
                  '/'+ data_dir +'/geo/geo_*.shp',
                  '/'+ data_dir +'/geo/geo_*.shx',
                  ])
        elif _is_dolphin_dir(data_dir):
            pic_path = data_dir + '/pic'
            if os.path.isdir(pic_path):
                _copy_minsar_log_to_pic(pic_path, inps.work_dir)
                create_html_if_needed(pic_path)
                scp_list.extend(['/' + pic_path])
            if not inps.piconly_flag:
                scp_list.extend(['/' + data_dir + '/timeseries/S1*.he5'])
        elif _is_pic_dir(data_dir) and os.path.isdir(data_dir):
            print(f"Uploading pic directory: {data_dir}")
            _copy_minsar_log_to_pic(data_dir, inps.work_dir)
            create_html_if_needed(data_dir)
            scp_list.extend(['/' + data_dir])
        elif data_dir.endswith('.he5') or glob.has_magic(data_dir):
            print(f"Uploading HE5 pattern: {data_dir}")
            scp_list.extend(['/' + data_dir])
        elif 'miaplpy' in data_dir:
            # Handle --all flag: upload entire directory
            if inps.all_flag:
                if 'network_' in data_dir:
                    dir_list = [ data_dir ]
                else:
                    dir_list = glob.glob(data_dir + '/network_*')

                for network_dir in dir_list:
                    if os.path.isdir(network_dir + '/pic'):
                        create_html_if_needed(network_dir + '/pic')
                    scp_list.extend(['/' + network_dir])
                continue  # Skip specific file patterns

            if 'network_' in data_dir:
               dir_list = [ data_dir ]
            else:
               dir_list = glob.glob(data_dir + '/network_*')

            # loop over network_* folder(s)
            # FA 8/2024: I may want to remove the network option., It is complicated. Rather give multiple directories
            for network_dir in dir_list:
                create_html_if_needed(network_dir + '/pic')

                scp_list.extend([ '/'+ network_dir + '/pic', ])

                if not inps.piconly_flag:
                    scp_list.extend([
                    '/'+ network_dir +'/*.he5',
                    '/'+ network_dir +'/demErr.h5',
                    '/'+ network_dir +'/velocity.h5',
                    '/'+ network_dir +'/temporalCoherence.h5',
                    '/'+ network_dir +'/avgSpatialCoh.h5',
                    '/'+ network_dir +'/maskTempCoh.h5',
                    '/'+ network_dir +'/numTriNonzeroIntAmbiguity.h5',
                    '/'+ network_dir +'/../maskPS.h5',
                    '/'+ network_dir +'/inputs/geometryRadar.h5',
                    '/'+ network_dir +'/geo/geo_velocity.h5'             # already included earlier
                    ])
                    if inps.geo_flag:
                       scp_list.extend([
                       '/'+ network_dir +'/geo/geo_*.h5',
                       '/'+ network_dir +'/geo/geo_*.dbf',
                       '/'+ network_dir +'/geo/geo_*.prj',
                       '/'+ network_dir +'/geo/geo_*.shp',
                       '/'+ network_dir +'/geo/geo_*.shx'
                       ])

                    timeseries_path = 'timeseries_demErr.h5'
                    if  os.path.exists(network_dir + '/' + 'timeseries_ERA5_demErr.h5'):
                        timeseries_path = 'timeseries_ERA5_demErr.h5'

                    # FA 8/24: This section for edgar to have the high-res files
                    if inps.geo_flag:
                        scp_list.extend([
                        '/'+ data_dir +'../maskPS.h5',
                        '/'+ data_dir +'/inputs/geometryRadar.h5',
                        '/'+ data_dir +'/temporalCoherence_lowpass_gaussian.h5',
                        '/'+ data_dir +'/maskTempCoh__lowpass_gaussian.h5',
                        '/'+ data_dir + '/' + timeseries_path
                        ])

                    if inps.triplets_flag:
                       scp_list.extend([
                       '/'+ network_dir +'/numTriNonzeroIntAmbiguity.h5',
                       ])

                    # After completion of network_* loops
                    scp_list.extend([
                    '/'+ os.path.dirname(data_dir) +'/maskPS.h5',
                    '/'+ os.path.dirname(data_dir) +'/miaplpyApp.cfg',
                    '/'+ os.path.dirname(data_dir) +'/inputs/geometryRadar.h5',
                    '/'+ os.path.dirname(data_dir) +'/inputs/baselines',
                    '/'+ os.path.dirname(data_dir) +'/inputs/*.template',
                    '/'+ os.path.dirname(data_dir) +'/inverted/tempCoh_average*',
                    '/'+ os.path.dirname(data_dir) +'/inverted/tempCoh_full*'
                    ])
        else:
            # Other directories (e.g., EnvD140, sarvey, etc.) - upload entire directory
            print(f"Uploading all contents of directory: {data_dir}")
            if os.path.isdir(data_dir + '/pic'):
                create_html_if_needed(data_dir + '/pic')
            scp_list.extend(['/' + data_dir])

    print('################')
    print('Data to upload: ')
    for element in scp_list:
        print(element)
    print('################')
    os.chdir(inps.work_dir)
    import time
    time.sleep(2)

    # Write upload.log for all uploaded directories
    remote_urls = []
    for data_dir in inps.data_dirs:
        data_dir = data_dir.rstrip('/')

        if _is_insarmaps_log(data_dir):
            continue

        pic_dir = _pic_dir_for_upload(data_dir)
        if pic_dir:
            rel_pic = os.path.relpath(pic_dir, inps.work_dir)
            remote_url = 'http://' + REMOTEHOST_DATA + REMOTE_DIR + project_name + '/' + rel_pic

            # Append to main upload.log
            with open('upload.log', 'a') as f:
                f.write(remote_url + "\n")

            # Write to pic/upload.log (only if pic directory exists)
            with open(pic_dir + '/upload.log', 'w') as f:
                f.write(remote_url + "\n")

            remote_urls.append(remote_url)
        else:
            # If no pic directory, URL points to the uploaded directory itself
            remote_url = 'http://' + REMOTEHOST_DATA + REMOTE_DIR + project_name + '/' + data_dir

            # Append to main upload.log
            with open('upload.log', 'a') as f:
                f.write(remote_url + "\n")

            remote_urls.append(remote_url)

    if _is_isce3_upload(inps):
        _append_isce3_project_logs(scp_list, inps.work_dir)

    # If miaplpy/inputs is uploaded and contains slcStack.h5, add missing ORBIT_DIRECTION / relative_orbit
    add_missing_attributes_for_upload(inps.work_dir, inps.data_dirs)

    print('\n################')
    for data_dir in inps.data_dirs:
        data_dir = data_dir.rstrip('/')
        # Only delete if directory name contains 'mintpy' or 'miaplpy'
        if 'mintpy' in data_dir or 'miaplpy' in data_dir:
            print('Deleting remote mintpy/miaplpy directories ...')
            remote_path = f'{REMOTE_DIR}{project_name}/{data_dir}'
            cleanup_cmd = f'ssh {REMOTE_CONNECTION} "rm -rf {remote_path}"'
            print(f'Deleting: {cleanup_cmd}')
            status = subprocess.Popen(cleanup_cmd, shell=True).wait()
            if status != 0:
                print(f'Warning: Could not delete {remote_path} (may not exist yet)')

    print('################\n')

    # Step 1: Collect all unique directories that need to be created
    unique_dirs = set()
    upload_commands = []

    for pattern in scp_list:
        if len(glob.glob(inps.work_dir + pattern)) >= 1:
            files = glob.glob(inps.work_dir + pattern)

            if os.path.isfile(files[0]):
                full_dir_name = os.path.dirname(files[0])
            elif os.path.isdir(files[0]):
                full_dir_name = os.path.dirname(files[0])
            else:
                raise Exception('ERROR finding directory in pattern in upload_data_products.py')

            dir_name = full_dir_name.removeprefix(inps.work_dir + '/')
            unique_dirs.add(dir_name)

            # Store upload command for later
            upload_cmd = f'rsync -avz --progress {inps.work_dir}{pattern} {REMOTE_CONNECTION_DIR}/{project_name}/{"/".join(pattern.split("/")[0:-1])}'
            upload_commands.append(upload_cmd)

    for data_dir in inps.data_dirs:
        raw = data_dir.rstrip('/')
        if _is_insarmaps_log(raw):
            continue
        local = os.path.join(inps.work_dir, raw)
        if os.path.isdir(local):
            unique_dirs.add(os.path.relpath(local, inps.work_dir))
        elif _is_pic_dir(raw):
            unique_dirs.add(os.path.basename(raw.lstrip('./')))

    # Step 2: Create ALL remote directories with ONE SSH command
    if unique_dirs:
        print('\nCreating all remote directories with one SSH command...')
        all_dirs = ' '.join([f'{REMOTE_DIR}{project_name}/{d}' for d in sorted(unique_dirs)])
        command = f'ssh {REMOTE_CONNECTION} "mkdir -p {all_dirs}"'
        print(command)
        status = subprocess.Popen(command, shell=True).wait()
        if status != 0:
            raise Exception('ERROR creating remote directories in upload_data_products.py')

    # Step 3: Upload all data
    for command in upload_commands:
        print('\nUploading data:')
        print(command)
        status = subprocess.Popen(command, shell=True).wait()
        if status != 0:
            raise Exception('ERROR uploading using rsync in upload_data_products.py')

    # Step 4: Adjust permissions under the project directory on the remote host
    if upload_commands or unique_dirs:
        print('\nAdjusting permissions for all uploaded directories...')
        project_remote = f'{REMOTE_DIR}{project_name}'
        command = f'ssh {REMOTEUSER}@{REMOTEHOST_DATA} "chmod -R u=rwX,go=rX {project_remote}"'
        print(command)
        status = subprocess.Popen(command, shell=True).wait()
        if status != 0:
            raise Exception('ERROR adjusting permissions in upload_data_products.py')

##########################################
    add_log_remote_he5(scp_list, inps.work_dir)
##########################################
    if not inps.quiet_summary:
        print('\nData at:')
        for url in remote_urls:
            print(url)

    return None

if __name__ == "__main__":
    main()
