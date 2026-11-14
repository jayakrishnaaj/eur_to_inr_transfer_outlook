from datetime import date, datetime
from pathlib import Path
import re
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "data/raw/currency/RBI_India_Forex_Reserves_Weekly.xlsx"
OUTPUT = PROJECT_ROOT / "data/interim/RBI_India_Forex_Reserves_Weekly_Clean.csv"
REPORT = PROJECT_ROOT / "reports/quality/RBI_India_Forex_Reserves_Weekly_Quality.csv"
START_DATE = pd.Timestamp("2020-01-01")
END_DATE = pd.Timestamp("2026-10-29")
SHEET_NAME = "Report 1"

COLUMNS = [
    "date",
    "rbi_total_reserves_inr_crore",
    "rbi_total_reserves_usd_mn",
    "rbi_foreign_currency_assets_inr_crore",
    "rbi_foreign_currency_assets_usd_mn",
    "rbi_reserve_gold_value_inr_crore",
    "rbi_reserve_gold_value_usd_mn",
    "rbi_reserve_gold_volume_metric_tonnes",
    "rbi_sdr_value_inr_crore",
    "rbi_sdr_holdings_sdr_mn",
    "rbi_sdr_value_usd_mn",
    "rbi_imf_reserve_tranche_inr_crore",
    "rbi_imf_reserve_tranche_usd_mn",
]

TEXT_DATE_FORMATS = (
    "%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d %b %Y", "%d %B %Y",
    "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d",
)
MISSING_TOKENS = {"", "-", ".", "NA", "N/A", "NAN", "NULL"}


def parse_source_date(value):
    if value is None or pd.isna(value):
        return pd.NaT
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(value).normalize()
    if isinstance(value, bool):
        return pd.NaT
    if isinstance(value, (int, float)):
        if not (20000 <= value <= 80000):
            return pd.NaT
        return pd.to_datetime(value, unit="D", origin="1899-12-30", errors="coerce").normalize()

    text = str(value).strip()
    if not text:
        return pd.NaT
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
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"Excel row {excel_row}, {column}: unexpected value {value!r}") from exc
    if not pd.notna(number) or not (-float("inf") < number < float("inf")):
        raise ValueError(f"Excel row {excel_row}, {column}: non-finite value")
    return number


def is_metadata_row(row):
    first = "" if pd.isna(row.iloc[0]) else str(row.iloc[0]).strip()
    fields = row.iloc[1:]
    known_heading = bool(re.match(
        r"(?i)^(?:notes?\b|see\s+notes\b|source\b|table\b|foreign\s+exchange\b|"
        r"financial\s+year\b|year\b|as\s+on\b|week\s+ended\b|date\b|"
        r"\*|\d{4}\s*[-–/]\s*\d{2,4}\b)", first
    ))
    has_measurements = False
    for value in fields:
        if pd.isna(value) or str(value).strip().upper() in MISSING_TOKENS:
            continue
        try:
            float(str(value).strip().replace(",", ""))
            has_measurements = True
            break
        except ValueError:
            continue
    return known_heading or not has_measurements


