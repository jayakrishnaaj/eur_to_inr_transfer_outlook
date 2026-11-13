import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
KEY = os.environ["FRED_API_KEY"]
os.makedirs("data/raw", exist_ok=True)
os.makedirs("data/interim", exist_ok=True)
START = "2019-01-01"   # team decision: train from 2020

RELEASES = {10: "us_cpi", 50: "us_jobs"}


def fred_release_dates(release_id, event_type):
    base = "https://api.stlouisfed.org/fred/release"
    common = {"release_id": release_id, "api_key": KEY, "file_type": "json"}

    info = requests.get(base, params=common, timeout=30).json()
    print(f"Release {release_id} = {info['releases'][0]['name']}")   # check the ID is right

    params = {**common, "realtime_start": START, "limit": 10000,
              "sort_order": "asc", "include_release_dates_with_no_data": "true"}
    data = requests.get(base + "/dates", params=params, timeout=30).json()
    if "release_dates" not in data:
        raise RuntimeError(f"Release {release_id}: {data.get('error_message', data)}")

    raw = pd.DataFrame(data["release_dates"])
    raw.to_csv(f"data/raw/fred_release_dates_{release_id}.csv", index=False)

    return pd.DataFrame({
        "date": raw["date"], "region": "US", "event_type": event_type,
        "scheduled": "yes", "decision": "", "change_bp": "",
        "known_before_fixing": "yes",
        "source_link": f"FRED release {release_id}",
    })


auto = pd.concat([fred_release_dates(rid, name) for rid, name in RELEASES.items()])

manual_files = ["data/external/events_manual.csv", "data/interim/cb_decisions_auto.csv"]
manual = pd.concat([pd.read_csv(f, dtype=str) for f in manual_files if os.path.exists(f)],
                   ignore_index=True)

ALLOWED_TYPES = {"ecb_decision", "rbi_decision", "fomc_decision",
                 "us_cpi", "us_jobs", "india_budget", "india_election",
                 "us_election"}
ALLOWED_DECISIONS = {"hike", "cut", "hold", ""}


def clean_events(df):
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    bad_dates = df[df["date"].isna()]
    if len(bad_dates):
        print("Rows with unreadable dates (fix in the CSV):\n", bad_dates)
    df = df.dropna(subset=["date"])

    for col in ["region", "event_type", "scheduled", "decision", "known_before_fixing"]:
        df[col] = df[col].fillna("").astype(str).str.strip().str.lower()
    df["region"] = df["region"].str.upper()
    df["change_bp"] = pd.to_numeric(df["change_bp"], errors="coerce")

    unknown = df[~df["event_type"].isin(ALLOWED_TYPES)]
    if len(unknown):
        print("Unknown event_type values (typos?):\n", unknown[["date", "event_type"]])
    wrong_dec = df[~df["decision"].isin(ALLOWED_DECISIONS)]
    if len(wrong_dec):
        print("Unexpected decision values:\n", wrong_dec[["date", "event_type", "decision"]])

    df = df[df["date"] >= START]
    df = df.drop_duplicates(subset=["date", "event_type"], keep="last")
    return df.sort_values(["date", "event_type"]).reset_index(drop=True)


events = clean_events(pd.concat([auto, manual], ignore_index=True))

today = pd.Timestamp.today().normalize()
past = events[events["date"] <= today]

print("\nEvents per year and type (past only):")
print(pd.crosstab(past["date"].dt.year, past["event_type"]))

weekend = events[events["date"].dt.dayofweek >= 5]
print(f"\nWeekend events: {len(weekend)}")
print(weekend[["date", "event_type", "scheduled"]])

print(f"\nFuture scheduled events already listed: {(events['date'] > today).sum()}")
print(f"Total events: {len(events)} from {events['date'].min().date()} "
      f"to {events['date'].max().date()}")

events.to_csv("data/interim/events_clean.csv", index=False)