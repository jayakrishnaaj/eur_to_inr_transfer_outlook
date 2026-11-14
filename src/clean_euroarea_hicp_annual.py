from pathlib import Path
import math
import re
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "data/raw/inflation/Eurostat_EuroArea_HICP_Inflation_Annual_2020_2026.xlsx"
OUTPUT = PROJECT_ROOT / "data/interim/Eurostat_EuroArea_HICP_Inflation_Annual_2020_2026_Clean.csv"
REPORT = PROJECT_ROOT / "reports/quality/Eurostat_EuroArea_HICP_Inflation_Annual_2020_2026_Quality.csv"
START_DATE = pd.Timestamp("2020-01-01")
END_DATE = pd.Timestamp("2026-10-01") 
SHEET_NAME = "Sheet 1"
VALUE_COLUMN = "euroarea_hicp_annual_inflation_pct"
MISSING_MARKERS = {"", ":", "-", ".", "NA", "N/A", "NULL", "NAN"}
MONTH_PATTERN = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")
NUMBER_PATTERN = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")
GEOGRAPHY_PREFIX = "Euro area (EA11-1999,"


def parse_rate(value: object, period: str) -> float:
    if value is None or pd.isna(value):
        return float("nan")
    if isinstance(value, bool):
        raise ValueError(f"Boolean HICP value for {period}")
    token = str(value).strip()
    if token.upper() in MISSING_MARKERS:
        return float("nan")
    if not NUMBER_PATTERN.fullmatch(token):
        raise ValueError(f"Unexpected HICP value for {period}: {value!r}")
    result = float(token)
    if not math.isfinite(result):
        raise ValueError(f"Non-finite HICP rate for {period}")
    return result


