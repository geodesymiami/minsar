#!/usr/bin/env python3
########################
# Author:  Falk Amelung
#######################

import os
import subprocess
import sys
import glob
import shutil
import shlex
from datetime import datetime
import argparse
from pathlib import Path
from minsar.objects.rsmas_logging import loglevel
from minsar.objects import message_rsmas
import minsar.utils.process_utilities as putils
import minsar.job_submission as js

sys.path.insert(0, os.getenv('SSARAHOME'))
import password_config as password

##############################################################################
EXAMPLE = """Examples:
    upload_horzvert.py Fernandina
    upload_horzvert.py Fernandina/mintpy
    upload_horzvert.py Fernandina/miaplpy/network_single_reference
    upload_horzvert.py hvGalapagosSenD128
    upload_horzvert.py hvGalapagosSenD128/mintpy
"""

DESCRIPTION = (
    "Uploads horizontal/vertical decomposition data products to jetstream server"
)

def create_parser():
    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE,
                 formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('data_dir', metavar="DIRECTORY", help='directory to upload (e.g., Fernandina or Fernandina/mintpy)')

    return parser

def cmd_line_parse(iargs=None):

    parser = create_parser()
    inps = parser.parse_args(args=iargs)

    print('inps: ', inps)
    return inps

###################################################
def add_log_remote_hdfeos5(scp_list, work_dir):
    # add uploaded he5 files to remote log file

    REMOTEHOST_DATA = os.getenv('REMOTEHOST_DATA')
    REMOTEUSER = os.getenv('REMOTEUSER')
    REMOTELOGFILE = os.getenv('REMOTELOGFILE')

    # Find all .he5 files in scp_list (now contains individual file paths)
    he5_items = [item for item in scp_list if item.endswith('.he5')]
    
    if not he5_items:
        return  # No .he5 files found in scp_list

    he5_files = []
    for item in he5_items:
        clean_path = item.lstrip('/')
        full_path = os.path.join(work_dir, clean_path)
        if os.path.isfile(full_path):
            he5_files.append(full_path)

    if not he5_files:
        print(f"No .he5 files found, skipping remote log update")
        return

    relative_he5_files = [os.path.relpath(item, start=work_dir) for item in he5_files]
    current_date = datetime.now().strftime('%Y%m%d')

    file_path = he5_files[0]

    from mintpy.utils import readfile
    metadata = readfile.read_attribute(file_path)
    if 'data_footprint' not in metadata:
        raise Exception('ERROR: data_footprint not found in metadata')
    data_footprint = metadata['data_footprint']

    for relative_file in relative_he5_files:
        escaped_data_footprint = shlex.quote(data_footprint)

        command = f"""ssh {REMOTEUSER}@{REMOTEHOST_DATA} "echo {current_date} {relative_file} {escaped_data_footprint} >> {REMOTELOGFILE}" """

        status = subprocess.Popen(command, shell=True).wait()
        if status != 0:
            raise Exception('ERROR appending to remote log file in upload_horzvert.py')

##############################################################################

