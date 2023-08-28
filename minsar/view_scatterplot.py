#!/usr/bin/env python3
# Authors: Farzaneh Aziz Zanjani & Falk Amelung              
# This script plots velocity, DEM error, and estimated elevation on the backscatter.
############################################################
import argparse
import os
import numpy as np
import h5py
import matplotlib.pyplot as plt
import georaster
import mintpy
from mintpy.utils import arg_utils
from mintpy.utils import readfile, utils as ut
import matplotlib as mpl
import cartopy.crs as ccrs
from cartopy.mpl.gridliner import LONGITUDE_FORMATTER, LATITUDE_FORMATTER


EXAMPLE = """example:

For plotting velocity in radar coordinates and redefining path for slcStack and maskPS.h5 files:
            view_scatterplot.py velocity.h5 demErr.h5 inputs/geometryRadar.h5 --PS ../maskPS.h5 --slcStack ../inputs/slcStack.h5 --sub-lat 25.875  25.8795  --sub-lon -80.123  -80.1205 --subplot velocity

For plotting everything in radar coordinates:
            view_scatterplot.py velocity.h5 demErr.h5 inputs/geometryRadar.h5  --sub-lat 25.875  25.8795  --sub-lon -80.123  -80.1205

For changing color bars:
            view_scatterplot.py velocity.h5 demErr.h5 inputs/geometryRadar.h5  --sub-lat 25.875  25.8795  --sub-lon -80.122  -80.121 -dl -60 60 -el -30 30 -esl -60 60 

For plotting everything in geo coordinates using available dsm tif file as background:
            view_scatterplot.py velocity.h5 demErr.h5 inputs/geometryRadar.h5  --sub-lat 25.875  25.8795  --sub-lon -80.123  -80.1205  --dsm Miami.tif --geo 

For plotting velocity in geo coordinates using available dsm tif file as background:
            view_scatterplot.py velocity.h5 demErr.h5 inputs/geometryRadar.h5  --sub-lat 25.875  25.8795  --sub-lon -80.123  -80.1205  --dsm Miami.tif --geo --subplot velocity
"""

