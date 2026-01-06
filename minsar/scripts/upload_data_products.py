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
from minsar.src.minsar.create_html import create_html

sys.path.insert(0, os.getenv('SSARAHOME'))
import password_config as password

##############################################################################
EXAMPLE = """For slcStack.h5 use:
     upload_data_products.py miaplpy/inputs

Examples:
    upload_data_products.py mintpy
    upload_data_products.py miaplpy
    upload_data_products.py miaplpy/network_single_reference
    upload_data_products.py miaplpy/inputs
"""

DESCRIPTION = (
    "Uploads mintpy and miaplpy data products to jetstream server"
)

def create_parser():
    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE,
                 formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('data_dirs', nargs='+', metavar="DIRECTORY", help='upload specific mintpy/miaplpy directory')
    parser.add_argument('--geo', dest='geo_flag', action='store_true', default=False, help='uploads geo  directory')
    parser.add_argument('--all', dest='all_flag', action='store_true', default=False, help='uploads full directory')
    parser.add_argument('--pic', dest='piconly_flag', action='store_true', default=False, help='uploads only pic directory')
    #parser.add_argument('--triplets', dest='triplets_flag', action='store_true', default=False, help='uploads numTriNonzeroIntAmbiguity.h5')
    parser.add_argument('--triplets', dest='triplets_flag', action='store_true', default=True, help='uploads numTriNonzeroIntAmbiguity.h5')

    return parser

def cmd_line_parse(iargs=None):

    parser = create_parser()
    inps = parser.parse_args(args=iargs)

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

def add_log_remote_hdfeos5(scp_list, work_dir):
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

    REMOTEHOST_DATA = os.getenv('REMOTEHOST_DATA')
    REMOTEUSER = os.getenv('REMOTEUSER')
    REMOTE_DIR = '/data/HDF5EOS/'
    REMOTE_CONNECTION = REMOTEUSER + '@' + REMOTEHOST_DATA
    REMOTE_CONNECTION_DIR = REMOTE_CONNECTION + ':' + REMOTE_DIR

    scp_list = []
    for data_dir in inps.data_dirs:
        data_dir = data_dir.rstrip('/')

        # If path is a subdirectory (contains '/') but NOT a miaplpy network directory,
        # upload all contents (e.g., mintpy/inputs, mintpy/pic, test1/EnvD140)
        # Exclude miaplpy network directories - they should use standard processing
        if '/' in data_dir and os.path.isdir(data_dir) and 'network_' not in data_dir:
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
            # sarvey. May work for other directories containing images
            if os.path.isdir(data_dir + '/pic'):
               create_html_if_needed(data_dir + '/pic')
            scp_list.extend([ '/'+ data_dir +'/pic', ])
            scp_list.extend([ '/'+ data_dir +'/../maskfiles/*', ])
            #scp_list.extend([ '/'+ data_dir +'/shp', ])
            #scp_list.extend([ '/'+ data_dir +'/outputs/output_csv/*.csv', ])

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
        
        # Check if this directory has a pic subdirectory
        pic_dir = data_dir + '/pic'
        if os.path.isdir(pic_dir):
            # If pic exists, URL points to pic directory
            remote_url = 'http://' + REMOTEHOST_DATA + REMOTE_DIR + project_name + '/' + data_dir + '/pic'
            
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

    print('\n################')
    print('Deleting remote directories...')
    for data_dir in inps.data_dirs:
        data_dir = data_dir.rstrip('/')
        remote_path = f'{REMOTE_DIR}{project_name}/{data_dir}'
        cleanup_cmd = f'ssh {REMOTE_CONNECTION} "rm -rf {remote_path}"'
        print(f'Deleting: {cleanup_cmd}')
        status = subprocess.Popen(cleanup_cmd, shell=True).wait()
        if status != 0:
            print(f'Warning: Could not delete {remote_path} (may not exist yet)')

    print('################\n')
    for pattern in scp_list:
        if ( len(glob.glob(inps.work_dir + '/' + pattern)) >= 1 ):
            #files=glob.glob(inps.work_dir + '/' + pattern)
            files=glob.glob(inps.work_dir + pattern)

            if os.path.isfile(files[0]):
               full_dir_name = os.path.dirname(files[0])
            elif os.path.isdir(files[0]):
               full_dir_name = os.path.dirname(files[0])
            else:
                raise Exception('ERROR finding directory in pattern in upload_data_products.py')

            dir_name = full_dir_name.removeprefix(inps.work_dir +'/')

            # create remote directory
            print ('\nCreating remote directory:',dir_name)
            command = 'ssh ' + REMOTE_CONNECTION + ' mkdir -p ' + REMOTE_DIR + project_name + '/' + dir_name
            print (command)
            status = subprocess.Popen(command, shell=True).wait()
            if status is not 0:
                raise Exception('ERROR creating remote directory in upload_data_products.py')

            # upload data
            print ('\nUploading data:')
            command = f'rsync -avz --progress {inps.work_dir}{pattern} {REMOTE_CONNECTION_DIR}/{project_name}/{"/".join(pattern.split("/")[0:-1])}'
            print (command)
            status = subprocess.Popen(command, shell=True).wait()
            if status is not 0:
                raise Exception('ERROR uploading using rsync in upload_data_products.py')

    # adjust permissions
    print ('\nAdjusting permissions:')
    command = 'ssh ' + REMOTEUSER + '@' +REMOTEHOST_DATA + ' chmod -R u=rwX,go=rX ' + REMOTE_DIR + project_name  + '/' + os.path.dirname(data_dir)
    print (command)
    status = subprocess.Popen(command, shell=True).wait()
    if status is not 0:
        raise Exception('ERROR adjusting permissions in upload_data_products.py')

##########################################
    add_log_remote_hdfeos5(scp_list, inps.work_dir)
##########################################
    print('\nData at:')
    for url in remote_urls:
        print(url)

    return None

if __name__ == "__main__":
    main()
