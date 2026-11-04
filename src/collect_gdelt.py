import os
import time
import requests
import pandas as pd

os.makedirs("data/raw", exist_ok=True)
os.makedirs("data/interim", exist_ok=True)

# ---------- SETTINGS ----------
# Test first with one month. For the full download later, change to:
#   START, END = "2019-01-01", (today's date)
START, END = "2024-10-01", "2024-10-31"

TOPICS = {                                   # short name -> what GDELT searches for
    "rupee": '"indian rupee"',
    "rbi":   '"reserve bank of india"',
    "ecb":   '"european central bank"',
}
MODES = {                                    # what we ask for -> our column name
    "timelinetone":   "tone",                # average mood of the articles
    "timelinevolraw": "count",               # number of articles
}
URL = "https://api.gdeltproject.org/api/v2/doc/doc"
PAUSE = 10                                   # seconds between requests (GDELT allows one every 5)
WAIT_IF_BLOCKED = 60                         # seconds to wait after GDELT says "slow down"
TRIES = 4
HEADERS = {"User-Agent": "Mozilla/5.0 (student project eur-inr-outlook)"}   # browser-like name tag


def fetch(query, mode, start, end):
    """Ask GDELT for one topic, one mode, one time window. Returns a small table."""
    params = {
        "query": query, "mode": mode, "format": "json", "timelinesmooth": 0,
        "startdatetime": start.strftime("%Y%m%d000000"),
        "enddatetime": end.strftime("%Y%m%d235959"),
    }
    for attempt in range(TRIES):
        r = requests.get(URL, params=params, headers=HEADERS, timeout=60)
        time.sleep(PAUSE)
        try:
            data = r.json()
            break
        except ValueError:                   # GDELT answered with text, not data
            print(f"   GDELT said: {r.text[:80]!r}")
            print(f"   Waiting {WAIT_IF_BLOCKED} s before try {attempt + 2}/{TRIES} ...")
            time.sleep(WAIT_IF_BLOCKED)
    else:
        raise RuntimeError(f"No usable answer for {query} {mode} {start.date()} - "
                           "GDELT is blocking this network. Try the browser test or another network.")

    timeline = data.get("timeline", [])
    if not timeline:                         # no articles at all in this window
        return pd.DataFrame(columns=["datetime", "value"])
    df = pd.DataFrame(timeline[0]["data"])
    df["datetime"] = pd.to_datetime(df["date"], format="%Y%m%dT%H%M%SZ")
    return df[["datetime", "value"]]


# ---------- 1. COLLECT: month by month, topic by topic ----------
months = pd.date_range(START, END, freq="MS")
results = {}
for name, query in TOPICS.items():
    for mode, col in MODES.items():
        pieces = []
        for m_start in months:
            m_end = min(m_start + pd.offsets.MonthEnd(0), pd.Timestamp(END))
            print(f"{name:6s} {col:5s} {m_start:%Y-%m}")
            pieces.append(fetch(query, mode, m_start, m_end))
        raw = pd.concat(pieces, ignore_index=True)
        raw.to_csv(f"data/raw/gdelt_{name}_{col}.csv", index=False)   # untouched copy

        # ---------- 2. CLEAN: one value per day ----------
        raw["date"] = raw["datetime"].dt.normalize()
        how = "sum" if col == "count" else "mean"   # counts add up, moods average out
        results[f"{name}_{col}"] = raw.groupby("date")["value"].agg(how)

daily = pd.DataFrame(results)
daily = daily.reindex(pd.date_range(START, END, freq="D"))     # make every day visible
daily.index.name = "date"
count_cols = [c for c in daily.columns if c.endswith("_count")]
daily[count_cols] = daily[count_cols].fillna(0)                # no articles = 0 articles

# ---------- 3. INSPECT ----------
print(f"\nDays: {len(daily)} from {daily.index.min().date()} to {daily.index.max().date()}")
print("\nMissing values per column (tone is empty on days with no articles):")
print(daily.isna().sum())
print("\nSummary:")
print(daily.describe().round(2))
print("\nBusiest day per topic:")
for c in count_cols:
    print(f"  {c:12s} {daily[c].idxmax().date()}  ({int(daily[c].max())} articles)")

# ---------- 4. SAVE ----------
daily.to_csv("data/interim/gdelt_daily.csv")
print("\nSaved data/interim/gdelt_daily.csv")