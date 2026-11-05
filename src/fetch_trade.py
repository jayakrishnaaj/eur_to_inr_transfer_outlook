import io
import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

START = "2019-01-01"
TODAY = pd.Timestamp.today().normalize()
KEY = Path(".fred_key").read_text().strip()
CAB_FILE = Path("data/raw/india_cab_manual.csv")   # India current account, typed in by hand

# days after the end of the month until the number is published
LAG_INDIA = 60
LAG_EURO = 52
LAG_CAB = 85


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


def monthly(name, dates, values, lag, source):
    # one table per series, with the date each value became public
    t = pd.DataFrame({"period_start": pd.to_datetime(dates), "value": pd.to_numeric(values, errors="coerce")})
    t = t.dropna()
    t["period_end"] = t["period_start"] + pd.offsets.MonthEnd(0)
    t["period"] = t["period_start"].dt.strftime("%Y-%m")
    t["available_from"] = t["period_end"] + pd.Timedelta(days=lag)
    t["series"], t["source"] = name, source
    return t


tables = []

# India exports and imports (US$ -> US$ bn)
for name, series_id in (("india_exports_usd_bn", "XTEXVA01INM667S"),
                        ("india_imports_usd_bn", "XTIMVA01INM667S")):
    url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}"
           f"&observation_start={START}&api_key={KEY}&file_type=json")
    obs = pd.DataFrame(json.loads(download(url))["observations"])
    values = pd.to_numeric(obs["value"], errors="coerce") / 1e9   # "." means no value
    tables.append(monthly(name, obs["date"], values, LAG_INDIA, f"FRED {series_id}"))

# euro area, 21 countries (EUR mn -> EUR bn)
for name, item in (("ea_current_account_eur_bn", "CA"), ("ea_goods_balance_eur_bn", "G")):
    key = f"BPS/M.Y.I10.W1.S1.S1.T.B.{item}._Z._Z._Z.EUR._T._X.N.ALL"
    url = f"https://data-api.ecb.europa.eu/service/data/{key}?startPeriod=2019-01&format=csvdata"
    ecb = pd.read_csv(io.BytesIO(download(url)))
    tables.append(monthly(name, ecb["TIME_PERIOD"], ecb["OBS_VALUE"] / 1e3, LAG_EURO, f"ECB {key}"))

# India current account (quarterly), only if the file has been filled in
# format: quarter,cab_usd_bn,release_date   e.g. 2024Q4,-11.5,2025-03-21
if CAB_FILE.exists() and len(pd.read_csv(CAB_FILE)):
    cab = pd.read_csv(CAB_FILE)
    q = pd.PeriodIndex(cab["quarter"], freq="Q")
    t = pd.DataFrame({"period_start": q.start_time, "period_end": q.end_time.normalize(),
                      "value": cab["cab_usd_bn"], "period": q.astype(str)})
    release = pd.to_datetime(cab["release_date"], errors="coerce")
    t["available_from"] = release.fillna(t["period_end"] + pd.Timedelta(days=LAG_CAB))
    t["series"], t["source"] = "india_cab_usd_bn", "RBI (manual)"
    tables.append(t)
else:
    print("note  India current account skipped (data/raw/india_cab_manual.csv is empty)")

for t in tables:
    print(f"ok    {t['series'].iloc[0]:28s} {t['period'].iloc[0]} .. {t['period'].iloc[-1]}")

# save all values with their publication date
cols = ["series", "period", "period_start", "period_end", "available_from", "value", "source"]
raw = pd.concat(tables)[cols].sort_values(["series", "period_start"])
Path("data/raw").mkdir(parents=True, exist_ok=True)
raw.to_csv("data/raw/trade_monthly_raw.csv", index=False, float_format="%.3f")

# weekly table: the newest value known on each Monday
weekly = pd.DataFrame({"week_start": pd.date_range(START, TODAY, freq="W-MON")})
for name, t in raw.groupby("series"):
    m = pd.merge_asof(weekly[["week_start"]], t.sort_values("available_from"),
                      left_on="week_start", right_on="available_from")
    weekly[name] = m["value"].values
    weekly[f"{name}_period"] = m["period"].values
weekly.insert(1, "india_trade_balance_usd_bn", weekly["india_exports_usd_bn"] - weekly["india_imports_usd_bn"])

Path("data/processed").mkdir(parents=True, exist_ok=True)
weekly.to_csv("data/processed/trade_weekly.csv", index=False, float_format="%.3f")
print(f"saved data/raw/trade_monthly_raw.csv and data/processed/trade_weekly.csv ({len(weekly)} weeks)")