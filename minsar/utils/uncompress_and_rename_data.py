#!/usr/bin/env python3
########################
# Author: Falk Amelung
# Based on unpack_sensors.py
########################

"""
Script to uncompress a single data file and rename the folder to date format.
This is designed to be run in parallel via SLURM for many data files.
"""

import os
import sys
import glob
import shutil
import argparse
import xml.etree.ElementTree as etree
from pathlib import Path


############################################################
EXAMPLE = """Examples:
    uncompress_and_rename_data.py TSX1_SM_036_strip_014_20171004111805.tar.gz
    uncompress_and_rename_data.py CSKS2_RAW_B_HI_06_HH_RA_SF_20201009161233_20201009161240.tar.gz
    uncompress_and_rename_data.py ASA_IMS_1PNUPA20100906_175446_000000172089_00084_44354_0000.N1
    uncompress_and_rename_data.py TSX1_SM_036_strip_014_20171004111805.tar.gz --remove
    uncompress_and_rename_data.py ALOS2195073550-180102-WBDR1.1__D.zip --output-dir SLC --alos-stack
"""


def create_parser():
    synopsis = 'Uncompress a single data file and rename folder to date format'
    epilog = EXAMPLE
    parser = argparse.ArgumentParser(description=synopsis, epilog=epilog, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('data_file', help='Path to data file (.zip, .tar, .gz)')
    parser.add_argument('--remove', action='store_true', 
                        help='Remove data file after successful extraction (default: move to ARCHIVED_FILES directory)')
    parser.add_argument('--data-type', default='slc', choices=['slc', 'raw'], 
                        help='Data type (default: %(default)s). Note: raw option not yet implemented')
    parser.add_argument('--output-dir', type=Path, help='Directory for organized acquisitions (default: archive directory)')
    parser.add_argument('--alos-stack', action='store_true', help='Use alosStack YYMMDD data directories for ALOS-2')
    return parser


def detect_sensor_type(data_file):
    """Detect sensor type from filename."""
    basename = os.path.basename(data_file)
    
    # Check for different sensor patterns
    if basename.startswith('ASA'):
        return 'Envisat'
    elif basename.startswith('SAR_'):
        return 'ERS'
    elif basename.startswith('CSK') or basename.startswith('EL'):
        return 'CSK'
    elif basename.startswith('TSX') or basename.startswith('TDX') or 'dims_op' in basename:
        return 'TSX/TDX'
    elif basename.startswith('ALPSRP'):
        return 'ALOS1'
    elif basename.startswith('ALOS2') or (basename.startswith('00') and 'ALOS2' in basename):
        return 'ALOS2'
    elif basename.startswith('RS2'):
        return 'RSAT2'
    else:
        print(f"ERROR: Could not detect sensor type from filename: {basename}")
        sys.exit(1)


def get_date_from_folder(data_folder, sensor):
    """Get acquisition date from extracted folder."""
    
    if 'ALOS' in sensor:
        return get_ALOS_date(data_folder)
    elif 'CSK' in sensor:
        return get_CSK_date(data_folder)
    elif 'RSAT2' in sensor:
        return get_RSAT_date(data_folder)
    elif 'TSX' in sensor:
        return get_TSX_TDX_date(data_folder)
    elif 'Envisat' in sensor:
        return get_ENVISAT_date(data_folder)
    elif 'ERS' in sensor:
        return get_ERS_date(data_folder)
    else:
        return False, 'FAIL'


def get_ALOS_date(ALOSfolder):
    workreport_files = ('*workreport', 'summary.txt')
    for workreport_file in workreport_files:
        workreports = glob.glob(os.path.join(ALOSfolder, workreport_file))
        if len(workreports) > 0:
            for workreport in workreports:
                template_dict = {}
                with open(workreport) as openfile:
                    for line in openfile:
                        c = line.split("=")
                        template_dict[c[0].strip()] = c[1].strip()
                acquisitionDate = (str(template_dict['Img_SceneCenterDateTime'][1:9]))
                if acquisitionDate:
                    return True, acquisitionDate
    return False, 'FAIL'


def get_CSK_date(CSKfolder):
    CSKfile = glob.glob(os.path.join(CSKfolder, 'CSK*.h5'))
    if len(CSKfile) > 0:
        CSKfile = os.path.basename(CSKfile[0])
        parts = CSKfile.split('_')
        if len(parts) > 8:
            if len(parts[8]) > 8:
                acquisitionDate = parts[8][0:8]
                return True, acquisitionDate
    return False, 'FAIL'


def get_RSAT_date(RSAT2folder):
    RSAT2file = glob.glob(os.path.join(RSAT2folder, 'product.xml'))
    if len(RSAT2file) > 0:
        RSAT2file = RSAT2file[0]
        tree = etree.parse(RSAT2file)
        root = tree.getroot()
        for attributes in root.iter('{http://www.rsi.ca/rs2/prod/xml/schemas}sourceAttributes'):
            attribute_list = list(attributes)
        for attribute in attribute_list:
            if attribute.tag == '{http://www.rsi.ca/rs2/prod/xml/schemas}rawDataStartTime':
                date = attribute.text
                acquisitionDate = date[0:4] + date[5:7] + date[8:10]
                if len(acquisitionDate) == 8:
                    return True, acquisitionDate
    return False, 'FAIL'


def get_TSX_TDX_date(TXfolder):
    try:
        TXfile = glob.glob(os.path.join(TXfolder, 'T*X-1.SAR.L1B/T*X*/T*X*.xml'), recursive=True)[0]
        if len(TXfile) > 0:
            acquisitionDate = TXfile.split('.')[-2].split('_')[-1][0:8]
            return True, acquisitionDate
    except:
        pass
    return False, 'FAIL'


def get_ENVISAT_date(ENVISAT_folder):
    ENVISAT_file = os.path.basename(ENVISAT_folder)
    if len(ENVISAT_file) > 0:
        parts = ENVISAT_file.split('_')
        acquisitionDate = parts[2][6:]
        return True, acquisitionDate
    return False, 'FAIL'

def get_ERS_date(folder):
    file = os.path.basename(folder)
    if len(file) > 0:
        parts = file.split('_')
        acquisitionDate = parts[2][6:]
        return True, acquisitionDate
    return False, 'FAIL'


def main():
    parser = create_parser()
    args = parser.parse_args()
    
    data_file = os.path.abspath(args.data_file)
    workdir = os.path.dirname(data_file)
    output_dir = args.output_dir.expanduser().resolve() if args.output_dir else Path(workdir)
    
    print(f"Processing: {data_file}")

    if not os.path.isfile(data_file):
        archived = os.path.join(workdir, 'ARCHIVED_FILES', os.path.basename(data_file))
        if os.path.isfile(archived):
            print(f"  Already unpacked, skipping: {os.path.basename(data_file)}")
            return 0
        print(f"ERROR: Data file not found: {data_file}")
        sys.exit(1)
    
    sensor_type = detect_sensor_type(data_file)
    print(f"  Sensor: {sensor_type}")
    if args.alos_stack and sensor_type != 'ALOS2':
        parser.error('--alos-stack requires an ALOS-2 archive')
    
    # Check if file needs uncompression based on extension
    file_ext = os.path.splitext(data_file)[1].lower()
    needs_uncompress = file_ext in ['.zip', '.tar', '.gz', '.tgz', '.bz2']
    
    if needs_uncompress:
        # Import uncompressfile from ISCE
        sys.path.append(os.path.join(os.getenv('ISCE_STACK'), 'stripmapStack'))
        from uncompressFile import uncompressfile
        
        out_folder = os.path.basename(data_file).split('.')[0]
        out_folder = os.path.join(workdir, out_folder)
        if os.path.isdir(out_folder):
            print(f"  Removing partial extract: {out_folder}")
            shutil.rmtree(out_folder)

        print(f"  Uncompressing to: {out_folder}")
        success = uncompressfile(data_file, out_folder)
        
        if not success:
            print(f"  ERROR: Uncompressing failed for {data_file}")
            # Move to FAILED_FILES directory
            failed_dir = os.path.join(workdir, 'FAILED_FILES')
            os.makedirs(failed_dir, exist_ok=True)
            try:
                os.rename(data_file, os.path.join(failed_dir, os.path.basename(data_file)))
                print(f"  Moved to FAILED_FILES")
            except OSError as e:
                print(f"  Failed to move to FAILED_FILES: {e}")
            sys.exit(1)
        
        successflag, imgDate = get_date_from_folder(out_folder, sensor_type)
    else:
        # File doesn't need uncompression (e.g., .N1 files for Envisat)
        print(f"  File already uncompressed, extracting date...")
        out_folder = data_file  # For uncompressed files, the data_file itself is used
        successflag, imgDate = get_date_from_folder(data_file, sensor_type)
    
    if not successflag:
        print(f"  ERROR: Could not extract date from {out_folder}")
        sys.exit(1)
    
    # Create date directory and move contents
    print(f"  Date: {imgDate}")
    if args.alos_stack:
        imgDate = imgDate[2:]
    date_dir = output_dir / imgDate
    date_dir.mkdir(parents=True, exist_ok=True)
    
    if needs_uncompress:
        # Handle extracted folder from compressed archive
        # Check if folder already exists in date directory
        image_folder_out = date_dir / os.path.basename(out_folder)
        if os.path.isdir(image_folder_out):
            shutil.rmtree(image_folder_out)
        
        # Move the extracted folder contents into the date folder
        if os.path.isfile(out_folder):
            # For Envisat (file, not directory) - though this shouldn't happen for compressed files
            shutil.move(out_folder, date_dir)
        else:
            # For other sensors (directory)
            for item in Path(out_folder).iterdir():
                destination = date_dir / item.name
                if destination.exists():
                    if destination.is_dir():
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                shutil.move(str(item), destination)
            Path(out_folder).rmdir()
        
        # Handle the compressed data file
        if args.remove:
            os.remove(data_file)
        else:
            archive_dir = os.path.join(workdir, 'ARCHIVED_FILES')
            os.makedirs(archive_dir, exist_ok=True)
            shutil.move(data_file, archive_dir)
    else:
        # Handle uncompressed file (e.g., Envisat .N1)
        # Move the file directly into the date directory
        dest_file = date_dir / os.path.basename(data_file)
        if os.path.exists(dest_file):
            os.remove(dest_file)
        
        shutil.move(data_file, date_dir)
        print(f"  Moved to: {date_dir}/")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

