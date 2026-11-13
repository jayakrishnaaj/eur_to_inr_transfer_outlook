from pathlib import Path

import pandas as pd

IN = Path("data/interim")
OUT = Path("data/processed")
START = "2020-01-01"


def read(name):
    df = pd.read_csv(IN / f"{name}.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df


def add(base, df, lag_days=0):
    df = df.dropna(subset=[c for c in df.columns if c != "date"], how="all")
    df = df.assign(known_from=df["date"] + pd.Timedelta(days=lag_days)).drop(columns="date")
    return pd.merge_asof(base, df.sort_values("known_from"), left_on="date",
                         right_on="known_from").drop(columns="known_from")


# target
target = read("ECB_EUR_INR_Exchange_Rate_Daily_2020_2026_Clean").rename(
    columns={"eur_inr_inr_per_eur": "eur_inr"})

# daily tables
fpi = read("fpi_clean_daily").drop(columns=["fpi_report_day", "usdinr_nsdl"])
growth = read("growth_clean_daily")
risk = read("risk_clean_daily")
trade = read("trade_clean_daily")
reserves = read("reserves_daily").drop(columns=["reserves_week_end"])
end = min(max(t["date"].max() for t in (target, fpi, growth, risk, trade, reserves)),
          pd.Timestamp.today().normalize())

# one row per calendar day
data = pd.DataFrame({"date": pd.date_range(START, end, freq="D")})
data = data.merge(target, on="date", how="left")


def ecb_holidays(year):
    # ECB (TARGET) closing days: 1 Jan, Good Friday, Easter Monday, 1 May, 25 + 26 Dec
    a, b, c = year % 19, year // 100, year % 100          
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    easter = pd.Timestamp(year, month, day + 1)
    return {pd.Timestamp(year, 1, 1), easter - pd.Timedelta(days=2), easter + pd.Timedelta(days=1),
            pd.Timestamp(year, 5, 1), pd.Timestamp(year, 12, 25), pd.Timestamp(year, 12, 26)}


closed = set().union(*(ecb_holidays(y) for y in range(2020, end.year + 1)))
data["is_ecb_day"] = ((data["date"].dt.dayofweek < 5) & ~data["date"].isin(closed)).astype(int)
# last EUR/INR published BEFORE this day
data = add(data, target.rename(columns={"eur_inr": "eur_inr_prev"}), lag_days=1)

flows = [c for c in fpi.columns if c.endswith("_day")]
data = data.merge(fpi[["date"] + flows], on="date", how="left")    
data = add(data, fpi.drop(columns=flows))                          
data = add(data, growth)
data = add(data, risk)
data = add(data, trade)
data = add(data, reserves)

# ECB rates fixed at the same time as the target -> previous day only 
data = add(data, read("ECB_EUR_USD_Exchange_Rate_Daily_2020_2026_Clean"), lag_days=1)
data = add(data, read("ECB_USD_INR_Exchange_Rate_Daily_2020_2026_Clean"), lag_days=1)

# US market closes come after 14:15 CET -> next day 
data = add(data, read("FRED_Global_Brent_Crude_Oil_Price_Daily_2020_2026_Clean"), lag_days=1)
data = add(data, read("FRED_US_10Y_Treasury_Yield_Daily_2020_2026_Clean"), lag_days=1)
data = add(data, read("FRED_US_Broad_Dollar_Index_Clean"), lag_days=1)

# policy rates: changes are announced before they take effect 
data = add(data, read("RBI_India_Monetary_Policy_Rates_And_Reserve_Requirements_Clean"))
data = add(data, read("FRED_EuroArea_ECB_Deposit_Facility_Rate_2020_2026_Clean"))
data["rate_gap_in_ea"] = data["rbi_repo_rate_pct"] - data["ecb_deposit_rate_pct"]

# uncertainty: daily indices next day, monthly ones ~a week after month end
data = add(data, read("gpr_clean"), lag_days=1)
data = add(data, read("us_epu_clean"), lag_days=1)
for name in ("gpr_india_clean", "in_epu_clean", "eu_epu_clean"):
    monthly = read(name)
    monthly["date"] = monthly["date"] + pd.offsets.MonthEnd(0)   # month start -> month end
    data = add(data, monthly, lag_days=7)

# calendar: known in advance 
calendar = read("calendar_clean").drop(columns=["de_holiday_name", "in_holiday_name", "is_de_workday"])
data = data.merge(calendar, on="date", how="left")

# events -> daily features 
events = read("events_clean")
ecb = events["event_type"] == "ecb_decision"
events.loc[ecb, "known_before_fixing"] = (events.loc[ecb, "date"] < "2022-07-21").map({True: "yes", False: "no"})

for event in ("ecb_decision", "rbi_decision", "fomc_decision", "us_cpi", "us_jobs", "india_budget"):
    e = events[events["event_type"] == event]
    late_surprise = (e["scheduled"] != "yes") & (e["known_before_fixing"] != "yes")
    known = e["date"] + pd.to_timedelta(late_surprise.astype(int), unit="D")
    data[f"is_{event}_day"] = data["date"].isin(known).astype(int) 
    if event != "india_budget":  
        upcoming = e[e["scheduled"] == "yes"][["date"]].rename(columns={"date": "next_event"})
        nxt = pd.merge_asof(data[["date"]], upcoming.sort_values("next_event"),
                            left_on="date", right_on="next_event", direction="forward")
        data[f"days_to_{event}"] = (nxt["next_event"] - data["date"]).dt.days

for event in ("ecb_decision", "rbi_decision", "fomc_decision"):
    e = events[(events["event_type"] == event) & events["change_bp"].notna()].copy()
    e["date"] = e["date"] + pd.to_timedelta((e["known_before_fixing"] != "yes").astype(int), unit="D")
    data = add(data, e[["date", "change_bp"]].rename(columns={"change_bp": f"last_{event}_bp"}))

# "since the previous fixing" versions 
since_prev_fix = data["is_ecb_day"].shift(fill_value=0).cumsum()   # new block after each fixing day
cols = flows + [c for c in data.columns if c.startswith("is_") and c.endswith("_day") and c != "is_ecb_day"]
since = data.groupby(since_prev_fix)[cols].cumsum(skipna=False).add_suffix("_since_fix")
data = pd.concat([data, since], axis=1)


OUT.mkdir(parents=True, exist_ok=True)
data.to_csv(OUT / "data_daily.csv", index=False, float_format="%.4f")

print(f"rows {len(data)} (every day), columns {data.shape[1]}, "
      f"{data.date.min():%Y-%m-%d} .. {data.date.max():%Y-%m-%d}")
print(f"ECB days (target filled): {data.is_ecb_day.sum()}, other days: {(data.is_ecb_day == 0).sum()}")
print(f"duplicate dates: {data.date.duplicated().sum()}")
missing = data.drop(columns="eur_inr").isna().sum()
print("missing values per column (target not counted):", missing[missing > 0].to_dict() or "none")
print(f"saved {OUT / 'data_daily.csv'}")

# checks
for name, table in (("target", target), ("fpi", fpi), ("growth", growth), ("risk", risk),
                    ("trade", trade), ("reserves", reserves)):
    assert not table["date"].duplicated().any(), f"{name}: duplicate dates in the source"
    print(f"source {name:9s} last date {table['date'].max():%Y-%m-%d}")
assert data.loc[data["eur_inr"].notna(), "is_ecb_day"].eq(1).all(), "a fixing on a non-ECB day"
last_fix = target["date"].max()
gap = data[(data["date"] > last_fix) & (data["is_ecb_day"] == 1)]
if len(gap):
    print(f"note: {len(gap)} ECB days after {last_fix:%Y-%m-%d} have no fixing yet - "
          f"use rows with eur_inr for training (or update the ECB source)")