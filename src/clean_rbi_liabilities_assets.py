from datetime import date, datetime
from pathlib import Path
import re
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "data/raw/currency/RBI_India_Central_Bank_Balance_Sheet.xlsx"
OUTPUT = PROJECT_ROOT / "data/interim/RBI_India_Central_Bank_Balance_Sheet_Clean.csv"
REPORT = PROJECT_ROOT / "reports/quality/RBI_India_Central_Bank_Balance_Sheet_Quality.csv"
START_DATE = pd.Timestamp("2020-01-01")
END_DATE = pd.Timestamp("2026-10-29")
SHEET_NAME = "Report 1"

COLUMNS = [
    "date",
    "rbi_notes_issued_inr_crore",
    "rbi_notes_in_circulation_inr_crore",
    "rbi_notes_banking_department_inr_crore",
    "rbi_deposits_total_inr_crore",
    "rbi_deposits_central_govt_inr_crore",
    "rbi_deposits_market_stabilisation_inr_crore",
    "rbi_deposits_state_govts_inr_crore",
    "rbi_deposits_scheduled_commercial_banks_inr_crore",
    "rbi_deposits_scheduled_state_coop_banks_inr_crore",
    "rbi_deposits_other_banks_inr_crore",
    "rbi_deposits_other_inr_crore",
    "rbi_other_liabilities_inr_crore",
    "rbi_total_liabilities_assets_inr_crore",
    "rbi_assets_foreign_currency_inr_crore",
    "rbi_assets_gold_inr_crore",
    "rbi_assets_rupee_securities_inr_crore",
    "rbi_loans_advances_total_inr_crore",
    "rbi_loans_central_govt_inr_crore",
    "rbi_loans_state_govts_inr_crore",
    "rbi_loans_nabard_inr_crore",
    "rbi_loans_scheduled_commercial_banks_inr_crore",
    "rbi_loans_scheduled_state_coop_banks_inr_crore",
    "rbi_loans_idbi_inr_crore",
    "rbi_loans_exim_bank_inr_crore",
    "rbi_loans_other_inr_crore",
    "rbi_bills_discounted_total_inr_crore",
    "rbi_bills_discounted_commercial_inr_crore",
    "rbi_bills_discounted_treasury_inr_crore",
    "rbi_investments_inr_crore",
    "rbi_other_assets_inr_crore",
]

MISSING_TOKENS = {"", "-", ".", "NA", "N/A", "NAN", "NULL"}
TEXT_DATE_FORMATS = (
    "%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d %b %Y",
    "%d %B %Y", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d",
)


def parse_source_date(value):
    if value is None or pd.isna(value) or isinstance(value, bool):
        return pd.NaT
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(value).normalize()
    if isinstance(value, (int, float)):
        if not (20000 <= value <= 80000):
            return pd.NaT
        return pd.to_datetime(
            value, unit="D", origin="1899-12-30", errors="coerce"
        ).normalize()
    text = str(value).strip()
    for fmt in TEXT_DATE_FORMATS:
        try:
            return pd.Timestamp(datetime.strptime(text, fmt))
        except ValueError:
            continue
    return pd.NaT


def parse_number(value, excel_row, column):
    if value is None or pd.isna(value):
        return float("nan")
    if isinstance(value, bool):
        raise ValueError(f"Excel row {excel_row}, {column}: boolean is not numeric")
    text = str(value).strip()
    if text.upper() in MISSING_TOKENS:
        return float("nan")
    text = text.replace(",", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1].strip()
    try:
        result = float(text)
    except ValueError as exc:
        raise ValueError(
            f"Excel row {excel_row}, {column}: unexpected value {value!r}"
        ) from exc
    if not pd.notna(result) or not -float("inf") < result < float("inf"):
        raise ValueError(f"Excel row {excel_row}, {column}: non-finite number")
    return result


def is_metadata_row(row):
    first = "" if pd.isna(row.iloc[0]) else str(row.iloc[0]).strip()
    other = row.iloc[1:]
    if all(pd.isna(v) or str(v).strip().upper() in MISSING_TOKENS for v in other):
        return bool(re.match(
            r"(?i)^(?:\s*$|notes?\b|see\s+notes\b|source\b|table\b|"
            r"financial\s+year\b|year\b|week\s+ended\b|\*|"
            r"\d{4}\s*[-–/]\s*\d{2,4}\b)", first
        ))
    return False


