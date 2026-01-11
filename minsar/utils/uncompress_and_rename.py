#!/usr/bin/env python3
########################
# Author: Falk Amelung
# Based on unpack_sensors.py by Sara Mirzaee
########################

"""
Script to uncompress a single archive file and rename the folder to date format.
This is designed to be run in parallel via SLURM for many archive files.

Usage:
    uncompress_and_rename.py archive_file sensor_type [--remove]
    
Example:
    uncompress_and_rename.py SLC_ORIG/TSX1_SM_036_strip_014_20170901.tar.gz TSX/TDX
"""

import os
import sys
import glob
import shutil
import argparse
import xml.etree.ElementTree as etree


def create_parser():
    parser = argparse.ArgumentParser(description='Uncompress and rename a single archive file')
    parser.add_argument('archive_file', help='Path to archive file (.zip, .tar, .gz)')
    parser.add_argument('sensor_type', help='Sensor type (e.g., CSK, TSX/TDX, ALOS1, ALOS2, RSAT2, Envisat)')
    parser.add_argument('--remove', action='store_true', help='Remove archive after successful extraction')
    parser.add_argument('--data-type', default='slc', choices=['slc', 'raw'], help='Data type (default: slc)')
    return parser


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


def main():
    parser = create_parser()
    args = parser.parse_args()
    
    # Import uncompressfile from ISCE
    sys.path.append(os.path.join(os.getenv('ISCE_STACK'), 'stripmapStack'))
    from uncompressFile import uncompressfile
    
    archive_file = os.path.abspath(args.archive_file)
    workdir = os.path.dirname(archive_file)
    out_folder = os.path.basename(archive_file).split('.')[0]
    out_folder = os.path.join(workdir, out_folder)
    
    print(f"Processing: {archive_file}")
    
    # Check if archive file exists
    if not os.path.isfile(archive_file):
        print(f"ERROR: Archive file not found: {archive_file}")
        sys.exit(1)
    
    # Uncompress the file
    print(f"  Uncompressing to: {out_folder}")
    success = uncompressfile(archive_file, out_folder)
    
    if not success:
        print(f"  ERROR: Uncompressing failed for {archive_file}")
        # Move to FAILED_FILES directory
        failed_dir = os.path.join(workdir, 'FAILED_FILES')
        os.makedirs(failed_dir, exist_ok=True)
        try:
            os.rename(archive_file, os.path.join(failed_dir, os.path.basename(archive_file)))
            print(f"  Moved to FAILED_FILES directory")
        except OSError as e:
            print(f"  Failed to move to FAILED_FILES: {e}")
        sys.exit(1)
    
    # Get the date from the extracted folder
    print(f"  Extracting date...")
    successflag, imgDate = get_date_from_folder(out_folder, args.sensor_type)
    
    if not successflag:
        print(f"  ERROR: Could not extract date from {out_folder}")
        sys.exit(1)
    
    # Create date directory and move contents
    print(f"  Renaming to date: {imgDate}")
    date_dir = os.path.join(workdir, imgDate)
    os.makedirs(date_dir, exist_ok=True)
    
    # Check if folder already exists in date directory
    image_folder_out = os.path.join(date_dir, os.path.basename(out_folder))
    if os.path.isdir(image_folder_out):
        print(f"  Removing existing folder: {image_folder_out}")
        shutil.rmtree(image_folder_out)
    
    # Move the extracted folder contents into the date folder
    if os.path.isfile(out_folder):
        # For Envisat (file, not directory)
        cmd = f'mv {out_folder} {date_dir}/.'
        os.system(cmd)
    else:
        # For other sensors (directory)
        cmd = f'mv {out_folder}/* {date_dir}/.'
        os.system(cmd)
        cmd = f'rmdir {out_folder}'
        os.system(cmd)
    
    print(f"  Success: {imgDate}")
    
    # Handle the archive file
    if args.remove:
        os.remove(archive_file)
        print(f"  Deleted archive: {archive_file}")
    else:
        archive_dir = os.path.join(workdir, 'ARCHIVED_FILES')
        os.makedirs(archive_dir, exist_ok=True)
        cmd = f'mv {archive_file} {archive_dir}/.'
        os.system(cmd)
        print(f"  Archived: {archive_file}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

