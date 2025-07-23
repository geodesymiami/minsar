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
        asf_search_args.py --product=SLC --start-date=2014-10-04 --end-date=2015-10-05 --intersectsWith='POLYGON((-77.98 0.78,-77.91 0.78,-77.91 0.85,-77.98 0.85,-77.98 0.78))' --relativeOrbit 142 --download
        asf_search_args.py --product=SLC --start=2014-10-04 --end=2015-10-05 --platform SENTINEL1 --print --download
        asf_search_args.py --product=CSLC --start=20141004 --end=20151005 --intersectsWith='POLYGON((-77.98 0.78,-77.91 0.78,-77.91 0.85,-77.98 0.85,-77.98 0.78))' --download --dir=PATH
        asf_search_args.py --product=CSLC --start=2014-10-04 --end=2015-10-05 --intersectsWith='POLYGON((-77.98 0.78,-77.91 0.7881,-77.91 0.85,-77.98 0.85,-77.98 0.78))' --download --dir=PATH

    To use parallel downloads:
        asf_search_args.py --product=SLC --start=2014-10-04 --end=2015-10-05 --relativeOrbit=170 --download --dir=path/to/folder --parallel=4

    To search for a specific intersectsWith area:
        asf_search_args.py --product=SLC --intersectsWith='POLYGON((-77.9853 0.7881,-77.9185 0.7881,-77.9185 0.8507,-77.9853 0.8507,-77.9853 0.7881))'

    To search for a specific Burst:
        asf_search_args.py --product=BURST --start=2014-10-04 --burst-id=349025 --download

    Polarization is "VV" always.
    """

parser = argparse.ArgumentParser(description=EXAMPLE,
                formatter_class=argparse.RawTextHelpFormatter,
                epilog=epi)

parser.add_argument('--intersectsWith', metavar='POLYGON', help='Poligon of the wanted area of interest to intersect with the search')
parser.add_argument('--start', metavar='YYYY-MM-DD or YYYYMMDD', help='Start date of the search')
parser.add_argument('--end', metavar='YYYY-MM-DD or YYYYMMDD', help='End date of the search')
parser.add_argument('--start-date', metavar='YYYY-MM-DD or YYYYMMDD', help='Start date of the search')
parser.add_argument('--end-date', metavar='YYYY-MM-DD or YYYYMMDD', help='End date of the search')
parser.add_argument('--node', choices=['ASC', 'DESC', 'ASCENDING', 'DESCENDING'], help='Flight direction of the satellite (ASCENDING or DESCENDING)')
parser.add_argument('--relativeOrbit', type=int, metavar='ORBIT', help='Relative Orbit Path')
parser.add_argument('--frame', type=int, metavar='FRAME', help='Frame number (Default: None')
parser.add_argument('--product', dest='product', choices=['SLC', 'CSLC', 'BURST'], help='Product type to download')
parser.add_argument('--processingLevel', dest='processing_level', choices=['SLC', 'CSLC', 'BURST'], default='SLC', help='Product type to download')
parser.add_argument('--platform', nargs='?',metavar='SENTINEL1, SENTINEL-1A, SENTINEL-1B, ALOS2', help='Platform to search')
parser.add_argument('--burst-id', nargs='*', type=str, metavar='BURST', help='Burst ID')
parser.add_argument('--download', action='store_true', help='Download the data')
parser.add_argument('--parallel', type=int, default=1, help='Download the data in parallel, specify the number of processes to use')
parser.add_argument('--print-burst', dest='print_burst',action='store_true', help='Print the search results')
parser.add_argument('--print', dest='print',action='store_true', help='Print the whole search results ')
parser.add_argument('--dir', metavar='FOLDER', help='Specify path to download the data, if not specified, the data will be downloaded in SCRATCHDIR directory')

inps = parser.parse_args()

sdate = None
edate = None
node = None
orbit = None
burst_id = None
product = []


# if 'BURST' in inps.product:
#     product.append(asf.PRODUCT_TYPE.BURST)

#     if inps.burst_id:
#         burst_id = inps.burst_id

# if 'CSLC' in inps.product or inps.product is None:
#     product.append(asf.PRODUCT_TYPE.CSLC)

if inps.start or inps.start_date:
    try:
        sdate = datetime.datetime.strptime(inps.start if inps.start else inps.start_date, '%Y-%m-%d').date()
    except:
        sdate = datetime.datetime.strptime(inps.start if inps.start else inps.start_date, '%Y%m%d').date()

if inps.end or inps.end_date:
    try:
        edate = datetime.datetime.strptime(inps.end if inps.end else inps.end_date, '%Y-%m-%d').date()
    except:
        edate = datetime.datetime.strptime(inps.end if inps.end else inps.end_date, '%Y%m%d').date()
else:
    edate = datetime.datetime.now().date()

platform = asf.PLATFORM.SENTINEL1

if inps.processing_level=='SLC':
    inps.polarization = ['VV','VV+VH'] 
if inps.processing_level=='BURST':
    inps.polarization = ['VV']


if inps.platform in ['SENTINEL1', 'SENTINEL-1', 'S1', 'S-1']:
    platform = asf.PLATFORM.SENTINEL1
elif inps.platform in ['SENTINEL-1A', 'SENTINEL1A', 'S-1A', 'S1A']:
    platform = asf.PLATFORM.SENTINEL1A
elif inps.platform in ['SENTINEL-1B', 'SENTINEL1B', 'S-1B', 'S1B']:
    platform = asf.PLATFORM.SENTINEL1B
elif inps.platform in ['ALOS-2', 'ALOS2']:
    # platform = asf.PLATFORM.ALOS-2
    platform = 'ALOS-2'
    inps.processing_level="L1.1"
    inps.polarization=None

if inps.node:
    if inps.node in ['ASCENDING', 'ASC']:
        node = asf.FLIGHT_DIRECTION.ASCENDING
    elif inps.node in ['DESCENDING', 'DESC']:
        node = asf.FLIGHT_DIRECTION.DESCENDING

if inps.download is not None:
    if inps.dir:
        path = inps.dir
    else:
        path = os.getcwd()
else:
    path = None

#pols = inps.pols

print("Searching for data...")

# product = [asf.PRODUCT_TYPE.BURST]  # FA 7/2025: does not seem to work although ChatGPT suggests it
# platform='ALOS-2'

inps.polarization = ['VV','VV+VH'] 
results = asf.search(
    platform=platform,
    processingLevel=inps.processing_level,
    start=sdate,
    end=edate,
    intersectsWith=inps.intersectsWith,
    flightDirection=node,
    relativeOrbit=inps.relativeOrbit,
    relativeBurstID=None,
    polarization=inps.polarization
)
print(f"Found {len(results)} results.\n\n")
print(results[0].properties)
if inps.print:
        # print(', '.join(results[0].properties.keys()))
        print(', '.join(k for k in results[0].properties.keys() if k not in ['centerLat', 'centerLon']))

burst_ids =[]
for r in results:
    if inps.print_burst:
        if 'BURST' in product:
            if r.properties['burst']['relativeBurstID'] not in burst_ids:
                burst_ids.append(r.properties['burst']['relativeBurstID'])
                print(f"Relative Burst ID: {r.properties['burst']['relativeBurstID']}")
        else:
            print('-' * 100)
            print(f"Start date: {r.properties['startTime']}, End date: {(r.properties['stopTime'])}, {r.geometry['type']}: {r.geometry['coordinates']}, Path of satellite: {r.properties['pathNumber']}, Granule:  {r.properties['granuleType']}")
    elif inps.print:
        # print(', '.join(str(v) for v in r.properties.values()))
        print(', '.join(str(v) for k, v in r.properties.items() if k not in ['centerLat', 'centerLon']))
        # print(r)


if inps.download == True:
    print(f"Downloading {len(results)} results")
    results.download(
         path = path,
         session = asf.ASFSession(),
         processes = inps.parallel
    )
