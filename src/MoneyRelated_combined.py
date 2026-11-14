from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

FILES = [
    "CBOE_US_VIX_Volatility_Index_Clean.csv",
    "ECB_EUR_INR_Exchange_Rate_Daily_2020_2026_Clean.csv",
    "ECB_EUR_USD_Exchange_Rate_Daily_2020_2026_Clean.csv",
    "ECB_USD_INR_Exchange_Rate_Daily_2020_2026_Clean.csv",
    "Eurostat_EuroArea_HICP_Inflation_Annual_2020_2026_Clean.csv",
    "Eurostat_EuroArea_HICP_Inflation_Monthly_2020_2026_Clean.csv",
    "FRED_EuroArea_ECB_Deposit_Facility_Rate_2020_2026_Clean.csv",
    "FRED_Global_Brent_Crude_Oil_Price_Daily_2020_2026_Clean.csv",
    "FRED_USD_INR_Exchange_Rate_Daily_2020_2026_Clean.csv",
    "FRED_US_10Y_Treasury_Yield_Daily_2020_2026_Clean.csv",
    "FRED_US_Broad_Dollar_Index_Clean.csv",
    "FRED_US_Henry_Hub_Natural_Gas_Price_Daily_2020_2026_Clean.csv",
    "FRED_US_WTI_Crude_Oil_Price_Daily_2020_2026_Clean.csv",
    "MOSPI_India_CPI_2012_Base_Current_2026_Clean.csv",
    "MOSPI_India_CPI_2012_Base_Historical_Through_2026_Clean.csv",
    "MOSPI_India_CPI_2024_Base_Current_2026_Clean.csv",
    "MOSPI_India_CPI_2024_Base_Historical_Through_2026_Clean.csv",
    "RBI_India_Central_Bank_Balance_Sheet_Clean.csv",
    "RBI_India_Forex_Reserves_Weekly_Clean.csv",
    "RBI_India_Monetary_Policy_Rates_And_Reserve_Requirements_Clean.csv",
    "RBI_India_Reserve_Money_Components_Clean.csv",
    "RBI_INR_Exchange_Rates_Daily_Clean.csv",
    "WorldBank_Global_Commodity_Prices_Monthly_Clean.csv",
]


def load_data(folder: Path) -> pd.DataFrame:
    missing = [filename for filename in FILES if not (folder / filename).is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing expected files in data/interim:\n" +
            "\n".join(f"  - {name}" for name in missing)
        )

    combined = pd.DataFrame()
    for number, filename in enumerate(FILES, start=1):
        frame = pd.read_csv(folder / filename, low_memory=False)
        if "date" not in frame.columns:
            raise ValueError(f"No 'date' column in {filename}")
        if frame.columns.duplicated().any():
            raise ValueError(f"Duplicate column headers in {filename}")

        frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
        if frame["date"].isna().any():
            raise ValueError(f"Blank dates in {filename}")
        if frame["date"].duplicated().any():
            raise ValueError(f"Duplicate date rows in {filename}; please inspect")

        frame = frame.set_index("date").sort_index()
        for column in frame.columns:
            if frame[column].dtype == "object":
                frame[column] = pd.to_numeric(frame[column], errors="raise")

        overlap = combined.columns.intersection(frame.columns)
        for column in overlap:
            old = combined[column]
            new = frame[column]
            a, b = old.align(new, join="inner")
            equal = a.eq(b) | (a.isna() & b.isna())
            conflicts = a.notna() & b.notna() & ~equal
            if conflicts.any():
                examples = [str(day.date()) for day in conflicts[conflicts].index[:5]]
                raise ValueError(
                    f"Conflicting values for '{column}' in '{filename}' "
                    f"on dates {examples}. Resolve manually before merging."
                )

        combined = combined.combine_first(frame)
        print(f"[{number:02d}/{len(FILES)}] Included {filename} ({len(frame):,} rows)")

    combined.index.name = "date"
    return combined.sort_index()


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=root / "data" / "interim")
    parser.add_argument("--output", type=Path,
                        default=root / "data" / "interim" / "MoneyRelated_combined.csv")
    parser.add_argument("--start", type=str, default=None,
                        help="Optional first calendar day: YYYY-MM-DD")
    parser.add_argument("--end", type=str, default=None,
                        help="Optional last calendar day: YYYY-MM-DD")
    parser.add_argument("--no-forward-fill", action="store_true",
                        help="Leave gaps as NaN instead of carrying last value forward")
    args = parser.parse_args()

    combined = load_data(args.input)
    if combined.empty:
        raise ValueError("All input files are empty")

    first = pd.Timestamp(args.start) if args.start else combined.index.min()
    last = pd.Timestamp(args.end) if args.end else combined.index.max()
    if first > last:
        raise ValueError("Start date must not be after end date")

    dates = pd.date_range(min(first, combined.index.min()), last, freq="D", name="date")
    combined = combined.reindex(dates)
    if not args.no_forward_fill:
        combined = combined.ffill()
    combined = combined.loc[first:last]

    if not combined.index.is_unique or combined.columns.duplicated().any():
        raise AssertionError("Merged output has duplicate dates or column names")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(args.output, index=True, date_format="%Y-%m-%d")
    print(f"\nSUCCESS: {args.output}")
    print(f"Files included: {len(FILES)}")
    print(f"Daily rows: {len(combined):,}")
    print(f"Unique indicator columns: {len(combined.columns)}")
    print(f"Date range: {combined.index.min().date()} to {combined.index.max().date()}")
    print("No duplicate dates or columns. Original files were not modified.")


if __name__ == "__main__":
    main()
