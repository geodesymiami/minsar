#!/usr/bin/env python3
########################
# Author: Heresh Fattahi
# Modified by Sara Mirzaee (still working)
#######################

import os, sys, glob
import argparse
import datetime
import time
sys.path.insert(0, os.getenv('SENTINEL_STACK'))
from Stack import config, run, sentinelSLC

helpstr = '''

Stack processor for Sentinel-1 data using ISCE software.

For a full list of different options, try stackSentinel.py -h

stackSentinel.py generates all configuration and run files required to be executed for a stack of Sentinel-1 TOPS data. 

Following are required to start processing:

1) a folder that includes Sentinel-1 SLCs, 
2) a DEM (Digital Elevation Model) 
3) a folder that includes precise orbits (use dloadOrbits.py to download/ update your orbit folder. Missing orbits downloaded on the fly.) 
4) a folder for Sentinel-1 Aux files (which is used for correcting the Elevation Antenna Pattern). 

Note that stackSentinel.py does not process any data. It only prepares a lot of input files for processing and a lot of run files. Then you need to execute all those generated run files in order. To know what is really going on, after running stackSentinel.py, look at each run file generated by stackSentinel.py. Each run file actually has several commands that are independent from each other and can be executed in parallel. The config files for each run file include the processing options to execute a specific command/function.

Note also that run files need to be executed in order, i.e., running run_3 needs results from run_2, etc.

##############################################

#Examples:

stackSentinel.py can be run for different workflows including: a stack of interferogram, a stack of correlation files, a stack of offsets or a coregistered stack of SLC. Workflow can be chosen with -W option.

%%%%%%%%%%%%%%%
Example 1:
# interferogram workflow with 2 nearest neighbor connections (default coregistration is NESD):

stackSentinel.py -s ../SLC/ -d ../../MexicoCity/demLat_N18_N20_Lon_W100_W097.dem.wgs84 -b '19 20 -99.5 -98.5' -a ../../AuxDir/ -o ../../Orbits -c 2

%%%%%%%%%%%%%%%
Example 2:
# interferogram workflow with all possible interferograms and coregistration with only geometry:

stackSentinel.py -s ../SLC/ -d ../../MexicoCity/demLat_N18_N20_Lon_W100_W097.dem.wgs84 -b '19 20 -99.5 -98.5' -a ../../AuxDir/ -o ../../Orbits -C geometry -c all

%%%%%%%%%%%%%%%
Example 3:
# correlation workflow with all possible correlation pairs and coregistration with geometry:

stackSentinel.py -s ../SLC/ -d ../../MexicoCity/demLat_N18_N20_Lon_W100_W097.dem.wgs84 -b '19 20 -99.5 -98.5' -a ../../AuxDir/ -o ../../Orbits -C geometry -c all -W correlation

%%%%%%%%%%%%%%%
Example 4:
# slc workflow that produces a coregistered stack of SLCs  

stackSentinel.py -s ../SLC/ -d ../../MexicoCity/demLat_N18_N20_Lon_W100_W097.dem.wgs84 -b '19 20 -99.5 -98.5' -a ../../AuxDir/ -o ../../Orbits -C NESD  -W slc

##############################################

#Note:

For all workflows, coregistration can be done using only geometry or with geometry plus refined azimuth offsets through NESD approach.
Existing workflows: slc, interferogram, correlation, offset

'''


class customArgparseAction(argparse.Action):
    def __call__(self, parser, args, values, option_string=None):
        '''
        The action to be performed.
        '''
        print(helpstr)
        parser.exit()


