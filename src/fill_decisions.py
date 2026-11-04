import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
KEY = os.environ["FRED_API_KEY"]
START = "2019-01-01"

# event type -> (FRED series, days to wait for the new rate to take effect)
RATE_SERIES = {
    "fomc_decision": ("DFEDTARU", 7),    # Fed: new rate applies the next day
    "ecb_decision":  ("ECBDFR",  14),    # ECB: new rate applies about a week later
}
KNOWN_BEFORE_FIXING = {"fomc_decision": "no", "ecb_decision": "yes"}
REGION = {"fomc_decision": "US", "ecb_decision": "EU"}


def load_rate(series_id):
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {"series_id": series_id, "api_key": KEY, "file_type": "json"}
    data = requests.get(url, params=params, timeout=30).json()
    if "observations" not in data:
        raise RuntimeError(f"{series_id}: {data.get('error_message', data)}")
    df = pd.DataFrame(data["observations"])[["date", "value"]]
    df.to_csv(f"data/raw/fred_{series_id}.csv", index=False)
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna().set_index("date")["value"].sort_index()


meetings = pd.read_csv("data/external/meeting_dates.csv", dtype=str)
meetings["date"] = pd.to_datetime(meetings["date"].str.strip())
meetings["event_type"] = meetings["event_type"].str.strip().str.lower()

rows = []
for etype, (series_id, window) in RATE_SERIES.items():
    rate = load_rate(series_id)
    last_rate_day = rate.index.max()
    sub = meetings[meetings["event_type"] == etype].sort_values("date")

    # --- fill in each meeting's outcome ---
    for _, m in sub.iterrows():
        effective_check = m["date"] + pd.Timedelta(days=window)
        if effective_check > last_rate_day:
            # future meeting (or too recent to see the new rate): leave the outcome empty
            decision, change = "", ""
        else:
            before = rate.asof(m["date"])           # rate on announcement day
            after = rate.asof(effective_check)      # rate after it took effect
            change = int(round((after - before) * 100))   # basis points
            decision = "hike" if change > 0 else "cut" if change < 0 else "hold"
        rows.append({
            "date": m["date"].date(), "region": REGION[etype], "event_type": etype,
            "scheduled": m["scheduled"].strip().lower(), "decision": decision,
            "change_bp": change, "known_before_fixing": KNOWN_BEFORE_FIXING[etype],
            "source_link": m["source_link"],
        })

    # --- cross-check: every rate change must belong to a meeting in the list ---
    changes = rate[rate.diff() != 0].iloc[1:]
    changes = changes[changes.index >= START]
    missed = [d.date() for d in changes.index
              if not ((sub["date"] < d) & (sub["date"] >= d - pd.Timedelta(days=window))).any()]
    print(f"{etype}: {len(sub)} meetings, {len(changes)} rate changes since {START}, "
          f"{len(missed)} changes without a meeting in your list")
    if missed:
        print("   Missing meeting for rate change effective on:", missed)

out = pd.DataFrame(rows)
out.to_csv("data/interim/cb_decisions_auto.csv", index=False)
print(out.groupby(["event_type", "decision"]).size())
