

from pathlib import Path

import numpy as np
import pandas as pd

IN = Path("data/processed/data_daily.csv")
OUT = Path("data/processed/features_ecb_clean.csv")
GAP_LOG = Path("docs/gap_log.csv")
START = "2020-01-08"           

full = pd.read_csv(IN, parse_dates=["date"])
rate_days = full[full["eur_inr"].notna()].reset_index(drop=True)

df = rate_days[rate_days["date"] >= START].reset_index(drop=True)


since = [c for c in df.columns if c.endswith("_since_fix")]
plain_twins = [c.replace("_since_fix", "") for c in since]       
constant = [c for c in df.columns if c != "date" and df[c].nunique(dropna=False) <= 1]
df = df.drop(columns=plain_twins + constant)


groups = {
    "target":       ["eur_inr", "eur_inr_prev"],
    "markets":      ["eur_usd_usd_per_eur", "usd_inr_inr_per_usd", "brent_usd_per_barrel",
                     "us_10y_treasury_yield_pct", "broad_usd_index_2006_100",
                     "rbi_repo_rate_pct", "ecb_deposit_rate_pct", "rate_gap_in_ea"],
    "fpi":          [c for c in df.columns if c.startswith("fpi_")],
    "growth":       [c for c in df.columns if c.startswith(("ea_esi", "ea_gdp", "ea_hicp",
                     "ea_unemployment", "in_cpi", "in_gdp", "in_iip", "in_ea_"))],
    "risk":         [c for c in df.columns if c.startswith(("vix", "baa_spread"))],
    "trade":        [c for c in df.columns if c.startswith(("ea_current", "ea_goods", "india_"))],
    "reserves":     ["total_inr_cr", "total_usd_mn", "fca_usd_mn", "gold_usd_mn", "sdr_usd_mn",
                     "imf_rtp_usd_mn", "ex_gold_usd_mn", "total_chg_1w", "total_chg_4w",
                     "fca_chg_1w", "fca_chg_4w", "ex_gold_chg_1w", "ex_gold_chg_4w"],
    "uncertainty":  ["gpr", "us_epu", "gpr_india", "in_epu", "eu_epu"],
    "calendar":     ["weekday", "day_of_month", "month", "is_de_holiday", "is_in_holiday",
                     "is_payday_window", "is_diwali", "days_to_diwali", "is_december",
                     "is_india_fy_end"],
    "events":       [c for c in df.columns if c.startswith(("days_to_", "last_"))
                     and c != "days_to_diwali"] + [c for c in df.columns if c.endswith("_since_fix")
                     and c.startswith("is_")],
}
ordered = ["date"] + [c for cols in groups.values() for c in cols]
assert sorted(ordered) == sorted(df.columns), \
    f"column not assigned to a group: {set(df.columns) ^ set(ordered)}"
df = df[ordered]


ints = [c for c in df.columns if c.startswith(("is_", "days_to_", "last_"))] + \
       ["weekday", "day_of_month", "month"]
df[ints] = df[ints].astype(int)

WARMUP_COLS = ["fpi_equity_4w", "fpi_debt_4w", "fpi_total_4w"]
gaps = df.drop(columns=WARMUP_COLS).isna().sum()
assert gaps.sum() == 0, f"missing values left: {gaps[gaps > 0].to_dict()}"
assert df.loc[df["date"] > "2020-01-28", WARMUP_COLS].notna().all().all(), "4-week FPI gap after January"
assert not df["date"].duplicated().any(), "duplicate dates"
assert df["date"].is_monotonic_increasing, "dates not sorted"
assert (df["date"].dt.day_of_week < 5).all(), "weekend row"
assert (df["date"] >= START).all()
prev = pd.concat([rate_days.loc[rate_days["date"] < START, "eur_inr"].tail(1),
                  df["eur_inr"].iloc[:-1]], ignore_index=True)
assert np.allclose(df["eur_inr_prev"], prev), "eur_inr_prev is not the previous fixing"
assert (df["weekday"] == df["date"].dt.day_of_week).all()
assert (df["day_of_month"] == df["date"].dt.day).all()
assert (df["month"] == df["date"].dt.month).all()
assert (df["is_december"] == (df["month"] == 12)).all()
flags = [c for c in df.columns if c.startswith("is_")]
assert df[flags].isin([0, 1]).all().all(), "flag outside 0/1"
assert (df[[c for c in df.columns if c.startswith("days_to_")]] >= 0).all().all()
assert (df[[c for c in df.columns if c.startswith("last_")]] % 5 == 0).all().all()
positive = ["eur_inr", "eur_inr_prev", "eur_usd_usd_per_eur", "usd_inr_inr_per_usd",
            "brent_usd_per_barrel", "broad_usd_index_2006_100", "vix", "baa_spread",
            "gpr", "us_epu", "gpr_india", "in_epu", "eu_epu", "total_usd_mn"]
assert (df[positive] > 0).all().all(), "non-positive value in a positive-only column"
for c in [c for c in flags if c.endswith("_since_fix")]:
    raw = c.replace("_since_fix", "")
    after_start = full.loc[full["date"] > rate_days.loc[rate_days["date"] < START, "date"].max(), raw]
    after_start = after_start[full["date"] <= df["date"].max()]
    assert df[c].sum() == after_start.sum(), f"{c}: events lost or double-counted"

dropped_rows = rate_days[rate_days["date"] < START]
log = []
for c in full.columns.drop("date"):
    on_rate_days = int(rate_days[c].isna().sum()) if c in rate_days else 0
    in_dropped = int(dropped_rows[c].isna().sum()) if c in dropped_rows else 0
    if c in df.columns:
        action = "kept"
    elif c in plain_twins:
        action = f"dropped: replaced by {c}_since_fix (includes weekend/holiday values)"
    elif c in constant:
        action = "dropped: constant on ECB days"
    else:
        action = "dropped"
    log.append({"column": c,
                "missing_on_all_days": int(full[c].isna().sum()),
                "missing_on_rate_days": on_rate_days,
                "of_which_before_" + START: in_dropped,
                "missing_in_clean_file": int(df[c].isna().sum()) if c in df else "",
                "action": action})
log = pd.DataFrame(log)
log.loc[log["column"] == "eur_inr", "action"] = (
    "target: rows without a rate (weekends, ECB holidays, days after the last fixing) removed")

OUT.parent.mkdir(parents=True, exist_ok=True)
GAP_LOG.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(OUT, index=False, float_format="%.4f")
log.to_csv(GAP_LOG, index=False)

print(f"input : {len(full)} calendar days, {len(rate_days)} with a rate, {full.shape[1]} columns")
print(f"output: {len(df)} ECB fixings ({df.date.min():%Y-%m-%d} .. {df.date.max():%Y-%m-%d}), "
      f"{df.shape[1]} columns, {int(df.isna().sum().sum())} missing values (4-week FPI warm-up only)")
print(f"rows dropped: {len(full) - len(rate_days)} without a rate, "
      f"{len(dropped_rows)} before {START} (first week, warm-up)")
print(f"columns dropped: {plain_twins + constant}")
print("columns per group:", {g: len(c) for g, c in groups.items()})
print("events on rate days:", {c.replace('_day_since_fix', ''): int(df[c].sum())
                               for c in flags if c.endswith('_since_fix')})
print(f"all checks passed -> saved {OUT} and {GAP_LOG}")
