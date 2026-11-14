from __future__ import annotations
import math
import re
from datetime import date
from pathlib import Path
import pandas as pd
from openpyxl import load_workbook

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "data/raw/inflation/Eurostat_EuroArea_HICP_Inflation_Monthly_2020_2026.xlsx"
OUTPUT = PROJECT_ROOT / "data/interim/Eurostat_EuroArea_HICP_Inflation_Monthly_2020_2026_Clean.csv"
REPORT = PROJECT_ROOT / "reports/quality/Eurostat_EuroArea_HICP_Inflation_Monthly_2020_2026_Quality.csv"
START_DATE = pd.Timestamp("2020-01-01")
END_DATE = pd.Timestamp("2026-10-29")
SHEET_NAME = "Sheet 1"
VALUE_COLUMN = "euroarea_hicp_monthly_inflation_pct"
MISSING_TOKENS = {"", ":", "-", ".", "NA", "N/A", "NULL", "NAN"}
PERIOD_RE = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])\Z")
GEO_PREFIX = "Euro area (EA11-1999,"


def parse_number(value: object, period: str) -> float:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return math.nan
    if isinstance(value, bool):
        raise ValueError(f"Boolean inflation value for {period}: {value!r}")
    if isinstance(value, (int, float)):
        parsed = float(value)
    else:
        token = str(value).strip()
        if token.upper() in MISSING_TOKENS:
            return math.nan
        if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", token):
            raise ValueError(f"Unexpected HICP numeric text for {period}: {value!r}")
        parsed = float(token)
    if not math.isfinite(parsed):
        raise ValueError(f"Non-finite HICP value for {period}: {value!r}")
    return parsed  


