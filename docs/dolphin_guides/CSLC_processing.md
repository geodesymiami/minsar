# Guide for downloading and processing CSLC using [Dolphin](https://github.com/isce-framework/dolphin)
## Download CSLC
> [!WARNING]
> CSLC download currently works only for **North America**.

You can use [asf_search module](https://github.com/geodesymiami/minsar/blob/main/minsar/src/minsar/cli/asf_search_args.py) to downlaod **CSLC**.
MinsarApp bash generates a similar command for that:
```bash
cat download_slc.sh
#!/usr/bin/env bash
asf_download.sh --processingLevel=CSLC --relativeOrbit=143 --platform=SENTINEL-1 --intersectsWith='Polygon((-98.71 18.96, -98.55 18.96, -98.55 19.08, -98.71 19.08, -98.71 18.96))' --start=2014-10-01 --end=2026-05-09 --parallel=6 --dir=SLC --download
check_download.py $PWD/CSLC --delete
asf_download.sh --processingLevel=CSLC --relativeOrbit=143 --platform=SENTINEL-1 --intersectsWith='Polygon((-98.71 18.96, -98.55 18.96, -98.55 19.08, -98.71 19.08, -98.71 18.96))' --start=2014-10-01 --end=2026-05-09 --parallel=6 --dir=CSLC --download
```

```bash
mkdir PopocatepetlSenD143
cd PopocatepetlSenD143
asf_download.sh --processingLevel=CSLC --relativeOrbit=143 --platform=SENTINEL-1 --intersectsWith='Polygon((-98.71 18.96, -98.55 18.96, -98.55 19.08, -98.71 19.08, -98.71 18.96))' --start=2014-10-01 --end=2026-05-09 --parallel=6 --dir=CSLC --download
```

## Process with Doplhin
First we need to generate the config file, Easy!
Get into the working directory and switch to Dolphin
```bash
conda activate dolphin-env
dolphin config --slc-files CSLC/*.h5  --subdataset "/data/VV" --output-options.bounds -90.6679 14.3203 -90.5455 14.4157
```
If you want to optimize the processing speed, add this option to the command line
```bash
--worker-settings.threads-per-worker 1 --worker-settings.block-shape 1024 1024 --n-parallel-bursts 6 --unwrap-options.n-parallel-jobs 8 --unwrap-options.snaphu-options.n-parallel-tiles 4 --timeseries-options.num-parallel-blocks 8 --timeseries-options.block-shape 512 512 --phase-linking.ministack-size 15 --phase-linking.shp-method GLRT --outfile dolphin_config.yaml
```

A new config file will be created `dolphin_config.yaml`

## Run Dolphin
Let's run using:
```bash
dolphin run dolphin_config.yaml
```

### On Stampede
You can write the **Slurm** job
```bash
#!/bin/bash
#SBATCH -J dolphin_job
#SBATCH -o dolphin_%j.out
#SBATCH -e dolphin_%j.err
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 40
#SBATCH -t 08:00:00
#SBATCH -p pvc

source ~/.bashrc
export CUDA_VISIBLE_DEVICES=""
export ISCE3_FORCE_CPU=1
export OMP_NUM_THREADS=1
export CUDA_VISIBLE_DEVICES=""
export NVIDIA_VISIBLE_DEVICES="none"
export ISCE3_USE_GPU=0

conda activate dolphin-env

# Run sweets
dolphin run ${PWD}/dolphin_config.yaml
```
