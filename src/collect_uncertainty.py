import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
KEY = os.environ["FRED_API_KEY"]
os.makedirs("data/raw", exist_ok=True)
os.makedirs("data/interim", exist_ok=True)


FRED_SERIES = {"USEPUINDXD": "us_epu", "INDEPUINDXM": "in_epu", "EUEPUINDXM": "eu_epu"}

def fetch_fred(series_id):
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {"series_id": series_id, "api_key": KEY, "file_type": "json"}
    data = requests.get(url, params=params, timeout=30).json()
    if "observations" not in data:
        raise RuntimeError(f"{series_id}: {data.get('error_message', data)}")
    raw = pd.DataFrame(data["observations"])[["date", "value"]]
    raw.to_csv(f"data/raw/fred_{series_id}.csv", index=False)   # untouched copy
    return raw


def clean(raw, name, date_col="date", value_col="value"):
    df = raw[[date_col, value_col]].copy()
    df.columns = ["date", name]
    df["date"] = pd.to_datetime(df["date"])
    df[name] = pd.to_numeric(df[name], errors="coerce")   # "." or text -> NaN
    df = df.dropna(subset=[name])                         # drop missing values
    df = df.sort_values("date").drop_duplicates("date", keep="last")
    df = df[df[name] >= 0]                                # index can't be negative
    return df.set_index("date")

cleaned = {}
for sid, name in FRED_SERIES.items():
    cleaned[name] = clean(fetch_fred(sid), name)


gpr_d = pd.read_excel("data/raw/gpr_daily_2026-10-28.xls", engine="calamine").copy()
gpr_d["day_parsed"] = pd.to_datetime(gpr_d["DAY"].astype(str), format="%Y%m%d")
cleaned["gpr"] = clean(gpr_d, "gpr", date_col="day_parsed", value_col="GPRD")

cleaned["gpr"] = cleaned["gpr"][cleaned["gpr"]["gpr"] > 0]

gpr_m = pd.read_excel("data/raw/gpr_monthly_2026-10-28.xls", engine="calamine").copy()
gpr_m["month_parsed"] = pd.to_datetime(gpr_m["month"])
cleaned["gpr_india"] = clean(gpr_m, "gpr_india", date_col="month_parsed", value_col="GPRC_IND")


for name, df in cleaned.items():
    s = df[name]
    gaps = s.index.to_series().diff().dt.days.max()
    print(f"{name:10s} {s.index.min().date()} to {s.index.max().date()} | "
          f"{len(s)} rows | min {s.min():.1f} max {s.max():.1f} | largest gap {gaps} days")
    df.to_csv(f"data/interim/{name}_clean.csv")