def cmd_line_parser():
    """
    Parse command line arguments and return the parsed arguments.

    Returns:
        argparse.Namespace: Parsed command line arguments
    """

    description = (
        "Plots velocity, DEM error, and estimated elevation on the backscatter."
    )
    epilog = EXAMPLE
    parser = arg_utils.create_argument_parser(
        name=__name__.split(".")[-1],
        synopsis=description,
        description=description,
        epilog=epilog,
        subparsers=None,
    )

    parser.add_argument(
        "--sub-lat",
        dest="sub_lat",
        nargs=2,
        default=(25.875, 25.8795),
        metavar="",
        type=float,
        help="Latitude for the corners of the box",
    )
    parser.add_argument(
        "--sub-lon",
        dest="sub_lon",
        nargs=2,
        default=(-80.122, -80.121),
        metavar="",
        type=float,
        help="Longitude for the corners of the box",
    )
    parser.add_argument(
        "--outfile",
        "-o",
        metavar="",
        type=str,
        default="scatter_backscatter_dem.png",
        help="Output PNG file name",
    )
    parser.add_argument(
        "velocity",
        metavar="",
        type=str,
        help="Velocity file",
    )
    parser.add_argument(
        "dem_error",
        metavar="",
        type=str,
        help="DEM error file",
    )
    parser.add_argument(
        "geometry",
        metavar="",
        type=str,
        help="Geolocation file",
    )
    parser.add_argument(
        "--PS",
        type=str,
        metavar="",
        default="./maskPS.h5",
        help="Mask PS file",
    )
    parser.add_argument(
        "--slcStack",
        metavar="",
        type=str,
        default="./slcStack.h5",
        help="SLC stack file",
    )

    parser.add_argument(
        "--dsm",
        type=str,
        metavar="",
        default="./dsm_reprojected_wgs84.tif",
        help="Path to Lidar elevation file",
    )
    parser.add_argument(
        "--out-amplitude",
        dest="out_amplitude",
        metavar="",
        type=str,
        default="./mean_amplitude.npy",
        help="File to write the amplitude from slcStack",
    )
    parser.add_argument(
        "--dem-offset",
        metavar="",
        dest="offset",
        type=float,
        default=0,
        help="DEM offset (geoid deviation), e.g., it is 26 for Miami",
    )
    parser.add_argument(
        "--project-dir",
        dest="project_dir",
        metavar="",
        type=str,
        default="./",
        help="Path to the directory containing data files",
    )

    parser.add_argument(
        "--subplot",
        dest="subplot",
        type=str,
        choices=["all", "velocity", "amplitude", "dem", "dem_error", "estimated_elevation"],
        default="all",
        help="Choose which subplot(s) to include: all, velocity, amplitude, dem, dem_error, estimated_elevation",
    )

    parser.add_argument(
        "--geo",
        dest="geo",
        action="store_true",
        help="Define if plotting in Geo coordinate or Radar coordinate",
    )
    parser.add_argument(
        "--vlim",
        nargs=2,
        metavar=("VMIN", "VMAX"),
        default=(-0.6, 0.6),
        type=float,
        help="Velocity limit for the colorbar. Default is -0.6 0.6",
    )
    parser.add_argument(
        "--dem-lim",
        "-dl",
        dest="dem_lim",
        nargs=2,
        metavar="",
        type=float,
        help="DEM limit for color bar, e.g., 0 50",
    )
    parser.add_argument(
        "--dem_error-lim",
        "-el",
        dest="dem_error_lim",
        nargs=2,
        metavar="",
        type=float,
        help="DEM error limit for color bar, e.g., -5 20",
    )
    parser.add_argument(
        "--dem-estimated-lim",
        "-esl",
        dest="dem_estimated_lim",
        nargs=2,
        metavar="",
        type=float,
        help="Estimated elevation limit for color bar, e.g., 0 50",
    )
    parser.add_argument(
        "--colormap",
        "-c",
        metavar="",
        type=str,
        default="jet",
        help="Colormap used for display, e.g., jet",
    )
    parser.add_argument(
        "--point-size",
        dest="point_size",
        metavar="",
        default=10,
        type=float,
        help="Points size",
    )
    parser.add_argument(
        "--fontsize",
        "-f",
        metavar="",
        type=float,
        default=10,
        help="Font size",
    )
    parser.add_argument(
        "--figsize",
        metavar=("WID", "LEN"),
        help="Width and length of the figure",
        type=float,
        nargs=2,
    )

    parser.add_argument(
        "--flip-lr",
        dest="flip_lr",
        metavar="",
        type=str,
        default="NO",
        help="If YES, flips the figure Left-Right. Default is NO.",
    )
    parser.add_argument(
        "--flip-ud",
        dest="flip_ud",
        metavar="",
        type=str,
        default="NO",
        help="If YES, flips the figure Up-Down. Default is NO.",
    )

    args = parser.parse_args()

    return args


def calculate_mean_amplitude(slcStack, out_amplitude):
    """
    Calculate the mean amplitude from the SLC stack and save it to a file.

    Args:
        slcStack (str): Path to the SLC stack file.
        out_amplitude (str): Path to the output amplitude file.

    Returns:
        None
    """

    with h5py.File(slcStack, 'r') as f:
        slcs = f['slc']
        s_shape = slcs.shape
        mean_amplitude = np.zeros((s_shape[1], s_shape[2]), dtype='float32')
        lines = np.arange(0, s_shape[1], 100)

        for t in lines:
            last = t + 100
            if t == lines[-1]:
                last = s_shape[1]  # Adjust the last index for the final block

            # Calculate mean amplitude for the current block
            mean_amplitude[t:last, :] = np.mean(np.abs(f['slc'][:, t:last, :]), axis=0)

        # Save the calculated mean amplitude to the output file
        np.save(out_amplitude, mean_amplitude)


