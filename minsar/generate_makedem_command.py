#! /usr/bin/env python3
###############################################################################

import os
import sys
import glob
import shutil

import math
import argparse
from minsar.objects import message_rsmas
from minsar.utils import process_utilities as putils
from minsar.utils import get_boundingBox_from_kml
from minsar.objects.dataset_template import Template
from minsar.utils import process_utilities as putils

EXAMPLE = """
  example:
  generate_makedem_command.py  $SAMPLES/GalapagosSenDT128.template
"""

DESCRIPTION = (""" Creates makedem_sardem.sh and makedem_isce.sh scripts.""")

def create_parser():
    synopsis = 'Create makedem commands'
    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('custom_template_file', help='template file with option settings.\n')
    inps = parser.parse_args()

    return inps

def format_bbox(bbox):
    west, south, east, north = bbox

    # Determine hemisphere for each coordinate
    south_str = f"S{abs(south):02d}" if south < 0 else f"N{abs(south):02d}"
    north_str = f"S{abs(north):02d}" if north < 0 else f"N{abs(north):02d}"
    west_str = f"W{abs(west):03d}" if west < 0 else f"E{abs(west):03d}"
    east_str = f"W{abs(east):03d}" if east < 0 else f"E{abs(east):03d}"

    # Format the output string
    name = f"{south_str}_{north_str}_{west_str}_{east_str}"
    return name

###########################################################################################
def exist_valid_dem_dir(dem_dir):
    """ Returns True of a valid dem dir exist. Otherwise remove dem and return False """
    if os.path.isdir(dem_dir):
        products = glob.glob(os.path.join(dem_dir, '*dem.wgs84*'))
        if len(products) >= 3:
            print('DEM products already exist. if not satisfying, remove the folder and run again')
            return True
        else:
            shutil.rmtree(dem_dir)
            return False
    else:
        return False

###########################################################################################
def get_SouthNorthWestEast_from_ssara_kml():
    """ Assumes ssara_kml file exists in inps.slc_dir """
    try:
       ssara_kml_file=sorted( glob.glob('SLC/ssara_search_*.kml') )[-1]
    except:
       # FA 7/2024: If there is no kml it should rerun generate_download_command
       # generate_download_command.main([inps.custom_template_file])
       raise FileExistsError('No SLC/ssara_search_*.kml found')

    print('using kml file:',ssara_kml_file)

    try:
        bbox = get_boundingBox_from_kml.main( [ssara_kml_file, '--delta_lon' , '0'] )
    except:
        raise Exception('Problem with *kml file: does not contain bbox information')

    bbox = bbox.split('SNWE:')[1]
    print('bbox:',bbox)
    bbox = [val for val in bbox.split()]

    south = bbox[0]
    north = bbox[1]
    west = bbox[2]
    east = bbox[3].split('\'')[0]

    south = math.floor(float(south) - 0.5)
    north = math.ceil(float(north) + 0.5)
    west = math.floor(float(west) - 0.5)
    east = math.ceil(float(east) + 0.5)

    return south, north, west, east

###########################################################################################
def get_SouthNorthWestEast_from_template(dataset_template):

    ssaraopt_string, ssaraopt_dict = dataset_template.generate_ssaraopt_string()
    if any(option.startswith('ssaraopt.intersectsWith') for option in dataset_template.get_options()):
       intersects_string = f"--intersectsWith={ssaraopt_dict['intersectsWith']}"
    else:
       intersects_string = putils.generate_intersects_string(dataset_template, delta_lat=0.1)

    extent_str, extent_list = putils.convert_intersects_string_to_extent_string(intersects_string)
    print('New intersectsWith string using delta_lat=0.0: ', intersects_string)
    print('New extent string using delta_lat=0.1: ', extent_str)

    south = extent_list[1]
    north = extent_list[3]
    west = extent_list[0]
    east = extent_list[2]

    south = math.floor(float(south) - 0.5)
    north = math.ceil(float(north) + 0.5)
    west = math.floor(float(west) - 1.5)
    east = math.ceil(float(east) + 1.5)

    return south, north, west, east

###########################################################################################
def main(iargs=None):

    inps = create_parser()

    if not iargs is None:
        input_arguments = iargs
    else:
        input_arguments = sys.argv[1::]

    inps.work_dir = os.getcwd()
    message_rsmas.log(inps.work_dir, os.path.basename(__file__) + ' ' + ' '.join(input_arguments))

    dem_dir = os.path.join(inps.work_dir, 'DEM')
    if not exist_valid_dem_dir(dem_dir):
        os.mkdir(dem_dir)

    dataset_template = Template(inps.custom_template_file)

    # south, north, west, east = get_SouthNorthWestEast_from_ssara_kml()
    south, north, west, east = get_SouthNorthWestEast_from_template(dataset_template)

    demBbox = str(int(south)) + ' ' + str(int(north)) + ' ' + str(int(west)) + ' ' + str(int(east))
    bbox_LeftBottomRightTop = [int(west), int(south), int(east), int(north)]
    output_name = f"DEM/elevation_{format_bbox(bbox_LeftBottomRightTop)}.dem"

    command_sardem = f"sardem --bbox {int(west)} {int(south)} {int(east)}  {int(north)} --data COP --make-isce-xml --output {output_name}"
    command_isce = 'dem.py -a stitch --filling --filling_value 0 -b ' + demBbox + ' -c -u https://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL1.003/2000.02.11/'

    log_command_sardem = f"echo \"$(date +\"%Y%m%d:%H-%M\") * {command_sardem} | tee -a log\""
    log_command_isce = f"echo \"$(date +\"%Y%m%d:%H-%M\") * {command_isce} | tee -a log\""

    with open('makedem_sardem.sh', 'w') as f:
        f.write("#!/usr/bin/env bash\n")
        f.write("mkdir -p DEM\n")
        f.write(log_command_sardem + '\n')
        f.write(''.join(command_sardem) + '\n')
    with open('makedem_isce.sh', 'w') as f:
        f.write("#!/usr/bin/env bash\n")
        f.write("mkdir -p DEM\n")
        f.write(log_command_isce + '\n')
        f.write("cd DEM\n")
        f.write(''.join(command_isce) + '\n')

    os.chmod('makedem_sardem.sh', 0o755)
    os.chmod('makedem_isce.sh', 0o755)

    print('Generated makedem_sardem.sh script.')
    print('End of generate_dem_command.py')

    return None

###########################################################################################
if __name__ == '__main__':
    main()
