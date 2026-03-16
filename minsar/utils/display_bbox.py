#!/usr/bin/env python3

import os
import sys
import subprocess
import folium
import argparse
import matplotlib.pyplot as plt
from shapely import wkt
import contextily as ctx

import webbrowser

try:
    from minsar.utils.system_utils import detect_operating_system, are_we_on_slurm_system
except ImportError:
    def detect_operating_system():
        return "Linux" if sys.platform != "darwin" else "macOS"
    def are_we_on_slurm_system():
        return False

##############################################################################
EXAMPLE = """Display and convert format of bounding boxes/polygons:

Usage:
  display_bbox.py LATMIN:LATMAX,LONMIN:LONMAX
  display_bbox.py 'POLYGON((lon1 lat1, lon2 lat2, ..., lon1 lat1))'

Examples:
  display_bbox.py 25.937:25.958,-80.125:-80.118
  display_bbox.py --lat 25.937 25.958 --lon -80.125 -80.118
  display_bbox.py 'POLYGON((-82.04 26.53, -81.92 26.53, -81.92 26.61, -82.04 26.61, -82.04 26.53))'
  display_bbox.py 25.937:25.958,-80.125:-80.118 --asf

Note:
  If you are using a POLYGON, you **must** wrap it in single quotes to prevent a shell syntax error.
"""

