#!/usr/bin/env python3

import asf_search as asf
import datetime
import argparse
import os

workDir = 'SCRATCHDIR'

# Define the description and epilog of the script
EXAMPLE = """Command line client for searching with the ASF Federated API,
downloading data, and more.  See the options and
descriptions below for details and usage examples.
"""

epi = """
Usage Examples:
    These will do the search and download data:
    Sentinel-1(IW, standard interferomrtric wide swath):
        asf_search_args.py --processingLevel=SLC --start-date=2014-10-04 --end-date=2015-10-05 --intersectsWith='POLYGON((-77.98 0.78,-77.91 0.78,-77.91 0.85,-77.98 0.85,-77.98 0.78))' --relativeOrbit 142 --print
        asf_search_args.py --processingLevel=SLC --start-date=2014-10-04 --end-date=2015-10-05 --platform SENTINEL1 --print 
        asf_search_args.py --processingLevel=CSLC --start=20141004 --end=20151005 --intersectsWith='POLYGON((-77.98 0.78,-77.91 0.78,-77.91 0.85,-77.98 0.85,-77.98 0.78))' --print --dir=$SCRATCHDIR/CSLC
        asf_search_args.py --processingLevel=CSLC --start=2014-10-04 --end=2015-10-05 --intersectsWith='POLYGON((-77.98 0.78,-77.91 0.7881,-77.91 0.85,-77.98 0.85,-77.98 0.78))' --print --dir=$SCRATCHDIR/CSLC
        asf_search_args.py --processingLevel=BURST --relativeOrbit=142 --intersectsWith='Polygon((-78.09 0.6, -77.74 0.6, -77.74 0.83, -78.09 0.83, -78.09 0.6))' --start=2014-10-31 --end=2015-01-01 --print
        asf_search_args.py --processingLevel=BURST --relativeOrbit=142 --intersectsWith='Polygon((-78.09 0.6, -77.74 0.6, -77.74 0.83, -78.09 0.83, -78.09 0.6))' --start=2014-10-31 --end=2015-01-01 --print-burst
        asf_search_args.py --processingLevel=SLC --start=2014-10-04 --end=2015-10-05 --relativeOrbit=170 --download --dir=$SCRATCHDIR/SLC --parallel=4
        asf_search_args.py --processingLevel=SLC --intersectsWith='POLYGON((-77.98 0.78,-77.91 0.78,-77.91 0.85,-77.98 0.85,-77.98 0.78))'
        asf_search_args.py --processingLevel=BURST --start=2014-10-04 --end=2015-12-31 --burst-id=349025 --download
    Stripmap (SM):
        asf_search_args.py --processingLevel=SLC --relativeOrbit 75 --intersectsWith='POLYGON((-24.5 14.8,-24.3 14.8,-24.3 15.1,-24.5 15.1,-24.5 14.8))' --start=2018-05-01 --end=2018-10-31 --beamMode=S6 --print
    ALOS-2 (ScanSAR L1.1):
        asf_search_args.py --processingLevel=1.1 --relativeOrbit 89 --intersectsWith='POLYGON((9.16 4.20,9.18 4.20,9.18 4.22,9.16 4.22,9.16 4.20))' --start=2014-10-04 --end=2015-12-31 --print

    Polarization is "VV" always.
    """

