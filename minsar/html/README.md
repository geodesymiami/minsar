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

`insarmaps.log` supports two line types (processed in file order):

1. **Full URL** — `http://` or `https://` with `startDataset=` in the query. The first such line is the template for map options (lat/lon/zoom, scales, dates, etc.).
2. **Dataset name only** — a line with no `startDataset=` and not a full URL is treated as a `startDataset` value; overlay expands it using the first URL line.

Full URL per line (legacy):

```
http://insarmaps.miami.edu/start/-0.81/-91.19/12?startDataset=FernandinaSenDT128
http://insarmaps.miami.edu/start/-0.81/-91.19/12?startDataset=FernandinaSenAT106
```

Mixed format (first line full URL, rest dataset names):

```
http://149.165.153.50/start/0.8251/-77.8998/12.4513?flyToDatasetCenter=false&startDataset=S1_desc_142_mintpy_...&pointLat=0.71389&pointLon=-77.88148&minScale=-6&maxScale=6&startDate=20150507&endDate=20260304&colorscale=velocity&pixelSize=7.5&contours=true
S1_asc_120_mintpy_20141013_XXXXXXXX_N0161W07905_N0161W07724_N0021W07724_N0021W07905
S1_vert_120_142_mintpy_20141013_XXXXXXXX_N0099W07826_N0099W07768_N0051W07768_N0051W07826
S1_horz_120_142_mintpy_20141013_XXXXXXXX_N0099W07826_N0099W07768_N0051W07768_N0051W07826
```

Iframe list URLs are automatically sorted by dataset type: desc, asc, horz, vert.

## Architecture and debugging

See **`ARCHITECTURE.md`** in this directory for:

- How dataset switching, custom reference points, and narrowed time periods work
- postMessage vs URL-reload sync (cross-origin constraints)
- **§19 — Reference point waiting:** user status messages, watchdogs, `insarmaps-ref-failed`, what remains broken
- Bug history and checklist for recreating overlay.html
- Switch-result table format for debugging Desc/Asc/Horz/Vert transfers

**Known limitation (2026-02-13):** In Time Controls mode, changing the reference point in the visible period iframe does not re-reference other period iframes’ data. Documented in `ARCHITECTURE.md` §13.