def createParser():
    parser = argparse.ArgumentParser(
        description='Preparing the directory structure and config files for stack processing of Sentinel data')

    parser.add_argument('-H', '--hh', nargs=0, action=customArgparseAction,
                        help='Display detailed help information.')

    parser.add_argument('-s', '--slc_directory', dest='slc_dirname', type=str, required=True,
                        help='Directory with all Sentinel SLCs')

    parser.add_argument('-o', '--orbit_directory', dest='orbit_dirname', type=str, required=True,
                        help='Directory with all orbits')

    parser.add_argument('-a', '--aux_directory', dest='aux_dirname', type=str, required=True,
                        help='Directory with all aux files')

    parser.add_argument('-w', '--working_directory', dest='work_dir', type=str, default='./',
                        help='Working directory ')

    parser.add_argument('-d', '--dem', dest='dem', type=str, required=True,
                        help='Directory with the DEM')

    parser.add_argument('-m', '--master_date', dest='master_date', type=str, default=None,
                        help='Directory with master acquisition')

    parser.add_argument('-c', '--num_connections', dest='num_connections', type=str, default='1',
                        help='number of interferograms between each date and subsequent dates. -- Default : 1')

    parser.add_argument('-O', '--num_overlap_connections', dest='num_overlap_connections', type=str, default='3',
                        help='number of overlap interferograms between each date and subsequent dates used for NESD computation (for azimuth offsets misregistration). -- Default : 3')

    parser.add_argument('-n', '--swath_num', dest='swath_num', type=str, default='1 2 3',
                        help="A list of swaths to be processed. -- Default : '1 2 3'")

    parser.add_argument('-b', '--bbox', dest='bbox', type=str, default=None,
                        help="Lat/Lon Bounding SNWE. -- Example : '19 20 -99.5 -98.5' -- Default : common overlap between stack")

    parser.add_argument('-t', '--text_cmd', dest='text_cmd', type=str, default=''
                        ,
                        help="text command to be added to the beginning of each line of the run files. -- Example : 'source ~/.bash_profile;' -- Default : ''")

    parser.add_argument('-x', '--exclude_dates', dest='exclude_dates', type=str, default=None
                        ,
                        help="List of the dates to be excluded for processing. -- Example : '20141007,20141031' -- Default: No dates excluded")

    parser.add_argument('-i', '--include_dates', dest='include_dates', type=str, default=None
                        ,
                        help="List of the dates to be included for processing. -- Example : '20141007,20141031' -- Default: No dates excluded")

    parser.add_argument('-z', '--azimuth_looks', dest='azimuthLooks', type=str, default='3'
                        , help='Number of looks in azimuth for interferogram multi-looking. -- Default : 3')

    parser.add_argument('-r', '--range_looks', dest='rangeLooks', type=str, default='9'
                        , help='Number of looks in range for interferogram multi-looking. -- Default : 9')

    parser.add_argument('-f', '--filter_strength', dest='filtStrength', type=str, default='0.5'
                        , help='Filter strength for interferogram filtering. -- Default : 0.5')

    parser.add_argument('-e', '--esd_coherence_threshold', dest='esdCoherenceThreshold', type=str, default='0.85'
                        ,
                        help='Coherence threshold for estimating azimuth misregistration using enhanced spectral diversity. -- Default : 0.85')

    parser.add_argument('--snr_misreg_threshold', dest='snrThreshold', type=str, default='10'
                        ,
                        help='SNR threshold for estimating range misregistration using cross correlation. -- Default : 10')

    parser.add_argument('-u', '--unw_method', dest='unwMethod', type=str, default='snaphu'
                        , help='Unwrapping method (icu or snaphu). -- Default : snaphu')

    parser.add_argument('-p', '--polarization', dest='polarization', type=str, default='vv'
                        , help='SAR data polarization -- Default : vv')

    parser.add_argument('-C', '--coregistration', dest='coregistration', type=str, default='NESD'
                        , help='Coregistration options: a) geometry b) NESD -- Default : NESD')

    parser.add_argument('-W', '--workflow', dest='workflow', type=str, default='interferogram'
                        ,
                        help='The InSAR processing workflow : (interferogram, offset, slc, correlation) -- Default : interferogram')

    parser.add_argument('--start_date', dest='startDate', type=str, default=None
                        ,
                        help='Start date for stack processing. Acquisitions before start date are ignored. format should be YYYY-MM-DD e.g., 2015-01-23')

    parser.add_argument('--stop_date', dest='stopDate', type=str, default=None
                        ,
                        help='Stop date for stack processing. Acquisitions after stop date are ignored. format should be YYYY-MM-DD e.g., 2017-02-26')

    parser.add_argument('-useGPU', '--useGPU', dest='useGPU', action='store_true', default=False,
                        help='Allow App to use GPU when available')

    return parser


