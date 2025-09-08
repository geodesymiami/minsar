#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Aug 21 15:36:31 2025

@author: edgar
"""

# Notes
# This script will convert two available S1.he5 files into Geospatial formats
# Data will be filtered (by temporal coherence) and resampled to a regular geospatial grid

# Special considerations:
#     - velocity and displacement are built by differencing the average first and last 3 dates
#     - velocity_linear is a linear fit to the displacement over time and comes with an R^2 fit column
#     - There is a slight mismatch between the full coherence and the gridded coherence (due to calculations before and after filtering). Hence there are 2 files
    
# Download S1 data files at: http://149.165.154.65/data/HDF5EOS/

# Tips for QGIS
#   1. To make the point colors of the gpkg files, navigate to the Symbology-settings, use a "Single Symbol", click on "Marker" then "Simple Marker".
#      Then click on the box on the right side of the "Fill color" bar and select "edit"
#      Type in the Expression: ramp_color('RdBu', scale_linear(VALUE, MIN, MAX, 0, 1))
#           Depending on the file, select the appropriate VALUE and MIN/MAX
#           e.g., "ramp_color('RdBu', scale_linear(dV_vel, -20, 20, 0, 1))"
#           Ideally, MIN = -MAX so that zero deformation is white!
#           Good Colorscales: "RdBu" (Red-White-Blue) for dV/dH or "Turbo" (Red-Green-Blue) for classic LOS colors
#      It is also often best to remove the point outline for better visibility
#   2. There are two temporal coherenge geotiffs, one for the full data, one only for good coherence.
#      The one with good coherence is slightly different as poor points are first removed before making the file based on averages
#      It is best to display both the filtered one overlying the full one
#      Make sure to match the colorscales!
#   3. Use the Plugin "InSAR Explorer" to visualise any timeseries data in the LOS or vertical/horizontal gpkg files
#      Mark the Target gpkg file, then click on the tool to open the plug-in plot window, then select a point
#      Only works if the file contains displacement values with the associated date DYYYYMMDD

# Change settings only in this first section below! Comment/uncomment which files to save at the bottom section!

import h5py
import os
import rasterio
import re
import gc
import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from datetime import datetime, timedelta
from rasterio.transform import from_origin
from sklearn.linear_model import LinearRegression
from scipy.spatial import cKDTree
import matplotlib.pyplot as plt
from shapely.geometry import LineString


# Set Name
VolcanoName = 'Volcano'


# File Paths
S1_FilePath = os.path.expanduser('/mnt/HDD2_4TB/Workspace/MintPy/Projects/Volcano')
ExportPath = os.path.expanduser('/mnt/HDD2_4TB/Workspace/MintPy/Projects/Volcano/MintPy_Exports')


# Import Files (careful to select the correct asc and dsc files)
S1_input_asc = os.path.join(S1_FilePath, 'AT_S1_XXXXX_filtDel4DS.he5')
S1_input_dsc = os.path.join(S1_FilePath, 'DT_S1_XXXXX_filtDel4DS.he5')


# Select export file types, type True or False
save_gpkg = True # Point geopackage files (e.g. for QGIS)
save_gpkg_markings = True # geopackage files with the reference point and the profile line (if enabled)
save_coherence = True # geotiffs for the temp and spat coherence
save_csv = False # As csv table (incl. perp baseline)
save_metadata = True # A .txt file with all metadata


# General Settings
coh_threshold = 0.7 # temporal coherence threshold (0-1)

grid_res_deg = 0.000135 # 15 m ≈ 0.000135 degrees (approx, depending on latitude)

timedelta_asc_dsc = 5 #maximum days between asc and dsc date to make a dV/dH point


# Reference Point
set_reference = False # type True or False

ref_lat = 00.000000;    ref_lon = 00.000000 # select point location


# Cut to specific time interval
set_dates = False # type True or False

start_date = pd.Timestamp("2023-01-01") # YYYY-MM-DD
end_date   = pd.Timestamp("2024-01-01")

# Profile Settings
create_profile = False # type True or False

lat1 = 00.000000;    lon1 = 00.000000 # profile start point
lat2 = 01.000000;    lon2 = 01.000000 # profile end point

max_dist_m = 30 # Max distance of points to the profile line (in m)

ArrowScale   = 20       # scaling factor applied to vectors
ArrowEvery   = 5        # subsampling for arrows
VectorLength = 50       # reference vector in mm/yr
VertExag     = 3        # DEM exaggeration factor
TickStep     = 200      # Elevation tick spacing in meters
ZeroLevel    = 0        # A correction height in m for offset geoid, e.g. if sealevel is not Zero (keep at 0 if unknown)


# %% Define output files

# Geopackages
output_gpk_LOS_asc = os.path.join(ExportPath, f'{VolcanoName}_LOS_AT.gpkg')
output_gpk_LOS_dsc = os.path.join(ExportPath, f'{VolcanoName}_LOS_DT.gpkg')
output_gpk_VerHor = os.path.join(ExportPath, f'{VolcanoName}_DecompositionSmall.gpkg')
output_gpk_TS_Ver = os.path.join(ExportPath, f'{VolcanoName}_Vertical_Timeseries.gpkg')
output_gpk_TS_Hor = os.path.join(ExportPath, f'{VolcanoName}_Horizontal_Timeseries.gpkg')
output_refPoint = os.path.join(ExportPath, f'{VolcanoName}_refPoint.gpkg')

# Geotiffs
output_spCoh_asc = os.path.join(ExportPath, f'{VolcanoName}_avgSpatialCoherence_AT.tif')
output_spCoh_dsc = os.path.join(ExportPath, f'{VolcanoName}_avgSpatialCoherence_DT.tif')
output_tempCoh_asc = os.path.join(ExportPath, f'{VolcanoName}_temporalCoherence_AT.tif')
output_tempCoh_dsc = os.path.join(ExportPath, f'{VolcanoName}_temporalCoherence_DT.tif')
output_tempCoh_asc_filtered = os.path.join(ExportPath, f'{VolcanoName}_temporalCoherence_AT_filtered.tif')
output_tempCoh_dsc_filtered = os.path.join(ExportPath, f'{VolcanoName}_temporalCoherence_DT_filtered.tif')

# CSVs
output_csv_LOS_asc = os.path.join(ExportPath, f'{VolcanoName}_LOS_AT.csv')
output_csv_LOS_dsc = os.path.join(ExportPath, f'{VolcanoName}_LOS_DT.csv')
output_csv_Ver = os.path.join(ExportPath, f'{VolcanoName}_Vertical.csv')
output_csv_Hor = os.path.join(ExportPath, f'{VolcanoName}_Horizontal.csv')

# Profile output files
output_csv_profile = os.path.join(ExportPath, f'{VolcanoName}_profile.csv')
output_profile = os.path.join(ExportPath, f'{VolcanoName}_profile.gpkg')

# Metadata
output_metadata_asc = os.path.join(ExportPath, f'{VolcanoName}_Metadata_AT.txt')
output_metadata_dsc = os.path.join(ExportPath, f'{VolcanoName}_Metadata_DT.txt')

# %% Export LOS metadata and Reference Point

# ASC
if save_metadata:
    with h5py.File(S1_input_asc, 'r') as f, open(output_metadata_asc, 'w') as out:
        for key, value in f.attrs.items():
            # Decode bytes if needed
            if isinstance(value, bytes):
                value = value.decode('utf-8')
            # Handle lists of strings or other iterable types
            elif isinstance(value, (list, tuple)) and all(isinstance(v, bytes) for v in value):
                value = [v.decode('utf-8') for v in value]
            out.write(f"{key}: {value}\n")


# DSC
if save_metadata:
    with h5py.File(S1_input_dsc, 'r') as f, open(output_metadata_dsc, 'w') as out:
        for key, value in f.attrs.items():
            # Decode bytes if needed
            if isinstance(value, bytes):
                value = value.decode('utf-8')
            # Handle lists of strings or other iterable types
            elif isinstance(value, (list, tuple)) and all(isinstance(v, bytes) for v in value):
                value = [v.decode('utf-8') for v in value]
            out.write(f"{key}: {value}\n")
        
if save_gpkg_markings and set_reference:
    ref_point = Point(ref_lon, ref_lat)
    gdf_point = gpd.GeoDataFrame({'name': ['ReferencePoint'], 'geometry': [ref_point]}, crs="EPSG:4326")
    gdf_point.to_file(output_refPoint, layer='reference_point', driver="GPKG")

# %% Functions

# Gridify function
def gridify(df, lat_col='latitude', lon_col='longitude'):
    df['lat_bin'] = (df[lat_col] / grid_res_deg).round(0) * grid_res_deg
    df['lon_bin'] = (df[lon_col] / grid_res_deg).round(0) * grid_res_deg
    return df

# Function to cut start and end dates
if set_dates:
    def filter_date_columns(df, start_date, end_date):
        keep_cols = []
        for col in df.columns:
            if col.startswith('D') and col[1:].isdigit():
                try:
                    col_date = pd.to_datetime(col[1:], format='%Y%m%d')
                    if start_date <= col_date <= end_date:
                        keep_cols.append(col)
                except ValueError:
                    # Not a valid date string
                    pass
            else:
                keep_cols.append(col)
        return df[keep_cols]



# %% Data prep and export asc

# Load data
with h5py.File(S1_input_asc, 'r') as f:
    # Define dataset base path
    base = 'HDFEOS/GRIDS/timeseries'
    lat = f[f'{base}/geometry/latitude'][:].flatten()
    lon = f[f'{base}/geometry/longitude'][:].flatten()
    height = f[f'{base}/geometry/height'][:].flatten()
    azimuth = f[f'{base}/geometry/azimuthAngle'][:].flatten()
    incidence = f[f'{base}/geometry/incidenceAngle'][:].flatten()
    slant = f[f'{base}/geometry/slantRangeDistance'][:].flatten()
    avg_coherence = f[f'{base}/quality/avgSpatialCoherence'][:].flatten()
    temporal_coherence = f[f'{base}/quality/temporalCoherence'][:].flatten()
    demError = f[f'{base}/quality/demError'][:].flatten()
    shadowMask = f[f'{base}/geometry/shadowMask'][:].flatten().astype(bool)
    displacement = f[f'{base}/observation/displacement'][:]
    dates = f[f'{base}/observation/date'][:].astype(str)
    bperp = f[f'{base}/observation/bperp'][:]

# Make a dataframe
df_asc = pd.DataFrame({
    'latitude': lat,
    'longitude': lon,
    'height': height,
    'azimuthAngle': azimuth,
    'incidenceAngle': incidence,
    'demError': demError,
    'avgSpatialCoherence': avg_coherence,
    'temporalCoherence': temporal_coherence,
    'slantRangeDistance': slant,
    'shadowMask': shadowMask,
})

# save bperp separately
bperp_asc = bperp

del lat, lon, height, azimuth, incidence, slant, avg_coherence, temporal_coherence, demError, shadowMask, bperp
gc.collect()


###########################################################################

# Identify and modify displacement columns
displacement_cols = []
for i, date in enumerate(dates):
    disp_flat = displacement[i].flatten()
    col_name = f'D{date}'
    displacement_cols.append(pd.Series(disp_flat, name=col_name))
    
del disp_flat, col_name
gc.collect()

displacement_df_asc = pd.concat(displacement_cols, axis=1) # Combine all displacement columns into a single DataFrame
displacement_df_asc = displacement_df_asc*1000
df_asc = pd.concat([df_asc, displacement_df_asc], axis=1) #concatenate base and displacement data efficiently

# Retain original column structure
df_asc_columns_original = df_asc.columns # Needed for later csv export

# Cutting to start and end date (if enabled)
if set_dates:
    df_asc = filter_date_columns(df_asc, start_date, end_date)

displacement_df_asc_columns = [col for col in df_asc.columns if col.startswith('D')]

del displacement_df_asc, displacement_cols, displacement
gc.collect()

# Grid the dataset
df_asc = gridify(df_asc)
df_asc = df_asc[~df_asc['shadowMask']]
df_asc = df_asc.drop(columns=['shadowMask']) # Remove mask columns

# Average cells to grid
group_cols = ['lat_bin', 'lon_bin']
df_asc = df_asc.groupby(group_cols).mean().reset_index()

# Drop original averaged latitude/longitude if they still exist and rename the gridded ones
df_asc.drop(columns=['latitude', 'longitude'], inplace=True, errors='ignore')
df_asc.rename(columns={'lat_bin': 'latitude', 'lon_bin': 'longitude'}, inplace=True)

# Get sorted unique coordinate bins to define grid
lats_sorted_asc = np.sort(df_asc['latitude'].unique())[::-1]
lons_sorted_asc = np.sort(df_asc['longitude'].unique())       
lon_grid_asc, lat_grid_asc = np.meshgrid(lons_sorted_asc, lats_sorted_asc)
avg_coh_grid_asc = np.full(lon_grid_asc.shape, np.nan)
temp_coh_grid_asc = np.full(lon_grid_asc.shape, np.nan)
coh_lookup_asc = df_asc.set_index(['latitude', 'longitude'])

if create_profile:
    df_asc_height = df_asc[['latitude', 'longitude', 'height']].copy()

###########################################################################
# Fill the 2D arrays
for i, lat in enumerate(lats_sorted_asc):
    for j, lon in enumerate(lons_sorted_asc):
        try:
            avg_coh_grid_asc[i, j] = coh_lookup_asc.at[(lat, lon), 'avgSpatialCoherence']
            temp_coh_grid_asc[i, j] = coh_lookup_asc.at[(lat, lon), 'temporalCoherence']
        except KeyError:
            continue  # Leave as NaN if missing

del coh_lookup_asc
gc.collect()

# Define transform for GeoTIFF export (top-left corner)
transform_asc = from_origin(
    west=lons_sorted_asc[0] - grid_res_deg / 2,
    north=lats_sorted_asc[0] + grid_res_deg / 2,
    xsize=grid_res_deg,
    ysize=grid_res_deg
)

# Define metadata for GeoTIFF export
meta_asc = {
    'driver': 'GTiff',
    'height': avg_coh_grid_asc.shape[0],
    'width': avg_coh_grid_asc.shape[1],
    'count': 1,
    'dtype': 'float32',
    'crs': 'EPSG:4326',
    'transform': transform_asc
}

# Export full Coherence GeoTIFFs
if save_coherence:
    with rasterio.open(output_tempCoh_asc, 'w', **meta_asc) as dst:
        dst.write(temp_coh_grid_asc.astype('float32'), 1)
    with rasterio.open(output_spCoh_asc, 'w', **meta_asc) as dst:
        dst.write(avg_coh_grid_asc.astype('float32'), 1)

###########################################################################

# Filtering and referencing
    
# Masking with the temporal coherence threshold
df_asc = df_asc[(df_asc['temporalCoherence'] >= coh_threshold)]

# Spatial Referencing
if set_reference:
    ref_idx_asc = ((df_asc['latitude'] - ref_lat)**2 + (df_asc['longitude'] - ref_lon)**2).idxmin() # Find the index of the point closest to the reference location
    for col in displacement_df_asc_columns:
        ref_value = df_asc.at[ref_idx_asc, col]
        df_asc.loc[:, col] = df_asc[col] - ref_value

# Temporal Referencing (always set first date point to zero deformation)
date_cols_asc = [col for col in df_asc.columns if col.startswith('D')]
first_date_col_asc = date_cols_asc[0]
df_asc.loc[:,date_cols_asc] = df_asc[date_cols_asc].subtract(df_asc[first_date_col_asc], axis=0)


###########################################################################

# Add velocities, displacements and IDs

# Convert dates to datetime
dates_asc = [datetime.strptime(col[1:], '%Y%m%d') for col in date_cols_asc]  # strip 'D' for parsing


# --- 1. Velocity from average of first & last 3 dates ---
asc_first_3_cols = date_cols_asc[:3]
asc_last_3_cols = date_cols_asc[-3:]

asc_first_avg_disp = df_asc[asc_first_3_cols].mean(axis=1)
asc_last_avg_disp = df_asc[asc_last_3_cols].mean(axis=1)

asc_time_delta_years = (dates_asc[-1] - dates_asc[0]).days / 365.25

df_asc.loc[:, 'velocity'] = (asc_last_avg_disp - asc_first_avg_disp) / asc_time_delta_years
df_asc.loc[:, 'displacement'] = (asc_last_avg_disp - asc_first_avg_disp)

del asc_first_3_cols, asc_last_3_cols, asc_first_avg_disp, asc_last_avg_disp
gc.collect()

# --- 2. Velocity from linear regression ---
asc_X = np.array([(d - dates_asc[0]).days / 365.25 for d in dates_asc]).reshape(-1, 1)
asc_velocity_linear_list = []
asc_r2_list = []
for _, row in df_asc.iterrows():
    y = row[date_cols_asc].values  # displacement series
    model = LinearRegression()
    model.fit(asc_X, y)
    asc_velocity_linear_list.append(model.coef_[0]) # *1000)  # slope -> mm/year
    asc_r2_list.append(model.score(asc_X, y))
df_asc.loc[:, 'velocity_linear'] = asc_velocity_linear_list
df_asc.loc[:, 'velocity_linear_r2'] = asc_r2_list

del asc_r2_list, asc_velocity_linear_list
gc.collect()

# move velocities before the date columns
asc_cols = list(df_asc.columns)
asc_cols.remove('velocity_linear_r2')
asc_cols.remove('velocity_linear')
asc_cols.remove('velocity')
asc_cols.remove('displacement')
insert_pos_asc = asc_cols.index(first_date_col_asc)
asc_cols = asc_cols[:insert_pos_asc] + ['velocity_linear_r2'] + asc_cols[insert_pos_asc:]
asc_cols = asc_cols[:insert_pos_asc] + ['velocity_linear'] + asc_cols[insert_pos_asc:]
asc_cols = asc_cols[:insert_pos_asc] + ['velocity'] + asc_cols[insert_pos_asc:]
asc_cols = asc_cols[:insert_pos_asc] + ['displacement'] + asc_cols[insert_pos_asc:]
df_asc = df_asc[asc_cols]

# Create the pointID column (starting at 1)
df_asc.insert(0, 'pointID', range(1, len(df_asc) + 1))


###########################################################################

# Prep Gridded and filtered dataset for geopackage export
if save_gpkg:
    geometry = [Point(xy) for xy in zip(df_asc['longitude'], df_asc['latitude'])] # Create geometry column from longitude & latitude
    gdf = gpd.GeoDataFrame(df_asc, geometry=geometry, crs='EPSG:4326') # Convert to GeoDataFrame
    gdf.to_file(output_gpk_LOS_asc, driver="GPKG")
    del geometry, gdf
    gc.collect()


###########################################################################

# Prep Gridded and filtered dataset for coherence geotiff export

# Extract relevant data
lats_asc = df_asc['latitude'].values
lons_asc = df_asc['longitude'].values
vals_asc = df_asc['temporalCoherence'].values

# Determine grid_asc extents
min_lon_asc, max_lon_asc = np.min(lons_asc), np.max(lons_asc)
min_lat_asc, max_lat_asc = np.min(lats_asc), np.max(lats_asc)

# Determine grid_asc size
ncols_asc = int(round((max_lon_asc - min_lon_asc) / grid_res_deg)) + 1
nrows_asc = int(round((max_lat_asc - min_lat_asc) / grid_res_deg)) + 1

# Create empty arrays with NaNs
grid_asc = np.full((nrows_asc, ncols_asc), np.nan, dtype=np.float32)

# Map each value to the grid cell
col_idx_asc = ((lons_asc - min_lon_asc) / grid_res_deg).round().astype(int)
row_idx_asc = ((max_lat_asc - lats_asc) / grid_res_deg).round().astype(int)
grid_asc[row_idx_asc, col_idx_asc] = vals_asc

del col_idx_asc, row_idx_asc, lats_asc, lons_asc, vals_asc
gc.collect()

# Create transforms — shifted by half a pixel so coords are pixel centers
transform_asc_filtered = from_origin(
    min_lon_asc - grid_res_deg / 2,
    max_lat_asc + grid_res_deg / 2,
    grid_res_deg,
    grid_res_deg
)

# save filtered coherence
if save_coherence:
    with rasterio.open(output_tempCoh_asc_filtered,'w', driver='GTiff', height=nrows_asc, width=ncols_asc,
        count=1, dtype=np.float32, crs='EPSG:4326', transform=transform_asc_filtered, nodata=np.nan
    ) as dst:
        dst.write(grid_asc, 1)
    del dst
    gc.collect()


###########################################################################

# Prep bperp for csv export

# Identify original date columns from bperp reference (before filtering)
all_date_cols = [col for col in df_asc_columns_original if re.fullmatch(r'D\d{8}', col)]

# Identify current date columns after filtering
remaining_date_cols = [col for col in df_asc.columns if re.fullmatch(r'D\d{8}', col)]

# Find index range of remaining columns in original list
start_idx = all_date_cols.index(remaining_date_cols[0])
end_idx = all_date_cols.index(remaining_date_cols[-1]) + 1  # +1 for inclusive slicing

# Slice bperp_asc accordingly
bperp_values_clipped = bperp_asc[start_idx:end_idx].tolist()

# Count non-date columns for header alignment
non_date_cols = sum([not re.fullmatch(r'D\d{8}', col) for col in df_asc.columns])

# Build header row
header_row = ['bperp'] + [''] * (non_date_cols - 1) + bperp_values_clipped

# Combine into DataFrame
df_bperp_asc = pd.DataFrame([header_row], columns=df_asc.columns)
df_bperp_asc = pd.concat([df_bperp_asc, df_asc], ignore_index=True)


# Export CSVs
if save_csv:
    df_bperp_asc.to_csv(output_csv_LOS_asc, index=False)

del df_bperp_asc
gc.collect()


# %% Data prep and export dsc

# Load data
with h5py.File(S1_input_dsc, 'r') as f:
    # Define dataset base path
    base = 'HDFEOS/GRIDS/timeseries'
    lat = f[f'{base}/geometry/latitude'][:].flatten()
    lon = f[f'{base}/geometry/longitude'][:].flatten()
    height = f[f'{base}/geometry/height'][:].flatten()
    azimuth = f[f'{base}/geometry/azimuthAngle'][:].flatten()
    incidence = f[f'{base}/geometry/incidenceAngle'][:].flatten()
    slant = f[f'{base}/geometry/slantRangeDistance'][:].flatten()
    avg_coherence = f[f'{base}/quality/avgSpatialCoherence'][:].flatten()
    temporal_coherence = f[f'{base}/quality/temporalCoherence'][:].flatten()
    demError = f[f'{base}/quality/demError'][:].flatten()
    shadowMask = f[f'{base}/geometry/shadowMask'][:].flatten().astype(bool)
    displacement = f[f'{base}/observation/displacement'][:]
    dates = f[f'{base}/observation/date'][:].astype(str)
    bperp = f[f'{base}/observation/bperp'][:]

# Make a dataframe
df_dsc = pd.DataFrame({
    'latitude': lat,
    'longitude': lon,
    'height': height,
    'azimuthAngle': azimuth,
    'incidenceAngle': incidence,
    'demError': demError,
    'avgSpatialCoherence': avg_coherence,
    'temporalCoherence': temporal_coherence,
    'slantRangeDistance': slant,
    'shadowMask': shadowMask,
})

# save bperp separately
bperp_dsc = bperp

del lat, lon, height, azimuth, incidence, slant, avg_coherence, temporal_coherence, demError, shadowMask, bperp
gc.collect()


###########################################################################

# Identify and modify displacement columns
displacement_cols = []
for i, date in enumerate(dates):
    disp_flat = displacement[i].flatten()
    col_name = f'D{date}'
    displacement_cols.append(pd.Series(disp_flat, name=col_name))
    
del disp_flat, col_name
gc.collect()

displacement_df_dsc = pd.concat(displacement_cols, axis=1) # Combine all displacement columns into a single DataFrame
displacement_df_dsc = displacement_df_dsc*1000
df_dsc = pd.concat([df_dsc, displacement_df_dsc], axis=1) #concatenate base and displacement data efficiently

# Retain original column structure
df_dsc_columns_original = df_dsc.columns # Needed for later csv export

# Cutting to start and end date (if enabled)
if set_dates:
    df_dsc = filter_date_columns(df_dsc, start_date, end_date)
    
displacement_df_dsc_columns = [col for col in df_dsc.columns if col.startswith('D')]

del displacement_df_dsc, displacement_cols, displacement
gc.collect()

# Grid the dataset
df_dsc = gridify(df_dsc)
df_dsc = df_dsc[~df_dsc['shadowMask']]
df_dsc = df_dsc.drop(columns=['shadowMask']) # Remove mask columns

# Average cells to grid
group_cols = ['lat_bin', 'lon_bin']
df_dsc = df_dsc.groupby(group_cols).mean().reset_index()

# Drop original averaged latitude/longitude if they still exist and rename the gridded ones
df_dsc.drop(columns=['latitude', 'longitude'], inplace=True, errors='ignore')
df_dsc.rename(columns={'lat_bin': 'latitude', 'lon_bin': 'longitude'}, inplace=True)

# Get sorted unique coordinate bins to define grid
lats_sorted_dsc = np.sort(df_dsc['latitude'].unique())[::-1]
lons_sorted_dsc = np.sort(df_dsc['longitude'].unique())       
lon_grid_dsc, lat_grid_dsc = np.meshgrid(lons_sorted_dsc, lats_sorted_dsc)
avg_coh_grid_dsc = np.full(lon_grid_dsc.shape, np.nan)
temp_coh_grid_dsc = np.full(lon_grid_dsc.shape, np.nan)
coh_lookup_dsc = df_dsc.set_index(['latitude', 'longitude'])

if create_profile:
    df_dsc_height = df_dsc[['latitude', 'longitude', 'height']].copy()

###########################################################################
# Fill the 2D arrays
for i, lat in enumerate(lats_sorted_dsc):
    for j, lon in enumerate(lons_sorted_dsc):
        try:
            avg_coh_grid_dsc[i, j] = coh_lookup_dsc.at[(lat, lon), 'avgSpatialCoherence']
            temp_coh_grid_dsc[i, j] = coh_lookup_dsc.at[(lat, lon), 'temporalCoherence']
        except KeyError:
            continue  # Leave as NaN if missing

del coh_lookup_dsc
gc.collect()

# Define transform for GeoTIFF export (top-left corner)
transform_dsc = from_origin(
    west=lons_sorted_dsc[0] - grid_res_deg / 2,
    north=lats_sorted_dsc[0] + grid_res_deg / 2,
    xsize=grid_res_deg,
    ysize=grid_res_deg
)

# Define metadata for GeoTIFF export
meta_dsc = {
    'driver': 'GTiff',
    'height': avg_coh_grid_dsc.shape[0],
    'width': avg_coh_grid_dsc.shape[1],
    'count': 1,
    'dtype': 'float32',
    'crs': 'EPSG:4326',
    'transform': transform_dsc
}

# Export full Coherence GeoTIFFs
if save_coherence:
    with rasterio.open(output_tempCoh_dsc, 'w', **meta_dsc) as dst:
        dst.write(temp_coh_grid_dsc.astype('float32'), 1)
    with rasterio.open(output_spCoh_dsc, 'w', **meta_dsc) as dst:
        dst.write(avg_coh_grid_dsc.astype('float32'), 1)

###########################################################################

# Filtering and referencing

# Masking with the temporal coherence threshold
df_dsc = df_dsc[(df_dsc['temporalCoherence'] >= coh_threshold)]

# Spatial Referencing
if set_reference:
    ref_idx_dsc = ((df_dsc['latitude'] - ref_lat)**2 + (df_dsc['longitude'] - ref_lon)**2).idxmin() # Find the index of the point closest to the reference location
    for col in displacement_df_dsc_columns:
        ref_value = df_dsc.at[ref_idx_dsc, col]
        df_dsc.loc[:, col] = df_dsc[col] - ref_value

# Temporal Referencing (always set first date point to zero deformation)
date_cols_dsc = [col for col in df_dsc.columns if col.startswith('D')]
first_date_col_dsc = date_cols_dsc[0]
df_dsc.loc[:,date_cols_dsc] = df_dsc[date_cols_dsc].subtract(df_dsc[first_date_col_dsc], axis=0)


###########################################################################

# Add velocities, displacements and IDs

# Convert dates to datetime
dates_dsc = [datetime.strptime(col[1:], '%Y%m%d') for col in date_cols_dsc]  # strip 'D' for parsing


# --- 1. Velocity from average of first & last 3 dates ---
dsc_first_3_cols = date_cols_dsc[:3]
dsc_last_3_cols = date_cols_dsc[-3:]

dsc_first_avg_disp = df_dsc[dsc_first_3_cols].mean(axis=1)
dsc_last_avg_disp = df_dsc[dsc_last_3_cols].mean(axis=1)

dsc_time_delta_years = (dates_dsc[-1] - dates_dsc[0]).days / 365.25

df_dsc.loc[:, 'velocity'] = (dsc_last_avg_disp - dsc_first_avg_disp) / dsc_time_delta_years
df_dsc.loc[:, 'displacement'] = (dsc_last_avg_disp - dsc_first_avg_disp)

del dsc_first_3_cols, dsc_last_3_cols, dsc_first_avg_disp, dsc_last_avg_disp
gc.collect()

# --- 2. Velocity from linear regression ---
dsc_X = np.array([(d - dates_dsc[0]).days / 365.25 for d in dates_dsc]).reshape(-1, 1)
dsc_velocity_linear_list = []
dsc_r2_list = []
for _, row in df_dsc.iterrows():
    y = row[date_cols_dsc].values  # displacement series
    model = LinearRegression()
    model.fit(dsc_X, y)
    dsc_velocity_linear_list.append(model.coef_[0]) # *1000)  # slope -> mm/year
    dsc_r2_list.append(model.score(dsc_X, y))
df_dsc.loc[:, 'velocity_linear'] = dsc_velocity_linear_list
df_dsc.loc[:, 'velocity_linear_r2'] = dsc_r2_list

del dsc_r2_list, dsc_velocity_linear_list
gc.collect()

# move velocities before the date columns
dsc_cols = list(df_dsc.columns)
dsc_cols.remove('velocity_linear_r2')
dsc_cols.remove('velocity_linear')
dsc_cols.remove('velocity')
dsc_cols.remove('displacement')
insert_pos_dsc = dsc_cols.index(first_date_col_dsc)
dsc_cols = dsc_cols[:insert_pos_dsc] + ['velocity_linear_r2'] + dsc_cols[insert_pos_dsc:]
dsc_cols = dsc_cols[:insert_pos_dsc] + ['velocity_linear'] + dsc_cols[insert_pos_dsc:]
dsc_cols = dsc_cols[:insert_pos_dsc] + ['velocity'] + dsc_cols[insert_pos_dsc:]
dsc_cols = dsc_cols[:insert_pos_dsc] + ['displacement'] + dsc_cols[insert_pos_dsc:]
df_dsc = df_dsc[dsc_cols]

# Create the pointID column (starting at 1)
df_dsc.insert(0, 'pointID', range(1, len(df_dsc) + 1))


###########################################################################

# Prep Gridded and filtered dataset for geopackage export
if save_gpkg:
    geometry = [Point(xy) for xy in zip(df_dsc['longitude'], df_dsc['latitude'])] # Create geometry column from longitude & latitude
    gdf = gpd.GeoDataFrame(df_dsc, geometry=geometry, crs='EPSG:4326') # Convert to GeoDataFrame
    gdf.to_file(output_gpk_LOS_dsc, driver="GPKG")
    del geometry, gdf
    gc.collect()


###########################################################################

# Prep Gridded and filtered dataset for coherence geotiff export

# Extract relevant data
lats_dsc = df_dsc['latitude'].values
lons_dsc = df_dsc['longitude'].values
vals_dsc = df_dsc['temporalCoherence'].values

# Determine grid_dsc extents
min_lon_dsc, max_lon_dsc = np.min(lons_dsc), np.max(lons_dsc)
min_lat_dsc, max_lat_dsc = np.min(lats_dsc), np.max(lats_dsc)

# Determine grid_dsc size
ncols_dsc = int(round((max_lon_dsc - min_lon_dsc) / grid_res_deg)) + 1
nrows_dsc = int(round((max_lat_dsc - min_lat_dsc) / grid_res_deg)) + 1

# Create empty arrays with NaNs
grid_dsc = np.full((nrows_dsc, ncols_dsc), np.nan, dtype=np.float32)

# Map each value to the grid cell
col_idx_dsc = ((lons_dsc - min_lon_dsc) / grid_res_deg).round().astype(int)
row_idx_dsc = ((max_lat_dsc - lats_dsc) / grid_res_deg).round().astype(int)
grid_dsc[row_idx_dsc, col_idx_dsc] = vals_dsc

del col_idx_dsc, row_idx_dsc, lats_dsc, lons_dsc, vals_dsc
gc.collect()

# Create transforms — shifted by half a pixel so coords are pixel centers
transform_dsc_filtered = from_origin(
    min_lon_dsc - grid_res_deg / 2,
    max_lat_dsc + grid_res_deg / 2,
    grid_res_deg,
    grid_res_deg
)

# save filtered coherence
if save_coherence:
    with rasterio.open(output_tempCoh_dsc_filtered,'w', driver='GTiff', height=nrows_dsc, width=ncols_dsc,
        count=1, dtype=np.float32, crs='EPSG:4326', transform=transform_dsc_filtered, nodata=np.nan
    ) as dst:
        dst.write(grid_dsc, 1)
        del dst
        gc.collect()


###########################################################################

# Identify original date columns from bperp reference (before filtering)
all_date_cols = [col for col in df_dsc_columns_original if re.fullmatch(r'D\d{8}', col)]

# Identify current date columns after filtering
remaining_date_cols = [col for col in df_dsc.columns if re.fullmatch(r'D\d{8}', col)]

# Find index range of remaining columns in original list
start_idx = all_date_cols.index(remaining_date_cols[0])
end_idx = all_date_cols.index(remaining_date_cols[-1]) + 1  # +1 for inclusive slicing

# Slice bperp_dsc accordingly
bperp_values_clipped = bperp_dsc[start_idx:end_idx].tolist()

# Count non-date columns for header alignment
non_date_cols = sum([not re.fullmatch(r'D\d{8}', col) for col in df_dsc.columns])

# Build header row
header_row = ['bperp'] + [''] * (non_date_cols - 1) + bperp_values_clipped

# Combine into DataFrame
df_bperp_dsc = pd.DataFrame([header_row], columns=df_dsc.columns)
df_bperp_dsc = pd.concat([df_bperp_dsc, df_dsc], ignore_index=True)


# Export CSVs
if save_csv:
    df_bperp_dsc.to_csv(output_csv_LOS_dsc, index=False)

del df_bperp_dsc
gc.collect()


# %% Decomposition in dV and dH

# Merge on the common grid points (i.e., lat_bin and lon_bin)
merged = pd.merge(df_asc, df_dsc, on=['latitude', 'longitude'], suffixes=('_asc', '_dsc'))

# Convert azimuth angles to radians and apply +90 deg shift
def azimuth_cos(angle_deg):
    return np.cos(np.radians(angle_deg + 90))

def sin_incidence(angle_deg):
    return np.sin(np.radians(angle_deg))

def cos_incidence(angle_deg):
    return np.cos(np.radians(angle_deg))

# Apply the decomposition formula
A = sin_incidence(merged['incidenceAngle_asc']) * azimuth_cos(merged['azimuthAngle_asc'])
B = cos_incidence(merged['incidenceAngle_asc'])
C = sin_incidence(merged['incidenceAngle_dsc']) * azimuth_cos(merged['azimuthAngle_dsc'])
D = cos_incidence(merged['incidenceAngle_dsc'])
disp_asc = merged['displacement_asc']
disp_dsc = merged['displacement_dsc']
vel_asc = merged['velocity_asc']
vel_dsc = merged['velocity_dsc']
vel_asc_linear = merged['velocity_linear_asc']
vel_dsc_linear = merged['velocity_linear_dsc']


# Solve the linear system:
# [A B] [dH] = disp_asc
# [C D] [dV] = disp_dsc
denominator = A * D - B * C
merged['dH_disp_total'] = (disp_asc * D - disp_dsc * B) / denominator
merged['dV_disp_total'] = (-disp_asc * C + disp_dsc * A) / denominator
merged['dH_vel'] = (vel_asc * D - vel_dsc * B) / denominator
merged['dV_vel'] = (-vel_asc * C + vel_dsc * A) / denominator
merged['dH_vel_lin'] = (vel_asc_linear * D - vel_dsc_linear * B) / denominator
merged['dV_vel_lin'] = (-vel_asc_linear * C + vel_dsc_linear * A) / denominator

# Create output DataFrames
merged['height_avg'] = (merged['height_asc'] + merged['height_dsc']) / 2
cols_to_keep = ['latitude', 'longitude', 'height_avg', 'demError_asc', 'demError_dsc', 
                'avgSpatialCoherence_asc', 'avgSpatialCoherence_dsc',
                'temporalCoherence_asc', 'temporalCoherence_dsc', 
                'velocity_linear_r2_asc', 'velocity_linear_r2_dsc',
                'dH_disp_total', 'dV_disp_total', 'dH_vel', 'dV_vel', 'dH_vel_lin', 'dV_vel_lin']
df_VerHor = merged[cols_to_keep].copy()
df_VerHor.insert(0, 'VerHorID', range(1, len(df_VerHor) + 1))


###########################################################################

# Building dV and dH timeseries

# Failsafe for overlapping dates
def resolve_col(df, base_name, side):
    """
    Return the correct column name in `df` for a date column base_name "DYYYYMMDD".
    Prefers unsuffixed if present; otherwise returns f"{base_name}_{side}" if present.
    """
    if base_name in df.columns:
        return base_name
    suffixed = f"{base_name}_{side}"
    if suffixed in df.columns:
        return suffixed
    raise KeyError(f"Neither '{base_name}' nor '{suffixed}' found in DataFrame columns.")
    


# Build matched date pairs within 5-day tolerance
matched_pairs = []
used_dsc_indices = set()

for i, asc_date in enumerate(dates_asc):
    closest_dsc_idx = None
    min_diff = timedelta(days=timedelta_asc_dsc)

    for j, dsc_date in enumerate(dates_dsc):
        if j in used_dsc_indices:
            continue
        diff = abs((asc_date - dsc_date).days)
        if diff <= timedelta_asc_dsc and diff < min_diff.days:
            min_diff = timedelta(days=diff)
            closest_dsc_idx = j

    if closest_dsc_idx is not None:
        matched_pairs.append((i, closest_dsc_idx))
        used_dsc_indices.add(closest_dsc_idx)

# Calculate time series displacements
records_ver = []
records_hor = []

for asc_idx, dsc_idx in matched_pairs:
    asc_date = dates_asc[asc_idx]
    dsc_date = dates_dsc[dsc_idx]
    avg_date = asc_date + (dsc_date - asc_date) / 2
    later_date = max(asc_date, dsc_date)
    avg_date_str = f'D{later_date.strftime("%Y%m%d")}' # or use this, it is latest date VS average date: avg_date_str = f'D{avgg_date.strftime("%Y%m%d")}'
    col_asc = resolve_col(merged, date_cols_asc[asc_idx], 'asc')
    col_dsc = resolve_col(merged, date_cols_dsc[dsc_idx], 'dsc')

    disp_asc = merged[col_asc]
    disp_dsc = merged[col_dsc]

    # Repeat decomposition
    A = sin_incidence(merged['incidenceAngle_asc']) * azimuth_cos(merged['azimuthAngle_asc'])
    B = cos_incidence(merged['incidenceAngle_asc'])
    C = sin_incidence(merged['incidenceAngle_dsc']) * azimuth_cos(merged['azimuthAngle_dsc'])
    D = cos_incidence(merged['incidenceAngle_dsc'])

    denominator = A * D - B * C
    dH_disp_total = (disp_asc * D - disp_dsc * B) / denominator
    dV_disp_total = (-disp_asc * C + disp_dsc * A) / denominator

    # Store displacement at this date
    records_ver.append(pd.DataFrame({
        'latitude': merged['latitude'],
        'longitude': merged['longitude'],
        avg_date_str: dV_disp_total
    }))
    records_hor.append(pd.DataFrame({
        'latitude': merged['latitude'],
        'longitude': merged['longitude'],
        avg_date_str: dH_disp_total
    }))

# Merge on coordinates
df_Ver = records_ver[0]
for df in records_ver[1:]:
    df_Ver = pd.merge(df_Ver, df, on=['latitude', 'longitude'])

df_Hor = records_hor[0]
for df in records_hor[1:]:
    df_Hor = pd.merge(df_Hor, df, on=['latitude', 'longitude'])

del A, B, C, D, denominator, df, dV_disp_total, dH_disp_total, disp_asc, disp_dsc, merged, vel_asc, vel_asc_linear, vel_dsc, vel_dsc_linear
gc.collect()

# Add data columns
# Define columns to insert (metadata + total displacement/velocity)
extra_cols = ['height_avg','demError_asc', 'demError_dsc',
              'avgSpatialCoherence_asc', 'avgSpatialCoherence_dsc',
              'temporalCoherence_asc', 'temporalCoherence_dsc',
              'velocity_linear_r2_asc', 'velocity_linear_r2_dsc',
              'dH_disp_total', 'dV_disp_total', 'dH_vel', 'dV_vel', 'dH_vel_lin', 'dV_vel_lin']

# Extract these from df_VerHor
extras = df_VerHor[extra_cols].copy()

# Insert into df_Ver
first_date_col = next(col for col in df_Ver.columns if col.startswith('D'))
insert_pos = df_Ver.columns.get_loc(first_date_col)
for col in reversed(extra_cols):  # reverse so insertion order is preserved
    df_Ver.insert(insert_pos, col, extras[col])

# Same for df_Hor
for col in reversed(extra_cols):
    df_Hor.insert(insert_pos, col, extras[col])

del extras
gc.collect()

df_Ver.insert(0, 'VerHorID', range(1, len(df_Ver) + 1))
df_Hor.insert(0, 'VerHorID', range(1, len(df_Hor) + 1))


###########################################################################

# Save geopackages
if save_gpkg:
    geometry = [Point(xy) for xy in zip(df_VerHor['longitude'], df_VerHor['latitude'])]
    gdf = gpd.GeoDataFrame(df_VerHor, geometry=geometry, crs='EPSG:4326')
    gdf.to_file(output_gpk_VerHor, layer='VerticalTimeseries', driver='GPKG')

    geometry = [Point(xy) for xy in zip(df_Ver['longitude'], df_Ver['latitude'])]
    gdf = gpd.GeoDataFrame(df_Ver, geometry=geometry, crs='EPSG:4326')
    gdf.to_file(output_gpk_TS_Ver, layer='VerticalTimeseries', driver='GPKG')

    geometry = [Point(xy) for xy in zip(df_Hor['longitude'], df_Hor['latitude'])]
    gdf = gpd.GeoDataFrame(df_Hor, geometry=geometry, crs='EPSG:4326')
    gdf.to_file(output_gpk_TS_Hor, layer='HorizontalTimeseries', driver='GPKG')
    
    del geometry, gdf
    gc.collect()


# %% Making a Profile

###########################################################################

# Define profile line distance sampling

def haversine(lat1, lon1, lat2, lon2):
    """Vectorized haversine distance in meters."""
    R = 6371000.0  # Earth radius in m
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = phi2 - phi1
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi/2.0)**2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda/2.0)**2
    return 2 * R * np.arcsin(np.sqrt(a))

# Define profile line generation

def make_profile(lat1, lon1, lat2, lon2):
    """
    Create a profile between two points and sample displacement + height data.
    Uses KDTree for fast nearest-neighbor search.
    """
    # global df_asc_height, df_dsc_height, df_VerHor, grid_res_deg

    # Build KDTree for each dataset
    asc_tree = cKDTree(np.radians(df_asc_height[['latitude','longitude']].values))
    dsc_tree = cKDTree(np.radians(df_dsc_height[['latitude','longitude']].values))
    ver_tree = cKDTree(np.radians(df_VerHor[['latitude','longitude']].values))

    # Profile points along line
    n_steps = int(max(abs(lat2 - lat1), abs(lon2 - lon1)) / grid_res_deg) + 1
    lats = np.linspace(lat1, lat2, n_steps)
    lons = np.linspace(lon1, lon2, n_steps)

    profile_rows = []
    dist_accum = 0.0

    # Precompute distances between consecutive profile points
    for i, (lat, lon) in enumerate(zip(lats, lons)):
        if i == 0:
            dist_accum = 0.0
        else:
            dist_accum += haversine(lats[i-1], lons[i-1], lat, lon)

        # ASC
        _, idx_asc = asc_tree.query(np.radians([lat, lon]))
        asc_point = df_asc_height.iloc[idx_asc]
        asc_dist = haversine(lat, lon, asc_point.latitude, asc_point.longitude)
        h_asc = asc_point.height if asc_dist <= max_dist_m else np.nan
        h_asc = h_asc-ZeroLevel

        # DSC
        _, idx_dsc = dsc_tree.query(np.radians([lat, lon]))
        dsc_point = df_dsc_height.iloc[idx_dsc]
        dsc_dist = haversine(lat, lon, dsc_point.latitude, dsc_point.longitude)
        h_dsc = dsc_point.height if dsc_dist <= max_dist_m else np.nan
        h_dsc = h_dsc-ZeroLevel

        # Average height
        height = np.nanmean([h_asc, h_dsc]) if not (np.isnan(h_asc) and np.isnan(h_dsc)) else 0

        # VerHor
        dV_vel = dH_vel = dV_vel_lin = dH_vel_lin = np.nan
        _, idx_ver = ver_tree.query(np.radians([lat, lon]))
        ver_point = df_VerHor.iloc[idx_ver]
        ver_dist = haversine(lat, lon, ver_point.latitude, ver_point.longitude)
        if ver_dist <= max_dist_m:
            dV_vel     = ver_point.get('dV_vel', np.nan)
            dH_vel     = ver_point.get('dH_vel', np.nan)
            dV_vel_lin = ver_point.get('dV_vel_lin', np.nan)
            dH_vel_lin = ver_point.get('dH_vel_lin', np.nan)

        profile_rows.append({
            'distance_m': dist_accum,
            'latitude': lat,
            'longitude': lon,
            'height': height,
            'dV_vel': dV_vel,
            'dH_vel': dH_vel,
            'dV_vel_lin': dV_vel_lin,
            'dH_vel_lin': dH_vel_lin
        })

    return pd.DataFrame(profile_rows)


# Define vector profile plotting

def plot_profile(df_profile):
    fig, ax = plt.subplots(figsize=(10,5))

    # Apply exaggeration to heights (terrain only)
    y_exag = df_profile['height'] * VertExag

    # Plot height with exaggeration
    ax.plot(df_profile['distance_m'], y_exag, 'k-')

    # Subsample arrows
    xs = df_profile['distance_m'].values[::ArrowEvery]
    ys = y_exag.values[::ArrowEvery]

    # Make vectors
    u = df_profile['dH_vel'].values[::ArrowEvery] * ArrowScale
    v = df_profile['dV_vel'].values[::ArrowEvery] * ArrowScale
    
    ax.quiver(xs, ys, u, v, color='r', angles='xy', scale_units='xy', scale=1)

    # --- Reference arrow (top-right, pointing left, always inside) ---
    x_min, x_max = df_profile['distance_m'].min(), df_profile['distance_m'].max()
    y_min_e, y_max_e = y_exag.min(), y_exag.max()
    ref_x = x_max - 0.01 * (x_max - x_min)
    ref_y = y_max_e - 0.01 * (y_max_e - y_min_e)

    ax.quiver(ref_x, ref_y, -VectorLength * ArrowScale, 0,
              color='r', angles='xy', scale_units='xy', scale=1)
    ax.text(ref_x - VectorLength * ArrowScale - 100, ref_y,
            f"{VectorLength} mm/yr", color='r', va='center', ha='right')

    # Labels / title (keeping your edits)
    ax.set_xlabel("Profile distance (m)")
    ax.set_ylabel("Elevation (m)")
    ax.set_title(f"Displacement profile ({VertExag}x exaggerated)")

    # Equal aspect so arrows don't warp when VertExag changes
    ax.set_aspect('equal', adjustable='box')

    # Clean y-ticks in true elevation units
    # # Axis fixed at zero
    hmax_true = df_profile['height'].max()
    true_ticks = np.arange( 
        0,  # force from 0
        np.ceil(hmax_true / TickStep) * TickStep + TickStep,
        TickStep)
    # # Axis flexible
    # hmin_true, hmax_true = df_profile['height'].min(), df_profile['height'].max()
    # true_ticks = np.arange(
    #     np.floor(hmin_true / TickStep) * TickStep,
    #     np.ceil(hmax_true / TickStep) * TickStep + TickStep,
    #     TickStep)
    ax.set_yticks(true_ticks * VertExag)
    ax.set_yticklabels([f"{int(t)}" for t in true_ticks])

    plt.tight_layout()
    plt.show()

###########################################################################

if create_profile:
    # Make the profile data
    profile = make_profile(lat1, lon1, lat2, lon2)

    # Plot the profile data
    plot_profile(profile)

    # Save the profile data to csv table
    profile.to_csv(output_csv_profile, index=False)


if create_profile and save_gpkg_markings:
    # Save the profile data to geopackage line
    profile_line = LineString([(lon1, lat1), (lon2, lat2)])
    gdf_line = gpd.GeoDataFrame({'name': ['ProfileLine'], 'geometry': [profile_line]}, crs="EPSG:4326")
    gdf_line.to_file(output_profile, layer='profile_line', driver="GPKG")


if save_gpkg_markings:
    ref_point = Point(ref_lon, ref_lat)
    gdf_point = gpd.GeoDataFrame({'name': ['ReferencePoint'], 'geometry': [ref_point]}, crs="EPSG:4326")
    gdf_point.to_file(output_refPoint, layer='reference_point', driver="GPKG")