def get_data(lon1, lon2, lat1, lat2, ymin, ymax, xmin, xmax, out_amplitude):
    """
    Extract relevant data based on specified coordinates and masks.

    Args:
        lon1 (float): Minimum longitude.
        lon2 (float): Maximum longitude.
        lat1 (float): Minimum latitude.
        lat2 (float): Maximum latitude.
        ymin (int): Minimum y index.
        ymax (int): Maximum y index.
        xmin (int): Minimum x index.
        xmax (int): Maximum x index.
        out_amplitude (str): Path to the amplitude file.

    Returns:
        tuple: A tuple containing amplitude, xv, yv, lon, lat, vel, demerr, dem, ddemerr, ddem.
    """
    args = cmd_line_parser() 
    project_dir = args.project_dir
    vel_file = args.velocity
    demError_file = args.dem_error
    geo_file = args.geometry
    mask_file_ps = args.PS
    slcStack = args.slcStack
    shift = args.offset

    latitude = readfile.read(geo_file, datasetName='latitude')[0]
    longitude = readfile.read(geo_file, datasetName='longitude')[0]
    DEM = readfile.read(geo_file, datasetName='height')[0] + shift

    demError = readfile.read(demError_file, datasetName='dem')[0]

    velocity, atr = readfile.read(vel_file, datasetName='velocity')

    mask = np.ones(velocity.shape, dtype=np.int8)
    
    mask[latitude<lat1] = 0
    mask[latitude>lat2] = 0
    mask[longitude<lon1] = 0
    mask[longitude>lon2] = 0
#    mask = np.ones(velocity.shape, dtype=np.float32)

#    mask[(latitude < lat1) & (latitude > lat2) & (longitude < lon1) & (longitude > lon2)] = 0

    amplitude = np.fliplr(np.load(out_amplitude)[ymin:ymax, xmin:xmax])

    mask_p = readfile.read(mask_file_ps, datasetName='mask')[0]

    mask *= mask_p  # Apply mask_p within the specified ymin, ymax, xmin, xmax

    vel = np.array(velocity[mask == 1] * 1000)
    lat = np.array(latitude[mask == 1])
    lon = np.array(longitude[mask == 1])
    demerr = np.array(demError[mask == 1])

    dem = np.array(DEM[mask == 1])

    x = np.linspace(0, velocity.shape[1] - 1, velocity.shape[1])
    y = np.linspace(0, velocity.shape[0] - 1, velocity.shape[0])
    x, y = np.meshgrid(x, y)
    xv = xmax - np.array(x[mask == 1])
    yv = np.array(y[mask == 1]) - ymin

    ddemerr = np.array(demError[mask == 1])
    ddem = np.array(DEM[mask == 1])

    return amplitude, xv, yv, lon, lat, vel, demerr, dem, ddemerr, ddem


def configure_plot_settings(args):
    """
    Configure plot settings based on command-line arguments.

    Args:
        args (argparse.Namespace): Parsed command-line arguments.

    Returns:
        matplotlib.figure.Figure, matplotlib.axes._subplots.AxesSubplot,
        matplotlib.colors.Colormap, matplotlib.colors.Normalize: Figure, Axes,
        colormap, and normalization for color scale.
    """
    plt.rcParams['font.size'] = args.fontsize
    plt.rcParams['axes.labelsize'] = args.fontsize
    plt.rcParams['xtick.labelsize'] = args.fontsize
    plt.rcParams['ytick.labelsize'] = args.fontsize
    plt.rcParams['axes.titlesize'] = args.fontsize

    if args.colormap:
        colormap = plt.get_cmap(args.colormap)
    else:
        colormap = plt.get_cmap('jet')

    vmin, vmax = args.vlim
    norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)

    fig, ax = plt.subplots(figsize=args.figsize)

    if args.geo:
        ax = plt.axes(projection=ccrs.PlateCarree())
        ax.set_extent([args.sub_lon[0], args.sub_lon[1], args.sub_lat[0], args.sub_lat[1]])
        ax.coastlines()
        ax.gridlines(draw_labels=True, linewidth=0.5, color='0.5', alpha=0.5,
                     xformatter=LONGITUDE_FORMATTER, yformatter=LATITUDE_FORMATTER)

        ax.plot([args.sub_lon[0], args.sub_lon[1], args.sub_lon[1], args.sub_lon[0], args.sub_lon[0]],
                [args.sub_lat[0], args.sub_lat[0], args.sub_lat[1], args.sub_lat[1], args.sub_lat[0]],
                color='red', linewidth=2, label='Region of Interest')
        ax.legend()

    return fig, ax, colormap, norm