def cmdLineParse(iargs=None):
    parser = createParser()
    inps = parser.parse_args(args=iargs)

    inps.slc_dirname = os.path.abspath(inps.slc_dirname)
    inps.orbit_dirname = os.path.abspath(inps.orbit_dirname)
    inps.aux_dirname = os.path.abspath(inps.aux_dirname)
    inps.work_dir = os.path.abspath(inps.work_dir)
    inps.dem = os.path.abspath(inps.dem)

    return inps


####################################
def get_dates(inps):
    # Given the SLC directory This function extracts the acquisition dates
    # and prepares a dictionary of sentinel slc files such that keys are
    # acquisition dates and values are object instances of sentinelSLC class
    # which is defined in Stack.py

    if inps.bbox is not None:
        bbox = [float(val) for val in inps.bbox.split()]

    if inps.exclude_dates is not None:
        excludeList = inps.exclude_dates.split(',')
    else:
        excludeList = []

    if inps.include_dates is not None:
        includeList = inps.include_dates.split(',')
    else:
        includeList = []

    if os.path.isfile(inps.slc_dirname):
        print('reading SAFE files from: ' + inps.slc_dirname)
        SAFE_files = []
        for line in open(inps.slc_dirname):
            SAFE_files.append(str.replace(line, '\n', '').strip())

    else:
        SAFE_files = glob.glob(os.path.join(inps.slc_dirname, 'S1*_IW_SLC*zip'))  # changed to zip file by Minyan Zhong

    if len(SAFE_files) == 0:
        raise Exception('No SAFE file found')

    elif len(SAFE_files) == 1:
        raise Exception('At least two SAFE file is required. Only one SAFE file found.')

    else:
        print ("Number of SAFE files found: " + str(len(SAFE_files)))

    if inps.startDate is not None:
        stackStartDate = datetime.datetime(*time.strptime(inps.startDate, "%Y-%m-%d")[0:6])
    else:
        # if startDate is None let's fix it to first JPL's staellite lunch date :)
        stackStartDate = datetime.datetime(*time.strptime("1958-01-31", "%Y-%m-%d")[0:6])

    if inps.stopDate is not None:
        stackStopDate = datetime.datetime(*time.strptime(inps.stopDate, "%Y-%m-%d")[0:6])
    else:
        stackStopDate = datetime.datetime(*time.strptime("2158-01-31", "%Y-%m-%d")[0:6])

    ################################
    # write down the list of SAFE files in a txt file which will be used:
    f = open('SAFE_files.txt', 'w')
    safe_count = 0
    safe_dict = {}
    bbox_poly = [[bbox[0], bbox[2]], [bbox[0], bbox[3]], [bbox[1], bbox[3]], [bbox[1], bbox[2]]]
    for safe in SAFE_files:
        safeObj = sentinelSLC(safe)
        safeObj.get_dates()
        if safeObj.start_date_time < stackStartDate or safeObj.start_date_time > stackStopDate:
            excludeList.append(safeObj.date)
            continue

        safeObj.get_orbit(inps.orbit_dirname, inps.work_dir)

        # check if the date safe file is needed to cover the BBOX
        reject_SAFE = False
        if safeObj.date not in excludeList and inps.bbox is not None:

            reject_SAFE = True
            pnts = safeObj.getkmlQUAD(safe)

            # looping over the corners, keep the SAF is one of the corners is within the BBOX
            lats = []
            lons = []
            for pnt in pnts:
                lon = float(pnt.split(',')[0])
                lat = float(pnt.split(',')[1])

                # keep track of all the corners to see of the product is larger than the bbox
                lats.append(lat)
                lons.append(lon)

                import matplotlib
                from matplotlib.path import Path as Path

                #                bbox = SNWE
                #                polygon = bbox[0] bbox[2]       SW
                #                          bbox[0] bbox[3]       SE
                #                          bbox[1] bbox[3]       NE
                #                          bbox[1] bbox[2]       NW

                poly = Path(bbox_poly)
                point = (lat, lon)
                in_bbox = poly.contains_point(point)

                # product corner falls within BBOX (SNWE)
                if in_bbox:
                    reject_SAFE = False

            # If the product is till being rejected, check if the BBOX corners fall within the frame
            if reject_SAFE:
                for point in bbox_poly:
                    frame = [[a, b] for a, b in zip(lats, lons)]
                    poly = Path(frame)
                    in_frame = poly.contains_point(point)
                    if in_frame:
                        reject_SAFE = False

        if not reject_SAFE:
            if safeObj.date not in safe_dict.keys() and safeObj.date not in excludeList:
                safe_dict[safeObj.date] = safeObj
            elif safeObj.date not in excludeList:
                safe_dict[safeObj.date].safe_file = safe_dict[safeObj.date].safe_file + ' ' + safe

            # write the SAFE file as it will be used
            f.write(safe + '\n')
            safe_count += 1
    # closing the SAFE file overview
    f.close()
    print ("Number of SAFE files to be used (cover BBOX): " + str(safe_count))

    ################################
    dateList = [key for key in safe_dict.keys()]
    dateList.sort()
    print ("*****************************************")
    print ("Number of dates : " + str(len(dateList)))
    print ("List of dates : ")
    print (dateList)

    ################################
    # get the overlap lat and lon bounding box
    S = []
    N = []
    W = []
    E = []
    safe_dict_bbox = {}
    safe_dict_bbox_finclude = {}
    safe_dict_finclude = {}
    safe_dict_frameGAP = {}
    print ('date      south      north')
    for date in dateList:
        # safe_dict[date].get_lat_lon()
        safe_dict[date].get_lat_lon_v2()

        # safe_dict[date].get_lat_lon_v3(inps)
        S.append(safe_dict[date].SNWE[0])
        N.append(safe_dict[date].SNWE[1])
        W.append(safe_dict[date].SNWE[2])
        E.append(safe_dict[date].SNWE[3])
        print (date, safe_dict[date].SNWE[0], safe_dict[date].SNWE[1])
        if inps.bbox is not None:
            if safe_dict[date].SNWE[0] <= bbox[0] and safe_dict[date].SNWE[1] >= bbox[1]:
                safe_dict_bbox[date] = safe_dict[date]
                safe_dict_bbox_finclude[date] = safe_dict[date]
            elif date in includeList:
                safe_dict_finclude[date] = safe_dict[date]
                safe_dict_bbox_finclude[date] = safe_dict[date]

        # tracking dates for which there seems to be a gap in coverage
        if not safe_dict[date].frame_nogap:
            safe_dict_frameGAP[date] = safe_dict[date]

    print ("*****************************************")
    print ("The overlap region among all dates (based on the preview kml files):")
    print (" South   North   East  West ")
    print (max(S), min(N), max(W), min(E))
    print ("*****************************************")
    if max(S) > min(N):
        print ("""WARNING: 
           There might not be overlap between some dates""")
        print ("*****************************************")
    ################################
    print ('All dates (' + str(len(dateList)) + ')')
    print (dateList)
    print("")
    if inps.bbox is not None:
        safe_dict = safe_dict_bbox
        dateList = [key for key in safe_dict.keys()]
        dateList.sort()
        print ('dates covering the bbox (' + str(len(dateList)) + ')')
        print (dateList)
        print("")

        if len(safe_dict_finclude) > 0:
            # updating the dateList that will be used for those dates that are forced include
            # but which are not covering teh BBOX completely
            safe_dict = safe_dict_bbox_finclude
            dateList = [key for key in safe_dict.keys()]
            dateList.sort()

            # sorting the dates of the forced include
            dateListFinclude = [key for key in safe_dict_finclude.keys()]
            print('dates forced included (do not cover the bbox completely, ' + str(len(dateListFinclude)) + ')')
            print(dateListFinclude)
            print("")

    # report any potential gaps in fame coverage
    if len(safe_dict_frameGAP) > 0:
        dateListframeGAP = [key for key in safe_dict_frameGAP.keys()]
        print('dates for which it looks like there are missing frames')
        print(dateListframeGAP)
        print("")

    if inps.master_date is None:
        if len(dateList) < 1:
            print('*************************************')
            print('Error:')
            print('No acquisition forfills the temporal range and bbox requirement.')
            sys.exit(1)
        inps.master_date = dateList[0]
        print ("The master date was not chosen. The first date is considered as master date.")

    print ("")
    print ("All SLCs will be coregistered to : " + inps.master_date)

    slaveList = [key for key in safe_dict.keys()]
    slaveList.sort()
    slaveList.remove(inps.master_date)
    print ("slave dates :")
    print (slaveList)
    print ("")

    return dateList, inps.master_date, slaveList, safe_dict


