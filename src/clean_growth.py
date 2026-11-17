import sys
from pathlib import Path

import pandas as pd

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/processed/growth_daily.csv")
OUT = Path("data/interim")
MODEL_START = "2020-01-01"

df = pd.read_csv(SRC, parse_dates=["date"]).sort_values("date")
assert not df["date"].duplicated().any(), "duplicate dates"
values = [c for c in df.columns if c != "date" and not c.endswith("_period")]
print(f"read  {len(df)} days, {df.date.min():%Y-%m-%d} .. {df.date.max():%Y-%m-%d}, {len(values)} series")

# when does each series start and any gaps after the start? 
problems = []
for c in values:
    first = df.loc[df[c].notna(), "date"].min()
    gaps = df.loc[df["date"] >= first, c].isna().sum()
    print(f"      {c:16s} from {first:%Y-%m-%d}   gaps after start: {gaps}")
    if first > pd.Timestamp(MODEL_START):
        problems.append(f"{c} only starts {first:%Y-%m-%d} (after {MODEL_START})")
    if gaps:
        problems.append(f"{c} has {gaps} missing days after it starts")

out = df[["date"] + values].copy()

OUT.mkdir(parents=True, exist_ok=True)
out.to_csv(OUT / "growth_clean_daily.csv", index=False, float_format="%.3f")
weekly = out[out["date"].dt.dayofweek == 0].rename(columns={"date": "week_start"})
weekly.to_csv(OUT / "growth_clean_weekly.csv", index=False, float_format="%.3f")

print(f"\nok    {len(out)} days  -> {OUT / 'growth_clean_daily.csv'}")
print(f"ok    {len(weekly)} weeks -> {OUT / 'growth_clean_weekly.csv'}")
left = out[out["date"] >= MODEL_START].isna().sum()
print(f"      missing values from {MODEL_START} on: {left[left > 0].to_dict() or 'none'}")
if problems:
    print("CHECK:\n - " + "\n - ".join(problems))