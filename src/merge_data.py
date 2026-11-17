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

# our daily tables
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
    # ECB closing days: 1 Jan, Good Friday, Easter Monday, 1 May, 25 + 26 Dec
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
data["is_ecb_day"] = ((data["date"].dt.day_of_week < 5) & ~data["date"].isin(closed)).astype(int)

#FPI: flow of that exact day (0 = no report that day)
data = data.merge(fpi, on="date", how="left")

#other tables: values as known that day
data = add(data, growth)
data = add(data, risk)
data = add(data, trade)
data = add(data, reserves)

#  ECB rates fixed at the same time as the target -> previous day only
data = add(data, read("ECB_EUR_USD_Exchange_Rate_Daily_2020_2026_Clean"), lag_days=1)
data = add(data, read("ECB_USD_INR_Exchange_Rate_Daily_2020_2026_Clean"), lag_days=1)

# US market closes come after the fixing -> next day 
data = add(data, read("FRED_Global_Brent_Crude_Oil_Price_Daily_2020_2026_Clean"), lag_days=1)
data = add(data, read("FRED_US_10Y_Treasury_Yield_Daily_2020_2026_Clean"), lag_days=1)
data = add(data, read("FRED_US_Broad_Dollar_Index_Clean"), lag_days=1)

# policy rates
data = add(data, read("RBI_India_Monetary_Policy_Rates_And_Reserve_Requirements_Clean"))
data = add(data, read("FRED_EuroArea_ECB_Deposit_Facility_Rate_2020_2026_Clean"))

# uncertainty
data = add(data, read("gpr_clean"), lag_days=1)
data = add(data, read("us_epu_clean"), lag_days=1)
for name in ("gpr_india_clean", "in_epu_clean", "eu_epu_clean"):
    monthly = read(name)
    monthly["date"] = monthly["date"] + pd.offsets.MonthEnd(0)   # month start -> month end
    data = add(data, monthly, lag_days=7)

# calendar
calendar = read("calendar_clean").drop(columns=["de_holiday_name", "in_holiday_name", "is_de_workday",
                                                "days_to_diwali"])
data = data.merge(calendar, on="date", how="left")

# events
events = read("events_clean")
# Since 21 Jul 2022 the ECB announces at 14:15 CET, after the fixing (14:10)
ecb = events["event_type"] == "ecb_decision"
events.loc[ecb, "known_before_fixing"] = (events.loc[ecb, "date"] < "2022-07-21").map({True: "yes", False: "no"})

for event in ("ecb_decision", "rbi_decision", "fomc_decision", "us_cpi", "us_jobs", "india_budget"):
    e = events[events["event_type"] == event]
    # 1 on the day the event is known (a surprise after the fixing counts the next day)
    late_surprise = (e["scheduled"] != "yes") & (e["known_before_fixing"] != "yes")
    known = e["date"] + pd.to_timedelta(late_surprise.astype(int), unit="D")
    data[f"is_{event}_day"] = data["date"].isin(known).astype(int)

# last rate decision in basis points: same day if known before the fixing, else next day
for event in ("ecb_decision", "rbi_decision", "fomc_decision"):
    e = events[(events["event_type"] == event) & events["change_bp"].notna()].copy()
    e["date"] = e["date"] + pd.to_timedelta((e["known_before_fixing"] != "yes").astype(int), unit="D")
    data = add(data, e[["date", "change_bp"]].rename(columns={"change_bp": f"last_{event}_bp"}))

# save
OUT.mkdir(parents=True, exist_ok=True)
data.to_csv(OUT / "data_daily_base.csv", index=False, float_format="%.4f")

print(f"rows {len(data)} (every day), columns {data.shape[1]}, "
      f"{data.date.min():%Y-%m-%d} .. {data.date.max():%Y-%m-%d}")
print(f"ECB days (target filled): {data.is_ecb_day.sum()}, other days: {(data.is_ecb_day == 0).sum()}")
missing = data.drop(columns="eur_inr").isna().sum()
print("missing values per column (target not counted):", missing[missing > 0].to_dict() or "none")
print(f"saved {OUT / 'data_daily_base.csv'}")

# checks
for name, table in (("target", target), ("fpi", fpi), ("growth", growth), ("risk", risk),
                    ("trade", trade), ("reserves", reserves)):
    assert not table["date"].duplicated().any(), f"{name}: duplicate dates in the source"
    print(f"source {name:9s} last date {table['date'].max():%Y-%m-%d}")
assert not data["date"].duplicated().any(), "duplicate dates in the merged file"
assert data.loc[data["eur_inr"].notna(), "is_ecb_day"].eq(1).all(), "a fixing on a non-ECB day"
gap = data[(data["date"] > target["date"].max()) & (data["is_ecb_day"] == 1)]
if len(gap):
    print(f"note: {len(gap)} ECB days after {target['date'].max():%Y-%m-%d} have no fixing yet")