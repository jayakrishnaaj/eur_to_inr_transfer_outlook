from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT_ROOT / "data" / "raw" / "currency" / "RBI_India_Reserve_Money_Components.xlsx"
OUTPUT = PROJECT_ROOT / "data" / "interim" / "RBI_India_Reserve_Money_Components_Clean.csv"
REPORT = PROJECT_ROOT / "reports" / "quality" / "RBI_India_Reserve_Money_Components_Quality.csv"
START_DATE = pd.Timestamp("2020-01-01")
END_DATE = pd.Timestamp("2026-10-29")
SHEET_NAME = "Report(i)"

COLUMNS = [
    "date",
    "rbi_reserve_money_inr_mn",
    "rbi_currency_in_circulation_inr_mn",
    "rbi_bankers_deposits_inr_mn",
    "rbi_other_deposits_inr_mn",
    "rbi_net_credit_government_inr_mn",
    "rbi_credit_banks_inr_mn",
    "rbi_credit_commercial_sector_inr_mn",
    "rbi_net_foreign_exchange_assets_inr_mn",
    "rbi_government_currency_liabilities_inr_mn",
    "rbi_net_nonmonetary_liabilities_inr_mn",
]


def parse_source_dates(values: pd.Series) -> pd.Series:
    """Handle Excel date cells, Excel serials, and text dates separately."""
    result = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    numeric = pd.to_numeric(values, errors="coerce")
    serial_rows = numeric.notna() & ~values.map(lambda v: isinstance(v, (pd.Timestamp,)))
    # Numeric source cells must represent plausible Excel calendar dates.
    if serial_rows.any():
        plausible = numeric.loc[serial_rows].between(20000, 80000)
        if not plausible.all():
            raise ValueError(
                "Invalid Excel date serial(s): "
                f"{numeric.loc[serial_rows][~plausible].head(5).tolist()}"
            )
        result.loc[serial_rows] = pd.to_datetime(
            numeric.loc[serial_rows], unit="D", origin="1899-12-30", errors="coerce"
        )

    nonserial = ~serial_rows & values.notna()
    if nonserial.any():
        result.loc[nonserial] = pd.to_datetime(
            values.loc[nonserial].astype("string").str.strip(),
            format="mixed",
            errors="coerce",
            dayfirst=False,
        )
    return result


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Source workbook not found: {SOURCE}")

    # Workbook: rows 1-7 contain titles/headers; data begins at row 8.
    raw = pd.read_excel(
        SOURCE,
        sheet_name=SHEET_NAME,
        header=None,
        usecols="B:L",
        skiprows=7,
        dtype=object,
        engine="openpyxl",
    )
    if raw.shape[1] != len(COLUMNS):
        raise ValueError(f"Expected {len(COLUMNS)} columns; found {raw.shape[1]}")
    raw.columns = COLUMNS
    raw_rows = len(raw)
    if raw.empty:
        raise ValueError("The RBI worksheet contains no rows after its headers")

    dates = parse_source_dates(raw["date"])
    # Exclude empty lines and explicitly recognized explanatory/footer lines only.
    # The RBI workbook includes a footer labelled "See Notes on Tables".
    source_text = raw["date"].astype("string").str.strip().fillna("")
    invalid_rows = dates.isna()
    recognized_notes = source_text.str.match(
        r"(?i)^(?:notes?\s*[:.]|source\s*[:.]|see\s+notes\s+on\s+tables\s*$|\*|\s*$)", na=False
    )
    unexpected = invalid_rows & ~recognized_notes
    if unexpected.any():
        raise ValueError(
            "Unrecognized non-date rows in the RBI worksheet: "
            f"{source_text.loc[unexpected].head(5).tolist()}"
        )
    excluded_note_rows = int((invalid_rows & recognized_notes).sum())

    data = raw.loc[~invalid_rows].copy()
    data["date"] = dates.loc[data.index]
    if data.empty:
        raise ValueError("No dated RBI observations found")

    # Parentheses denote negative values in some Excel exports; negative
    # amounts are permitted for net balance-sheet components.
    for col in COLUMNS[1:]:
        tokens = data[col].astype("string").str.strip()
        tokens = tokens.replace({"": pd.NA, "-": pd.NA, ".": pd.NA, "NA": pd.NA, "N/A": pd.NA})
        tokens = tokens.str.replace(",", "", regex=False)
        tokens = tokens.str.replace(r"^\((.+)\)$", r"-\1", regex=True)
        parsed = pd.to_numeric(tokens, errors="coerce")
        bad = tokens.notna() & parsed.isna()
        if bad.any():
            raise ValueError(
                f"Unexpected numeric value(s) in {col}: "
                f"{tokens.loc[bad].head(5).tolist()}"
            )
        data[col] = parsed.astype("float64")

    duplicate_dates = int(data["date"].duplicated().sum())
    conflicting = data.groupby("date")[COLUMNS[1:]].nunique(dropna=False).gt(1).any(axis=1)
    if conflicting.any():
        raise ValueError(
            "Conflicting values for duplicate RBI dates: "
            f"{conflicting[conflicting].index.strftime('%Y-%m-%d').tolist()[:5]}"
        )
    data = data.sort_values("date").drop_duplicates("date", keep="first")
    valid_unique_rows = len(data)
    source_date_min = data["date"].min().date().isoformat()
    source_date_max = data["date"].max().date().isoformat()

    in_period = data["date"].between(START_DATE, END_DATE)
    out_of_range = int((~in_period).sum())
    data = data.loc[in_period, COLUMNS].reset_index(drop=True)
    if data.empty:
        raise ValueError("No RBI observations within the selected study period")

    # Gaps are informational: some RBI series have weekly or semi-monthly dates.
    gap_days = data["date"].diff().dt.days
    flagged_gaps = [
        f"{date:%Y-%m-%d} ({int(days)} days)"
        for date, days in zip(data.loc[gap_days.gt(7), "date"], gap_days[gap_days.gt(7)])
    ]
    missing = {col: int(data[col].isna().sum()) for col in COLUMNS[1:]}

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(OUTPUT, index=False, date_format="%Y-%m-%d", float_format="%.10g", na_rep="")

    report_rows = [
        {"metric": "dataset", "value": "RBI India Reserve Money Components"},
        {"metric": "source", "value": str(SOURCE.relative_to(PROJECT_ROOT))},
        {"metric": "processed", "value": str(OUTPUT.relative_to(PROJECT_ROOT))},
        {"metric": "sheet", "value": SHEET_NAME},
        {"metric": "source_units", "value": "INR million (all numeric columns)"},
        {"metric": "raw_rows", "value": raw_rows},
        {"metric": "excluded_notes_or_blank_rows", "value": excluded_note_rows},
        {"metric": "valid_unique_dated_source_rows", "value": valid_unique_rows},
        {"metric": "source_date_min", "value": source_date_min},
        {"metric": "source_date_max", "value": source_date_max},
        {"metric": "processed_rows", "value": len(data)},
        {"metric": "processed_date_min", "value": data["date"].min().date().isoformat()},
        {"metric": "processed_date_max", "value": data["date"].max().date().isoformat()},
        {"metric": "duplicate_dates_removed", "value": duplicate_dates},
        {"metric": "out_of_range_observations_excluded", "value": out_of_range},
        *({"metric": f"missing_{col}", "value": count} for col, count in missing.items()),
        {
            "metric": "gaps_longer_than_7_calendar_days",
            "value": "; ".join(flagged_gaps) if flagged_gaps else "none",
        },
        {
            "metric": "gap_interpretation",
            "value": "Review against RBI reporting frequency; weekly/semi-monthly gaps may be expected",
        },
        {"metric": "date_semantics", "value": "RBI source observation date, not verified publication date"},
        {"metric": "publication_alignment", "value": "NOT DONE: verify actual release availability before historical ML merges"},
        {"metric": "imputation", "value": "NONE"},
    ]
    pd.DataFrame(report_rows, columns=["metric", "value"]).to_csv(
        REPORT, index=False, encoding="utf-8"
    )

    print(f"Saved: {OUTPUT.relative_to(PROJECT_ROOT)} ({len(data)} rows, {len(COLUMNS)} columns)")
    print(f"Duplicate dates removed: {duplicate_dates}; out-of-range excluded: {out_of_range}")
    print(f"Missing numeric values: {missing}")
    print(f"Gaps over 7 calendar days flagged: {len(flagged_gaps)}")
    print(f"Quality report: {REPORT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