DESCRIPTION = (
    "Displays and converts subset/bounding boxes"
)
def create_parser():
    parser = argparse.ArgumentParser(
        description="Display a bounding box or polygon on a map.",
        epilog=EXAMPLE, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("subset", nargs="?", help="Bounding box 'lat_min:lat_max,lon_min:lon_max' or WKT POLYGON")
    parser.add_argument("--lat", nargs=2, type=float, help="Latitude range: min max")
    parser.add_argument("--lon", nargs=2, type=float, help="Longitude range: min max")
    parser.add_argument("--satellite", action="store_true", help="Overlay satellite basemap (Esri World Imagery)")
    parser.add_argument("--asf", action="store_true", help="Print ASF Vertex URL; on Mac, open Safari with the URL")
    return parser

def draw_rectangle(subset):
    lat_part, lon_part = subset.split(',')
    lat_min, lat_max = map(float, lat_part.split(':'))
    lon_min, lon_max = map(float, lon_part.split(':'))
    center_lat = (lat_min + lat_max) / 2
    center_lon = (lon_min + lon_max) / 2

    m = folium.Map(location=[center_lat, center_lon], zoom_start=14)
    folium.Rectangle(
        bounds=[[lat_min, lon_min], [lat_max, lon_max]],
        color='blue', fill=True, fill_opacity=0.3
    ).add_to(m)
    return m

def draw_polygon(wkt_string):
    shape = wkt.loads(wkt_string)
    coords = list(shape.exterior.coords)
    latlon = [[lat, lon] for lon, lat in coords]

    avg_lat = sum(p[0] for p in latlon) / len(latlon)
    avg_lon = sum(p[1] for p in latlon) / len(latlon)

    m = folium.Map(location=[avg_lat, avg_lon], zoom_start=14)
    folium.Polygon(
        locations=latlon,
        color='green', fill=True, fill_opacity=0.3
    ).add_to(m)
    return m

try:
    from minsar.utils.convert_bbox import (
        ASF_VERTEX_BASE,
        ASF_DEFAULT_START,
        ASF_DEFAULT_END,
        ASF_NISAR_DEFAULT_START,
        ASF_NISAR_DEFAULT_END,
        _asf_vertex_url,
    )
except ImportError:
    ASF_VERTEX_BASE = "https://search.asf.alaska.edu/#/"
    ASF_DEFAULT_START = "2020-01-01"
    ASF_DEFAULT_END = "2020-02-01"
    ASF_NISAR_DEFAULT_START = "2026-01-01"
    ASF_NISAR_DEFAULT_END = "2026-02-28"
    _asf_vertex_url = None


def _bounds_to_wkt(lat_min, lat_max, lon_min, lon_max):
    """Return WKT POLYGON for rectangular bbox (lon lat order, closed)."""
    return (
        f"POLYGON(({lon_min} {lat_min},{lon_max} {lat_min},"
        f"{lon_max} {lat_max},{lon_min} {lat_max},{lon_min} {lat_min}))"
    )


###########################################################
def main():
    if len(sys.argv) < 2 or sys.argv[1] in ['-h', '--help']:
        print(EXAMPLE)
        sys.exit(0)

    # Detect common unquoted polygon misuse
    if len(sys.argv) > 2 and sys.argv[1].startswith("POLYGON"):
        print("[ERROR] It looks like you're using a POLYGON without quotes.")
        print("Please wrap the POLYGON string in single quotes like this:\n")
        print("  ./display_bbox.py 'POLYGON((...))'\n")
        sys.exit(1)

    parser = create_parser()
    inps = parser.parse_args(args=sys.argv[1:])

    if inps.subset:
        arg = inps.subset
    elif inps.lat is not None and inps.lon is not None:
        arg = f"{inps.lat[0]}:{inps.lat[1]},{inps.lon[0]}:{inps.lon[1]}"
    else:
        print("[ERROR] Provide subset (LATMIN:LATMAX,LONMIN:LONMAX or POLYGON) or --lat and --lon.")
        print(EXAMPLE)
        sys.exit(1)

    try:
        if arg.lower().startswith("polygon"):
            m = draw_polygon(arg)
        else:
            m = draw_rectangle(arg)
    except Exception as e:
        print(f"[ERROR] Failed to parse input: {e}")
        print(EXAMPLE)
        sys.exit(1)

    if arg.lower().startswith("polygon"):
        # Extract WKT coordinates and derive bounds
        coords = list(wkt.loads(arg).exterior.coords)
        lons, lats = zip(*coords)
        lat_min, lat_max = min(lats), max(lats)
        lon_min, lon_max = min(lons), max(lons)
        wkt_str = arg
    else:
        lat_part, lon_part = arg.split(',')
        lat_min, lat_max = map(float, lat_part.split(':'))
        lon_min, lon_max = map(float, lon_part.split(':'))
        wkt_str = _bounds_to_wkt(lat_min, lat_max, lon_min, lon_max)

    if inps.asf:
        if _asf_vertex_url is not None:
            s1_url = _asf_vertex_url(
                wkt_str, lat_min, lat_max, lon_min, lon_max,
                ASF_DEFAULT_START, ASF_DEFAULT_END, "SENTINEL-1%20BURSTS",
            )
            nisar_url = _asf_vertex_url(
                wkt_str, lat_min, lat_max, lon_min, lon_max,
                ASF_NISAR_DEFAULT_START, ASF_NISAR_DEFAULT_END, "NISAR",
                extra_params=["processingLevel=GSLC", "prodConfig=PR", "sciProducts=GSLC"],
            )
            print("\nSentinel-1 bursts")
            print(s1_url)
            print("")
            print("NISAR")
            print(nisar_url)
            print("")
            print("WKT (paste in Vertex if needed):")
            print(wkt_str)
            if detect_operating_system() == "macOS":
                subprocess.run(["open", "-a", "Safari", s1_url], check=False)
        else:
            url = ASF_VERTEX_BASE.rstrip("/") + "/#/"
            print("\nASF Vertex URL (open in browser):")
            print(url)
            print("WKT (paste in Vertex 'Area of Interest • WKT'):")
            print(wkt_str)
            if detect_operating_system() == "macOS":
                subprocess.run(["open", "-a", "Safari", url], check=False)
        print("")

    print('\nFor topsStack:')
    print(f'topsStack.boundingBox                = {lat_min:.1f} {lat_max:.1f} {lon_min:.1f} {lon_max:.1f}')
    print('\nFor miaplpy:')
    print(f'mintpy.subset.lalo                   = {lat_min:.3f}:{lat_max:.3f},{lon_min:.3f}:{lon_max:.3f}    #[S:N,W:E / no], auto for no')
    print(f'miaplpy.subset.lalo                  = {lat_min:.3f}:{lat_max:.3f},{lon_min:.3f}:{lon_max:.3f}    #[S:N,W:E / no], auto for no')
    print('\nFor subsetting:')
    print('setmintpyfalk')
    print(f'subset.py slcStack.h5 --lat {lat_min:.3f} {lat_max:.3f} --lon {lon_min:.3f} {lon_max:.3f}')
    print(f'subset.py geometryRadar.h5 --lat {lat_min:.3f} {lat_max:.3f} --lon {lon_min:.3f} {lon_max:.3f}\n')
    output_file = "bbox_map.html"
    m.save(output_file)
    on_hpc = are_we_on_slurm_system()
    if on_hpc:
        print(f"Map saved to {output_file}. On HPC no browser is opened; copy the file to your local machine to view.\n")
    else:
        print(f"Map saved to {output_file}. Open with:\nopen -a Safari {output_file}\n")
        url = f"file:///{os.getcwd()}/{output_file}"
        webbrowser.open(url)

if __name__ == "__main__":
    main()
