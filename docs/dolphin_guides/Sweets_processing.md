# Process data using [Sweets](https://github.com/isce-framework/sweets) workflow
## Create the usual minsar template
```bash
cd $TE
create_template.py  18.96:19.08,-98.71:-98.55 Popocatepetl --start-date 20240801 --end-date 20241231 --flight-dir desc
```

## Download the SLCs
```bash
minsarApp.bash $TE/PopocatepetlSenD143.template --dostep download
```

## Create Sweets config file

```bash
cd $SCRATCHDIR/PopocatepetlSenD143
create_sweet.py $TE/PopocatepetlSenD143.template
```

## Run job file
```bash
sbatch run_sweets.job 
```
