import sys
from pathlib import Path

import pandas as pd

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/processed/fpi_daily.csv")
OUT = Path("data/interim")
AVAILABLE_AFTER_DAYS = 1
FLOWS = ["equity_net_usd_mn", "debt_net_usd_mn", "total_net_usd_mn"]

df = pd.read_csv(SRC, parse_dates=["reporting_date"])
print(f"read  {len(df)} reports, {df.reporting_date.min():%Y-%m-%d} .. {df.reporting_date.max():%Y-%m-%d}")

# basic checks 
assert not df["reporting_date"].duplicated().any(), "duplicate reporting dates"
parts = [c for c in df.columns if c.endswith("_net_usd_mn") and not c.startswith("total")]
gap = (df[parts].fillna(0).sum(axis=1) - df["total_net_usd_mn"]).abs()
assert (gap <= 1).all(), "sub-totals don't add up to the total on some days"

# columns and structural missing values 
df[parts] = df[parts].fillna(0)                       
df = df[["reporting_date"] + FLOWS + ["usdinr_nsdl"]].sort_values("reporting_date")

#calendar-day grid, flows = 0 on days without a report 
df["available_from"] = df["reporting_date"] + pd.Timedelta(days=AVAILABLE_AFTER_DAYS)

days = pd.date_range(df["available_from"].min(), df["available_from"].max(), freq="D")
daily = df.set_index("available_from").reindex(days)
daily.index.name = "date"
daily["fpi_report_day"] = daily["reporting_date"].notna().astype(int)   # 1 = new report arrived
daily[FLOWS] = daily[FLOWS].fillna(0)
daily["usdinr_nsdl"] = daily["usdinr_nsdl"].ffill()                    # a rate IS a level -> carry forward

daily = daily.rename(columns={c: f"fpi_{c.replace('_net_usd_mn', '')}_day" for c in FLOWS})
daily = daily.drop(columns=["reporting_date"]).reset_index()

# weekly: sum of the flows that became known Mon
w = daily.set_index("date")
day_cols = [c for c in w.columns if c.endswith("_day")]
weekly = w[day_cols].resample("W-SUN").sum()                 
weekly.index = weekly.index + pd.Timedelta(days=1)           
weekly.columns = [c.replace("_day", "_week") for c in weekly.columns]
weekly = weekly.join(w[["usdinr_nsdl"]], how="left")
weekly = weekly[(weekly.index - pd.Timedelta(days=1) <= w.index.max())     
                & (weekly.index - pd.Timedelta(days=7) >= w.index.min())]   
weekly.index.name = "week_start"
weekly = weekly.reset_index()

OUT.mkdir(parents=True, exist_ok=True)
daily.to_csv(OUT / "fpi_clean_daily.csv", index=False, float_format="%.2f")
weekly.to_csv(OUT / "fpi_clean_weekly.csv", index=False, float_format="%.2f")

print(f"ok    {len(daily)} days  -> {OUT / 'fpi_clean_daily.csv'}")
print(f"ok    {len(weekly)} weeks -> {OUT / 'fpi_clean_weekly.csv'}")
print(f"      missing values left: {int(daily.isna().sum().sum())}")
print(daily.tail(3).to_string(index=False))