def main(iargs=None):

    inps = cmd_line_parse()

    inps.work_dir = os.getcwd()
    data_dir = inps.data_dir.rstrip('/')
    
    # Determine project name (top-level directory)
    path_parts = data_dir.split('/')
    project_name = path_parts[0]
    
    os.chdir(inps.work_dir)

    if not iargs is None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1::]

    message_rsmas.log(inps.work_dir, os.path.basename(__file__) + ' ' + ' '.join(input_arguments))

    REMOTEHOST_DATA = os.getenv('REMOTEHOST_DATA')
    REMOTEUSER = os.getenv('REMOTEUSER')
    REMOTE_DIR = '/data/HDF5EOS/'
    REMOTE_CONNECTION = REMOTEUSER + '@' + REMOTEHOST_DATA
    REMOTE_CONNECTION_DIR = REMOTE_CONNECTION + ':' + REMOTE_DIR

    scp_list = []
    
    # Check if a specific subdirectory is given (e.g., Fernandina/mintpy)
    if '/' in data_dir:
        # Upload only the specific subdirectory - all files but no subdirectories
        subdir = data_dir
        
        # Get all files (not directories) in the subdirectory
        full_subdir_path = os.path.join(inps.work_dir, subdir)
        if os.path.isdir(full_subdir_path):
            all_items = glob.glob(os.path.join(full_subdir_path, '*'))
            for item in all_items:
                if os.path.isfile(item):
                    rel_path = os.path.relpath(item, inps.work_dir)
                    scp_list.append('/' + rel_path)
    else:
        # Upload project directory: all top-level files (no subdirs) and mintpy*/miaplpy* directories recursively
        project_dir = data_dir
        
        # Get all files (not directories) at the top level of the project directory
        full_project_path = os.path.join(inps.work_dir, project_dir)
        if os.path.isdir(full_project_path):
            all_items = glob.glob(os.path.join(full_project_path, '*'))
            for item in all_items:
                if os.path.isfile(item):
                    rel_path = os.path.relpath(item, inps.work_dir)
                    scp_list.append('/' + rel_path)
        
        # Find and add mintpy* directories (upload recursively)
        mintpy_dirs = glob.glob(os.path.join(inps.work_dir, project_dir, 'mintpy*'))
        for mintpy_dir in mintpy_dirs:
            if os.path.isdir(mintpy_dir):
                rel_dir = os.path.relpath(mintpy_dir, inps.work_dir)
                scp_list.append('/' + rel_dir)
        
        # Find and add miaplpy* directories (upload recursively)
        miaplpy_dirs = glob.glob(os.path.join(inps.work_dir, project_dir, 'miaplpy*'))
        for miaplpy_dir in miaplpy_dirs:
            if os.path.isdir(miaplpy_dir):
                rel_dir = os.path.relpath(miaplpy_dir, inps.work_dir)
                scp_list.append('/' + rel_dir)

    print('################')
    print('Data to upload: ')
    for element in scp_list:
        print(element)
    print('################')
    os.chdir(inps.work_dir)
    import time
    time.sleep(2)

    remote_url = 'http://' + REMOTEHOST_DATA + REMOTE_DIR + data_dir

    print('\n################')
    print('Deleting remote directory...')
    remote_path = f'{REMOTE_DIR}{data_dir}'
    cleanup_cmd = f'ssh {REMOTE_CONNECTION} "rm -rf {remote_path}"'
    print(f'Deleting: {cleanup_cmd}')
    status = subprocess.Popen(cleanup_cmd, shell=True).wait()
    if status != 0:
        print(f'Warning: Could not delete {remote_path} (may not exist yet)')

    print('################\n')
    for pattern in scp_list:
        # Remove leading slash if present
        clean_pattern = pattern.lstrip('/')
        
        # Check if path exists
        full_path = os.path.join(inps.work_dir, clean_pattern)
        if not os.path.exists(full_path):
            print(f'Warning: Path does not exist, skipping: {full_path}')
            continue

        # Determine if it's a file or directory
        if os.path.isfile(full_path):
            # It's a file
            parent_dir = os.path.dirname(clean_pattern)
            
            # Create remote parent directory
            print(f'\nCreating remote directory: {parent_dir}')
            command = f'ssh {REMOTE_CONNECTION} "mkdir -p {REMOTE_DIR}{parent_dir}"'
            print(command)
            status = subprocess.Popen(command, shell=True).wait()
            if status != 0:
                raise Exception('ERROR creating remote directory in upload_horzvert.py')

            # Upload file
            print(f'\nUploading file: {clean_pattern}')
            command = f'rsync -avz --progress {full_path} {REMOTE_CONNECTION_DIR}{parent_dir}/'
            print(command)
            status = subprocess.Popen(command, shell=True).wait()
            if status != 0:
                raise Exception('ERROR uploading file using rsync in upload_horzvert.py')
                
        elif os.path.isdir(full_path):
            # It's a directory - upload recursively
            parent_dir = os.path.dirname(clean_pattern)
            
            # Create remote parent directory
            print(f'\nCreating remote parent directory: {parent_dir}')
            command = f'ssh {REMOTE_CONNECTION} "mkdir -p {REMOTE_DIR}{parent_dir}"'
            print(command)
            status = subprocess.Popen(command, shell=True).wait()
            if status != 0:
                raise Exception('ERROR creating remote directory in upload_horzvert.py')

            # Upload directory recursively
            print(f'\nUploading directory: {clean_pattern}')
            command = f'rsync -avz --progress {full_path} {REMOTE_CONNECTION_DIR}{parent_dir}/'
            print(command)
            status = subprocess.Popen(command, shell=True).wait()
            if status != 0:
                raise Exception('ERROR uploading directory using rsync in upload_horzvert.py')

    # adjust permissions
    print('\nAdjusting permissions:')
    command = 'ssh ' + REMOTEUSER + '@' + REMOTEHOST_DATA + ' chmod -R u=rwX,go=rX ' + REMOTE_DIR + project_name
    print(command)
    status = subprocess.Popen(command, shell=True).wait()
    if status is not 0:
        raise Exception('ERROR adjusting permissions in upload_horzvert.py')

##########################################
    add_log_remote_hdfeos5(scp_list, inps.work_dir)
##########################################
    print('Data at:')
    print(remote_url)

    return None

if __name__ == "__main__":
    main()