def main():
    if not SOURCE.is_file():
        raise FileNotFoundError(f"RBI workbook not found: {SOURCE}")

    header = pd.read_excel(
        SOURCE, sheet_name=SHEET_NAME, header=None, usecols="B:AF",
        skiprows=5, nrows=1, dtype=object, engine="openpyxl",
    )
    if header.shape[1] != len(COLUMNS) or str(header.iloc[0, 0]).strip() != "Week Ended":
        raise ValueError("Unexpected RBI worksheet layout: check B6:AF6")

    raw = pd.read_excel(
        SOURCE, sheet_name=SHEET_NAME, header=None, usecols="B:AF",
        skiprows=6, dtype=object, engine="openpyxl",
    )
    if raw.shape[1] != len(COLUMNS):
        raise ValueError(f"Expected {len(COLUMNS)} columns; found {raw.shape[1]}")
    if raw.empty:
        raise ValueError("No source rows found after the RBI worksheet header")
    raw.columns = COLUMNS
    raw_rows = len(raw)

    dates = raw["date"].map(parse_source_date)
    metadata_mask = dates.isna() & raw.apply(is_metadata_row, axis=1)
    unexpected_mask = dates.isna() & ~metadata_mask
    if unexpected_mask.any():
        examples = [
            f"Excel row {i + 7}: {raw.at[i, 'date']!r}"
            for i in raw.index[unexpected_mask][:5]
        ]
        raise ValueError("Unrecognized non-date rows: " + "; ".join(examples))

    excluded_metadata_rows = int(metadata_mask.sum())
    data = raw.loc[dates.notna()].copy()
    data["date"] = pd.to_datetime(dates.loc[data.index])
    if data.empty:
        raise ValueError("No dated RBI balance-sheet observations found")

    for column in COLUMNS[1:]:
        data[column] = [
            parse_number(value, int(i) + 7, column)
            for i, value in data[column].items()
        ]

    duplicate_dates = int(data["date"].duplicated().sum())
    conflicts = data.groupby("date")[COLUMNS[1:]].nunique(dropna=False).gt(1).any(axis=1)
    if conflicts.any():
        raise ValueError(
            "Conflicting duplicate RBI dates: "
            + ", ".join(conflicts[conflicts].index.strftime("%Y-%m-%d")[:5])
        )
    data = data.sort_values("date").drop_duplicates("date", keep="first")
    unique_source_rows = len(data)
    source_min = data["date"].min().date().isoformat()
    source_max = data["date"].max().date().isoformat()

    in_period = data["date"].between(START_DATE, END_DATE)
    out_of_range = int((~in_period).sum())
    data = data.loc[in_period, COLUMNS].reset_index(drop=True)
    if data.empty:
        raise ValueError("No RBI observations within the selected study period")

    intervals = data["date"].diff().dt.days.dropna().astype(int).value_counts().sort_index()
    gap_days = data["date"].diff().dt.days
    long_gaps = [
        f"{day:%Y-%m-%d} ({int(days)} days)"
        for day, days in zip(data.loc[gap_days.gt(10), "date"], gap_days[gap_days.gt(10)])
    ]
    missing = {column: int(data[column].isna().sum()) for column in COLUMNS[1:]}
    sparse = [column for column, count in missing.items() if count > 0.5 * len(data)]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(OUTPUT, index=False, date_format="%Y-%m-%d", float_format="%.12g", na_rep="")

    report_rows = [
        {"metric": "dataset", "value": "RBI India Central Bank Balance Sheet (weekly)"},
        {"metric": "source", "value": str(SOURCE.relative_to(PROJECT_ROOT))},
        {"metric": "processed", "value": str(OUTPUT.relative_to(PROJECT_ROOT))},
        {"metric": "sheet", "value": SHEET_NAME},
        {"metric": "units", "value": "INR crore (all financial columns)"},
        {"metric": "raw_rows", "value": raw_rows},
        {"metric": "excluded_metadata_or_blank_rows", "value": excluded_metadata_rows},
        {"metric": "valid_unique_dated_source_rows", "value": unique_source_rows},
        {"metric": "source_date_min", "value": source_min},
        {"metric": "source_date_max", "value": source_max},
        {"metric": "processed_rows", "value": len(data)},
        {"metric": "processed_date_min", "value": data["date"].min().date().isoformat()},
        {"metric": "processed_date_max", "value": data["date"].max().date().isoformat()},
        {"metric": "financial_columns_preserved", "value": len(COLUMNS) - 1},
        {"metric": "duplicate_dates_removed", "value": duplicate_dates},
        {"metric": "out_of_range_observations_excluded", "value": out_of_range},
        *({"metric": f"missing_{column}", "value": count} for column, count in missing.items()),
        {"metric": "columns_over_50_pct_missing_flagged", "value": "; ".join(sparse) if sparse else "none"},
        {"metric": "sparse_column_policy", "value": "Flag only; preserve every financial series in cleaned dataset"},
        {"metric": "observation_interval_distribution_days", "value": "; ".join(f"{int(k)} days: {int(v)}" for k, v in intervals.items()) if not intervals.empty else "none"},
        {"metric": "gaps_over_10_calendar_days", "value": "; ".join(long_gaps) if long_gaps else "none"},
        {"metric": "gap_interpretation", "value": "Review against RBI weekly schedule and holidays; no dates fabricated"},
        {"metric": "date_semantics", "value": "RBI week-ending observation date, not verified release date"},
        {"metric": "publication_alignment", "value": "NOT DONE: verify historical RBI releases before ML merges"},
        {"metric": "imputation", "value": "NONE"},
        {"metric": "outlier_deletion", "value": "NONE"},
    ]
    pd.DataFrame(report_rows, columns=["metric", "value"]).to_csv(
        REPORT, index=False, encoding="utf-8"
    )

    print(f"Saved: {OUTPUT.relative_to(PROJECT_ROOT)} ({len(data)} rows, {len(COLUMNS)} columns)")
    print(f"Duplicate dates removed: {duplicate_dates}; out-of-range excluded: {out_of_range}")
    print(f"Columns with >50% missing values flagged (not dropped): {len(sparse)}")
    print(f"Gaps over 10 calendar days flagged: {len(long_gaps)}")
    print(f"Quality report: {REPORT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
