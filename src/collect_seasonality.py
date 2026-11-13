import os
import pandas as pd
import holidays

os.makedirs("data/interim", exist_ok=True)

START, END = "2019-01-01", "2027-12-31"   
YEARS = range(2019, 2029)                 # one extra year so "days until next Diwali" works at the end

de_hol = holidays.country_holidays("DE", years=YEARS)   # German national holidays
in_hol = holidays.country_holidays("IN", years=YEARS)   # Indian holidays (incl. Diwali)

cal = pd.DataFrame({"date": pd.date_range(START, END, freq="D")})
d = cal["date"].dt

cal["weekday"] = d.dayofweek                 # 0 = Monday ... 6 = Sunday
cal["day_of_month"] = d.day
cal["month"] = d.month
cal["is_weekend"] = (cal["weekday"] >= 5).astype(int)

cal["de_holiday_name"] = cal["date"].map(lambda x: de_hol.get(x.date(), ""))
cal["in_holiday_name"] = cal["date"].map(lambda x: in_hol.get(x.date(), ""))
cal["is_de_holiday"] = (cal["de_holiday_name"] != "").astype(int)
cal["is_in_holiday"] = (cal["in_holiday_name"] != "").astype(int)

cal["is_de_workday"] = ((cal["is_weekend"] == 0) & (cal["is_de_holiday"] == 0)).astype(int)
cal["ym"] = d.to_period("M")
workdays = cal[cal["is_de_workday"] == 1].copy()
workdays["rank_from_end"] = workdays.groupby("ym").cumcount(ascending=False) + 1
cal["is_payday_window"] = cal["date"].isin(
    workdays.loc[workdays["rank_from_end"] <= 3, "date"]).astype(int)

diwali = sorted(pd.Timestamp(day) for day, name in in_hol.items() if "Diwali" in name)
cal["is_diwali"] = cal["date"].isin(diwali).astype(int)
cal["days_to_diwali"] = cal["date"].map(
    lambda x: next((dw - x).days for dw in diwali if dw >= x))

cal["is_december"] = (cal["month"] == 12).astype(int)            # holiday season, year-end
cal["is_india_fy_end"] = ((cal["month"] == 3) & (cal["day_of_month"] >= 25)).astype(int)  # India's financial year ends 31 March

cal = cal.drop(columns=["ym"])

print(f"Rows: {len(cal)} days from {cal['date'].min().date()} to {cal['date'].max().date()}")

print("\nHolidays per year:")
print(cal.groupby(cal["date"].dt.year)[["is_de_holiday", "is_in_holiday"]].sum())

print("\nDiwali dates (check two of them against a calendar):")
print([x.date().isoformat() for x in diwali if x.year <= 2027])

per_month = cal.groupby(cal["date"].dt.to_period("M"))["is_payday_window"].sum()
print(f"\nPayday-window days per month: always 3? {bool((per_month == 3).all())}")

print("\nExample: the last days of October 2026")
print(cal[(cal["date"] >= "2026-10-26") & (cal["date"] <= "2026-11-09")]
      [["date", "weekday", "is_de_holiday", "is_payday_window", "is_diwali", "days_to_diwali"]]
      .to_string(index=False))

cal.to_csv("data/interim/calendar_clean.csv", index=False)
print("\nSaved data/interim/calendar_clean.csv")