def selectNeighborPairs(dateList, num_connections,
                        updateStack=False):  # should be changed to able to account for the existed aquisitions -- Minyan Zhong

    pairs = []
    if num_connections == 'all':
        num_connections = len(dateList) - 1
    else:
        num_connections = int(num_connections)

    num_connections = num_connections + 1
    for i in range(len(dateList) - 1):
        for j in range(i + 1, i + num_connections):
            if j < len(dateList):
                pairs.append((dateList[i], dateList[j]))

    return pairs


########################################
# Below are few workflow examples.

def slcStack(inps, acquisitionDates, stackMasterDate, slaveDates, safe_dict, updateStack, mergeSLC=False):
    #############################
    i = 0

    i += 1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i) + "_unpack_slc_topo_master")
    if not updateStack:
        runObj.unpackStackMasterSLC(safe_dict)
    runObj.unpackSlavesSLC(stackMasterDate, slaveDates, safe_dict)
    runObj.finalize()

    i += 1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i) + "_average_baseline")
    runObj.averageBaseline(stackMasterDate, slaveDates)
    runObj.finalize()

    if inps.coregistration in ['NESD', 'nesd']:
        if not updateStack:
            i += 1
            runObj = run()
            runObj.configure(inps, 'run_' + str(i) + "_extract_burst_overlaps")
            runObj.extractOverlaps()
            runObj.finalize()

        i += 1
        runObj = run()
        runObj.configure(inps, 'run_' + str(i) + "_overlap_geo2rdr_resample")
        runObj.overlap_geo2rdr_resample(slaveDates)
        runObj.finalize()

        i += 1
        runObj = run()
        runObj.configure(inps, 'run_' + str(i) + "_pairs_misreg")
        if updateStack:
            runObj.pairs_misregistration(slaveDates, safe_dict)
        else:
            runObj.pairs_misregistration(acquisitionDates, safe_dict)
        runObj.finalize()

        i += 1
        runObj = run()
        runObj.configure(inps, 'run_' + str(i) + "_timeseries_misreg")
        runObj.timeseries_misregistration()
        runObj.finalize()

    i += 1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i) + "_geo2rdr_resample")
    runObj.geo2rdr_resample(slaveDates)
    runObj.finalize()

    i += 1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i) + "_extract_stack_valid_region")
    runObj.extractStackValidRegion()
    runObj.finalize()

    if mergeSLC:
        i += 1
        runObj = run()
        runObj.configure(inps, 'run_' + str(i) + "_merge")
        runObj.mergeMaster(stackMasterDate, virtual='False')
        runObj.mergeSlaveSLC(slaveDates, virtual='False')
        runObj.finalize()

        i += 1
        runObj = run()
        runObj.configure(inps, 'run_' + str(i) + "_grid_baseline")
        runObj.gridBaseline(stackMasterDate, slaveDates)
        runObj.finalize()

    return i


