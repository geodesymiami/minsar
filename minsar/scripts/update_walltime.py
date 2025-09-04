#! /usr/bin/env python3
import os
import sys
import shutil
import time
import argparse
import subprocess
import minsar
import minsar.utils.process_utilities as putils

def walltime_is_longer_than_2_hours(wall_time):
    h, m, s = map(int, wall_time.strip().split(':'))
    total_seconds = h * 3600 + m * 60 + s
    return total_seconds > 2 * 3600  # 7200 seconds

def main(iargs=None):

     parser = argparse.ArgumentParser(description='CLI Parser')
     arg_group = parser.add_argument_group('General options:')
     arg_group.add_argument('job_file_name', help='The job file that failed with a timeout error.\n')

     inps = parser.parse_args(args=iargs)

     wall_time = putils.extract_walltime_from_job_file(inps.job_file_name)
     new_wall_time = putils.multiply_walltime(wall_time, factor=1.2)
     
     #  dev queue: don't change walltime to longer than 2 hours (limit on Stamepede3)
     queue_name = putils.extract_queuename_from_job_file(inps.job_file_name)
     if "dev" in queue_name and walltime_is_longer_than_2_hours(new_wall_time):
         new_wall_time = "02:00:00"

     putils.replace_walltime_in_job_file(inps.job_file_name, new_wall_time)

if __name__ == "__main__":
     main()
