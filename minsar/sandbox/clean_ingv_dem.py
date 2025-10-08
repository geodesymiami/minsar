#!/usr/bin/env python3

import sys
import numpy as np
import rasterio

if len(sys.argv) != 3:
    print("Usage: python clean_ingv_dem.py <input_file> <output_file>")
    sys.exit(1)

input_file = sys.argv[1]
output_file = sys.argv[2]

# Open input DEM
with rasterio.open(input_file) as src:
    profile = src.profile.copy()
    data = src.read(1)

    # Detect NoData value
    nodata = src.nodata
    if nodata is None:
        print("⚠️  Warning: NoData value not set in original file. Assuming -9999.")
        nodata = -9999

    # Replace NoData with 0
    data_clean = np.where(data == nodata, 0, data)

    # Update profile
    profile.update({
        "dtype": "int16",
        "nodata": None
    })

    # Write to output
    with rasterio.open(output_file, "w", **profile) as dst:
        dst.write(data_clean.astype(np.int16), 1)


