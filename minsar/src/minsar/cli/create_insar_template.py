#!/usr/bin/env python3
import os
import re
import sys
import math
import argparse
import datetime
from datetime import datetime as dt
from datetime import timedelta as td
from minsar.utils import asf_extractor, read_excel


EXAMPLE = f"""
DEFAULT FULLPATH FOR xlsfile IS ${os.getenv('SCRATCHDIR')}

create_insar_template.py --xlsfile Central_America.xlsx --save
create_insar_template.py --subswath '1 2' --url https://search.asf.alaska.edu/#/?zoom=9.065&center=130.657,31.033&polygon=POLYGON((130.5892%2031.2764,131.0501%2031.2764,131.0501%2031.5882,130.5892%2031.5882,130.5892%2031.2764))&productTypes=SLC&flightDirs=Ascending&resultsLoaded=true&granule=S1B_IW_SLC__1SDV_20190627T092113_20190627T092140_016880_01FC2F_0C69-SLC
create_insar_template.py --polygon 'POLYGON((130.5892 31.2764,131.0501 31.2764,131.0501 31.5882,130.5892 31.5882,130.5892 31.2764))' --relativeOrbit 54 --subswath '1 2' --satellite 'Sen' --start-date '20160601' --end-date '20230926'
create_insar_template.py --polygon 'POLYGON((27.1216 36.557,27.2123 36.557,27.2123 36.62,27.1216 36.62,27.1216 36.557))' --relativeOrbit 131 --start-date 20220101 --end-date 20220228 --filename volcano
"""
SCRATCHDIR = os.getenv('SCRATCHDIR')

