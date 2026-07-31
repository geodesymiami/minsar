#!/usr/bin/env python3

from datetime import date
from io import StringIO

import pandas as pd
import requests


STATION = "72202012839"  # KMIA: USAF 722020 + WBAN 12839
START_DATE = date(2016, 1, 1)
END_DATE = date.today()

OUTPUT_FILE = "KMIA_temperature_2016_present_11UTC_23UTC.csv"

TARGET_HOURS = (11, 23)
MAX_TIME_DIFFERENCE = pd.Timedelta(minutes=30)


def download_year(year: int) -> pd.DataFrame:
    """Download one annual NOAA Global Hourly CSV file."""

    url = (
        "https://www.ncei.noaa.gov/data/global-hourly/access/"
        f"{year}/{STATION}.csv"
    )

    print(f"Downloading {year}: {url}")

    response = requests.get(
        url,
        timeout=120,
        headers={"User-Agent": "KMIA-temperature-downloader/1.0"},
    )

    if response.status_code == 404:
        print(f"Warning: no NOAA file found for {year}")
        return pd.DataFrame()

    response.raise_for_status()

    if not response.text.strip():
        print(f"Warning: empty NOAA file for {year}")
        return pd.DataFrame()

    df = pd.read_csv(
        StringIO(response.text),
        low_memory=False,
    )

    print(f"  received {len(df):,} observations")

    return df


def decode_temperature(tmp: pd.Series) -> pd.Series:
    """
    Decode the NOAA TMP field.

    Examples:
        +0278,1 -> 27.8 °C
        +9999,9 -> missing
    """

    values = tmp.astype("string").str.split(",").str[0]

    values = values.replace(
        {
            "+9999": pd.NA,
            "-9999": pd.NA,
            "9999": pd.NA,
            "": pd.NA,
        }
    )

    return pd.to_numeric(values, errors="coerce") / 10.0


def choose_nearest_observation(
    observations: pd.DataFrame,
    target: pd.Timestamp,
):
    """Return the valid observation nearest a requested time."""

    candidates = observations[
        (
            observations["timestamp_utc"]
            >= target - MAX_TIME_DIFFERENCE
        )
        & (
            observations["timestamp_utc"]
            <= target + MAX_TIME_DIFFERENCE
        )
    ].copy()

    if candidates.empty:
        return None

    candidates["time_difference"] = (
        candidates["timestamp_utc"] - target
    ).abs()

    return candidates.loc[candidates["time_difference"].idxmin()]


def create_daily_table(observations: pd.DataFrame) -> pd.DataFrame:
    """Create one row per day with temperatures near 11 and 23 UTC."""

    observations = observations.copy()

    observations["timestamp_utc"] = pd.to_datetime(
        observations["DATE"],
        utc=True,
        errors="coerce",
    )

    observations["temperature_C"] = decode_temperature(
        observations["TMP"]
    )

    observations = observations.dropna(
        subset=["timestamp_utc", "temperature_C"]
    )

    start_timestamp = pd.Timestamp(START_DATE, tz="UTC")
    end_timestamp = pd.Timestamp(END_DATE, tz="UTC")

    rows = []

    for day in pd.date_range(
        start_timestamp,
        end_timestamp,
        freq="D",
    ):
        row = {"date": day.strftime("%Y-%m-%d")}

        for hour in TARGET_HOURS:
            target = day + pd.Timedelta(hours=hour)

            observation = choose_nearest_observation(
                observations,
                target,
            )

            temperature_column = f"temp{hour:02d}UTC_C"
            timestamp_column = f"observation_time_{hour:02d}UTC"
            offset_column = f"time_offset_{hour:02d}UTC_minutes"

            if observation is None:
                row[temperature_column] = pd.NA
                row[timestamp_column] = pd.NA
                row[offset_column] = pd.NA
            else:
                observed_time = observation["timestamp_utc"]

                row[temperature_column] = observation["temperature_C"]

                row[timestamp_column] = observed_time.strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                )

                row[offset_column] = (
                    observed_time - target
                ).total_seconds() / 60.0

        rows.append(row)

    return pd.DataFrame(rows)


def main() -> None:
    yearly_data = []

    for year in range(
        START_DATE.year,
        END_DATE.year + 1,
    ):
        df = download_year(year)

        if not df.empty:
            yearly_data.append(df)

    if not yearly_data:
        raise RuntimeError(
            "NOAA returned no observations. "
            "Check internet access and station identifier."
        )

    observations = pd.concat(
        yearly_data,
        ignore_index=True,
    )

    required_columns = {"DATE", "TMP"}
    missing_columns = required_columns - set(observations.columns)

    if missing_columns:
        raise RuntimeError(
            f"Missing NOAA columns: {sorted(missing_columns)}\n"
            f"Available columns: {list(observations.columns)}"
        )

    print()
    print(f"Total observations: {len(observations):,}")

    output = create_daily_table(observations)

    output.to_csv(
        OUTPUT_FILE,
        index=False,
        float_format="%.1f",
    )

    print()
    print(output.head())
    print()
    print(f"Wrote {len(output):,} days to:")
    print(OUTPUT_FILE)

    print()
    print("Missing temperature counts:")
    print(
        output[
            ["temp11UTC_C", "temp23UTC_C"]
        ].isna().sum()
    )


if __name__ == "__main__":
    main()
