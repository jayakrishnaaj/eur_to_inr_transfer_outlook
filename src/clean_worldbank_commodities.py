from pathlib import Path
import math
import re
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT_ROOT / "data/raw/energy/WorldBank_Global_Commodity_Prices_Monthly.xlsx"
OUTPUT = PROJECT_ROOT / "data/interim/WorldBank_Global_Commodity_Prices_Monthly_Clean.csv"
REPORT = PROJECT_ROOT / "reports/quality/WorldBank_Global_Commodity_Prices_Monthly_Quality.csv"
START_DATE = pd.Timestamp("2020-01-01")
END_DATE = pd.Timestamp("2026-10-01")  # Inclusive reference month, if present.
SHEET_NAME = "Monthly Prices"

# Each source heading maps to (standardized output column, expected workbook unit,
# human-readable unit). No currency or physical-unit conversions are performed.
SERIES = {
    "Gold": ("gold_usd_per_troy_oz", "($/troy oz)", "USD/troy ounce"),
    "Silver": ("silver_usd_per_troy_oz", "($/troy oz)", "USD/troy ounce"),
    "Copper": ("copper_usd_per_mt", "($/mt)", "USD/metric tonne"),
    "Aluminum": ("aluminum_usd_per_mt", "($/mt)", "USD/metric tonne"),
    "Iron ore, cfr spot": ("iron_ore_usd_per_dmtu", "($/dmtu)", "USD/dry metric ton unit"),
    "Natural gas, Europe": ("europe_gas_usd_per_mmbtu", "($/mmbtu)", "USD/million BTU"),
    "Crude oil, Brent": ("wb_brent_usd_per_barrel", "($/bbl)", "USD/barrel"),
}
OUTPUT_COLUMNS = ["date", *(definition[0] for definition in SERIES.values())]
MISSING_TOKENS = {"", "-", ".", "...", "…", "NA", "N/A", "NAN", "NULL"}
PERIOD_PATTERN = re.compile(r"^(\d{4})M(0[1-9]|1[0-2])$")