def plot_subset_radar(lon1, lon2, lat1, lat2, ymin, ymax, xmin, xmax, v_min, v_max, out_amplitude, dem_offset, dem_name, out_name, size=200, fig=None, axs=None):

    amplitude,  xv, yv, lon, lat, vel, demerr, dem, ddemerr, ddem = get_data(lon1, lon2, lat1, lat2, ymin, ymax, xmin, xmax, out_amplitude)
    
    args = cmd_line_parser()
    vl = args.vlim[0]
    vh = args.vlim[1]

    fig, axs = plt.subplots(nrows=1, ncols=5, figsize=args.figsize or (15, 5))

    for ax in axs:
        ax.imshow(amplitude, cmap='gray', vmin=0, vmax=300)
        ax.axes.get_xaxis().set_visible(False)
        ax.axes.get_yaxis().set_visible(False)

    im = axs[0].scatter(xv, yv, c=vel/10, s=size, cmap=args.colormap, vmin=vl, vmax=vh)
    im.set_clim(vl, vh)
    cbar = plt.colorbar(im, ax=axs[0], shrink=1, orientation='horizontal', pad=0.04)
    cbar.set_label('velocity [cm/yr]')

    cbar = axs[1].imshow(amplitude, cmap='gray', vmin=0, vmax=300)
    cbar = plt.colorbar(cbar, ax=axs[1], shrink=1, orientation='horizontal', pad=0.04)
    cbar.set_label('Amplitude')

    im = axs[2].scatter(xv, yv, c=dem, s=size, cmap=args.colormap)
    cbar = plt.colorbar(im, ax=axs[2], shrink=1, orientation='horizontal', pad=0.04)
    cbar.set_label('SRTM DEM [m]')
    if args.dem_lim is not None:
        im.set_clim(args.dem_lim[0], args.dem_lim[1])

    im = axs[3].scatter(xv, yv, c=-demerr, s=size, cmap=args.colormap)
    cbar = plt.colorbar(im, ax=axs[3], shrink=1, orientation='horizontal', pad=0.04)
    cbar.set_label('DEM Error [m]')
    if args.dem_error_lim is not None:
        im.set_clim(args.dem_error_lim[0], args.dem_error_lim[1])

    im = axs[4].scatter(xv, yv, c=-demerr+dem, s=size, cmap=args.colormap)
    cbar = plt.colorbar(im, ax=axs[4], shrink=1, orientation='horizontal', pad=0.04)
    cbar.set_label('Estimated \nelevation [m]')
    if args.dem_estimated_lim is not None:
        im.set_clim(args.dem_estimated_lim[0], args.dem_estimated_lim[1])

    plt.savefig(out_name, bbox_inches='tight', dpi=300)
    plt.close(fig)

