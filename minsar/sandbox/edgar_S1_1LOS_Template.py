# -*- coding: utf-8 -*-
"""
Created on Sat Aug 23 16:09:34 2025

@author: Edgar
"""

# Notes
# This script will convert one S1.he5 files into Geospatial formats
# Data will be filtered (by temporal coherence) and can be exported in full or be resampled to a regular geospatial grid

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
from datetime import datetime
from shapely.geometry import Point
from rasterio.transform import from_origin
from sklearn.linear_model import LinearRegression


# Set Name
VolcanoName = 'Volcano_ATorDT'


# File Paths
S1_FilePath = os.path.expanduser('/mnt/HDD2_4TB/Workspace/MintPy/Projects/Volcano')
ExportPath = os.path.expanduser('/mnt/HDD2_4TB/Workspace/MintPy/Projects/Volcano/MintPy_Exports')


# Import File
S1_input = os.path.join(S1_FilePath, 'S1_XXXX_filtDel4DS.he5')


# Select whether to save the full resolution file or a gridded version
save_FullRes = True
save_GridRes = False

# Select export file types, type True or False
save_gpkg = True # Point geopackage files (e.g. for QGIS)
save_gpkg_markings = False # geopackage files with the reference point and the profile line (if enabled)
save_coherence = True # geotiffs for the temp and spat coherence (only for gridded data)
save_csv = False # As csv table (incl. perp baseline)
save_metadata = True # As txt file with all metadata


# General Settings
coh_threshold = 0.7 # temporal coherence threshold (0-1)

grid_res_deg = 0.000135 # 15 m ≈ 0.000135 degrees (approx, depending on latitude)


# Reference Point
set_reference = False # type True or False

ref_lat = 00.000000;    ref_lon = 00.000000 # select point location


# Cut to specific time interval
set_dates = False # type True or False

start_date = pd.Timestamp("2023-01-01") # YYYY-MM-DD
end_date   = pd.Timestamp("2024-01-01")


# %% Define output files

# Geopackages
output_gpk_LOS = os.path.join(ExportPath, f'{VolcanoName}_LOS.gpkg')
output_gpk_LOS_FullRes = os.path.join(ExportPath, f'{VolcanoName}_LOS_FullRes.gpkg')
output_refPoint = os.path.join(ExportPath, f'{VolcanoName}_refPoint.gpkg')

# Geotiffs (only gridded files)
output_spCoh = os.path.join(ExportPath, f'{VolcanoName}_avgSpatialCoherence.tif')
output_tempCoh = os.path.join(ExportPath, f'{VolcanoName}_temporalCoherence.tif')
output_tempCoh_filtered = os.path.join(ExportPath, f'{VolcanoName}_temporalCoherence_filtered.tif')

# CSVs
output_csv_LOS = os.path.join(ExportPath, f'{VolcanoName}_LOS.csv')
output_csv_LOS_FullRes = os.path.join(ExportPath, f'{VolcanoName}_LOS_FullRes.csv')

# Metadata
output_metadata = os.path.join(ExportPath, f'{VolcanoName}_Metadata.txt')


# %% Export LOS metadata and Reference Point

if save_metadata:
    with h5py.File(S1_input, 'r') as f, open(output_metadata, 'w') as out:
        for key, value in f.attrs.items():
            # Decode bytes if needed
            if isinstance(value, bytes):
                value = value.decode('utf-8')
            # Handle lists of strings or other iterable types
            elif isinstance(value, (list, tuple)) and all(isinstance(v, bytes) for v in value):
                value = [v.decode('utf-8') for v in value]
            out.write(f"{key}: {value}\n")

        
if save_gpkg_markings:
    ref_point = Point(ref_lon, ref_lat)
    gdf_point = gpd.GeoDataFrame({'name': ['ReferencePoint'], 'geometry': [ref_point]}, crs="EPSG:4326")
    gdf_point.to_file(output_refPoint, layer='reference_point', driver="GPKG")


