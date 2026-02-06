# Insarmaps HTML Templates

This directory contains HTML templates for displaying insarmaps data in various layouts.

## Templates

- **overlay.html** - Overlay view with dropdown selector (supports any number of frames)
- **matrix.html** - Matrix view with 2-column (2 frames) or 2x2 grid (4 frames) layout; all frames sync via reload whenever any currentMapParams change (lat/lon/zoom/scale/contour/colorscale/background/opacity/etc.)
- **row.html** - Alias for matrix.html (for backward compatibility)

These templates read `insarmaps.log` and `download_commands.txt` when the page loads. 

## Usage

The templates are automatically copied to your working directory when you run:

```bash
create_insarmaps_framepages.py insarmaps.log --outdir <output_directory>
```

Or as part of the `horzvert_timeseries.bash` workflow.

## File Format

The templates expect `insarmaps.log` to contain one URL per line:

```
http://insarmaps.miami.edu/start/-0.81/-91.19/12?startDataset=FernandinaSenDT128
http://insarmaps.miami.edu/start/-0.81/-91.19/12?startDataset=FernandinaSenAT106
http://insarmaps.miami.edu/start/-0.81/-91.19/12?startDataset=FernandinaSenDT128_vert
http://insarmaps.miami.edu/start/-0.81/-91.19/12?startDataset=FernandinaSenDT128_horz
```

URLs are automatically sorted by dataset type: desc, asc, horz, vert.

## Template consistency

All templates (overlay, matrix) share:
- `USE_FULL_DATASET_IN_URL = true` by default
- `flyToDatasetCenter=false` in iframe URLs for embedding
- Loading hidden on first `insarmaps-url-update` postMessage, or after 15 s

See `ARCHITECTURE.md` for overlay behavior (postMessage sync, Time Controls, wait/cooldown) and matrix sync (§ 8).