def plot_subset_geo(lon1, lon2, lat1, lat2, ymin, ymax, xmin, xmax, v_min, v_max, out_amplitude, dem_offset, dem_name, out_name, size=200, fig=None, axs=None):
    amplitude,  xv, yv, lon, lat, vel, demerr, dem, ddemerr, ddem = get_data(lon1, lon2, lat1, lat2, ymin, ymax, xmin, xmax, out_amplitude)
    args = cmd_line_parser()
    dsm = args.dsm
    vl = args.vlim[0]
    vh = args.vlim[1]

    fig, axss = plt.subplots(nrows=1, ncols=4, figsize=args.figsize or (15, 5))

    def plot_scatter(ax, data, cmap, c_label, clim=None, marker='o', colorbar=True):
        im = ax.scatter(lon, lat, c=data, s=size, cmap=cmap, marker=marker)
        if colorbar:
            cbar = plt.colorbar(im, ax=ax, shrink=1, orientation='horizontal', pad=0.1)
            cbar.set_label(c_label)
            if clim is not None:
                im.set_clim(clim[0], clim[1])
        ax.axes.get_xaxis().set_visible(False)
        ax.axes.get_yaxis().set_visible(False)

    if os.path.isfile(dsm):
        cmap = 'Greys_r'
        clim_raster = (-20, 30)
    else:
        cmap = args.colormap
        clim_raster = None

    for i, ax in enumerate(axss):
        if os.path.isfile(dsm):
            my_image = georaster.SingleBandRaster(dsm, load_data=(lon1, lon2, lat1, lat2), latlon=True)
            ax.imshow(my_image.r, extent=my_image.extent, cmap=cmap, vmin=clim_raster[0], vmax=clim_raster[1])
        if i == 0:
            plot_scatter(ax, vel/10, args.colormap, 'velocity (cm/yr)', (vl, vh))
        else:
            plot_scatter(ax, None, None, None, colorbar=False)

    if os.path.isfile(dsm):
        axss[0].axes.get_xaxis().set_visible(False)
        axss[0].axes.get_yaxis().set_visible(False)
    else:
        axss[0].axes.get_xaxis().set_visible(True)
        axss[0].axes.get_yaxis().set_visible(True)

    plot_scatter(axss[1], dem, args.colormap, 'SRTM DEM [m]', args.dem_lim)
    plot_scatter(axss[2], -demerr, args.colormap, 'DEM Error [m]', args.dem_error_lim)
    plot_scatter(axss[3], dem - demerr, args.colormap, 'Estimated elevation [m]', args.dem_estimated_lim, marker='o')

    plt.savefig(out_name, bbox_inches='tight', dpi=300)
    plt.close(fig)

def plot_subset_radar_single(lon1, lon2, lat1, lat2, ymin, ymax, xmin, xmax, v_min, v_max, out_amplitude, dem_offset, dem_name, out_name, size=200, fig=None, axs=None):

    amplitude,  xv, yv, lon, lat, vel, demerr, dem, ddemerr, ddem = get_data(lon1, lon2, lat1, lat2, ymin, ymax, xmin, xmax, out_amplitude)
    
    args = cmd_line_parser()
    vl = args.vlim[0]
    vh = args.vlim[1]
    subplot = args.subplot
 
    fig, ax = plt.subplots(nrows=1, ncols=1, figsize=args.figsize or (5, 5))

    ax.imshow(amplitude, cmap='gray', vmin=0, vmax=300)
    ax.axes.get_xaxis().set_visible(False)
    ax.axes.get_yaxis().set_visible(False)

    if subplot == 'velocity':
         im = ax.scatter(xv, yv, c=vel/10, s=size, cmap=args.colormap, vmin=vl, vmax=vh)
         im.set_clim(vl, vh)
         cbar = plt.colorbar(im, ax=ax, shrink=1, orientation='horizontal', pad=0.04)
         cbar.set_label('velocity [cm/yr]')
    elif subplot == 'amplitude':
         cbar = ax.imshow(amplitude, cmap='gray', vmin=0, vmax=300)
         cbar = plt.colorbar(cbar, ax=ax, shrink=1, orientation='horizontal', pad=0.04)
         cbar.set_label('Amplitude')
    elif subplot == 'dem':
         im = ax.scatter(xv, yv, c=dem, s=size, cmap=args.colormap)
         cbar = plt.colorbar(im, ax=ax, shrink=1, orientation='horizontal', pad=0.04)
         cbar.set_label('SRTM DEM [m]')
         if args.dem_lim is not None:
             im.set_clim(args.dem_lim[0], args.dem_lim[1])
    elif subplot == 'dem_error':
         im = ax.scatter(xv, yv, c=-demerr, s=size, cmap=args.colormap)
         cbar = plt.colorbar(im, ax=ax, shrink=1, orientation='horizontal', pad=0.04)
         cbar.set_label('DEM Error [m]')
         if args.dem_error_lim is not None:
             im.set_clim(args.dem_error_lim[0], args.dem_error_lim[1])
    elif subplot == 'estimated_elevation':
         im = ax.scatter(xv, yv, c=-demerr+dem, s=size, cmap=args.colormap)
         cbar = plt.colorbar(im, ax=ax, shrink=1, orientation='horizontal', pad=0.04)
         cbar.set_label('Estimated \nelevation [m]')
         if args.dem_estimated_lim is not None:
             im.set_clim(args.dem_estimated_lim[0], args.dem_estimated_lim[1])

    plt.savefig(out_name, bbox_inches='tight', dpi=300)
    plt.close(fig)
    