def correlationStack(inps, acquisitionDates, stackMasterDate, slaveDates, safe_dict, pairs, updateStack):
    #############################
    i = slcStack(inps, acquisitionDates, stackMasterDate, slaveDates, safe_dict, updateStack)

    i += 1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i) + "_merge_master")
    runObj.mergeMaster(stackMasterDate, virtual='False')
    runObj.finalize()

    i += 1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i) + "_merge_burst_igram")
    runObj.burstIgram_mergeBurst(acquisitionDates, safe_dict, pairs)
    runObj.finalize()

    i += 1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i) + "_filter_coherence")
    runObj.filter_coherence(pairs)
    runObj.finalize()


def interferogramStack(inps, acquisitionDates, stackMasterDate, slaveDates, safe_dict, pairs, updateStack):
    i = slcStack(inps, acquisitionDates, stackMasterDate, slaveDates, safe_dict, updateStack)

    i += 1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i) + "_merge_burst_igram")
    runObj.burstIgram_mergeBurst(acquisitionDates, safe_dict, pairs)
    runObj.finalize()

    i += 1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i) + "_filter_coherence")
    runObj.filter_coherence(pairs)
    runObj.finalize()

    i += 1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i) + "_unwrap")
    runObj.unwrap(pairs)
    runObj.finalize()

    i += 1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i) + "_merge_master_slave_slc")
    runObj.mergeMaster(stackMasterDate, virtual='True')
    runObj.mergeSlaveSLC(slaveDates, virtual='True')
    runObj.finalize()


