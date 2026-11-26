# Getting started with MinSAR

MinSAR takes an area and a satellite track and produces displacement time series: it downloads the SAR data and a DEM, forms interferograms with ISCE, and runs MintPy and/or MiaplPy. Everything is started with one command, `minsarApp.bash`.

This guide covers the first run, the two ways of telling MinSAR what to process, and how to set and keep processing options.

## 1. Set up

Install MinSAR as described in [installation.md](installation.md). In every new shell, load the environment:

```bash
source $MINSAR_HOME/setup/environment.bash
```

`$MINSAR_HOME` is the directory you cloned the repository into. Personal settings (queue, allocation, email) go in `~/.minsar/user_env.bash`, which `environment.bash` reads.

Four directories matter from the start:

| Variable | What it is |
|---|---|
| `$SCRATCHDIR` | Where processing happens. Each dataset gets its own directory, for example `$SCRATCHDIR/GalapagosSenD128`. |
| `$SAMPLESDIR` | Example templates that come with the code (`$MINSAR_HOME/samples`). |
| `$TE` | Your own template files, written and maintained by hand. |
| `$ATE` | Template files that MinSAR writes for you when you give it an AOI. Do not edit these. |

## 2. First run

A small Sentinel-1 test dataset over the Galapagos:

```bash
minsarApp.bash $SAMPLESDIR/unittestGalapagosSenD128.template
```

This creates `$SCRATCHDIR/unittestGalapagosSenD128`, submits the jobs and waits for them. The command you ran and every command it runs are appended to the file `log` in that directory.

The processing steps, in order:

| Step | What it does |
|---|---|
| `download` | download the SAR data |
| `dem` | download the DEM |
| `jobfiles` | write the run files and job files |
| `ifgram` | interferogram processing with ISCE |
| `mintpy` | small-baseline time series (MintPy) |
| `miaplpy` | persistent and distributed scatterer time series (MiaplPy) |

To restart from a step, or run one step only:

```bash
minsarApp.bash $SAMPLESDIR/unittestGalapagosSenD128.template --start ifgram
minsarApp.bash $SAMPLESDIR/unittestGalapagosSenD128.template --dostep dem
minsarApp.bash $SAMPLESDIR/unittestGalapagosSenD128.template --start miaplpy --no-mintpy
```

`minsarApp.bash --help` lists all options.

## 3. Two ways to say what to process

### A template file in `$TE`

A template is a text file of `key = value` lines. Its name is the dataset name: `GalapagosSenD128.template` is the Galapagos, Sentinel-1, descending track 128.

```bash
minsarApp.bash $TE/GalapagosSenD128.template
```

You write this file, usually by copying one from `$SAMPLESDIR`. MinSAR reads exactly that file and never regenerates it.

### An AOI and a name

Give the area as `south:north,west:east` and a project name. MinSAR finds the tracks that cover it, writes the template into `$ATE`, and runs it:

```bash
minsarApp.bash -0.86:-0.81,-91.19:-91.13 Galapagos --flight-dir desc
```

This writes `$ATE/GalapagosSenD128.template` from the default template `$MINSAR_HOME/minsar/defaults/processing_Sentinel1.template` (`processing_Alos2.template` with `--platform ALOS2`), adds your custom options (section 5), and starts processing in `$SCRATCHDIR/GalapagosSenD128`.

The file in `$ATE` is rewritten on every AOI run. Changes you make to it by hand are lost.

### Which one to use

| | Template in `$TE` | AOI, template in `$ATE` |
|---|---|---|
| Who writes the template | you | MinSAR |
| Rewritten on each run | no | yes, on each AOI run |
| Custom options file applied | no | yes |
| Good for | a dataset with a hand-tuned set of options that should not change | a new area, and anything you want to rerun with the current defaults |

## 4. Changing options for a dataset

Options are template keys of six families: `mintpy.*`, `miaplpy.*`, `minsar.*`, `topsStack.*`, `stripmapStack.*`, `alos2Stack.*`. The data search has its own keys: `asf.*` for Sentinel-1, ALOS-2 and NISAR, and `ssaraopt.*` for TerraSAR-X and COSMO-SkyMed.

You do not need to copy a template from `$ATE` to `$TE` to change an option. There are two ways that keep the AOI workflow:

- **On the command line**, to try a value.
- **In the custom options file**, to keep it (section 5).

Copy a template to `$TE` only if you want to freeze it and maintain it by hand from then on. A template in `$TE` never receives options from the custom options file.

### Options on the command line

Any key of the six families can be given as `--key value`. It works with a template and with an AOI:

```bash
minsarApp.bash $TE/GalapagosSenD128.template --mintpy.troposphericDelay.method no --topsStack.coregistration geometry
minsarApp.bash -0.86:-0.81,-91.19:-91.13 Galapagos --flight-dir desc --miaplpy.interferograms.networkType delaunay
```