def month_labels(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    return [dt.strftime("%Y-%m") for dt in pd.date_range(start, end, freq="MS")]


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Source workbook not found: {SOURCE}")

    workbook = load_workbook(SOURCE, read_only=False, data_only=True)
    try:
        if SHEET_NAME not in workbook.sheetnames:
            raise ValueError(
                f"Missing worksheet {SHEET_NAME!r}; available sheets: {workbook.sheetnames}"
            )
        sheet = workbook[SHEET_NAME]
        rows = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()
    if not rows or not any(any(value is not None for value in row) for row in rows):
        raise ValueError("The Eurostat worksheet contains no populated cells")

    metadata = {
        str(row[0]).strip(): row[2]
        for row in rows[:8]
        if len(row) > 2 and row[0] is not None
    }
    if str(metadata.get("Time frequency", "")).strip() != "Monthly":
        raise ValueError(f"Unexpected Eurostat frequency: {metadata.get('Time frequency')!r}")
    if str(metadata.get("Unit of measure", "")).strip() != "Monthly rate of change":
        raise ValueError(f"Unexpected HICP measure: {metadata.get('Unit of measure')!r}")
    classification = "Classification of individual consumption by purpose (COICOP) - 2018"
    if str(metadata.get(classification, "")).strip() != "Total":
        raise ValueError("Expected all-items/Total COICOP classification")

    time_rows = [r for r in rows if r and str(r[0]).strip() == "TIME"]
    if len(time_rows) != 1:
        raise ValueError(f"Expected exactly one TIME row; found {len(time_rows)}")
    header = time_rows[0]
    geo_rows = [
        r for r in rows
        if r and isinstance(r[0], str)
        and r[0].startswith(GEO_PREFIX) and "EA21-2026" in r[0]
    ]
    if len(geo_rows) != 1:
        raise ValueError(f"Expected exactly one evolving euro-area row; found {len(geo_rows)}")
    selected = geo_rows[0]

    observations: list[dict[str, object]] = []
    flag_details: list[str] = []
    source_period_count = 0
    out_of_range_count = 0
    for index, label in enumerate(header):
        period = str(label).strip() if label is not None else ""
        if not PERIOD_RE.fullmatch(period):
            continue
        source_period_count += 1
        observation_date = pd.Timestamp(f"{period}-01")
        if not START_DATE <= observation_date <= END_DATE:
            out_of_range_count += 1
            continue
        if index >= len(selected):
            raise ValueError(f"Missing source cell for period {period}")
        value = parse_number(selected[index], period)
        observations.append({"date": observation_date, VALUE_COLUMN: value})
        if index + 1 < len(selected):
            next_label = str(header[index + 1]).strip() if index + 1 < len(header) else ""
            flag = selected[index + 1]
            if not PERIOD_RE.fullmatch(next_label) and flag is not None and str(flag).strip():
                flag_details.append(f"{period}: {str(flag).strip()}")

    if not observations:
        raise ValueError("No euro-area monthly HICP observations in the study period")
    data = pd.DataFrame(observations)
    conflicts = data.groupby("date")[VALUE_COLUMN].nunique(dropna=False).gt(1)
    if conflicts.any():
        raise ValueError(
            "Conflicting values for duplicate months: "
            + ", ".join(conflicts[conflicts].index.strftime("%Y-%m").tolist()[:5])
        )
    duplicates = int(data["date"].duplicated().sum())
    data = data.sort_values("date").drop_duplicates("date").reset_index(drop=True)

    recorded_months = set(data["date"].dt.strftime("%Y-%m"))
    missing_months = [month for month in month_labels(START_DATE, END_DATE) if month not in recorded_months]
    values = data[VALUE_COLUMN].dropna()
    period_step = data["date"].dt.to_period("M").astype("int64").diff()
    change = data[VALUE_COLUMN].diff().abs().where(period_step.eq(1))
    valid_changes = change.dropna()
    jump_dates: list[str] = []
    threshold: float | None = None
    if len(valid_changes) > 20:
        median_change = valid_changes.median()
        mad = (valid_changes - median_change).abs().median()
        if mad > 0:
            threshold = float(median_change + 15 * mad)
            jump_dates = data.loc[change.gt(threshold), "date"].dt.strftime("%Y-%m").tolist()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(OUTPUT, index=False, date_format="%Y-%m-%d", na_rep="", float_format="%.10g")

    report_rows = [
        {"metric": "dataset", "value": "Eurostat Euro Area HICP Monthly Inflation"},
        {"metric": "source", "value": str(SOURCE.relative_to(PROJECT_ROOT))},
        {"metric": "processed", "value": str(OUTPUT.relative_to(PROJECT_ROOT))},
        {"metric": "worksheet", "value": SHEET_NAME},
        {"metric": "source_series", "value": selected[0]},
        {"metric": "frequency", "value": "monthly"},
        {"metric": "measure", "value": "Month-on-month percentage change in all-items HICP"},
        {"metric": "unit", "value": "percent"},
        {"metric": "source_period_columns", "value": source_period_count},
        {"metric": "out_of_range_periods_excluded", "value": out_of_range_count},
        {"metric": "processed_rows", "value": len(data)},
        {"metric": "processed_date_min", "value": data["date"].min().date().isoformat()},
        {"metric": "processed_date_max", "value": data["date"].max().date().isoformat()},
        {"metric": "duplicate_months_removed", "value": duplicates},
        {"metric": "missing_values_preserved", "value": int(data[VALUE_COLUMN].isna().sum())},
        {"metric": "missing_calendar_months", "value": "; ".join(missing_months) if missing_months else "none"},
        {"metric": "minimum_valid_pct", "value": float(values.min()) if not values.empty else ""},
        {"metric": "maximum_valid_pct", "value": float(values.max()) if not values.empty else ""},
        {"metric": "observation_flags", "value": "; ".join(flag_details) if flag_details else "none"},
        {"metric": "large_change_threshold_percentage_points", "value": threshold if threshold is not None else "not calculated"},
        {"metric": "large_change_months_to_review", "value": "; ".join(jump_dates) if jump_dates else "none"},
        {"metric": "date_semantics", "value": "First day of reference month; not a publication timestamp"},
        {"metric": "publication_alignment", "value": "PENDING: verify historical release availability before as-of ML merge"},
        {"metric": "revision_risk", "value": "Current export may differ from first-published historical values"},
        {"metric": "composition_risk", "value": "Evolving euro-area aggregate; membership changes require interpretation"},
        {"metric": "imputation", "value": "NONE"},
        {"metric": "outlier_deletion", "value": "NONE"},
    ]
    pd.DataFrame(report_rows, columns=["metric", "value"]).to_csv(REPORT, index=False, encoding="utf-8")

    print(f"Saved: {OUTPUT.relative_to(PROJECT_ROOT)} ({len(data)} monthly observations)")
    print(f"Missing values: {int(data[VALUE_COLUMN].isna().sum())}; missing calendar months: {len(missing_months)}")
    print(f"Duplicate months removed: {duplicates}; observation flags: {len(flag_details)}")
    print(f"Large movements flagged: {len(jump_dates)}")
    print(f"Quality report: {REPORT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
