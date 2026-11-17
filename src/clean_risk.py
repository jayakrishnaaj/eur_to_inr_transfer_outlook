import sys
from pathlib import Path

import pandas as pd

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/processed/risk_daily.csv")
OUT = Path("data/interim")
MODEL_START = "2020-01-01"

df = pd.read_csv(SRC, parse_dates=["date"]).sort_values("date")
assert not df["date"].duplicated().any(), "duplicate dates"
print(f"read  {len(df)} days, {df.date.min():%Y-%m-%d} .. {df.date.max():%Y-%m-%d}")

# drop the short high-yield series and the check-only column
df = df.drop(columns=[c for c in df.columns if c.startswith("hy_spread") or c == "risk_obs_date"])
cols = [c for c in df.columns if c != "date"]

# carry levels forward over single-market holidays (after each series has started)
before = df[cols].isna().sum()
for c in cols:
    first = df[c].first_valid_index()
    if first is not None:
        df.loc[first:, c] = df.loc[first:, c].ffill()
filled = (before - df[cols].isna().sum())
print("      filled with last known value:", {k: int(v) for k, v in filled.items() if v} or "nothing")

# report what is still missing in the model period (should be nothing)
left = df[df["date"] >= MODEL_START][cols].isna().sum()
print(f"      missing values from {MODEL_START} on: {left[left > 0].to_dict() or 'none'}")

OUT.mkdir(parents=True, exist_ok=True)
df.to_csv(OUT / "risk_clean_daily.csv", index=False, float_format="%.3f")
weekly = df[df["date"].dt.dayofweek == 0].rename(columns={"date": "week_start"})
weekly.to_csv(OUT / "risk_clean_weekly.csv", index=False, float_format="%.3f")
print(f"ok    {len(df)} days  -> {OUT / 'risk_clean_daily.csv'}")
print(f"ok    {len(weekly)} weeks -> {OUT / 'risk_clean_weekly.csv'}")
print(df.tail(2).to_string(index=False))