def main():
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Source workbook not found: {SOURCE}")

    raw = pd.read_excel(
        SOURCE, sheet_name=SHEET_NAME, header=None, usecols="B:N",
        dtype=object, engine="openpyxl",
    )
    if raw.shape[1] != len(COLUMNS):
        raise ValueError(f"Expected {len(COLUMNS)} columns; found {raw.shape[1]}")
    if raw.empty:
        raise ValueError("The RBI worksheet is empty")
    raw.columns = COLUMNS
    raw_rows = len(raw)

    source_dates = raw["date"].map(parse_source_date)
    nondate = source_dates.isna()
    unexpected_rows = [
        int(i) + 1 for i in raw.index[nondate]
        if not is_metadata_row(raw.loc[i])
    ]
    if unexpected_rows:
        raise ValueError(
            "Non-date rows with apparent measurements (Excel row numbers): "
            f"{unexpected_rows[:10]}"
        )
    excluded_metadata_rows = int(nondate.sum())

    data = raw.loc[~nondate].copy()
    data["date"] = source_dates.loc[data.index]
    if data.empty:
        raise ValueError("No dated RBI reserve observations found")

    for col in COLUMNS[1:]:
        data[col] = [
            parse_number(value, int(i) + 1, col)
            for i, value in data[col].items()
        ]

    duplicate_dates = int(data["date"].duplicated().sum())
    conflicts = data.groupby("date")[COLUMNS[1:]].nunique(dropna=False).gt(1).any(axis=1)
    if conflicts.any():
        raise ValueError(
            "Conflicting duplicate reporting dates: "
            f"{conflicts[conflicts].index.strftime('%Y-%m-%d').tolist()[:5]}"
        )
    data = data.sort_values("date").drop_duplicates("date", keep="first")
    source_date_min = data["date"].min().date().isoformat()
    source_date_max = data["date"].max().date().isoformat()
    unique_dated_rows = len(data)

    in_period = data["date"].between(START_DATE, END_DATE)
    out_of_range = int((~in_period).sum())
    data = data.loc[in_period, COLUMNS].reset_index(drop=True)
    if data.empty:
        raise ValueError("No RBI observations within the selected study period")

    intervals = data["date"].diff().dt.days.dropna().astype(int)
    interval_counts = intervals.value_counts().sort_index().to_dict()
    gaps = data["date"].diff().dt.days
    long_gaps = [
        f"{day:%Y-%m-%d} ({int(days)} days)"
        for day, days in zip(data.loc[gaps.gt(10), "date"], gaps[gaps.gt(10)])
    ]
    missing = {col: int(data[col].isna().sum()) for col in COLUMNS[1:]}

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(OUTPUT, index=False, date_format="%Y-%m-%d", float_format="%.12g", na_rep="")

    report_rows = [
        {"metric": "dataset", "value": "RBI Table No. 33 - Foreign Exchange Reserves - Weekly"},
        {"metric": "source", "value": str(SOURCE.relative_to(PROJECT_ROOT))},
        {"metric": "processed", "value": str(OUTPUT.relative_to(PROJECT_ROOT))},
        {"metric": "sheet", "value": SHEET_NAME},
        {"metric": "raw_rows", "value": raw_rows},
        {"metric": "excluded_header_footer_or_blank_rows", "value": excluded_metadata_rows},
        {"metric": "valid_unique_dated_source_rows", "value": unique_dated_rows},
        {"metric": "source_date_min", "value": source_date_min},
        {"metric": "source_date_max", "value": source_date_max},
        {"metric": "processed_rows", "value": len(data)},
        {"metric": "processed_date_min", "value": data["date"].min().date().isoformat()},
        {"metric": "processed_date_max", "value": data["date"].max().date().isoformat()},
        {"metric": "duplicate_dates_removed", "value": duplicate_dates},
        {"metric": "out_of_range_observations_excluded", "value": out_of_range},
        *({"metric": f"missing_{col}", "value": count} for col, count in missing.items()),
        {"metric": "interval_distribution_calendar_days", "value": "; ".join(
            f"{days} days: {count}" for days, count in interval_counts.items()
        ) if interval_counts else "none"},
        {"metric": "gaps_longer_than_10_calendar_days", "value": "; ".join(long_gaps) if long_gaps else "none"},
        {"metric": "gap_interpretation", "value": "Weekly dates may shift due to holidays; flagged gaps require review, not filling"},
        {"metric": "units", "value": "INR crore, USD million, metric tonnes and SDR million as named in columns"},
        {"metric": "date_semantics", "value": "Weekly RBI observation/reporting date, not verified release date"},
        {"metric": "publication_alignment", "value": "NOT DONE: verify actual release availability before historical ML merges"},
        {"metric": "imputation", "value": "NONE"},
    ]
    pd.DataFrame(report_rows, columns=["metric", "value"]).to_csv(REPORT, index=False, encoding="utf-8")

    print(f"Saved: {OUTPUT.relative_to(PROJECT_ROOT)} ({len(data)} rows, {len(COLUMNS)} columns)")
    print(f"Duplicate dates removed: {duplicate_dates}; out-of-range excluded: {out_of_range}")
    print(f"Missing numeric values: {missing}")
    print(f"Gaps over 10 calendar days flagged: {len(long_gaps)}")
    print(f"Quality report: {REPORT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
