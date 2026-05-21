#!/usr/bin/env python3

from glob import glob
from pathlib import Path
import os
import re
from mintpy.cli import load_data, save_hdfeos5, temporal_average, generate_mask, smallbaselineApp
from mintpy.utils import ptime
from mintpy.objects import timeseries
import rasterio
import numpy as np
import subprocess

# TODO FOR DEBUG
if False:
    project_dir = Path(os.path.join(os.getenv("SCRATCH"), "PopocatepetlSenD143"))
    os.chdir(project_dir)

    if True:
        lists = ['unwrapped/*.unw', 'unwrapped/*.unw.rsc', 'unwrapped/*.unw.xml', 'unwrapped/*.unw.aux.xml', 'reference/data.rsc', 'timeseries.h5', 'mintpy/inputs/smallbaselineApp.cfg', 'mintpy/inputs/*.h5']
        print("!!! WARNING: Deleting existing files matching patterns: " + ", ".join(lists) + " !!!")
        for l in lists:
            for f in glob(l):
                os.remove(f)
else:
    project_dir = Path.cwd()


def merge_rsc_metadata(rsc_pattern="unwrapped/*.unw.rsc"):
    """Merge multiple .rsc files into a single metadata dictionary.
    If keys repeat, keep only the first value encountered."""

    merged = {}
    rsc_files = sorted(glob(rsc_pattern))

    for rsc_file in rsc_files:
        with open(rsc_file, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    key = parts[0]
                    value = ' '.join(parts[1:])

                    # Only store if key doesn't exist yet (first occurrence wins)
                    if key not in merged:
                        merged[key] = value

    return merged


def isce_data_type(dtype):
    # MintPy expects ISCE-style names
    return {
        "uint8": "BYTE",
        "int16": "SHORT",
        "int32": "INT",
        "float32": "FLOAT",
        "float64": "DOUBLE",
    }[dtype]


def collect_data(timeseries_path):
    deformation_data = []
    for f in os.listdir(str(timeseries_path)):
        path = timeseries_path / f

        if path.suffix.lower() not in {".tif", ".tiff"}:
            continue

        stem = path.stem
        if not re.fullmatch(r"\d{8}_\d{8}", stem):
            continue

        reference, secondary = stem.split("_", 1)
        with rasterio.open(path) as src:
            data = src.read(1)
            shape = data.shape
            crs = src.crs.to_string() if src.crs else None
            bbox = src.bounds
            transform = src.transform
            deformation_data.append({"reference": reference, "secondary": secondary, "data": data})

    metadata=dict(crs=crs,transform=transform,bbox=bbox, LENGTH=shape[0], WIDTH=shape[1])
    deformation_data.append({'reference': reference, 'secondary': reference, 'data': np.zeros(shape)})
    deformation_data = sorted(deformation_data, key=lambda x: x['secondary'])

    return deformation_data, metadata


timeseries_path = project_dir / 'timeseries'
mintpy_dir = project_dir / 'mintpy'
inputs = mintpy_dir / 'inputs'
unwrapped = project_dir / 'unwrapped'
baselines = project_dir / 'baselines'

template_file = inputs / "smallbaselineApp.cfg"

# Create mintpy folder if missing
os.makedirs(inputs, exist_ok=True)
os.chdir(mintpy_dir)
# Create smallbaselineApp.cfg
if not template_file.exists():
    smallbaselineApp.main(['-g'])


template_updates = {
"mintpy.load.processor": "isce",
"mintpy.load.autoPath": "yes",
"mintpy.load.unwFile": "../unwrapped/*.unw",
"mintpy.load.connCompFile": "../unwrapped/*.unw.conncomp.tif",
"mintpy.load.corFile": "None",
}

text = template_file.read_text()
for key, value in template_updates.items():
    pattern = rf"^{re.escape(key)}\s*=.*$"
    replacement = f"{key:<27} = {value}"
    text = re.sub(pattern, replacement, text, count=1, flags=re.MULTILINE)

template_file.write_text(text)


os.chdir(os.path.join(project_dir, 'mintpy'))
print(f"Changed directory to {os.path.join(project_dir, 'mintpy')}\n")

# Generate ISCE-style .unw and .unw.xml files for each unwrapped TIFF file
print("=" * 60)
print("Generating ISCE .unw/.unw.xml files from unwrapped TIFFs...\n")

for tif in unwrapped.glob("*.unw.tif"):
    unw = tif.with_suffix("").with_suffix(".unw")
    xml = unw.with_suffix(".unw.xml")

    # Get expected file size from TIFF
    with rasterio.open(tif) as ds:
        length, width = ds.height, ds.width
        dtype = isce_data_type(ds.dtypes[0])

    expected_size = length * width * 4  # 4 bytes for float32

    # Regenerate .unw if missing or truncated/corrupted
    if not unw.exists() or os.path.getsize(unw) != expected_size:
        print(f"\nProcessing {tif.name} -> {unw.name}")
        subprocess.run(
            ["gdal_translate", "-of", "ENVI", "-ot", "Float32", str(tif), str(unw)],
            check=True,
        )

if True:
    load_data.main(['-t', str(template_file), '--project', str(inputs)])


ifgramstack = inputs /'ifgramStack.h5'

metadata1 = merge_rsc_metadata("../unwrapped/*.unw.rsc")

deformation_data, metadata2 = collect_data(timeseries_path)
data = np.stack([d['data'] for d in deformation_data])
date_list = [d['secondary'] for d in deformation_data]
ts_file = project_dir / 'timeseries.h5'
metadata = {**metadata2, **metadata1}
metadata['PROJECT_NAME'] = project_dir.name

bperp = {}
for baseline in glob(str(baselines / '*' / '*.txt')):
    secondary = os.path.basename(baseline).replace('.txt', '').split('_')[-1]
    with open(baseline, 'r', encoding='utf-8') as f:
        bp = []
        for line in f:
            if line.lower().startswith('bperp'):
                bp.append(float(re.findall(r"[-+]?\d*\.\d+|\d+", line)[0]))
        bperp[secondary] = np.average(bp)
bperp_sorted = [avg for secondary, avg in sorted(bperp.items(), key=lambda x: x[0])]


if not ts_file.exists():
    ts = timeseries()
    ts = ts.write2hdf5(data=data, outFile=ts_file, dates=date_list, bperp=bperp_sorted, metadata=metadata, refFile=None, compression=None)

geom_file = glob(str(inputs / '*geometry*.h5'))[0]
temporal_coherence = glob(str(project_dir / 'phase_linking' / 'linked_phase' / '*temporal*coherence*average*'))[0]

avg_spatial_coh = project_dir / "avgSpatialCoh.h5"

if not avg_spatial_coh.exists():
    try:
        temporal_average.main([str(ifgramstack), "-d", "coherence", "-o", str(project_dir / "avgSpatialCoh.h5")])
    except Exception as e:
        print(f"Error during temporal averaging: {e}")
        avg_spatial_coh = temporal_coherence

mask = glob(str(project_dir / '*mask*'))[0] if glob(str(project_dir / '*mask*')) else None 
if not mask or not Path(mask).exists():
    mask = project_dir / "maskTempCoh.h5"
    generate_mask.main([temporal_coherence, "-m", '0.7', '-o', str(mask)])

args = [str(ts_file), "-g", str(geom_file), '-t', str(template_file), '--tc', str(temporal_coherence), '--asc', str(avg_spatial_coh), '-m', str(mask), '--subset']
save_hdfeos5.main(args)