"""Combining the money related csv togeter after changing the data to daily"""
from __future__ import annotations
import argparse
import re
from pathlib import Path
import pandas as pd

DAILY_FILES = [
    "Eurostat_EuroArea_HICP_Inflation_Annual_2020_2026_Daily.csv",
    "Eurostat_EuroArea_HICP_Inflation_Monthly_2020_2026_Daily.csv",
    "MOSPI_India_CPI_2012_Base_Current_2026_Daily.csv",
    "MOSPI_India_CPI_2012_Base_Historical_Through_2026_Daily.csv",
    "MOSPI_India_CPI_2024_Base_Current_2026_Daily.csv",
    "MOSPI_India_CPI_2024_Base_Historical_Through_2026_Daily.csv",
    "RBI_India_Monetary_Policy_Rates_And_Reserve_Requirements_Daily.csv",
    "RBI_India_Reserve_Money_Components_Daily.csv",
    "WorldBank_Monthly_Indices_Daily.csv",
    "WorldBank_Monthly_Prices_Daily.csv",
    "RBI_India_Forex_Reserves_Weekly_Clean_Daily.csv",
]
CLEAN_FILES = [
    "CBOE_US_VIX_Volatility_Index_Clean.csv",
    "ECB_EUR_INR_Exchange_Rate_Daily_2020_2026_Clean.csv",
    "ECB_EUR_USD_Exchange_Rate_Daily_2020_2026_Clean.csv",
    "ECB_USD_INR_Exchange_Rate_Daily_2020_2026_Clean.csv",
    "FRED_EuroArea_ECB_Deposit_Facility_Rate_2020_2026_Clean.csv",
    "FRED_Global_Brent_Crude_Oil_Price_Daily_2020_2026_Clean.csv",
    "FRED_USD_INR_Exchange_Rate_Daily_2020_2026_Clean.csv",
    "FRED_US_10Y_Treasury_Yield_Daily_2020_2026_Clean.csv",
    "FRED_US_Broad_Dollar_Index_Clean.csv",
    "FRED_US_Henry_Hub_Natural_Gas_Price_Daily_2020_2026_Clean.csv",
    "FRED_US_WTI_Crude_Oil_Price_Daily_2020_2026_Clean.csv",
    "RBI_India_Central_Bank_Balance_Sheet_Clean.csv",
    "RBI_INR_Exchange_Rates_Daily_Clean.csv",
]


PREFIXES = {
    "Eurostat_EuroArea_HICP_Inflation_Annual_2020_2026_Daily.csv": "eurostat_hicp_annual",
    "Eurostat_EuroArea_HICP_Inflation_Monthly_2020_2026_Daily.csv": "eurostat_hicp_monthly",
    "MOSPI_India_CPI_2012_Base_Current_2026_Daily.csv": "mospi_2012_current",
    "MOSPI_India_CPI_2012_Base_Historical_Through_2026_Daily.csv": "mospi_2012_historical",
    "MOSPI_India_CPI_2024_Base_Current_2026_Daily.csv": "mospi_2024_current",
    "MOSPI_India_CPI_2024_Base_Historical_Through_2026_Daily.csv": "mospi_2024_historical",
    "RBI_India_Monetary_Policy_Rates_And_Reserve_Requirements_Daily.csv": "rbi_policy",
    "RBI_India_Reserve_Money_Components_Daily.csv": "rbi_reserve_money",
    "WorldBank_Monthly_Indices_Daily.csv": "worldbank_indices",
    "WorldBank_Monthly_Prices_Daily.csv": "worldbank_prices",
    "RBI_India_Forex_Reserves_Weekly_Clean_Daily.csv": "rbi_forex_reserves",
}


def slug(value: object) -> str:
    """Sanitize labels while preserving distinguishing names."""
    s = str(value).strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_") or "na"


