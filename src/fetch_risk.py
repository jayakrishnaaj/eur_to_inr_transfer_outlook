import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

START = "2019-01-01"
TODAY = pd.Timestamp.today().normalize()
SERIES = {"vix": "VIXCLS", "hy_spread": "BAMLH0A0HYM2", "baa_spread": "BAA10Y"}
KEY = Path(".fred_key").read_text().strip()
Path("data/raw/fred").mkdir(parents=True, exist_ok=True)
Path("data/processed").mkdir(parents=True, exist_ok=True)


def download(url):
    # try 3 times before giving up
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except Exception as e:
            print(f"   try {attempt + 1} failed ({e})")
            time.sleep(5)
    raise RuntimeError(f"could not download {url}")


# download
data = {}
for name, series_id in SERIES.items():
    url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}"
           f"&observation_start={START}&api_key={KEY}&file_type=json")
    obs = pd.DataFrame(json.loads(download(url))["observations"])[["date", "value"]]
    obs.to_csv(f"data/raw/fred/{series_id}.csv", index=False)
    obs["value"] = pd.to_numeric(obs["value"], errors="coerce")  # "." means no value
    data[name] = obs.dropna().set_index(pd.to_datetime(obs.dropna()["date"]))["value"]
    print(f"ok    {name:11s} {data[name].index.min():%Y-%m-%d} .. {data[name].index.max():%Y-%m-%d}")

# combine, fill holidays with the last value
wide = pd.DataFrame(data).sort_index().ffill()

# US closing values come after the ECB rate, so use them from the next day
wide.index.name = "risk_obs_date"
wide = wide.reset_index()
wide["available_from"] = wide["risk_obs_date"] + pd.Timedelta(days=1)

# save daily and weekly tables
for label, freq, col in (("daily", "D", "date"), ("weekly", "W-MON", "week_start")):
    dates = pd.DataFrame({col: pd.date_range(START, TODAY, freq=freq)})
    table = pd.merge_asof(dates, wide, left_on=col, right_on="available_from")
    table = table.drop(columns="available_from")
    table = table[[col, "risk_obs_date"] + [c for c in table.columns if c not in (col, "risk_obs_date")]]
    table.to_csv(f"data/processed/risk_{label}.csv", index=False, float_format="%.3f")
    print(f"saved data/processed/risk_{label}.csv ({len(table)} rows)")