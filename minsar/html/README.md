# Insarmaps HTML Templates

This directory contains HTML templates for displaying insarmaps data in various layouts.

## Templates

- **overlay.html** - Overlay view with dropdown selector (supports any number of frames)
- **matrix.html** - Matrix view with 2-column (2 frames) or 2x2 grid (4 frames) layout
- **column.html** - Column view with vertical stacking (2 or 4 frames)

These templates read `insarmaps.log` and `download_commands.txt` when the page loads. 

## Usage

The templates are copied to the mintpy/miaplpy directory by `horzvert_timeseries.bash` (from this directory). For standalone use:

```bash
create_insarmaps_framepages.py insarmaps.log --outdir <output_directory>
```

## File Format

The templates expect `insarmaps.log` to contain one URL per line:

```
http://insarmaps.miami.edu/start/-0.81/-91.19/12?startDataset=FernandinaSenDT128
http://insarmaps.miami.edu/start/-0.81/-91.19/12?startDataset=FernandinaSenAT106
http://insarmaps.miami.edu/start/-0.81/-91.19/12?startDataset=FernandinaSenDT128_vert
http://insarmaps.miami.edu/start/-0.81/-91.19/12?startDataset=FernandinaSenDT128_horz
```

URLs are automatically sorted by dataset type: desc, asc, horz, vert.