def create_parser(iargs=None, namespace=None):
    """ Creates command line argument parser object. """
    parser = argparse.ArgumentParser(description=EXAMPLE, formatter_class=argparse.RawTextHelpFormatter, epilog=epi)

    parser.add_argument('--intersectsWith', metavar='POLYGON', help='Poligon of the wanted area of interest to intersect with the search')
    parser.add_argument('--start', metavar='YYYY-MM-DD or YYYYMMDD', help='Start date of the search')
    parser.add_argument('--end', metavar='YYYY-MM-DD or YYYYMMDD', help='End date of the search')
    parser.add_argument('--start-date', metavar='YYYY-MM-DD or YYYYMMDD', default=None, help='Start date of the search')
    parser.add_argument('--end-date', metavar='YYYY-MM-DD or YYYYMMDD', default=None, help='End date of the search')
    parser.add_argument('--processingLevel', dest='processing_level', choices=['SLC', 'CSLC', 'BURST', '1.1'], default='SLC', help='Product type to download')
    parser.add_argument('--beamMode', dest='beam_mode',  default=None, help='Beam mode (IW, S1 to S7)')
    parser.add_argument('--flightDirection', choices=['ASC', 'DESC', 'ASCENDING', 'DESCENDING'], default=None, help='Flight direction of the satellite (ASCENDING or DESCENDING)')
    parser.add_argument('--relativeOrbit', dest='relative_orbit', type=int, default=None, metavar='ORBIT', help='Relative Orbit Path')
    parser.add_argument('--burst-id', nargs='*', type=str, metavar='BURST', default=None, help='Burst ID')
    parser.add_argument('--frame', type=int, metavar='FRAME', help='Frame number (Default: None')
    parser.add_argument('--platform', nargs='?',metavar='SENTINEL1, ALOS2', help='Platform to search')
    parser.add_argument('--parallel', type=int, default=6, help='Number of parallel downloads (Default: 1)')
    parser.add_argument('--print', dest='print', action='store_true', help='Print the whole search results')
    parser.add_argument('--download', action='store_true', help='Download the data')
    parser.add_argument('--print-burst', dest='print_burst', action='store_true', help='Print burst IDs')
    parser.add_argument('--dir', metavar='FOLDER', help='Specify path to download the data, if not specified, the data will be downloaded in SCRATCHDIR directory')

    inps = parser.parse_args()

    if "BURST" in inps.processing_level:
        inps.processing_level = asf.PRODUCT_TYPE.BURST
    elif "CSLC" in inps.processing_level:
        inps.processing_level = asf.PRODUCT_TYPE.CSLC
    elif "SLC" in inps.processing_level:
        inps.processing_level = asf.PRODUCT_TYPE.SLC
    elif "1.1" in inps.processing_level:
        inps.processing_level = asf.PRODUCT_TYPE.L1_1

    if inps.start or inps.start_date:
        try:
            inps.start_date = datetime.datetime.strptime(inps.start if inps.start else inps.start_date, '%Y-%m-%d').date()
        except:
            inps.start_date = datetime.datetime.strptime(inps.start if inps.start else inps.start_date, '%Y%m%d').date()

    if inps.end or inps.end_date:
        try:
            inps.end_date = datetime.datetime.strptime(inps.end if inps.end else inps.end_date, '%Y-%m-%d').date()
        except:
            inps.end_date = datetime.datetime.strptime(inps.end if inps.end else inps.end_date, '%Y%m%d').date()
    else:
        inps.end_date = datetime.datetime.now().date()

    if inps.processing_level==asf.PRODUCT_TYPE.SLC:
        inps.polarization = ['VV','VV+VH'] 
    elif inps.processing_level==asf.PRODUCT_TYPE.BURST:
        inps.polarization = ['VV']
        inps.dataset = asf.DATASET.SLC_BURST
    else:
        inps.polarization = ['VV', 'VV+VH']

    if inps.platform in ['SENTINEL1', 'SENTINEL-1', 'S1', 'S-1']:
        inps.platform = asf.PLATFORM.SENTINEL1
        inps.beam_swath = 'IW'
    elif inps.platform in ['ALOS-2', 'ALOS2'] or inps.processing_level==asf.PRODUCT_TYPE.L1_1:
        # platform = asf.PLATFORM.ALOS-2
        inps.platform = asf.PLATFORM.ALOS
        inps.processing_level=asf.PRODUCT_TYPE.L1_1
        inps.dataset = asf.DATASET.ALOS_2
        inps.polarization=['HH', 'HV']

    if inps.flightDirection:
        if inps.flightDirection in ['ASCENDING', 'ASC']:
            inps.flightDirection = asf.FLIGHT_DIRECTION.ASCENDING
        elif inps.flightDirection in ['DESCENDING', 'DESC']:
            inps.flightDirection = asf.FLIGHT_DIRECTION.DESCENDING

    if inps.download is not None:
        if inps.dir:
            inps.dir = os.path.expandvars(inps.dir)
            os.makedirs(inps.dir, exist_ok=True)
        else:
            inps.dir = os.getcwd()
    else:
        inps.dir = None

    if not (inps.download or inps.print_burst):
        inps.print = True

    return inps

def main(iargs=None, namespace=None):
    """Main function to execute the search and download."""
    inps = create_parser(iargs, namespace)

    print("Searching for data...\n")

    results = asf.search(
        platform=inps.platform,
        processingLevel=inps.processing_level,
        start=inps.start_date,
        end=inps.end_date,
        intersectsWith=inps.intersectsWith,
        flightDirection=inps.flightDirection,
        beamMode=inps.beam_mode,
        relativeOrbit=inps.relative_orbit,
        relativeBurstID=inps.burst_id,
        polarization=inps.polarization,
        dataset=inps.dataset,
    )

    print(f"Found {len(results)} results.")
    if inps.print and len(results) > 0:
            print(', '.join(k for k in results[0].properties.keys() if k not in ['centerLat', 'centerLon']))

    burst_ids =[]
    for r in results:
        if inps.print_burst:
            if asf.PRODUCT_TYPE.BURST in inps.processing_level:
                if r.properties['burst']['relativeBurstID'] not in burst_ids:
                    burst_ids.append(r.properties['burst']['relativeBurstID'])
                    print(f"Relative Burst ID: {r.properties['burst']['relativeBurstID']}")
            else:
                print('-' * 100)
                print(f"Start date: {r.properties['startTime']}, End date: {(r.properties['stopTime'])}, {r.geometry['type']}: {r.geometry['coordinates']}, Path of satellite: {r.properties['pathNumber']}, Granule:  {r.properties['granuleType']}")
        elif inps.print:
            print(', '.join(str(v) for k, v in r.properties.items() if k not in ['centerLat', 'centerLon']))

    if inps.download == True:
        print(f"Downloading {len(results)} results...")
        print(f"Parallel: {inps.parallel}")
        print(f"Download directory: {inps.dir}")
        results.download(
            path = inps.dir,
            session = asf.ASFSession(),
            processes = inps.parallel
        )

    print("Done.")


if __name__ == "__main__":
    main()