def plot_subset_geo_single(lon1, lon2, lat1, lat2, ymin, ymax, xmin, xmax, v_min, v_max, out_amplitude, dem_offset, dem_name, out_name, size=200, fig=None, axs=None):
    amplitude,  xv, yv, lon, lat, vel, demerr, dem, ddemerr, ddem = get_data(lon1, lon2, lat1, lat2, ymin, ymax, xmin, xmax, out_amplitude)
    args = cmd_line_parser()
    dsm = args.dsm
    vl = args.vlim[0]
    vh = args.vlim[1]
    subplot = args.subplot

    fig, ax = plt.subplots(nrows=1, ncols=1, figsize=args.figsize or (5, 5))

    def plot_scatter(ax, data, cmap, c_label, clim=None, marker='o', colorbar=True):
        im = ax.scatter(lon, lat, c=data, s=size, cmap=cmap, marker=marker)
        if colorbar:
            cbar = plt.colorbar(im, ax=ax, shrink=1, orientation='horizontal', pad=0.1)
            cbar.set_label(c_label)
            if clim is not None:
                im.set_clim(clim[0], clim[1])
        ax.axes.get_xaxis().set_visible(False)
        ax.axes.get_yaxis().set_visible(False)

    if os.path.isfile(dsm):
        cmap = 'Greys_r'
        clim_raster = (-100, 100)
    else:
        cmap = args.colormap
        clim_raster = None

    if os.path.isfile(dsm):
        my_image = georaster.SingleBandRaster(dsm, load_data=(lon1, lon2, lat1, lat2), latlon=True)
        hist, bins = np.histogram(my_image.r, bins=256, range=(-100, 1000))
        threshold = bins[np.argmax(hist)]
        water_mask = my_image.r <= threshold
        masked_image = np.where(water_mask, 0, my_image.r)
        ax.imshow(masked_image, extent=my_image.extent, cmap=cmap, vmin=clim_raster[0], vmax=clim_raster[1])
       # ax.imshow(my_image.r, extent=my_image.extent, cmap=cmap, vmin=clim_raster[0], vmax=clim_raster[1])

    
    if subplot == 'velocity':
        plot_scatter(ax, vel/10, args.colormap, 'velocity (cm/yr)', (vl, vh))
    elif subplot == 'amplitude':
        plot_scatter(ax, ampltide, args.colormap, 'Amplitude')
    elif subplot == 'dem':
        plot_scatter(ax, dem, args.colormap, 'SRTM DEM [m]', args.dem_lim)    
    elif subplot == 'dem_error':
        plot_scatter(ax, -demerr, args.colormap, 'DEM Error [m]', args.dem_error_lim)
    elif subplot == 'estimated_elevation':
        plot_scatter(ax, dem - demerr, args.colormap, 'Estimated elevation [m]', args.dem_estimated_lim, marker='o')

    if os.path.isfile(dsm):
        ax.axes.get_xaxis().set_visible(False)
        ax.axes.get_yaxis().set_visible(False)
    else:
        ax.axes.get_xaxis().set_visible(True)
        ax.axes.get_yaxis().set_visible(True)
    
    plt.savefig(out_name, bbox_inches='tight', dpi=300)
    plt.close(fig)
    

