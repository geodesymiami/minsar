#!/usr/bin/env python3
########################
# Author: Falk Amelung
#######################

import os
import sys
import argparse
import subprocess
from minsar.objects import message_rsmas
from minsar.job_submission import JOB_SUBMIT

############################################################
EXAMPLE = """Examples:
    create_horzvert_timeseries_jobfile.py ChilesSenD142/mintpy ChilesSenA120/mintpy --ref-lalo 0.649 -77.878
    create_horzvert_timeseries_jobfile.py ChilesSenD142/mintpy ChilesSenA120/mintpy --ref-lalo 0.649 -77.878 --intervals 6
    create_horzvert_timeseries_jobfile.py hvGalapagosSenD128/mintpy hvGalapagosSenA106/mintpy --ref-lalo -0.81 -91.190
    create_horzvert_timeseries_jobfile.py hvGalapagosSenD128/miaplpy/network_single_reference hvGalapagosSenA106/miaplpy/network_single_reference --ref-lalo -0.81 -91.190 --no-ingest-los
    create_horzvert_timeseries_jobfile.py hvGalapagosSenD128/miaplpy/network_single_reference hvGalapagosSenA106/miaplpy/network_single_reference --ref-lalo -0.81 -91.190 --no-insarmaps
    create_horzvert_timeseries_jobfile.py FernandinaSenD128/mintpy/ FernandinaSenA106/mintpy/ --ref-lalo -0.453 -91.390
    create_horzvert_timeseries_jobfile.py FernandinaSenD128/miaplpy/network_delaunay_4 FernandinaSenA106/miaplpy/network_delaunay_4 --ref-lalo -0.415 -91.543
    create_horzvert_timeseries_jobfile.py MaunaLoaSenDT87/mintpy MaunaLoaSenAT124/mintpy --period 20181001:20191031 --ref-lalo 19.50068 -155.55856
    
    # Additional examples with SLURM options:
    create_horzvert_timeseries_jobfile.py ChilesSenD142/mintpy ChilesSenA120/mintpy --ref-lalo 0.649 -77.878 --queue skx --walltime 1:30
    create_horzvert_timeseries_jobfile.py hvGalapagosSenD128/mintpy hvGalapagosSenA106/mintpy --ref-lalo -0.81 -91.190 --submit
"""
###########################################################################################
def create_parser():
    synopsis = 'Create jobfile for horizontal/vertical decomposition and ingestion into insarmaps'
    epilog = EXAMPLE
    parser = argparse.ArgumentParser(description=synopsis, epilog=epilog, formatter_class=argparse.RawTextHelpFormatter)
    
    # Positional arguments
    parser.add_argument('file1', help='First input directory/file')
    parser.add_argument('file2', help='Second input directory/file')
    
    # Options from horzvert_insarmaps.bash
    parser.add_argument('--mask-thresh', dest='mask_thresh', type=float,
                        help='Coherence threshold for masking (default: 0.55)')
    parser.add_argument('--ref-lalo', dest='ref_lalo', nargs='+', 
                        help='Reference point (lat,lon or lat lon)')
    parser.add_argument('--lat-step', dest='lat_step', type=float,
                        help='Latitude step for geocoding (default: -0.0002)')
    parser.add_argument('--horz-az-angle', dest='horz_az_angle', type=float,
                        help='Horizontal azimuth angle (default: 90)')
    parser.add_argument('--window-size', dest='window_size', type=int,
                        help='Window size for reference point lookup (default: 3)')
    parser.add_argument('--intervals', dest='intervals', type=int,
                        help='Interval block index (default: 2)')
    parser.add_argument('--start-date', dest='start_date', type=str,
                        help='Start date of limited period (YYYYMMDD)')
    parser.add_argument('--end-date', dest='end_date', type=str,
                        help='End date of limited period (YYYYMMDD)')
    parser.add_argument('--period', dest='period', type=str,
                        help='Period of the search (YYYYMMDD:YYYYMMDD)')
    parser.add_argument('--no-ingest-los', dest='no_ingest_los', action='store_true',
                        help='Skip ingesting both input files (FILE1 and FILE2) with --ref-lalo (default: ingest-los is enabled)')
    parser.add_argument('--no-insarmaps', dest='no_insarmaps', action='store_true',
                        help='Skip running ingest_insarmaps.bash (default: insarmaps ingestion is enabled)')
    parser.add_argument('--debug', dest='debug', action='store_true',
                        help='Enable debug mode (set -x)')
    
    # SLURM job options
    parser.add_argument("--queue", dest="queue", metavar="QUEUE", 
                        default=os.getenv('QUEUENAME'), 
                        help="Name of queue to submit job to")
    parser.add_argument('--walltime', dest='wall_time', metavar="WALLTIME (HH:MM)", 
                        default=None, 
                        help='job walltime (default: from job_defaults.cfg)')
    parser.add_argument('--submit', dest='submit', action='store_true',
                        help='submit the job after creating the jobfile')
   
    inps = parser.parse_args()
    return inps

