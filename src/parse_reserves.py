from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

START = "2019-01-01"
PUBLICATION_LAG_DAYS = 8

# (header text in row 1, unit in row 2) -> our column name
WANTED = {
    ("total reserves", "us $millions"): "total_usd_mn",
    ("foreign currency assets", "us $millions"): "fca_usd_mn",
    ("gold", "us $millions"): "gold_usd_mn",
    ("sdrs", "us $millions"): "sdr_usd_mn",
    ("reserve tranche", "us $millions"): "imf_rtp_usd_mn",
    ("total reserves", "₹ crores"): "total_inr_cr",
}


def read_rbi_table(path: str) -> pd.DataFrame:
    raw = pd.read_excel(path, header=None)

    # find the two header rows: the one containing "Total Reserves" and the units row below it
    hdr = next(i for i in range(min(30, len(raw)))
               if raw.iloc[i].astype(str).str.contains("Total Reserves", case=False).any())
    names = raw.iloc[hdr].ffill()             
    units = raw.iloc[hdr + 1]
    date_col = next(c for c in raw.columns
                    if "week" in str(raw.iloc[hdr, c]).lower() or "year" in str(raw.iloc[hdr, c]).lower())

    cols = {}
    for c in raw.columns:
        n, u = str(names[c]).lower(), str(units[c]).lower().strip()
        for (want_n, want_u), new in WANTED.items():
            if want_n in n and u == want_u and new not in cols.values():
                cols[c] = new
    missing = set(WANTED.values()) - set(cols.values())
    if missing:
        print(f"WARN  columns not found: {missing}")

    body = raw.iloc[hdr + 2:]
    def as_date(v):
        if isinstance(v, (pd.Timestamp,)) or hasattr(v, "year") and hasattr(v, "day"):
            return pd.Timestamp(v)
        s = str(v).strip()
        return pd.to_datetime(s[:10], format="%Y-%m-%d", errors="coerce") if len(s) >= 10 else pd.NaT
    week_end = body[date_col].map(as_date)
    df = body[week_end.notna()][list(cols)].rename(columns=cols)
    df.insert(0, "week_end", week_end[week_end.notna()])
    for c in cols.values():
        df[c] = pd.to_numeric(df[c], errors="coerce")             # '.' / '-' -> NaN
    return df.sort_values("week_end").drop_duplicates("week_end").reset_index(drop=True)


def add_available(df: pd.DataFrame) -> pd.DataFrame:
    df["available_from"] = df["week_end"] + pd.Timedelta(days=PUBLICATION_LAG_DAYS)
    return df


def as_of(df: pd.DataFrame, dates: pd.DatetimeIndex, date_col: str) -> pd.DataFrame:
    base = pd.DataFrame({date_col: dates})
    m = pd.merge_asof(base, df.sort_values("available_from"),
                      left_on=date_col, right_on="available_from", direction="backward")
    return m.drop(columns=["available_from"]).rename(columns={"week_end": "reserves_week_end"})


def main(xlsx: str, start: str, out_dir: str):
    df = add_available(read_rbi_table(xlsx))
    print(f"read  {len(df)} weeks, {df.week_end.min():%Y-%m-%d} to {df.week_end.max():%Y-%m-%d}")

    # missing-week check (every row should be 7 days after the previous one)
    gaps = df[df["week_end"].diff().dt.days.fillna(7) != 7]
    recent_gaps = gaps[gaps["week_end"] >= start]
    if len(recent_gaps):
        print("WARN  gaps since start:", [f"{d:%Y-%m-%d}" for d in recent_gaps["week_end"]])
    else:
        print(f"ok    no missing weeks since {start}")
    days_old = (pd.Timestamp.today() - df["week_end"].max()).days
    if days_old > 14:
        print(f"WARN  newest week is {days_old} days old - download a fresh copy of the table")

    Path("data/raw").mkdir(parents=True, exist_ok=True)
    df.to_csv("data/raw/reserves_weekly_clean.csv", index=False, float_format="%.2f")

    today = pd.Timestamp.today().normalize()
    keep = df[df["week_end"] >= pd.Timestamp(start) - pd.Timedelta(days=60)]   # a little earlier so day 1 has a value
    daily = as_of(keep, pd.date_range(start, today, freq="D"), "date")
    weekly = as_of(keep, pd.date_range(start, today, freq="W-MON"), "week_start")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    daily.to_csv(f"{out_dir}/reserves_daily.csv", index=False, float_format="%.2f")
    weekly.to_csv(f"{out_dir}/reserves_weekly.csv", index=False, float_format="%.2f")

    print(f"\n{len(daily)} days -> {out_dir}/reserves_daily.csv")
    print(f"{len(weekly)} weeks -> {out_dir}/reserves_weekly.csv")
    show = ["week_end", "total_usd_mn", "fca_usd_mn", "gold_usd_mn", "available_from"]
    print("\nlatest weeks (US$ mn):")
    print(df[show].tail(4).to_string(index=False))


if __name__ == "__main__":
    args = sys.argv[1:]
    files = [a for a in args if a.lower().endswith((".xlsx", ".xls"))]
    if not files:
        sys.exit("Usage: python parse_reserves.py <RBI table 33 .xlsx> [--start YYYY-MM-DD] [--out DIR]")
    start = args[args.index("--start") + 1] if "--start" in args else START
    out = args[args.index("--out") + 1] if "--out" in args else "data/interim"
    main(files[0], start, out)