def create_parser():
    synopsis = 'Create Template for insar processing'
    epilog = EXAMPLE
    parser = argparse.ArgumentParser(description=synopsis, epilog=epilog, formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('--xlsfile', type=str, help="Path to the xlsfile file with volcano data.")
    parser.add_argument('--template', type=str, help="Path to the template file (default: template.txt in docs folder).")
    parser.add_argument('--url', type=str, help="URL to the ASF data.")
    parser.add_argument('--intersectsWith', type=str, dest='polygon', help="Polygon coordinates in WKT format.")
    parser.add_argument('--relativeOrbit', dest='relative_orbit', type=int, help="relative orbit number.")
    parser.add_argument('--direction', type=str, choices=['A', 'D'], default='A', help="Flight direction (default: %(default)s).")
    parser.add_argument('--subswath', type=str, default='1 2 3', help="subswath numbers as a string (default: %(default)s).")
    parser.add_argument('--troposphericDelay-method',dest='tropospheric_delay_method', type=str, default='auto', help="Tropospheric correction mode.")
    parser.add_argument('--minTempCoh', dest='min_temp_coh', type=float, default=0.75, help="Threshold value for temporal coherence.")
    parser.add_argument('--lat-step', dest='lat_step', type=float, default=15, help="Latitude step size in meters (default: %(default)s meters).")
    parser.add_argument('--satellite', type=str, choices=['Sen'], default='Sen', help="Specify satellite (default: %(default)s).")
    parser.add_argument('--filename', dest='file_name', type=str, default=None, help=f"Name of template file (Default: Unknown).")
    parser.add_argument('--save', action="store_true")
    parser.add_argument('--start-date', nargs='*', metavar='YYYYMMDD', type=str, default=['20170101'],help='Start date')
    parser.add_argument('--end-date', nargs='*', metavar='YYYYMMDD', type=str, default=['auto'], help='End date')
    parser.add_argument('--dir', dest='out_dir', type=str, default=os.getcwd(), help='Output directory (Default: current directory.)')
    parser.add_argument('--period', nargs='*', metavar='YYYYMMDD:YYYYMMDD, YYYYMMDD,YYYYMMDD', type=str, help='Period of the search')
    parser.add_argument('--coherence-based', action='store_true', help='Enable coherence based processing')

    inps = parser.parse_args()

    if inps.period:
        for p in inps.period:
            delimiters = '[,:\-\s]'
            dates = re.split(delimiters, p)

            if len(dates[0]) and len(dates[1]) != 8:
                msg = 'Date format not valid, it must be in the format YYYYMMDD'
                raise ValueError(msg)

            inps.start_date.append(dates[0])
            inps.end_date.append(dates[1])
    else:
        if not inps.start_date:
            inps.start_date = "20160601"
        if not inps.end_date:
            inps.end_date = datetime.datetime.now().strftime("%Y%m%d")

    if not inps.template:
        from pathlib import Path
        try:
            repo_root = Path(__file__).resolve().parents[3]
            candidate = repo_root / "docs" / "template.txt"
            if candidate.exists():
                inps.template = str(candidate)
            else:
                root = (sys.argv[0].split('MakeTemplate')[0]) if isinstance(sys.argv[0], str) else ''
                inps.template = os.path.join(root, 'MakeTemplate', "docs", "template.txt")
        except Exception:
            inps.template = os.path.join(os.getcwd(), "docs", "template.txt")
    else:
        if not os.path.exists(inps.template):
            pwd = os.path.join(os.getcwd(), inps.template)
            scr = os.path.join(SCRATCHDIR, inps.template) if SCRATCHDIR else None
            inps.template = pwd if os.path.exists(pwd) else scr

    inps.coherence_based = 'yes' if inps.coherence_based else 'no'

    return inps


def miaplpy_check_longitude(lon1, lon2):
    """
    Adjusts longitude values based on the Miaplpy criteria.
    """
    if abs(lon1 - lon2) > 0.2:
        val = (abs(lon1 - lon2) - 0.2) / 2
        mia_lon1 = round(lon1 - val, 2) if lon1 > 0 else round(lon1 + val, 2)
        mia_lon2 = round(lon2 + val, 2) if lon2 > 0 else round(lon2 - val, 2)
    else:
        mia_lon1 = lon1
        mia_lon2 = lon2
    return mia_lon1, mia_lon2


def topstack_check_longitude(lon1, lon2):
    """
    Adjusts longitude values based on the TopStack criteria.
    """
    if abs(lon1 - lon2) < 5:
        val = (5 - abs(lon1 - lon2)) / 2
        top_lon1 = round(lon1 + val, 2) if lon1 > 0 else round(lon1 - val, 2)
        top_lon2 = round(lon2 - val, 2) if lon2 > 0 else round(lon2 + val, 2)
    else:
        top_lon1 = min(lon1, lon2)
        top_lon2 = max(lon1, lon2)
    return top_lon1, top_lon2


def generate_lat_lon_steps(latitude_step, lat1, lat2):
    """
    Generates latitude and longitude steps based on the input latitude step.

    Args:
        lat_step: Latitude step size in degrees.
        lat1, lat2: Latitude range.

    Returns:
        A tuple containing the latitude and longitude steps.
    """
    #Convert lat_step from meters to degrees
    lat_step = latitude_step / 111320
    latitude = (lat1 + lat2)/2
    lon_step = round(lat_step / math.cos(math.radians(float(latitude))), 5)
    return lat_step, lon_step


def create_insar_template(inps, relative_orbit, subswath, tropospheric_delay_method, latitude_step, start_date, end_date, satellite, lat1, lat2, lon1, lon2, mia_lon1, mia_lon2, top_lon1, top_lon2):
    """
    Creates an InSAR template configuration.

    Args:
        inps: Input parameters object containing various attributes.
        satellite: Satellite name or identifier.
        lat1, lat2: Latitude range.
        lon1, lon2: Longitude range.
        mia_lon1, mia_lon2: Miaplpy longitude range.
        top_lon1, top_lon2: Topstack longitude range.

    Returns:
        The generated template configuration.
    """
    lat_step, lon_step = generate_lat_lon_steps(latitude_step, lat1, lat2)

    print(f"Latitude range: {lat1}, {lat2}\n")
    print(f"Longitude range: {lon1}, {lon2}\n")
    print(f"Miaplpy longitude range: {mia_lon1}, {mia_lon2}\n")
    print(f"Topstack longitude range: {top_lon1}, {top_lon2}\n")

    template = generate_config(
        relative_orbit=relative_orbit,
        satellite=satellite,
        lat1=lat1,
        lat2=lat2,
        lon1=lon1,
        lon2=lon2,
        top_lon1=top_lon1,
        top_lon2=top_lon2,
        subswath=subswath,
        tropospheric_delay_method=tropospheric_delay_method,
        mia_lon1=mia_lon1,
        mia_lon2=mia_lon2,
        lat_step=lat_step,
        lon_step=lon_step,
        start_date=inps.start_date[0],
        end_date= inps.end_date[0],
        min_temp_coh=inps.min_temp_coh,
        coherence_based=inps.coherence_based,
        template_file=inps.template
    )

    return template


def parse_polygon(polygon):
        polygon = polygon.replace("POLYGON((", "").replace("))", "")

        latitude = []
        longitude = []

        for word in polygon.split(','):
            if (float(word.split(' ')[1])) not in latitude:
                latitude.append(float(word.split(' ')[1]))
            if (float(word.split(' ')[0])) not in longitude:
                longitude.append(float(word.split(' ')[0]))

        lon1, lon2 = round(min(longitude),2), round(max(longitude),2)
        lat1, lat2 = round(min(latitude),2), round(max(latitude),2)

        return lat1, lat2, lon1, lon2


def get_satellite_name(satellite):
    if satellite == 'Sen':
        return 'SENTINEL-1A,SENTINEL-1B'
    elif satellite == 'Radarsat':
        return 'RADARSAT2'
    elif satellite == 'TerraSAR':
        return 'TerraSAR-X'
    else:
        raise ValueError("Invalid satellite name. Choose from ['Sen', 'Radarsat', 'TerraSAR']")


def generate_config(relative_orbit, satellite, lat1, lat2, lon1, lon2, top_lon1, top_lon2, subswath, tropospheric_delay_method, mia_lon1, mia_lon2, lat_step, lon_step, start_date, end_date, min_temp_coh, coherence_based, template_file):
    """
    Generate configuration either by rendering a template file with ***markers*** or by
    falling back to the built-in f-string config.
    """
    if template_file and os.path.exists(template_file):
        _RE_MARKER = re.compile(r'\*\*\*(\w+)\*\*\*')
        with open(template_file, 'r', encoding='utf8') as f:
            text = f.read()

        # mapping of marker -> value (all converted to strings when substituted)
        mapping = {
            'satellite': satellite,
            'relative_orbit': relative_orbit,
            'start_date': start_date,
            'end_date': end_date,
            'subswath': subswath,
            'tropospheric_delay_method': tropospheric_delay_method,
            'lat1': lat1,
            'lat2': lat2,
            'lon1': lon1,
            'lon2': lon2,
            'mia_lon1': mia_lon1,
            'mia_lon2': mia_lon2,
            'lat_step': lat_step,
            'lon_step': lon_step,
            'min_temp_coh': min_temp_coh,
            'coherence_based': coherence_based,
        }

        def _repl(m):
            key = m.group(1)
            if key in mapping and mapping[key] is not None:
                return str(mapping[key])
            # leave unknown markers unchanged
            return m.group(0)

        return _RE_MARKER.sub(_repl, text)

    config = f"""\
######################################################
ssaraopt.platform                  = {satellite}  # [Sentinel-1 / ALOS2 / RADARSAT2 / TerraSAR-X / COSMO-Skymed]
ssaraopt.relativeOrbit             = {relative_orbit}
ssaraopt.startDate                 = {start_date}  # YYYYMMDD
ssaraopt.endDate                   = {end_date}    # YYYYMMDD
######################################################
topsStack.subswath                 = {subswath} # '1 2'
topsStack.numConnections           = 3    # comment
topsStack.azimuthLooks             = 5    # comment
topsStack.rangeLooks               = 20   # comment
topsStack.filtStrength             = 0.2  # comment
topsStack.unwMethod                = snaphu  # comment
topsStack.coregistration           = auto  # [NESD geometry], auto for NESD
#topsStack.excludeDates            =  20240926
######################################################
mintpy.load.autoPath               = yes
mintpy.compute.cluster             = local #[local / slurm / pbs / lsf / none], auto for none, cluster type
mintpy.compute.numWorker           = 40 #[int > 1 / all], auto for 4 (local) or 40 (non-local), num of workers
mintpy.plot.maxMemory              = 0.2  #[float], auto for 4, max memory used by one call of view.py for plotting.
mintpy.networkInversion.parallel   = yes  #[yes / no], auto for no, parallel processing using dask
mintpy.save.hdfEos5                = yes   #[yes / update / no], auto for no, save timeseries to UNAVCO InSAR Archive format
mintpy.save.hdfEos5.update         = yes   #[yes / no], auto for no, put XXXXXXXX as endDate in output filename
mintpy.save.hdfEos5.subset         = yes   #[yes / no], auto for no, put subset range info in output filename
mintpy.save.kmz                    = yes   #[yes / no], auto for yes, save geocoded velocity to Google Earth KMZ file
mintpy.reference.minCoherence      = auto      #[0.0-1.0], auto for 0.85, minimum coherence for auto method
mintpy.troposphericDelay.method    = {tropospheric_delay_method}   # pyaps  #[pyaps / height_correlation / base_trop_cor / no], auto for pyaps
######################################################
miaplpy.load.processor               = isce
miaplpy.multiprocessing.numProcessor = 40
miaplpy.inversion.rangeWindow        = 24   # range window size for searching SHPs, auto for 15
miaplpy.inversion.azimuthWindow      = 7    # azimuth window size for searching SHPs, auto for 15
miaplpy.timeseries.tempCohType       = full     # [full, average], auto for full.
miaplpy.interferograms.networkType   = delaunay # network
miaplpy.unwrap.snaphu.tileNumPixels  = 10000000000     # number of pixels in a tile, auto for 10000000
######################################################
minsar.miaplpyDir.addition           = date  #[name / lalo / no] auto for no (miaply_$name_startDate_endDate))
mintpy.subset.lalo                   = {lat1}:{lat2},{lon1}:{lon2}
miaplpy.subset.lalo                  = {lat1}:{lat2},{mia_lon1}:{mia_lon2}  #[S:N,W:E / no], auto for no
miaplpy.load.startDate               = auto  # 20200101
miaplpy.load.endDate                 = auto
mintpy.geocode.laloStep              = {lat_step},{lon_step}
miaplpy.timeseries.minTempCoh        = {min_temp_coh}      # auto for 0.5
mintpy.networkInversion.minTempCoh   = {min_temp_coh}
mintpy.network.coherenceBased  = yes
######################################################
minsar.insarmaps_flag                = True
minsar.upload_flag                   = True
minsar.insarmaps_dataset             = filt*DS
"""
    return config


def main(iargs=None):
    inps = create_parser() if not isinstance(iargs, argparse.Namespace) else iargs
    data_collection = []

    def _loc_dict(lat1, lat2, lon1, lon2, satellite):
        mia_lon1, mia_lon2 = miaplpy_check_longitude(lon1, lon2)
        top_lon1, top_lon2 = topstack_check_longitude(lon1, lon2)
        return {
            'latitude1': lat1,
            'latitude2': lat2,
            'longitude1': lon1,
            'longitude2': lon2,
            'miaplpy.longitude1': mia_lon1,
            'miaplpy.longitude2': mia_lon2,
            'topsStack.longitude1': top_lon1,
            'topsStack.longitude2': top_lon2,
            'satellite': satellite
        }

    if inps.xlsfile:
        df = read_excel.main(inps.xlsfile)

        for index, row in df.iterrows():
            lat1, lat2, lon1, lon2 = parse_polygon(row.polygon)
            yesterday = dt.now() - td(days=1)

            for _, row in df.iterrows():
                lat1, lat2, lon1, lon2 = parse_polygon(row.polygon)
                satellite = get_satellite_name(row.get('satellite'))
                loc = _loc_dict(lat1, lat2, lon1, lon2, satellite)

                processed_values = {
                    **loc,
                    'relative_orbit': row.get('ssaraopt.relativeOrbit', ''),
                    'start_date': row.get('ssaraopt.startDate', ''),
                    'end_date': yesterday.strftime('%Y%m%d') if 'auto' in row.get('ssaraopt.endDate', '') else row.get('ssaraopt.endDate', ''),
                    'tropospheric_delay_method': row.get('mintpy.troposphericDelay', 'auto'),
                    'subswath': row.get('topsStack.subswath', ''),
                }

                row_dict = row.to_dict()
                row_dict.update(processed_values)
                data_collection.append(row_dict)
    else:
        # URL or polygon input
        if inps.url:
            relative_orbit, satellite, direction, lat1, lat2, lon1, lon2 = asf_extractor.main(inps.url)
        else:
            lat1, lat2, lon1, lon2 = parse_polygon(inps.polygon)
            satellite = get_satellite_name(inps.satellite)

            if not inps.relative_orbit:
                from minsar.src.minsar.cli import asf_search_args as asf
                args = []
                if inps.relative_orbit:
                    args += ["--relativeOrbit", str(inps.relative_orbit)]
                if inps.start_date:
                    args += ["--start-date", inps.start_date[0] if isinstance(inps.start_date, (list,tuple)) else str(inps.start_date)]
                if inps.end_date:
                    args += ["--end-date", inps.end_date[0] if inps.end_date[0]!='auto' else dt.now().strftime("%Y%m%d")]
                args += ["--platform", satellite]
                asf.main(iargs=args)
            direction = inps.direction
            relative_orbit = inps.relative_orbit

        loc = _loc_dict(lat1, lat2, lon1, lon2, satellite)

        processed_values = {
            **loc,
            'name': inps.name if hasattr(inps, 'name') else 'Unknown',
            'direction': direction,
            'ssaraopt.startDate': inps.start_date if hasattr(inps, 'start_date') else 'auto',
            'ssaraopt.endDate': inps.end_date if hasattr(inps, 'end_date') else 'auto',
            'ssaraopt.relativeOrbit': inps.relative_orbit if hasattr(inps, 'relative_orbit') else None,
            'topsStack.subswath': inps.subswath if hasattr(inps, 'subswath') else None,
            'mintpy.troposphericDelay.method': inps.tropospheric_delay_method,
            'polygon': inps.polygon if hasattr(inps, 'polygon') else None,
            'relative_orbit': relative_orbit
        }

        data_collection.append(processed_values)

    for data in data_collection:
        template = create_insar_template(
            inps=inps,
            relative_orbit = data.get('relative_orbit',''),
            subswath = data.get('topsStack.subswath', ''),
            tropospheric_delay_method = data.get('inps.tropospheric_delay_method', 'auto'),
            latitude_step = inps.lat_step,
            start_date = data.get('start_date', ''),
            end_date = data.get('end_date', ''),
            satellite=data.get('satellite'),
            lat1=data.get('latitude1'),
            lat2=data.get('latitude2'),
            lon1=data.get('longitude1'),
            lon2=data.get('longitude2'),
            mia_lon1=data.get('miaplpy.longitude1'),
            mia_lon2=data.get('miaplpy.longitude2'),
            top_lon1=data.get('topsStack.longitude1'),
            top_lon2=data.get('topsStack.longitude2')
        )

        if inps.file_name or inps.save:
            name = inps.file_name if inps.file_name else data.get('name', '')
            sat = "Sen" if "SEN" in data.get('satellite', '').upper()[:4] else ""
            template_name = os.path.join(f"{name}{sat}{data.get('direction')}{data.get('relative_orbit')}.template")
            if inps.out_dir:
                template_name = os.path.join(inps.out_dir, template_name)
            with open(template_name, 'w') as f:
                f.write(template)
                print(f"Template saved in {template_name}")

if __name__ == '__main__':
    main(iargs=sys.argv)
