#!/usr/bin/env python3
"""Plot KMZ/KML polygon outlines on a lat/lon map."""

from __future__ import annotations

import argparse
import glob
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

try:
    from mintpy.utils.web_basemap import BASEMAP_CHOICES
except ImportError:
    BASEMAP_CHOICES = (
        "cartodb_dark",
        "cartodb_light",
        "esri_gray",
        "esri_satellite",
        "mapbox",
        "osm",
        "osm_gray",
    )

DESCRIPTION = """\
Plot KMZ/KML polygon outlines in latitude/longitude.
Same map subset and web basemap flags as view.py; outlines only.
"""

EXAMPLE = """Examples:
display_polygon.py Runways*kmz --sub-lat 25.7999 25.8042 --sub-lon -80.3025 -80.296 --add-basemap
display_polygon.py aoi.kml --color yellow --linewidth 1.5
display_polygon.py Runways*kmz --sub-lat 25.7999 25.8042 --sub-lon -80.3025 -80.296 --add-basemap --nodisplay -o runways.png
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EXAMPLE,
    )
    parser.add_argument("kmz", nargs="+", metavar="KMZ", help="KMZ/KML polygon files (shell globs OK)")
    parser.add_argument("--sub-lat", dest="subset_lat", type=float, nargs=2, metavar=("LATMIN", "LATMAX"), help="latitude range to display")
    parser.add_argument("--sub-lon", dest="subset_lon", type=float, nargs=2, metavar=("LONMIN", "LONMAX"), help="longitude range to display")
    parser.add_argument(
        "--add-basemap", dest="basemap", nargs="?", const="esri_satellite", default=None,
        choices=BASEMAP_CHOICES, metavar="PROVIDER",
        help="web tile basemap (default: esri_satellite; choices: %(choices)s)",
    )
    parser.add_argument(
        "--basemap-alpha", dest="basemap_alpha", type=float, default=1.0, metavar="ALPHA",
        help="basemap opacity between 0 and 1 (default: %(default)g)",
    )
    parser.add_argument("--color", default="yellow", help="outline color (default: %(default)s)")
    parser.add_argument("--linewidth", type=float, default=1.5, metavar="NUM", help="outline width in points (default: %(default)s)")
    parser.add_argument("-o", "--outfile", default=None, help="save the figure to this file")
    parser.add_argument("--save", dest="save_fig", action="store_true", help="save the figure")
    parser.add_argument("--nodisplay", dest="disp_fig", action="store_false", help="save and do not display the figure")
    return parser


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_coordinate_text(text: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for token in text.strip().split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        points.append((float(parts[0]), float(parts[1])))
    return points


def _rings_from_kml_root(root: ET.Element) -> list[list[tuple[float, float]]]:
    """Lon/lat rings from KML Polygon and LineString coordinates."""
    rings: list[list[tuple[float, float]]] = []
    for element in root.iter():
        kind = _local_tag(element.tag)
        if kind == "Polygon":
            for sub in element.iter():
                if _local_tag(sub.tag) == "coordinates" and sub.text:
                    ring = _parse_coordinate_text(sub.text)
                    if len(ring) >= 3:
                        rings.append(ring)
        elif kind == "LineString":
            for sub in element:
                if _local_tag(sub.tag) == "coordinates" and sub.text:
                    ring = _parse_coordinate_text(sub.text)
                    if len(ring) >= 2:
                        rings.append(ring)
    return rings


def _rings_from_path(path: Path) -> list[list[tuple[float, float]]]:
    suffix = path.suffix.lower()
    if suffix == ".kmz":
        with zipfile.ZipFile(path) as archive:
            kml_names = [name for name in archive.namelist() if name.lower().endswith(".kml")]
            if not kml_names:
                raise ValueError(f"no KML member in KMZ: {path}")
            root = ET.fromstring(archive.read(kml_names[0]))
        return _rings_from_kml_root(root)
    if suffix == ".kml":
        return _rings_from_kml_root(ET.parse(path).getroot())
    raise ValueError(f"expected .kmz or .kml, got: {path}")


def expand_kmz_arguments(raw_paths: list[str]) -> list[Path]:
    expanded: list[Path] = []
    for raw in raw_paths:
        if any(ch in raw for ch in "*?[]"):
            matches = sorted(glob.glob(raw))
            if not matches:
                raise FileNotFoundError(f"no files match KMZ glob: {raw}")
            expanded.extend(Path(p).resolve() for p in matches)
        else:
            path = Path(raw).expanduser().resolve()
            if not path.is_file():
                raise FileNotFoundError(f"KMZ/KML not found: {path}")
            expanded.append(path)
    return expanded


def _sorted_pair(values: list[float] | None, name: str, lo: float, hi: float) -> tuple[float, float] | None:
    if values is None:
        return None
    a, b = sorted(values)
    if a < lo or b > hi:
        raise ValueError(f"{name} must be within {lo} to {hi}")
    return a, b


def _data_bounds(rings: list[list[tuple[float, float]]]) -> tuple[float, float, float, float]:
    lons = [lon for ring in rings for lon, _lat in ring]
    lats = [lat for ring in rings for _lon, lat in ring]
    lon0, lon1 = min(lons), max(lons)
    lat0, lat1 = min(lats), max(lats)
    lon_pad = max(0.001, 0.05 * (lon1 - lon0))
    lat_pad = max(0.001, 0.05 * (lat1 - lat0))
    return lon0 - lon_pad, lon1 + lon_pad, lat0 - lat_pad, lat1 + lat_pad


def _map_extent(rings, subset_lat, subset_lon) -> tuple[float, float, float, float]:
    """Return west, east, south, north."""
    west, east, south, north = _data_bounds(rings)
    if subset_lon is not None:
        west, east = subset_lon
    if subset_lat is not None:
        south, north = subset_lat
    if east <= west or north <= south:
        raise ValueError("map extent is empty; check --sub-lat and --sub-lon")
    return west, east, south, north


def _degree_format(span: float) -> str:
    """Decimal places so a small lat/lon window is not shown as an offset."""
    span = abs(span)
    if span < 0.01:
        return "%.4f"
    if span < 0.1:
        return "%.3f"
    if span < 1:
        return "%.2f"
    return "%.1f"


def _figsize(west: float, east: float, south: float, north: float) -> tuple[float, float]:
    width = 8.0
    lon_span = max(east - west, 1e-9)
    lat_span = max(north - south, 1e-9)
    height = min(max(width * lat_span / lon_span, 3.0), 11.0)
    return width, height


def _default_outfile(paths: list[Path]) -> Path:
    if len(paths) == 1:
        return Path(f"{paths[0].stem}.png")
    return Path("polygons.png")


def plot_polygons(args) -> None:
    paths = expand_kmz_arguments(args.kmz)
    file_rings: list[tuple[Path, list[list[tuple[float, float]]]]] = []
    for path in paths:
        rings = _rings_from_path(path)
        if not rings:
            print(f"WARNING: no polygons in {path.name}", file=sys.stderr)
            continue
        print(f"plotting shapes from {path.name} ({len(rings)} rings)")
        file_rings.append((path, rings))
    if not file_rings:
        raise ValueError("no polygons found in KMZ/KML inputs")

    rings = [ring for _path, group in file_rings for ring in group]
    west, east, south, north = _map_extent(rings, args.subset_lat, args.subset_lon)

    if not args.disp_fig:
        import matplotlib
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FormatStrFormatter

    fig, ax = plt.subplots(figsize=_figsize(west, east, south, north))
    if args.basemap:
        from mintpy.utils.web_basemap import add_web_basemap

        add_web_basemap(
            ax,
            xlim=(west, east),
            ylim=(south, north),
            provider_key=args.basemap,
            alpha=args.basemap_alpha,
            print_msg=True,
        )

    for _path, group in file_rings:
        for ring in group:
            lons, lats = zip(*ring)
            ax.plot(lons, lats, color="k", linewidth=args.linewidth + 1.0, zorder=2, solid_capstyle="round")
            ax.plot(lons, lats, color=args.color, linewidth=args.linewidth, zorder=3, solid_capstyle="round")

    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    ax.set_aspect("equal", adjustable="box")
    ax.xaxis.set_major_formatter(FormatStrFormatter(_degree_format(east - west)))
    ax.yaxis.set_major_formatter(FormatStrFormatter(_degree_format(north - south)))
    ax.tick_params(which="both", direction="in", top=True, right=True)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    if len(file_rings) == 1:
        ax.set_title(file_rings[0][0].name)
    else:
        ax.set_title(f"{len(file_rings)} polygon files")
    fig.tight_layout()

    if args.save_fig:
        outfile = Path(args.outfile) if args.outfile else _default_outfile(paths)
        fig.savefig(outfile, dpi=300, bbox_inches="tight")
        print(f"save figure to {outfile.resolve()}")

    if args.disp_fig:
        plt.show()
    else:
        plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    if args.outfile or not args.disp_fig:
        args.save_fig = True
    if args.basemap is not None and (args.basemap_alpha < 0 or args.basemap_alpha > 1):
        parser.error("--basemap-alpha must be between 0 and 1.")
    if args.linewidth <= 0:
        parser.error("--linewidth must be positive.")
    try:
        args.subset_lat = _sorted_pair(args.subset_lat, "--sub-lat", -90.0, 90.0)
        args.subset_lon = _sorted_pair(args.subset_lon, "--sub-lon", -360.0, 360.0)
    except ValueError as exc:
        parser.error(str(exc))
    if args.basemap == "mapbox":
        from mintpy.utils.web_basemap import mapbox_access_token, warn_mapbox_token_missing

        if not mapbox_access_token():
            warn_mapbox_token_missing(print_msg=True)
    try:
        plot_polygons(args)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