def checked_dates(frame: pd.DataFrame, filename: str) -> pd.DataFrame:
    if "date" not in frame:
        raise ValueError(f"Missing date column: {filename}")
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    if frame["date"].isna().any():
        raise ValueError(f"Null date found in {filename}")
    return frame


def unique_date_index(frame: pd.DataFrame, filename: str) -> pd.DataFrame:
    frame = checked_dates(frame, filename)
    if frame["date"].duplicated().any():
        raise ValueError(f"{filename} has multiple rows for the same date. "
                         "Use a dimension-aware conversion; do not drop duplicates.")
    return frame.set_index("date").sort_index()


def cpi_filter(frame: pd.DataFrame, base: int, detail: str) -> pd.DataFrame:
    if detail == "all":
        return frame
    selection = (frame["state"].astype("string").str.casefold() == "all india") & (
        frame["sector"].astype("string").str.casefold() == "combined")
    if base == 2012:
        selection &= (frame["group"].astype("string").str.casefold() == "general") & (
            frame["subgroup"].astype("string").str.casefold() == "general-overall")
    else:
        selection &= (frame["division"].astype("string").str.casefold() == "cpi (general)")
    return frame.loc[selection].copy()


def load_cpi(path: Path, detail: str) -> pd.DataFrame:
    """Read giant long-form CPI files in chunks, then pivot safely by dimensions."""
    filename = path.name
    prefix = PREFIXES[filename]
    base = 2012 if "2012_Base" in filename else 2024
    dims = (["baseyear", "state", "sector", "group", "subgroup"] if base == 2012 else
            ["base_year", "series", "state", "sector", "division", "group",
             "class", "sub_class", "item", "code"])
    value_cols = ["index", "inflation"]
    # Keep the data useful for modelling: status/imputation are metadata, not rates.
    pieces = []
    for chunk in pd.read_csv(path, chunksize=100_000, low_memory=False):
        required = ["date", *dims, *value_cols]
        absent = set(required) - set(chunk.columns)
        if absent:
            raise ValueError(f"{filename}: missing {sorted(absent)}")
        chunk = cpi_filter(chunk, base, detail)
        if chunk.empty:
            continue
        chunk = chunk[required].copy()
        pieces.append(chunk)
    if not pieces:
        raise ValueError(f"{filename}: no CPI data matches the selection")
    raw = checked_dates(pd.concat(pieces, ignore_index=True), filename)
    if detail == "headline":
        values = raw[["date", *value_cols]]
        values = unique_date_index(values, filename)
        return values.rename(columns={v: f"{prefix}_{v}" for v in value_cols})

    # Each dimension tuple is its own feature. Never accidentally take the
    # first of distinct series sharing a date.
    for col in dims:
        raw[col] = raw[col].astype("string").fillna("na").str.strip()
    raw["series_key"] = raw[dims].agg("|".join, axis=1)
    if raw.duplicated(["date", "series_key"]).any():
        bad = raw.loc[raw.duplicated(["date", "series_key"], keep=False),
                      ["date", "series_key"]].head(5)
        raise ValueError(f"Duplicate CPI date/dimension in {filename}:\n{bad}")
    # Pivot one feature at a time to limit peak memory.
    outputs = []
    for metric in value_cols:
        wide = raw.pivot(index="date", columns="series_key", values=metric)
        wide.columns = [f"{prefix}_{metric}__{slug(k)}" for k in wide.columns]
        if wide.columns.duplicated().any():
            raise ValueError(f"Ambiguous CPI column slugs in {filename}")
        outputs.append(wide)
    return pd.concat(outputs, axis=1).sort_index()


