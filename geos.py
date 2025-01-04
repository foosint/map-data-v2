import json
import os
import re
import sys

import pandas as pd

# public sheet id
SHEET_ID = "1u0N-CJNyuB4oSRwHpPkI27bAzwjCfBbAPUH4DKO7gqY"
# worksheet name
SHEET_NAME = "MapData"


def clean_and_normalize_coordinates(coord: str) -> str:
    # Remove leading and trailing spaces
    coord = coord.strip()

    # Replace brackets
    coord = coord.replace("(", "").replace(")", "")

    # Replace zero with space
    coord = re.sub(r"\u200B", "", coord)

    # Replace invisible characters (non-breaking spaces, zero-width spaces) with a standard space
    coord = re.sub(r"\s+", " ", coord)  # Normalize all spaces to a single space

    # Replace any combination of spaces and commas with a single comma
    coord = re.sub(r"[ ,]+", ",", coord)  # Ensure coordinates are comma-separated

    # Ensure there is no space before or after the comma
    coord = re.sub(r"\s*,\s*", ",", coord)  # Clean up spaces around the comma

    return coord


def is_valid_coordinates(coord: str) -> bool:

    # Regex pattern for valid latitude and longitude
    pattern = r"^-?([1-8]?\d(\.\d+)?|90(\.0+)?),-?(180(\.0+)?|((1[0-7]\d)|([1-9]?\d))(\.\d+)?)$"

    # Step 2: Check if the cleaned string matches the valid pattern
    return bool(re.match(pattern, coord))


def get_normalized_coordinates(coord: str) -> tuple[bool, str]:
    # Step 1: Clean the coordinates
    cleaned_coord = clean_and_normalize_coordinates(coord)

    # Step 2: Validate the cleaned coordinates
    is_valid = is_valid_coordinates(cleaned_coord)

    return (is_valid, cleaned_coord)


def get_all_geos():

    geos = {}

    # public url
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"
    # load sheet data into dataframe
    df = pd.read_csv(url)

    # filter only columns we want
    columns_to_keep = ["Location", "Name", "Description", "code"]
    df = df[columns_to_keep]

    # rename column
    df.rename(columns={"Location": "c"}, inplace=True)  # coords
    df.rename(columns={"Name": "d"}, inplace=True)  # date
    df.rename(columns={"Description": "t"}, inplace=True)  # decaription
    df.rename(columns={"code": "s"}, inplace=True)  # side
    # filter empty rows
    df = df.dropna(how="all")

    # transform dates
    df["d"] = df["d"].str.extract(r"\[(\d{2}/\d{2}/\d{2})\]")
    df["d"] = pd.to_datetime(df["d"], format="%y/%m/%d")

    # Filter out rows before January 2023
    start_date = os.getenv("START_DATE", default="2023-01-01")
    filter_date = pd.to_datetime(start_date)
    df = df[df["d"] >= filter_date]
    print(f"Number of rows: {df.shape[0]}")

    # Loop through rows
    for _, row in df.iterrows():
        formatted_date = row["d"].strftime("%Y%m%d")
        side = row["s"].lower()
        t = row["t"]
        c = row["c"]

        # check for invalid side
        if side not in ["ru", "ua"]:
            print(f"Invalid side: {formatted_date} - {side}")

        # check for Nan texts
        if pd.isna(t):
            # print(row)
            t = ""

        # check for invalid coordinates
        (is_valid_coord, coord) = get_normalized_coordinates(c)
        if not is_valid_coord:
            print(f"Invalid Coords: {formatted_date} {c} - {coord}")
            continue

        coords = coord.split(",", 1)

        geo_data = {
            "c": coords,
            "t": t,
        }

        # create empty geos dict
        if formatted_date not in geos:
            geos[formatted_date] = {"ru": [], "ua": []}

        geos[formatted_date][side].append(geo_data)

    # Save dictionary as JSON
    with open("./data/geos.json", "w", encoding="utf-8") as file:
        json.dump(geos, file, ensure_ascii=False)  # Pretty-prints with indentation


# Entry point for the script
if __name__ == "__main__":
    get_all_geos()
