import sys
from pathlib import Path

import pandas as pd

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/raw/trade_monthly_raw.csv")
OUT = Path("data/interim")
MODEL_START = "2020-01-01"

raw = pd.read_csv(SRC, parse_dates=["period_start", "period_end", "available_from"])
print(f"read  {len(raw)} observations, series: {sorted(raw.series.unique())}")

# checks per series
problems = []
assert not raw.duplicated(["series", "period"]).any(), "a series has the same period twice"
for name, g in raw.groupby("series"):
    g = g.sort_values("period_start")
    freq = "QS" if "cab" in name else "MS"
    expected = pd.date_range(g.period_start.min(), g.period_start.max(), freq=freq)
    missing = sorted(set(expected) - set(g.period_start))
    print(f"      {name:28s} {g.period.iloc[0]} .. {g.period.iloc[-1]}  "
          f"({len(g)} periods, {len(missing)} missing)")
    if missing:
        problems.append(f"{name}: missing periods {[f'{m:%Y-%m}' for m in missing[:5]]}")
    if (g.available_from <= g.period_end).any():
        problems.append(f"{name}: a value is 'available' before its period ended")
if "india_cab_usd_bn" not in set(raw.series):
    print("      note: India current account not included (india_cab_manual.csv is empty)")

rel = raw[["series", "available_from", "period", "value"]]

# as-of tables: each value valid from its publication date
today = pd.Timestamp.today().normalize()
days = pd.DataFrame({"date": pd.date_range("2019-01-01", today, freq="D")})
out = days.copy()
for name, g in rel.groupby("series"):
    g = g.sort_values("available_from")
    m = pd.merge_asof(days, g, left_on="date", right_on="available_from", direction="backward")
    out[name] = m["value"].values

left = out[out["date"] >= MODEL_START].isna().sum()
print(f"\n      missing values from {MODEL_START} on: {left[left > 0].to_dict() or 'none'}")
newest = rel.groupby("series")["available_from"].max()
for name, d in newest.items():
    if (today - d).days > 75:
        problems.append(f"{name}: newest value published {d:%Y-%m-%d} - run fetch_trade.py again")

OUT.mkdir(parents=True, exist_ok=True)
out.to_csv(OUT / "trade_clean_daily.csv", index=False, float_format="%.3f")
weekly = out[out["date"].dt.dayofweek == 0].rename(columns={"date": "week_start"})
weekly.to_csv(OUT / "trade_clean_weekly.csv", index=False, float_format="%.3f")
print(f"ok    {len(out)} days  -> {OUT / 'trade_clean_daily.csv'}")
print(f"ok    {len(weekly)} weeks -> {OUT / 'trade_clean_weekly.csv'}")
if problems:
    print("CHECK:\n - " + "\n - ".join(problems))