def main(iargs=None):
    
    inps = create_parser()
    inps.work_dir = os.getcwd()

    input_arguments = sys.argv[1::]
    message_rsmas.log(inps.work_dir, os.path.basename(__file__) + ' ' + ' '.join(input_arguments))

    # Set default values for JOB_SUBMIT
    inps.num_data = 1
    
    job_obj = JOB_SUBMIT(inps)

    job_name = f"horzvert_timeseries"
    job_file_name = job_name
    
    command_parts = ['horzvert_timeseries.bash', inps.file1, inps.file2]
    
    # Add optional arguments
    if inps.mask_thresh is not None:
        command_parts.extend(['--mask-thresh', str(inps.mask_thresh)])
    
    if inps.ref_lalo:
        command_parts.append('--ref-lalo')
        if len(inps.ref_lalo) == 1:
            # Single argument like "lat,lon"
            command_parts.append(inps.ref_lalo[0])
        else:
            # Two arguments like lat lon
            command_parts.extend(inps.ref_lalo[:2])
    
    if inps.lat_step is not None:
        command_parts.extend(['--lat-step', str(inps.lat_step)])
    
    if inps.horz_az_angle is not None:
        command_parts.extend(['--horz-az-angle', str(inps.horz_az_angle)])
    
    if inps.window_size is not None:
        command_parts.extend(['--window-size', str(inps.window_size)])
    
    if inps.intervals is not None:
        command_parts.extend(['--intervals', str(inps.intervals)])
    
    if inps.start_date:
        command_parts.extend(['--start-date', inps.start_date])
    
    if inps.end_date:
        command_parts.extend(['--end-date', inps.end_date])
    
    if inps.period:
        command_parts.extend(['--period', inps.period])
    
    if inps.no_ingest_los:
        command_parts.append('--no-ingest-los')
    
    if inps.no_insarmaps:
        command_parts.append('--no-insarmaps')
    
    if inps.debug:
        command_parts.append('--debug')
    
    final_command = [' '.join(command_parts)]
    
    # Create the jobfile
    job_obj.submit_script(job_name, job_file_name, final_command, writeOnly='True')
    job_file_path = os.path.join(inps.work_dir, job_file_name + '.job')
    print('jobfile created: ', job_file_name + '.job')
    
    # Submit the job if --submit option is provided
    if inps.submit:
        try:
            result = subprocess.run(['sbatch', job_file_path], 
                                  check=True, 
                                  capture_output=True, 
                                  text=True)
            print('Job submitted:', result.stdout.strip())
        except subprocess.CalledProcessError as e:
            print(f'Error submitting job: {e.stderr}')
            return 1
        except FileNotFoundError:
            print('Error: sbatch command not found. Are you on a SLURM cluster?')
            return 1

    return None

###########################################################################################

if __name__ == "__main__":
    main()