def offsetStack(inps, acquisitionDates, stackMasterDate, slaveDates, safe_dict, pairs, updateStack):
    i = slcStack(inps, acquisitionDates, stackMasterDate, slaveDates, safe_dict, updateStack)

    i += 1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i) + "_merge_master_slave_slc")
    runObj.mergeMaster(stackMasterDate, virtual='False')
    runObj.mergeSlaveSLC(slaveDates, virtual='False')
    runObj.finalize()

    i += 1
    runObj = run()
    runObj.configure(inps, 'run_' + str(i) + "_dense_offsets")
    runObj.denseOffsets(pairs)
    runObj.finalize()


def checkCurrentStatus(inps):
    acquisitionDates, stackMasterDate, slaveDates, safe_dict = get_dates(inps)
    coregSLCDir = os.path.join(inps.work_dir, 'coreg_slaves')
    stackUpdate = False
    if os.path.exists(coregSLCDir):
        coregSlaves = glob.glob(os.path.join(coregSLCDir, '[0-9]???[0-9]?[0-9]?'))
        coregSLC = [os.path.basename(slv) for slv in coregSlaves]
        coregSLC.sort()
        if len(coregSLC) > 0:
            print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
            print('')
            print('An existing stack with following coregistered SLCs was found:')
            print(coregSLC)
            print('')
            print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')

        else:
            pass

        newAcquisitions = list(set(slaveDates).difference(set(coregSLC)))
        newAcquisitions.sort()
        if len(newAcquisitions) > 0:
            print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
            print('')
            print('New acquisitions was found: ')
            print(newAcquisitions)
            print('')
            print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
        else:
            print('         *********************************           ')
            print('                 *****************           ')
            print('                     *********           ')
            print('Warning:')
            print('The stack already exists. No new acquisition found to update the stack.')
            print('')
            print('                     *********           ')
            print('                 *****************           ')
            print('         *********************************           ')
            sys.exit(1)

        if inps.coregistration in ['NESD', 'nesd']:

            numSLCReprocess = 2 * int(inps.num_overlap_connections)
            if numSLCReprocess > len(slaveDates):
                numSLCReprocess = len(slaveDates)

            latestCoregSLCs = coregSLC[-1 * numSLCReprocess:]
            latestCoregSLCs_original = list(set(slaveDates).intersection(set(latestCoregSLCs)))
            if len(latestCoregSLCs_original) < numSLCReprocess:
                raise Exception(
                    'The original SAFE files for latest {0} coregistered SLCs is needed'.format(numSLCReprocess))

        else:  # add by Minyan Zhong, should be changed later as numSLCReprocess should be 0

            numSLCReprocess = int(inps.num_connections)
            if numSLCReprocess > len(slaveDates):
                numSLCReprocess = len(slaveDates)

            latestCoregSLCs = coregSLC[-1 * numSLCReprocess:]
            latestCoregSLCs_original = list(set(slaveDates).intersection(set(latestCoregSLCs)))
            if len(latestCoregSLCs_original) < numSLCReprocess:
                raise Exception(
                    'The original SAFE files for latest {0} coregistered SLCs is needed'.format(numSLCReprocess))

        print ('Last {0} coregistred SLCs to be updated: '.format(numSLCReprocess), latestCoregSLCs)

        slaveDates = latestCoregSLCs + newAcquisitions
        slaveDates.sort()

        acquisitionDates = slaveDates.copy()
        acquisitionDates.append(stackMasterDate)
        acquisitionDates.sort()
        print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
        print('')
        print('acquisitions used in this update: ')
        print('')
        print(acquisitionDates)
        print('')
        print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
        print('')
        print('stack master:')
        print('')
        print(stackMasterDate)
        print('')
        print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
        print('')
        print('slave acquisitions to be processed: ')
        print('')
        print(slaveDates)
        print('')
        print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
        safe_dict_new = {}
        for d in acquisitionDates:
            safe_dict_new[d] = safe_dict[d]
        safe_dict = safe_dict_new
        stackUpdate = True
    else:
        print('No existing stack was identified. A new stack will be generated.')

    return acquisitionDates, stackMasterDate, slaveDates, safe_dict, stackUpdate


