#!/usr/bin/env python3
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer


def clamp(x, a, b):
    return max(a, min(b, x))


def vel_to_kml_color(v, vmin=-0.8, vmax=0.8):
    """
    Color legend:
    dark blue -> cyan -> green -> yellow -> red
    KML color AABBGGRR.
    """
    a = 220
    vv = float(v)
    t = (vv - vmin) / (vmax - vmin) if vmax > vmin else 0.5
    t = clamp(t, 0.0, 1.0)

    if t < 0.25:
        # dark blue -> cyan
        u = t / 0.25
        r = 0
        g = int(255 * u)
        b = int(120 * (1 - u) + 255 * u)
    elif t < 0.50:
        # cyan -> green
        u = (t - 0.25) / 0.25
        r = 0
        g = 255
        b = int(255 * (1 - u))
    elif t < 0.75:
        # green -> yellow
        u = (t - 0.50) / 0.25
        r = int(255 * u)
        g = 255
        b = 0
    else:
        # yellow -> red
        u = (t - 0.75) / 0.25
        r = 255
        g = int(255 * (1 - u))
        b = 0

    return f"{a:02x}{b:02x}{g:02x}{r:02x}"


def write_kml(
    df: pd.DataFrame,
    out_kml: str,
    name: str = "InSAR points",
    z_col: str = "z_plot",
    color_col: str = "vel_cm_yr",
    vmin: float = -0.8,
    vmax: float = 0.8,
    icon_scale: float = 0.5,
    hide_labels: bool = True,
):
    v = df[color_col].astype(float).to_numpy()
    bins = np.linspace(vmin, vmax, 21)  # 20 bins
    bin_ids = np.digitize(v, bins)
    bin_ids = np.clip(bin_ids, 1, len(bins) - 1)

    styles = {}
    for b in np.unique(bin_ids):
        vv = 0.5 * (bins[b - 1] + bins[b])
        styles[b] = vel_to_kml_color(vv, vmin=vmin, vmax=vmax)

    out_kml = str(out_kml)
    Path(out_kml).parent.mkdir(parents=True, exist_ok=True)

    with open(out_kml, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<kml xmlns="http://www.opengis.net/kml/2.2">\n')
        f.write("  <Document>\n")
        f.write(f"    <name>{name}</name>\n")

        for b, col in styles.items():
            f.write(f'    <Style id="vbin_{b}">\n')
            f.write("      <IconStyle>\n")
            f.write(f"        <color>{col}</color>\n")
            f.write(f"        <scale>{icon_scale}</scale>\n")
            f.write("        <Icon>\n")
            f.write("          <href>http://maps.google.com/mapfiles/kml/shapes/shaded_dot.png</href>\n")
            f.write("        </Icon>\n")
            f.write("      </IconStyle>\n")
            if hide_labels:
                f.write("      <LabelStyle><scale>0</scale></LabelStyle>\n")
            f.write("    </Style>\n")

        for i, row in df.iterrows():
            lon = float(row.get("X_corr", row["X"]))
            lat = float(row.get("Y_corr", row["Y"]))
            z = float(row[z_col])
            vv = float(row[color_col])
            b = int(bin_ids[df.index.get_loc(i)])

            coh = row.get("coherence", "")
            f.write("    <Placemark>\n")
            f.write(f"      <styleUrl>#vbin_{b}</styleUrl>\n")
            if hide_labels:
                f.write("      <LabelStyle><scale>0</scale></LabelStyle>\n")
            f.write("      <description><![CDATA[\n")
            f.write(f"        velocity (cm/yr): {vv}<br>\n")
            f.write(f"        coherence: {coh}<br>\n")
            f.write(f"        {z_col}: {z}\n")
            f.write("      ]]></description>\n")
            f.write("      <Point>\n")
            f.write("        <altitudeMode>absolute</altitudeMode>\n")
            f.write(f"        <coordinates>{lon},{lat},{z}</coordinates>\n")
            f.write("      </Point>\n")
            f.write("    </Placemark>\n")

        f.write("  </Document>\n</kml>\n")


def infer_orbit_from_heading(heading_deg: float) -> str:
    """Heading is direction of motion clockwise from North."""
    hd = heading_deg % 360.0
    # Northward: around 0/360 => ascending
    if hd >= 315.0 or hd <= 45.0:
        return "ascending"
    # Southward: around 180 => descending
    if 135.0 <= hd <= 225.0:
        return "descending"
    # Fallback: pick closest of the two
    return "ascending" if abs((hd - 0) % 360) < abs(hd - 180) else "descending"


def sample_median(h5ds, step=50) -> float:
    arr = h5ds[::step, ::step]
    arr = arr[np.isfinite(arr)]
    return float(np.nanmedian(arr)) if arr.size else float("nan")


def parse_args():
    p = argparse.ArgumentParser(
        description="Export InSAR CSV points to 3D KML (Google Earth) with TSX ascending/descending XY correction."
    )
    p.add_argument("--input", required=True, help="Input CSV (must have X,Y,velocity,dem,dem_error).")
    p.add_argument("--output", required=True, help="Output KML path.")
    p.add_argument("--kml-name", default="InSAR 3D points", help="KML document name.")
    p.add_argument("--vlim", type=float, default=1.5, help="Velocity limit in cm/yr; colors saturate at ±vlim.")
    p.add_argument("--icon-scale", type=float, default=0.5, help="KML icon size scale.")
    p.add_argument("--hide-labels", action="store_true", default=True, help="Hide labels / point IDs (default: on).")
    p.add_argument("--show-labels", dest="hide_labels", action="store_false", help="Show labels / point IDs.")
    p.add_argument("--flip-sign", action="store_true", help="Flip XY correction sign if points move the wrong way.")
    p.add_argument("--no-xy-corr", action="store_true", help="Disable XY correction; use original X/Y.")

    # Read from geometryRadar.h5
    p.add_argument("--geometry-h5", default=None, help="Path to inputs/geometryRadar.h5 to auto-read HEADING/ANTENNA_SIDE and auto-estimate geoid/incidence.")

    # Orbit direction selector (optional; if omitted, inferred from HEADING)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--ascending", action="store_true", help="Force ascending sign convention.")
    g.add_argument("--descending", action="store_true", help="Force descending sign convention.")

    # Manual overrides (needed if no --geometry-h5)
    p.add_argument("--heading-deg", type=float, default=None, help="Override HEADING (deg). If omitted, read from geometry-h5.")
    p.add_argument("--antenna-side", type=int, default=None, help="Override ANTENNA_SIDE. If omitted, read from geometry-h5.")
    p.add_argument("--inc-deg", type=float, default=None, help="Override incidence angle (deg). If omitted, median from geometry-h5; else 43.")
    p.add_argument("--geoid-offset", type=float, default=None, help="Override geoid offset (m). If omitted, use -median(height) from geometry-h5; else 27.")

    # XY shift scaling
    p.add_argument("--scale", type=float, default=1.0, help="Scale factor on horizontal shift (tune 0.7–1.2).")
    return p.parse_args()


def main():
    args = parse_args()

    df = pd.read_csv(Path(args.input))
    out_kml = Path(args.output)

    # Velocity units:  mm/yr -> cm/yr
    df["vel_cm_yr"] = df["velocity"] / 10.0

    # Elevation proxy:
    df["elev_insarmaps"] = df["dem_error"] - df["dem"]
    df["h_m"] = df["dem_error"].astype(float).clip(lower=0.0)

    # ---- Auto-read from geometryRadar.h5 if provided ----
    heading_deg = args.heading_deg
    antenna_side = args.antenna_side
    inc_deg = args.inc_deg
    geoid_offset = args.geoid_offset
    orbit_dir = "ascending" if args.ascending else ("descending" if args.descending else None)

    if args.geometry_h5:
        try:
            import h5py
        except ImportError as e:
            raise SystemExit("h5py is required when using --geometry-h5. Install it or run without --geometry-h5.") from e

        with h5py.File(args.geometry_h5, "r") as f:
            attrs = f["/"].attrs
            if heading_deg is None and "HEADING" in attrs:
                heading_deg = float(attrs["HEADING"])
            if antenna_side is None and "ANTENNA_SIDE" in attrs:
                antenna_side = int(attrs["ANTENNA_SIDE"])
            if orbit_dir is None and "ORBIT_DIRECTION" in attrs:
                orbit_dir = attrs["ORBIT_DIRECTION"].decode() if isinstance(attrs["ORBIT_DIRECTION"], bytes) else str(attrs["ORBIT_DIRECTION"])

            # Auto-estimate incidence angle from dataset median (sampled)
            if inc_deg is None and "incidenceAngle" in f:
                inc_deg = sample_median(f["incidenceAngle"], step=50)

            # Auto-estimate geoid offset from height median (sampled)
            # Your height median is ~ -27 or -26 -> geoid_offset ~ +27/+26
            if geoid_offset is None and "height" in f:
                h_med = sample_median(f["height"], step=50)
                if np.isfinite(h_med):
                    geoid_offset = -h_med

    # Fallbacks if still missing
    if heading_deg is None:
        raise SystemExit("Missing HEADING. Provide --geometry-h5 or --heading-deg.")
    if antenna_side is None:
        # TSX typically -1 in your stacks, but keep explicit
        antenna_side = -1
    if inc_deg is None or not np.isfinite(inc_deg):
        inc_deg = 43.0
    if geoid_offset is None or not np.isfinite(geoid_offset):
        geoid_offset = 27.0
    if orbit_dir is None:
        orbit_dir = infer_orbit_from_heading(heading_deg)

    # Z for visualization
    df["z_plot"] = df["elev_insarmaps"] - float(geoid_offset)

    if not args.no_xy_corr:
        # lon/lat -> meters (UTM 17N for Miami)
        to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32617", always_xy=True)
        to_ll = Transformer.from_crs("EPSG:32617", "EPSG:4326", always_xy=True)
        x, y = to_utm.transform(df["X"].to_numpy(), df["Y"].to_numpy())

        # Look direction from HEADING + ANTENNA_SIDE
        H = np.deg2rad(heading_deg)
        tE, tN = np.sin(H), np.cos(H)
        rE, rN = (tN, -tE)    # right-of-track
        lE, lN = (-tN, tE)    # left-of-track

        if int(antenna_side) == -1:
            uE, uN = rE, rN
        else:
            uE, uN = lE, lN

        norm = np.hypot(uE, uN)
        uE, uN = uE / norm, uN / norm

        theta = np.deg2rad(float(inc_deg))
        d = float(args.scale) * df["h_m"].to_numpy() / np.tan(theta)

        # Orbit-dependent sign (validated for your Miami TSX stacks)
        sign = 1.0 if orbit_dir.lower().startswith("desc") else -1.0
        if args.flip_sign:
            sign *= -1.0

        x_corr = x + sign * uE * d
        y_corr = y + sign * uN * d

        lon_corr, lat_corr = to_ll.transform(x_corr, y_corr)
        df["X_corr"] = lon_corr
        df["Y_corr"] = lat_corr

    vmin = -float(args.vlim)
    vmax = +float(args.vlim)

    write_kml(
        df=df,
        out_kml=str(out_kml),
        name=args.kml_name,
        z_col="z_plot",
        color_col="vel_cm_yr",
        vmin=vmin,
        vmax=vmax,
        icon_scale=float(args.icon_scale),
        hide_labels=bool(args.hide_labels),
    )

    print("Wrote:", out_kml)
    print("orbit:", orbit_dir, "| heading_deg:", heading_deg, "| antenna_side:", antenna_side, "| inc_deg:", inc_deg, "| geoid_offset:", geoid_offset)
    print("mean lon orig:", df["X"].mean())
    if "X_corr" in df.columns:
        print("mean lon corr:", df["X_corr"].mean())


if __name__ == "__main__":
    main()