def parse_price(value, *, column: str, period: str, excel_row: int) -> float:
    """Parse a price while preserving genuine missing cells and rejecting anomalies."""
    if value is None or pd.isna(value):
        return float("nan")
    if isinstance(value, bool):
        raise ValueError(f"Excel row {excel_row}, {column}, {period}: boolean is not numeric")

    text = str(value).strip()
    if text.upper() in MISSING_TOKENS:
        return float("nan")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1].strip()
    # Commodity prices are represented with period decimals and optional
    # grouping commas in the supplied workbook convention.
    text = text.replace(",", "")
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(
            f"Excel row {excel_row}, {column}, {period}: unexpected value {value!r}"
        ) from exc
    if not math.isfinite(number):
        raise ValueError(f"Excel row {excel_row}, {column}, {period}: non-finite price")
    if number < 0:
        raise ValueError(f"Excel row {excel_row}, {column}, {period}: negative price")
    return number


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Source workbook not found: {SOURCE}")

    # Original workbook: row 5 = commodity headings; row 6 = units;
    # observations begin at row 7. No fixed final row is assumed.
    raw = pd.read_excel(
        SOURCE,
        sheet_name=SHEET_NAME,
        header=None,
        usecols="A:BT",
        dtype=object,
        engine="openpyxl",
    )
    if len(raw) < 6:
        raise ValueError("Monthly Prices worksheet is missing header or unit rows")
    source_rows = len(raw)
    headings = raw.iloc[4].map(lambda x: str(x).strip() if pd.notna(x) else "")
    units = raw.iloc[5].map(lambda x: str(x).strip() if pd.notna(x) else "")

    source_indices = {}
    for heading, (standard, expected_unit, _) in SERIES.items():
        matches = [idx for idx, name in enumerate(headings) if name == heading]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one heading {heading!r}, found {len(matches)}")
        idx = matches[0]
        if units.iloc[idx] != expected_unit:
            raise ValueError(
                f"Unexpected workbook unit for {heading!r}: "
                f"{units.iloc[idx]!r} (expected {expected_unit!r})"
            )
        source_indices[standard] = idx

    records = []
    dated_source_rows = 0
    excluded_metadata_rows = 0
    out_of_range_rows = 0
    source_months = []
    selected_indices = list(source_indices.values())

    for row_index in range(6, len(raw)):
        row = raw.iloc[row_index]
        excel_row = row_index + 1
        first_cell = row.iloc[0]
        label = "" if pd.isna(first_cell) else str(first_cell).strip()
        match = PERIOD_PATTERN.fullmatch(label)
        if match is None:
            # Blank explanatory lines and named notes are not time-series data.
            # Unexpected labels with price-like cells must not be silently skipped.
            selected_values = row.iloc[selected_indices]
            populated_numeric_cells = selected_values.map(
                lambda value: pd.notna(value) and str(value).strip() != ""
            ).any()
            recognized_note = (
                not label
                or bool(re.match(r"(?i)^(notes?\b|source\b|remarks?\b|\*|see\s+notes\b)", label))
            )
            if populated_numeric_cells or not recognized_note:
                raise ValueError(
                    f"Unexpected non-period row at Excel row {excel_row}: {label!r}"
                )
            excluded_metadata_rows += 1
            continue

        month = pd.Timestamp(f"{match.group(1)}-{match.group(2)}-01")
        dated_source_rows += 1
        source_months.append(month)
        if not (START_DATE <= month <= END_DATE):
            out_of_range_rows += 1
            continue

        record = {"date": month}
        for column, idx in source_indices.items():
            record[column] = parse_price(
                row.iloc[idx], column=column, period=label, excel_row=excel_row
            )
        records.append(record)

    if not records:
        raise ValueError("No commodity observations in the selected study period")

    data = pd.DataFrame.from_records(records, columns=OUTPUT_COLUMNS)
    duplicates = int(data["date"].duplicated().sum())
    conflicts = data.groupby("date")[OUTPUT_COLUMNS[1:]].nunique(dropna=False).gt(1).any(axis=1)
    if conflicts.any():
        raise ValueError(
            "Conflicting values for duplicate months: "
            f"{conflicts[conflicts].index.strftime('%Y-%m').tolist()[:5]}"
        )
    data = data.sort_values("date").drop_duplicates("date", keep="first").reset_index(drop=True)

    # A monthly series has one reference date per month. Detect absent months
    # between the first and last observed months; do not manufacture new rows.
    complete_months = pd.date_range(data["date"].iloc[0], data["date"].iloc[-1], freq="MS")
    missing_months = complete_months.difference(pd.DatetimeIndex(data["date"]))
    missing_counts = {column: int(data[column].isna().sum()) for column in OUTPUT_COLUMNS[1:]}

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(OUTPUT, index=False, date_format="%Y-%m-%d", na_rep="", float_format="%.12g")

    report_rows = [
        {"metric": "dataset", "value": "World Bank Global Commodity Prices - Monthly"},
        {"metric": "source", "value": str(SOURCE.relative_to(PROJECT_ROOT))},
        {"metric": "processed", "value": str(OUTPUT.relative_to(PROJECT_ROOT))},
        {"metric": "sheet", "value": SHEET_NAME},
        {"metric": "source_rows_including_header", "value": source_rows},
        {"metric": "dated_source_rows", "value": dated_source_rows},
        {"metric": "excluded_metadata_or_blank_rows", "value": excluded_metadata_rows},
        {"metric": "source_date_min", "value": min(source_months).strftime("%Y-%m-%d") if source_months else "none"},
        {"metric": "source_date_max", "value": max(source_months).strftime("%Y-%m-%d") if source_months else "none"},
        {"metric": "processed_rows", "value": len(data)},
        {"metric": "processed_date_min", "value": data["date"].min().strftime("%Y-%m-%d")},
        {"metric": "processed_date_max", "value": data["date"].max().strftime("%Y-%m-%d")},
        {"metric": "duplicate_dates_removed", "value": duplicates},
        {"metric": "out_of_range_observations_excluded", "value": out_of_range_rows},
        *({"metric": f"missing_{column}", "value": count} for column, count in missing_counts.items()),
        {"metric": "missing_month_count_within_observed_span", "value": len(missing_months)},
        {"metric": "missing_months_within_observed_span", "value": "; ".join(missing_months.strftime("%Y-%m")) if len(missing_months) else "none"},
        *(
            {"metric": f"unit_{standard}", "value": unit}
            for standard, _, unit in SERIES.values()
        ),
        {"metric": "frequency", "value": "monthly"},
        {"metric": "date_semantics", "value": "First day of reference month, NOT verified publication/availability date"},
        {"metric": "publication_alignment", "value": "NOT DONE: verify historical release timestamps before predictive ML merges"},
        {"metric": "imputation", "value": "NONE"},
        {"metric": "outlier_deletion", "value": "NONE"},
        {"metric": "provenance_review", "value": "Review workbook provenance and any Mismatch Details sheet before redistribution"},
    ]
    pd.DataFrame(report_rows, columns=["metric", "value"]).to_csv(
        REPORT, index=False, encoding="utf-8"
    )

    print(f"Saved: {OUTPUT.relative_to(PROJECT_ROOT)} ({len(data)} rows, {len(OUTPUT_COLUMNS)} columns)")
    print(f"Duplicates removed: {duplicates}; out-of-range rows excluded: {out_of_range_rows}")
    print(f"Missing numeric values: {missing_counts}")
    print(f"Missing months within observed span: {len(missing_months)}")
    print(f"Quality report: {REPORT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