def main(iargs=None):
    inps = cmdLineParse(iargs)

    if os.path.exists(os.path.join(inps.work_dir, 'run_files')):
        print('')
        print('**************************')
        print('run_files folder exists.')
        print(os.path.join(inps.work_dir, 'run_files'), ' already exists.')
        print('Please remove or rename this folder and try again.')
        print('')
        print('**************************')
        sys.exit(1)

    if inps.workflow not in ['interferogram', 'offset', 'correlation', 'slc']:
        print('')
        print('**************************')
        print('Error: workflow ', inps.workflow, ' is not valid.')
        print('Please choose one of these workflows: interferogram, offset, correlation, slc')
        print('Use argument "-W" or "--workflow" to choose a specific workflow.')
        print('**************************')
        print('')
        sys.exit(1)

    acquisitionDates, stackMasterDate, slaveDates, safe_dict, updateStack = checkCurrentStatus(inps)

    if updateStack:
        print('')
        print('Updating an existing stack ...')
        print('')
        pairs = selectNeighborPairs(slaveDates, inps.num_connections, updateStack)  # will be change later
    else:
        pairs = selectNeighborPairs(acquisitionDates, inps.num_connections, updateStack)

    print ('*****************************************')
    print ('Coregistration method: ', inps.coregistration)
    print ('Workflow: ', inps.workflow)
    print ('*****************************************')
    if inps.workflow == 'interferogram':

        interferogramStack(inps, acquisitionDates, stackMasterDate, slaveDates, safe_dict, pairs, updateStack)

    elif inps.workflow == 'offset':

        offsetStack(inps, acquisitionDates, stackMasterDate, slaveDates, safe_dict, pairs, updateStack)

    elif inps.workflow == 'correlation':

        correlationStack(inps, acquisitionDates, stackMasterDate, slaveDates, safe_dict, pairs, updateStack)

    elif inps.workflow == 'slc':

        slcStack(inps, acquisitionDates, stackMasterDate, slaveDates, safe_dict, updateStack, mergeSLC=True)


if __name__ == "__main__":
    # Main engine
    main()