def main():
    args = cmd_line_parser()

    lat1 = args.sub_lat[0]
    lat2 = args.sub_lat[1]
    lon1 = args.sub_lon[0]
    lon2 = args.sub_lon[1]
    vl = args.vlim[0]
    vh = args.vlim[1]
    dem_offset = args.offset
    subplot = args.subplot
    
    vel_file = args.velocity  
    demError_file = args.dem_error
    geo_file = args.geometry
    mask_file_ps = args.PS
    slcStack = args.slcStack
    outfile = args.outfile
    out_amplitude = args.out_amplitude
    project_dir = args.project_dir

    if not os.path.exists(out_amplitude):
        calculate_mean_amplitude(slcStack, out_amplitude)

    plt.rcParams["font.size"] = args.fontsize

    if args.flip_lr == 'YES':
        print('flip figure left and right')
        plt.gca().invert_xaxis()
     
    if args.flip_ud == 'YES':
        print('flip figure up and down')
        plt.gca().invert_yaxis()

    points_lalo = np.array([[lat1, lon1],
                            [lat2, lon2]])
    attr = readfile.read_attribute(vel_file)
    coord = ut.coordinate(attr, geo_file)
    yg1, xg1 = coord.geo2radar(points_lalo[0][0], points_lalo[0][1])[:2]
    yg2, xg2 = coord.geo2radar(points_lalo[1][0], points_lalo[1][1])[:2]
    yg3, xg3 = coord.geo2radar(points_lalo[0][0], points_lalo[1][1])[:2]
    yg4, xg4 = coord.geo2radar(points_lalo[1][0], points_lalo[1][1])[:2]
    print("Lat, Lon, y, x: ", points_lalo[0][0], points_lalo[0][1], yg1, xg1)
    print("Lat, Lon, y, x: ", points_lalo[1][0], points_lalo[1][1], yg2, xg2)
    print("Lat, Lon, y, x: ", points_lalo[0][0], points_lalo[1][1], yg3, xg3)
    print("Lat, Lon, y, x: ", points_lalo[1][0], points_lalo[1][1], yg4, xg4)
    ymin = min(yg1, yg2, yg3, yg4)
    ymax = max(yg1, yg2, yg3, yg4)
    xmin = min(xg1, xg2, xg3, xg4)
    xmax = max(xg1, xg2, xg3, xg4)
    print(ymin, xmin, ymax, xmax)
    
    fig, axs, colormap, norm = configure_plot_settings(args)
    
    if args.geo and subplot == 'all':
        plot_subset_geo(lon1=lon1, lon2=lon2, lat1=lat1, lat2=lat2, ymin=ymin, ymax=ymax, xmin=xmin, xmax=xmax,
                        v_min=vl, v_max=vh, out_amplitude=out_amplitude, dem_offset=dem_offset, dem_name='dem',
                        out_name=outfile, size=args.point_size, fig=fig, axs=axs)
    elif args.geo and subplot != 'all':
        plot_subset_geo_single(lon1=lon1, lon2=lon2, lat1=lat1, lat2=lat2, ymin=ymin, ymax=ymax, xmin=xmin, xmax=xmax,
                        v_min=vl, v_max=vh, out_amplitude=out_amplitude, dem_offset=dem_offset, dem_name='dem',
                        out_name=outfile, size=args.point_size, fig=fig, axs=axs)
    elif subplot == 'all':
        plot_subset_radar(lon1=lon1, lon2=lon2, lat1=lat1, lat2=lat2, ymin=ymin, ymax=ymax, xmin=xmin, xmax=xmax,
                          v_min=vl, v_max=vh, out_amplitude=out_amplitude, dem_offset=dem_offset, dem_name='dem',
                          out_name=outfile, size=args.point_size, fig=fig, axs=axs)
    elif subplot != 'all':
        plot_subset_radar_single(lon1=lon1, lon2=lon2, lat1=lat1, lat2=lat2, ymin=ymin, ymax=ymax, xmin=xmin, xmax=xmax,
                          v_min=vl, v_max=vh, out_amplitude=out_amplitude, dem_offset=dem_offset, dem_name='dem',
                          out_name=outfile, size=args.point_size, fig=fig, axs=axs)
plt.show()
if __name__ == '__main__':
    main()

