#!/usr/bin/env python3
"""
Plot LOS displacement time series for one or two point IDs from CSV file(s).

Example usage
-------------
Single point:
    plot_displacement.py \
        --p1 349562 \
        --f1 file1.csv \
        --output point1displacement.png

Two points:
    plot_displacement.py \
        --p1 349562 --f1 file1.csv \
        --p2 456356 --f2 file2.csv \
        --output point1point2displacement.png

Optional title:
    python3 plot_displacement.py \
        --p1 349562 --f1 file1.csv \
        --title "Building 1" \
        --output building1.png
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot LOS displacement time series for one or two point IDs from CSV file(s)."
    )

    parser.add_argument("--p1", type=int, required=True, help="Point ID for first point")
    parser.add_argument("--f1", type=str, required=True, help="CSV file for first point")

    parser.add_argument("--p2", type=int, default=None, help="Point ID for second point")
    parser.add_argument("--f2", type=str, default=None, help="CSV file for second point")

    parser.add_argument(
        "--title",
        type=str,
        default="LOS Displacement Time Series",
        help='Plot title (default: "LOS Displacement Time Series")',
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output PNG file",
    )

    # Optional manual override if direction cannot be inferred from filename
    parser.add_argument(
        "--dir1",
        type=str,
        choices=["ascending", "descending", "asc", "desc", "A", "D"],
        default=None,
        help="Optional direction override for point 1",
    )
    parser.add_argument(
        "--dir2",
        type=str,
        choices=["ascending", "descending", "asc", "desc", "A", "D"],
        default=None,
        help="Optional direction override for point 2",
    )

    return parser.parse_args()


def normalize_direction(direction: str | None) -> str | None:
    if direction is None:
        return None
    d = direction.strip().lower()
    if d in {"ascending", "asc", "a"}:
        return "Ascending"
    if d in {"descending", "desc", "d"}:
        return "Descending"
    return None


def infer_direction_from_filename(filename: str) -> str | None:
    """
    Try to infer orbit direction from filename.
    Looks for common patterns such as:
      - ascending / descending
      - _A_ / _D_
      - suffixes with A or D
      - asc / desc
    """
    name = Path(filename).stem.lower()

    if "ascending" in name or re.search(r"(^|[_\-])asc([_\-]|$)", name):
        return "Ascending"
    if "descending" in name or re.search(r"(^|[_\-])desc([_\-]|$)", name):
        return "Descending"

    # Common shorthand like ..._A..., ..._D...
    if re.search(r"(^|[_\-])a([_\-]|$)", name):
        return "Ascending"
    if re.search(r"(^|[_\-])d([_\-]|$)", name):
        return "Descending"

    return None


def load_point_timeseries(csv_file: str, point_id: int) -> tuple[pd.DataFrame, float | None]:
    df = pd.read_csv(csv_file)

    if "point_id" not in df.columns:
        raise ValueError(f"'point_id' column not found in {csv_file}")

    row = df[df["point_id"] == point_id]
    if row.empty:
        raise ValueError(f"Point ID {point_id} not found in {csv_file}")

    row = row.iloc[0]

    date_cols = [c for c in df.columns if re.fullmatch(r"D\d{8}", str(c))]
    if not date_cols:
        raise ValueError(f"No displacement date columns like DYYYYMMDD found in {csv_file}")

    ts = pd.DataFrame(
        {
            "date": pd.to_datetime([c[1:] for c in date_cols], format="%Y%m%d"),
            "displacement_mm": pd.to_numeric([row[c] for c in date_cols], errors="coerce"),
        }
    )

    ts = ts.dropna(subset=["displacement_mm"]).sort_values("date").reset_index(drop=True)
    ts["displacement_cm"] = ts["displacement_mm"] / 10.0

    velocity = None
    if "velocity" in df.columns:
        try:
            velocity = float(row["velocity"])
        except Exception:
            velocity = None

    return ts, velocity


def build_label(
    point_name: str,
    velocity: float | None,
    direction: str | None,
) -> str:
    parts = [point_name]

    if direction is not None:
        parts.append(direction)

    if velocity is not None:
        parts.append(f"v={velocity:.2f} mm/yr")

    return " (" + ", ".join(parts[1:]) + ")" if len(parts) > 1 else point_name \
        if point_name == parts[0] else f"{point_name} ({', '.join(parts[1:])})"


def main() -> None:
    args = parse_args()

    if (args.p2 is None) ^ (args.f2 is None):
        raise ValueError("For second point, both --p2 and --f2 must be provided together.")

    dir1 = normalize_direction(args.dir1) or infer_direction_from_filename(args.f1)
    dir2 = normalize_direction(args.dir2) or (infer_direction_from_filename(args.f2) if args.f2 else None)

    ts1, v1 = load_point_timeseries(args.f1, args.p1)

    # -----------------------------
    # SINGLE-POINT
    # -----------------------------
    if args.p2 is None:
        fig, ax = plt.subplots(figsize=(14, 7))

        label1_parts = []
        if dir1 is not None:
            label1_parts.append(dir1)
        if v1 is not None:
            label1_parts.append(f"v={v1:.2f} mm/yr")
        label1 = f"P1 ({', '.join(label1_parts)})" if label1_parts else "P1"

        ax.scatter(ts1["date"], ts1["displacement_cm"], s=45, label=label1)

        ax.set_title(args.title, fontsize=24)
        ax.set_xlabel("Date", fontsize=16)
        ax.set_ylabel("LOS Displacement (cm)", fontsize=16)
        ax.grid(True, alpha=0.35)
        ax.legend(fontsize=11)

        # clean y ticks
        y_min = ts1["displacement_cm"].min()
        y_max = ts1["displacement_cm"].max()

        y_top = 2 if y_max <= 1.5 else 2 * int((y_max + 1.999) // 2)
        y_bottom = 2 * int(y_min // 2)
        if y_bottom >= y_min:
            y_bottom -= 2

        yticks = list(range(int(y_bottom), int(y_top) + 1, 2))
        ax.set_ylim(y_bottom, y_top)
        ax.set_yticks(yticks)

    # -----------------------------
    # TWO-POINT
    # -----------------------------
    else:
        ts2, v2 = load_point_timeseries(args.f2, args.p2)

        fig, (ax1, ax2) = plt.subplots(
            2, 1,
            figsize=(14, 10),
            sharex=True,
            gridspec_kw={"hspace": 0.08}
        )

        fig.suptitle(args.title, fontsize=24)

        label1_parts = []
        if dir1 is not None:
            label1_parts.append(dir1)
        if v1 is not None:
            label1_parts.append(f"v={v1:.2f} mm/yr")
        label1 = f"P1 ({', '.join(label1_parts)})" if label1_parts else "P1"

        label2_parts = []
        if dir2 is not None:
            label2_parts.append(dir2)
        if v2 is not None:
            label2_parts.append(f"v={v2:.2f} mm/yr")
        label2 = f"P2 ({', '.join(label2_parts)})" if label2_parts else "P2"

        # Top panel
        ax1.scatter(ts1["date"], ts1["displacement_cm"], s=45, label=label1)
        ax1.set_ylabel("LOS Displacement (cm)", fontsize=15)
        ax1.grid(True, alpha=0.35)
        ax1.legend(fontsize=11, loc="upper right")

        # Bottom panel
        ax2.scatter(ts2["date"], ts2["displacement_cm"], s=45, label=label2, color="tab:orange")
        ax2.set_ylabel("LOS Displacement (cm)", fontsize=15)
        ax2.set_xlabel("Date", fontsize=16)
        ax2.grid(True, alpha=0.35)
        ax2.legend(fontsize=11, loc="upper right")

        # Clean y ticks separately for each subplot
        for ax, ts in [(ax1, ts1), (ax2, ts2)]:
            y_min = ts["displacement_cm"].min()
            y_max = ts["displacement_cm"].max()

            y_top = 2 if y_max <= 1.5 else 2 * int((y_max + 1.999) // 2)
            y_bottom = 2 * int(y_min // 2)
            if y_bottom >= y_min:
                y_bottom -= 2

            yticks = list(range(int(y_bottom), int(y_top) + 1, 2))
            ax.set_ylim(y_bottom, y_top)
            ax.set_yticks(yticks)

    plt.tight_layout(rect=[0, 0, 1, 0.96])

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved plot to: {output_path}")

if __name__ == "__main__":
    main()