# %% Functions

# Gridify function
if save_GridRes:
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


# %% Data prep and export Full resolution data

if save_FullRes:
    # Load data
    with h5py.File(S1_input, 'r') as f:
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
    df = pd.DataFrame({
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


    del lat, lon, height, azimuth, incidence, slant, avg_coherence, temporal_coherence, demError, shadowMask
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

    displacement_df = pd.concat(displacement_cols, axis=1) # Combine all displacement columns into a single DataFrame
    displacement_df = displacement_df*1000
    df = pd.concat([df, displacement_df], axis=1) #concatenate base and displacement data efficiently
   
    # Retain original column structure
    df_columns_original = df.columns # Needed for later csv export

    # Cutting to start and end date (if enabled)
    if set_dates:
        df = filter_date_columns(df, start_date, end_date)
   
    displacement_df_columns = [col for col in df.columns if col.startswith('D')]

    del displacement_df, displacement_cols, displacement
    gc.collect()


    ###########################################################################

    # Filtering and referencing

    # Masking with the temporal coherence threshold
    df = df[(df['temporalCoherence'] >= coh_threshold)]

    # Spatial Referencing
    if set_reference:
        ref_idx = ((df['latitude'] - ref_lat)**2 + (df['longitude'] - ref_lon)**2).idxmin() # Find the index of the point closest to the reference location
        for col in displacement_df_columns:
            ref_value = df.at[ref_idx, col]
            df.loc[:, col] = df[col] - ref_value

    # Temporal Referencing (always set first date point to zero deformation)
    date_cols = [col for col in df.columns if col.startswith('D')]
    first_date_col = date_cols[0]
    df.loc[:,date_cols] = df[date_cols].subtract(df[first_date_col], axis=0)


    ###########################################################################

    # Add velocities, displacements and IDs

    # Convert dates to datetime
    dates = [datetime.strptime(col[1:], '%Y%m%d') for col in date_cols]  # strip 'D' for parsing


    # --- 1. Velocity from average of first & last 3 dates ---
    first_3_cols = date_cols[:3]
    last_3_cols = date_cols[-3:]

    first_avg_disp = df[first_3_cols].mean(axis=1)
    last_avg_disp = df[last_3_cols].mean(axis=1)

    time_delta_years = (dates[-1] - dates[0]).days / 365.25

    df.loc[:, 'velocity'] = (last_avg_disp - first_avg_disp) / time_delta_years
    df.loc[:, 'displacement'] = (last_avg_disp - first_avg_disp)

    del first_3_cols, last_3_cols, first_avg_disp, last_avg_disp
    gc.collect()

    # --- 2. Velocity from linear regression ---
    X = np.array([(d - dates[0]).days / 365.25 for d in dates]).reshape(-1, 1)
    velocity_linear_list = []
    r2_list = []
    for _, row in df.iterrows():
        y = row[date_cols].values  # displacement series
        model = LinearRegression()
        model.fit(X, y)
        velocity_linear_list.append(model.coef_[0]) # *1000)  # slope -> mm/year
        r2_list.append(model.score(X, y))
    df.loc[:, 'velocity_linear'] = velocity_linear_list
    df.loc[:, 'velocity_linear_r2'] = r2_list

    del r2_list, velocity_linear_list
    gc.collect()

    # move velocities before the date columns
    cols = list(df.columns)
    cols.remove('velocity_linear_r2')
    cols.remove('velocity_linear')
    cols.remove('velocity')
    cols.remove('displacement')
    insert_pos = cols.index(first_date_col)
    cols = cols[:insert_pos] + ['velocity_linear_r2'] + cols[insert_pos:]
    cols = cols[:insert_pos] + ['velocity_linear'] + cols[insert_pos:]
    cols = cols[:insert_pos] + ['velocity'] + cols[insert_pos:]
    cols = cols[:insert_pos] + ['displacement'] + cols[insert_pos:]
    df = df[cols]

    # Create the pointID column (starting at 1)
    df.insert(0, 'pointID', range(1, len(df) + 1))


    ###########################################################################


    if save_gpkg:
        geometry = [Point(xy) for xy in zip(df['longitude'], df['latitude'])] # Create geometry column from longitude & latitude
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs='EPSG:4326') # Convert to GeoDataFrame
        gdf.to_file(output_gpk_LOS_FullRes, driver="GPKG")
        del geometry, gdf
        gc.collect()
        
    
    ###########################################################################

    # Prep bperp for csv export

    # Identify original date columns from bperp reference (before filtering)
    all_date_cols = [col for col in df_columns_original if re.fullmatch(r'D\d{8}', col)]

    # Identify current date columns after filtering
    remaining_date_cols = [col for col in df.columns if re.fullmatch(r'D\d{8}', col)]

    # Find index range of remaining columns in original list
    start_idx = all_date_cols.index(remaining_date_cols[0])
    end_idx = all_date_cols.index(remaining_date_cols[-1]) + 1  # +1 for inclusive slicing

    # Slice bperp accordingly
    bperp_values_clipped = bperp[start_idx:end_idx].tolist()

    # Count non-date columns for header alignment
    non_date_cols = sum([not re.fullmatch(r'D\d{8}', col) for col in df.columns])

    # Build header row
    header_row = ['bperp'] + [''] * (non_date_cols - 1) + bperp_values_clipped

    # Combine into DataFrame
    df_bperp = pd.DataFrame([header_row], columns=df.columns)
    df_bperp = pd.concat([df_bperp, df], ignore_index=True)
    
    # Export CSVs
    if save_csv:
        df_bperp.to_csv(output_csv_LOS_FullRes, index=False)

    del df_bperp
    gc.collect()


# %% Data prep and export Gridded File

if save_GridRes:

    # Load data
    with h5py.File(S1_input, 'r') as f:
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
    df = pd.DataFrame({
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


    del lat, lon, height, azimuth, incidence, slant, avg_coherence, temporal_coherence, demError, shadowMask
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

    displacement_df = pd.concat(displacement_cols, axis=1) # Combine all displacement columns into a single DataFrame
    displacement_df = displacement_df*1000
    df = pd.concat([df, displacement_df], axis=1) #concatenate base and displacement data efficiently
    
    # Retain original column structure
    df_columns_original = df.columns # Needed for later csv export

    # Cutting to start and end date (if enabled)
    if set_dates:
        df = filter_date_columns(df, start_date, end_date)
    
    displacement_df_columns = [col for col in df.columns if col.startswith('D')]

    del displacement_df, displacement_cols, displacement
    gc.collect()

    # Grid the dataset
    df = gridify(df)
    df = df[~df['shadowMask']]
    df = df.drop(columns=['shadowMask']) # Remove mask columns

    # Average cells to grid
    group_cols = ['lat_bin', 'lon_bin']
    df = df.groupby(group_cols).mean().reset_index()

    # Drop original averaged latitude/longitude if they still exist and rename the gridded ones
    df.drop(columns=['latitude', 'longitude'], inplace=True, errors='ignore')
    df.rename(columns={'lat_bin': 'latitude', 'lon_bin': 'longitude'}, inplace=True)

    # Get sorted unique coordinate bins to define grid
    lats_sorted = np.sort(df['latitude'].unique())[::-1]
    lons_sorted = np.sort(df['longitude'].unique())       
    lon_grid, lat_grid = np.meshgrid(lons_sorted, lats_sorted)
    avg_coh_grid = np.full(lon_grid.shape, np.nan)
    temp_coh_grid = np.full(lon_grid.shape, np.nan)
    coh_lookup = df.set_index(['latitude', 'longitude'])

    ###########################################################################
    # Fill the 2D arrays
    for i, lat in enumerate(lats_sorted):
        for j, lon in enumerate(lons_sorted):
            try:
                avg_coh_grid[i, j] = coh_lookup.at[(lat, lon), 'avgSpatialCoherence']
                temp_coh_grid[i, j] = coh_lookup.at[(lat, lon), 'temporalCoherence']
            except KeyError:
                continue  # Leave as NaN if missing

    del coh_lookup
    gc.collect()

    # Define transform for GeoTIFF export (top-left corner)
    transform = from_origin(
        west=lons_sorted[0] - grid_res_deg / 2,
        north=lats_sorted[0] + grid_res_deg / 2,
        xsize=grid_res_deg,
        ysize=grid_res_deg
    )

    # Define metadata for GeoTIFF export
    meta = {
        'driver': 'GTiff',
        'height': avg_coh_grid.shape[0],
        'width': avg_coh_grid.shape[1],
        'count': 1,
        'dtype': 'float32',
        'crs': 'EPSG:4326',
        'transform': transform
    }

    # Export full Coherence GeoTIFFs
    if save_coherence:
        with rasterio.open(output_tempCoh, 'w', **meta) as dst:
            dst.write(temp_coh_grid.astype('float32'), 1)
        with rasterio.open(output_spCoh, 'w', **meta) as dst:
            dst.write(avg_coh_grid.astype('float32'), 1)

    ###########################################################################

    # Filtering and referencing

    # Masking with the temporal coherence threshold
    df = df[(df['temporalCoherence'] >= coh_threshold)]

    # Spatial Referencing
    if set_reference:
        ref_idx = ((df['latitude'] - ref_lat)**2 + (df['longitude'] - ref_lon)**2).idxmin() # Find the index of the point closest to the reference location
        for col in displacement_df_columns:
            ref_value = df.at[ref_idx, col]
            df.loc[:, col] = df[col] - ref_value

    # Temporal Referencing (always set first date point to zero deformation)
    date_cols = [col for col in df.columns if col.startswith('D')]
    first_date_col = date_cols[0]
    df.loc[:,date_cols] = df[date_cols].subtract(df[first_date_col], axis=0)


    ###########################################################################

    # Add velocities, displacements and IDs

    # Convert dates to datetime
    dates = [datetime.strptime(col[1:], '%Y%m%d') for col in date_cols]  # strip 'D' for parsing


    # --- 1. Velocity from average of first & last 3 dates ---
    first_3_cols = date_cols[:3]
    last_3_cols = date_cols[-3:]

    first_avg_disp = df[first_3_cols].mean(axis=1)
    last_avg_disp = df[last_3_cols].mean(axis=1)

    time_delta_years = (dates[-1] - dates[0]).days / 365.25

    df.loc[:, 'velocity'] = (last_avg_disp - first_avg_disp) / time_delta_years
    df.loc[:, 'displacement'] = (last_avg_disp - first_avg_disp)

    del first_3_cols, last_3_cols, first_avg_disp, last_avg_disp
    gc.collect()

    # --- 2. Velocity from linear regression ---
    X = np.array([(d - dates[0]).days / 365.25 for d in dates]).reshape(-1, 1)
    velocity_linear_list = []
    r2_list = []
    for _, row in df.iterrows():
        y = row[date_cols].values  # displacement series
        model = LinearRegression()
        model.fit(X, y)
        velocity_linear_list.append(model.coef_[0]) # *1000)  # slope -> mm/year
        r2_list.append(model.score(X, y))
    df.loc[:, 'velocity_linear'] = velocity_linear_list
    df.loc[:, 'velocity_linear_r2'] = r2_list

    del r2_list, velocity_linear_list
    gc.collect()

    # move velocities before the date columns
    cols = list(df.columns)
    cols.remove('velocity_linear_r2')
    cols.remove('velocity_linear')
    cols.remove('velocity')
    cols.remove('displacement')
    insert_pos = cols.index(first_date_col)
    cols = cols[:insert_pos] + ['velocity_linear_r2'] + cols[insert_pos:]
    cols = cols[:insert_pos] + ['velocity_linear'] + cols[insert_pos:]
    cols = cols[:insert_pos] + ['velocity'] + cols[insert_pos:]
    cols = cols[:insert_pos] + ['displacement'] + cols[insert_pos:]
    df = df[cols]

    # Create the pointID column (starting at 1)
    df.insert(0, 'pointID', range(1, len(df) + 1))


    ###########################################################################

    # Prep Gridded and filtered dataset for geopackage export
    if save_gpkg:
        geometry = [Point(xy) for xy in zip(df['longitude'], df['latitude'])] # Create geometry column from longitude & latitude
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs='EPSG:4326') # Convert to GeoDataFrame
        gdf.to_file(output_gpk_LOS, driver="GPKG")
        del geometry, gdf
        gc.collect()


    ###########################################################################

    # Prep Gridded and filtered dataset for coherence geotiff export

    # Extract relevant data
    lats = df['latitude'].values
    lons = df['longitude'].values
    vals = df['temporalCoherence'].values

    # Determine grid extents
    min_lon, max_lon = np.min(lons), np.max(lons)
    min_lat, max_lat = np.min(lats), np.max(lats)

    # Determine grid size
    ncols = int(round((max_lon - min_lon) / grid_res_deg)) + 1
    nrows = int(round((max_lat - min_lat) / grid_res_deg)) + 1

    # Create empty arrays with NaNs
    grid = np.full((nrows, ncols), np.nan, dtype=np.float32)

    # Map each value to the grid cell
    col_idx = ((lons - min_lon) / grid_res_deg).round().astype(int)
    row_idx = ((max_lat - lats) / grid_res_deg).round().astype(int)
    grid[row_idx, col_idx] = vals

    del col_idx, row_idx, lats, lons, vals
    gc.collect()

    # Create transforms — shifted by half a pixel so coords are pixel centers
    transform_filtered = from_origin(
        min_lon - grid_res_deg / 2,
        max_lat + grid_res_deg / 2,
        grid_res_deg,
        grid_res_deg
    )

    # save filtered coherence
    if save_coherence:
        with rasterio.open(output_tempCoh_filtered,'w', driver='GTiff', height=nrows, width=ncols,
            count=1, dtype=np.float32, crs='EPSG:4326', transform=transform_filtered, nodata=np.nan
        ) as dst:
            dst.write(grid, 1)
        del dst
        gc.collect()


    ###########################################################################

    # Prep bperp for csv export

    # Identify original date columns from bperp reference (before filtering)
    all_date_cols = [col for col in df_columns_original if re.fullmatch(r'D\d{8}', col)]

    # Identify current date columns after filtering
    remaining_date_cols = [col for col in df.columns if re.fullmatch(r'D\d{8}', col)]

    # Find index range of remaining columns in original list
    start_idx = all_date_cols.index(remaining_date_cols[0])
    end_idx = all_date_cols.index(remaining_date_cols[-1]) + 1  # +1 for inclusive slicing

    # Slice bperp accordingly
    bperp_values_clipped = bperp[start_idx:end_idx].tolist()

    # Count non-date columns for header alignment
    non_date_cols = sum([not re.fullmatch(r'D\d{8}', col) for col in df.columns])

    # Build header row
    header_row = ['bperp'] + [''] * (non_date_cols - 1) + bperp_values_clipped

    # Combine into DataFrame
    df_bperp = pd.DataFrame([header_row], columns=df.columns)
    df_bperp = pd.concat([df_bperp, df], ignore_index=True)


    # Export CSVs
    if save_csv:
        df_bperp.to_csv(output_csv_LOS, index=False)

    del df_bperp
    gc.collect()