def cell_text(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Source workbook not found: {SOURCE}")

    raw = pd.read_excel(
        SOURCE,
        sheet_name=SHEET_NAME,
        header=None,
        dtype=object,
        engine="openpyxl",
    )
    if raw.shape[0] < 10 or raw.shape[1] < 4:
        raise ValueError("Unexpected worksheet dimensions: inspect the Eurostat workbook")
    if cell_text(raw.iat[4, 2]) != "Monthly":
        raise ValueError("Unexpected frequency: expected Monthly")
    if "Annual rate of change" not in cell_text(raw.iat[5, 2]):
        raise ValueError("Unexpected measure: expected Annual rate of change")
    if cell_text(raw.iat[6, 2]) != "Total":
        raise ValueError("Unexpected HICP classification: expected Total")

    geography_rows = [
        i for i in range(len(raw))
        if cell_text(raw.iat[i, 0]).startswith(GEOGRAPHY_PREFIX)
    ]
    if len(geography_rows) != 1:
        raise ValueError(
            "Expected exactly one evolving euro-area aggregate row, "
            f"found {len(geography_rows)}"
        )
    row_idx = geography_rows[0]
    source_geography = cell_text(raw.iat[row_idx, 0])

    months = {}
    for col_idx, header in enumerate(raw.iloc[8]):
        label = cell_text(header)
        if not MONTH_PATTERN.fullmatch(label):
            continue
        if label in months:
            raise ValueError(f"Duplicate month heading in workbook: {label}")
        months[label] = col_idx
    if not months:
        raise ValueError("No YYYY-MM monthly headings found on Excel row 9")

    source_periods = sorted(months)
    chosen = [month for month in source_periods if START_DATE <= pd.Timestamp(month + "-01") <= END_DATE]
    if not chosen:
        raise ValueError("No Eurostat observations in the selected research period")

    records = []
    observed_flags = []
    for month in chosen:
        col_idx = months[month]
        rate = parse_rate(raw.iat[row_idx, col_idx], month)
        flag = ""
        if col_idx + 1 < raw.shape[1] and col_idx + 1 not in months.values():
            flag = cell_text(raw.iat[row_idx, col_idx + 1])
        if flag:
            observed_flags.append(f"{month}: {flag}")
        records.append({"date": pd.Timestamp(month + "-01"), VALUE_COLUMN: rate})

    clean = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    full_months = pd.date_range(START_DATE, END_DATE, freq="MS")
    missing_months = full_months.difference(clean["date"])
    missing_month_labels = missing_months.strftime("%Y-%m").tolist()

    nonmissing = clean[VALUE_COLUMN].dropna()
    differences = nonmissing.diff().abs().dropna()
    jumps = []
    threshold = None
    if len(nonmissing) > 20 and not differences.empty:
        med = differences.median()
        mad = (differences - med).abs().median()
        if mad > 0:
            threshold = float(med + 15 * mad)
            jumps = clean.loc[differences[differences > threshold].index, "date"].dt.strftime("%Y-%m").tolist()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(OUTPUT, index=False, date_format="%Y-%m-%d", na_rep="")

    report_rows = [
        {"metric": "dataset", "value": "Eurostat Euro Area All-Items HICP Annual Rate of Change (Monthly)"},
        {"metric": "source", "value": str(SOURCE.relative_to(PROJECT_ROOT))},
        {"metric": "processed", "value": str(OUTPUT.relative_to(PROJECT_ROOT))},
        {"metric": "worksheet", "value": SHEET_NAME},
        {"metric": "source_geography", "value": source_geography},
        {"metric": "source_row_excel", "value": row_idx + 1},
        {"metric": "source_dataset_label", "value": cell_text(raw.iat[1, 1])},
        {"metric": "source_last_updated", "value": cell_text(raw.iat[2, 1])},
        {"metric": "source_measure", "value": "Annual rate of change; Monthly; Total HICP"},
        {"metric": "source_month_headings", "value": len(source_periods)},
        {"metric": "source_period_min", "value": source_periods[0]},
        {"metric": "source_period_max", "value": source_periods[-1]},
        {"metric": "out_of_range_periods_excluded", "value": len(source_periods) - len(chosen)},
        {"metric": "processed_rows", "value": len(clean)},
        {"metric": "processed_date_min", "value": clean["date"].min().date().isoformat()},
        {"metric": "processed_date_max", "value": clean["date"].max().date().isoformat()},
        {"metric": "missing_values_preserved", "value": int(clean[VALUE_COLUMN].isna().sum())},
        {"metric": "missing_months_without_source_column", "value": "; ".join(missing_month_labels) if missing_month_labels else "none"},
        {"metric": "observation_flags_for_review", "value": "; ".join(observed_flags) if observed_flags else "none"},
        {"metric": "large_changes_flagged", "value": "; ".join(jumps) if jumps else "none"},
        {"metric": "large_change_threshold_percentage_points", "value": threshold if threshold is not None else "not calculated"},
        {"metric": "min_valid_pct", "value": float(nonmissing.min()) if not nonmissing.empty else "not available"},
        {"metric": "max_valid_pct", "value": float(nonmissing.max()) if not nonmissing.empty else "not available"},
        {"metric": "unit", "value": "Percent year over year; monthly observations"},
        {"metric": "date_semantics", "value": "First day of reference month; NOT publication/availability date"},
        {"metric": "publication_alignment", "value": "NOT DONE: verify historical Eurostat release timestamps before as-of ML merges"},
        {"metric": "revision_risk", "value": "Downloaded workbook is a snapshot; historical first-published values may differ"},
        {"metric": "composition_risk", "value": "Evolving euro-area membership; confirm geography definition for longitudinal analyses"},
        {"metric": "imputation", "value": "NONE"},
        {"metric": "outlier_deletion", "value": "NONE"},
    ]
    pd.DataFrame(report_rows, columns=["metric", "value"]).to_csv(
        REPORT, index=False, encoding="utf-8"
    )

    print(f"Saved: {OUTPUT.relative_to(PROJECT_ROOT)} ({len(clean)} monthly rows)")
    print(f"Missing HICP values preserved: {clean[VALUE_COLUMN].isna().sum()}")
    print(f"Missing months flagged (not fabricated): {len(missing_month_labels)}")
    print(f"Eurostat observation flags for review: {len(observed_flags)}")
    print(f"Large changes flagged (not deleted): {len(jumps)}")
    print(f"Quality report: {REPORT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