The value is written into the template file before processing starts. Key names are checked, so a misspelled key stops the run with the closest valid name. An option on the command line wins over the same key in the custom options file.

For common options there are shortcuts:

| Shortcut | Template key it sets |
|---|---|
| `--start-date`, `--end-date` | the dates of the stage where processing starts (table below) |
| `--exclude-dates 20240619,20240701` | `minsar.excludeDates` |
| `--range-looks`, `--azimuth-looks` | `topsStack.rangeLooks`, `topsStack.azimuthLooks` (`alos2Stack.*` for ALOS-2) |
| `--coregistration geometry` (AOI only) | `topsStack.coregistration` |
| `--tropo no` (AOI only) | `mintpy.troposphericDelay.method` |
| `--insarmaps-dataset DS` (AOI only) | `minsar.insarmaps_dataset` |
| `--mintpy-plot`, `--mintpy-no-plot` (AOI only) | `mintpy.plot` |
| `--period`, `--quick-run`, `--last-year`, `--exclude-season` (AOI only) | download period, see `create_template.py --help` |

`--start-date` and `--end-date` mean different things depending on where processing starts:

| Processing starts at | Dates set | Meaning |
|---|---|---|
| `download` (the default), `dem`, `jobfiles`, `ifgram` | `asf.startDate`, `asf.endDate` | which acquisitions are downloaded |
| `--start miaplpy` | `miaplpy.load.startDate`, `miaplpy.load.endDate` | which of the processed dates MiaplPy uses |
| `--start mintpy` | `mintpy.network.startDate`, `mintpy.network.endDate` | which interferograms MintPy uses |

```bash
minsarApp.bash $TE/GalapagosSenD128.template --start-date 20200101 --end-date 20221231
minsarApp.bash $TE/GalapagosSenD128.template --start miaplpy --start-date 20210101
```

More detail is in [start-date_end-date_usage.md](start-date_end-date_usage.md).

## 5. The custom options file

One text file holds your options for all datasets that are created from an AOI. The variable `$MINSAR_CUSTOM_OPTIONS` points to it. The default is `$MINSAR_HOME/minsar/defaults/sample_custom_template_options.txt`, which is part of the repository. Use your own file by adding a line to `~/.minsar/user_env.bash`:

```bash
export MINSAR_CUSTOM_OPTIONS=~/.minsar/custom_template_options.txt
```

The file has one section per dataset:

```ini
[GalapagosSenD128]
aoi = -1.03:0.15,-91.65:-90.9
topsStack.azimuthLooks = 5
topsStack.rangeLooks = 20
mintpy.reference.lalo = -0.7,-90.95
minsar.insarmaps_dataset = DS
options = --no-mintpy --miaplpy
```

- The section name is matched against the template name. `[GalapagosSenD128]` applies to that track only. `[Galapagos]` applies to every Galapagos track. If several sections match, the longest name wins.
- Template keys are written into the `$ATE` template each time it is created, replacing the defaults.
- `aoi` is the area, and `options` holds `minsarApp.bash` flags. With these two lines the dataset can be rerun by name alone: `run_minsar.bash GalapagosSenD128`
- Each key takes a single value without spaces. Key names are checked.

## 6. Keeping options you are happy with

A typical sequence for a new area:

1. Run the AOI with the defaults: `minsarApp.bash -0.86:-0.81,-91.19:-91.13 Galapagos --flight-dir desc`
2. Look at the result and try other values on the command line, restarting from the step they affect: `minsarApp.bash $ATE/GalapagosSenD128.template --start mintpy --mintpy.reference.lalo -0.7,-90.95`
3. When the options are right, save them: `save_custom_options.py $ATE/GalapagosSenD128.template`

`save_custom_options.py` compares the template to the default template and writes every key that differs into the `[GalapagosSenD128]` section of your custom options file, together with the `aoi`. A section of that name that is already there is replaced. Track number and dates are not saved, because they are set anew on each AOI run. To also store `minsarApp.bash` flags, add them after `--`:

```bash
save_custom_options.py $ATE/GalapagosSenD128.template -- --no-mintpy --miaplpy
```

You can also edit the custom options file directly; a new section is just a `[Name]` line followed by `key = value` lines.

To change a default for everybody, edit `minsar/defaults/processing_Sentinel1.template` or `minsar/defaults/processing_Alos2.template` and commit the change. New AOI runs use it; existing templates in `$TE` are not touched.

## 7. Where to read next

- [README.md](README.md): overview of the processing steps
- [start-date_end-date_usage.md](start-date_end-date_usage.md): date options in detail
- [README_burst_download.md](README_burst_download.md): Sentinel-1 burst download
- [download_data_troubleshooting.md](download_data_troubleshooting.md), [known_issues.md](known_issues.md), [memory_issues.md](memory_issues.md): when something fails