def load_eurostat(path: Path) -> pd.DataFrame:
    """Eurostat has a row per geography and date; pivot geography into columns."""
    filename = path.name
    prefix = PREFIXES[filename]
    df = checked_dates(pd.read_csv(path, low_memory=False), filename)
    if df.duplicated(["date", "geo"]).any():
        raise ValueError(f"Duplicate Eurostat geography/date: {filename}")
    wide = df.pivot(index="date", columns="geo", values="rate")
    wide.columns = [f"{prefix}_{slug(c)}" for c in wide.columns]
    if wide.columns.duplicated().any():
        raise ValueError(f"Duplicated Eurostat geography names: {filename}")
    return wide.sort_index()


def load_regular(path: Path, is_daily: bool) -> pd.DataFrame:
    filename = path.name
    df = pd.read_csv(path, low_memory=False)
    # 'observation_date' is provenance metadata, not a model indicator;
    # retain source values without duplicate observation-date columns.
    df = df.drop(columns=["observation_date"], errors="ignore")
    df = unique_date_index(df, filename)
    if is_daily:
        prefix = PREFIXES[filename]
        df = df.rename(columns={c: f"{prefix}_{slug(c)}" for c in df.columns})
    # Existing cleaned names are already descriptive; keep them unchanged.
    return df


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interim", type=Path, default=project_root / "data" / "interim")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--start", default=None, help="YYYY-MM-DD; defaults to first date")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD; defaults to last date")
    parser.add_argument("--cpi-detail", choices=["headline", "all"], default="headline",
                        help="headline: All India Combined General; all: every CPI dimension")
    args = parser.parse_args()
    interim = args.interim.resolve()
    output = args.output or interim / "MoneyRelated_combined_daily.csv"

    located = []
    for filename in DAILY_FILES:
        path = interim / "daily" / filename
        if not path.is_file():
            # Accommodate older interim folder layouts without moving files.
            path = interim / filename
        located.append((filename, path, True))
    for filename in CLEAN_FILES:
        located.append((filename, interim / filename, False))
    missing = [str(p) for _, p, _ in located if not p.is_file()]
    if missing:
        raise FileNotFoundError("Missing input CSV files:\n" + "\n".join(missing))

    frames = []
    taken_cols = set()
    for number, (filename, path, is_daily) in enumerate(located, 1):
        if is_daily and filename.startswith("MOSPI_"):
            df = load_cpi(path, args.cpi_detail)
        elif is_daily and filename.startswith("Eurostat_"):
            df = load_eurostat(path)
        else:
            df = load_regular(path, is_daily)
        if df.index.duplicated().any() or df.columns.duplicated().any():
            raise ValueError(f"Duplicate dates or indicator names in {filename}")
        overlap = taken_cols.intersection(df.columns)
        if overlap:
            raise ValueError(f"Duplicate feature names from {filename}: {sorted(overlap)[:10]}")
        taken_cols.update(df.columns)
        frames.append(df)
        print(f"[{number:02d}/24] {filename}: {len(df):,} dates, {len(df.columns):,} features")

    # Join on dates (not by row number). Different sources have different date ranges.
    combined = pd.concat(frames, axis=1, join="outer").sort_index()
    begin = pd.Timestamp(args.start) if args.start else combined.index.min()
    finish = pd.Timestamp(args.end) if args.end else combined.index.max()
    if begin > finish:
        raise ValueError("--start must be on or before --end")
    # Reindex before forward filling, so earlier observations remain available
    # when the user chooses a later start date. Never backfill into the past.
    idx = pd.date_range(min(begin, combined.index.min()), finish, freq="D", name="date")
    combined = combined.reindex(idx).ffill().loc[begin:finish]
    if not combined.index.is_unique or not combined.columns.is_unique:
        raise AssertionError("Duplicate date or feature in output")
    output.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output, index_label="date", date_format="%Y-%m-%d")
    print(f"\nSUCCESS: {output}\nSource files: 24\nDaily rows: {len(combined):,}"
          f"\nDistinct features: {len(combined.columns):,}\nNo duplicate dates or columns.")
    print("NOTE: Values use observation dates, not confirmed publication dates.")


if __name__ == "__main__":
    main()
