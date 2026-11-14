from pathlib import Path
import re
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "data" / "raw" / "currency" / "FRED_USD_INR_Exchange_Rate_Daily_2020_2026.csv"
OUTPUT = PROJECT_ROOT / "data" / "interim" / "FRED_USD_INR_Exchange_Rate_Daily_2020_2026_Clean.csv"
REPORT = PROJECT_ROOT / "reports" / "quality" / "FRED_USD_INR_Exchange_Rate_Daily_2020_2026_Quality.csv"
START_DATE = pd.Timestamp("2020-01-01")
END_DATE = pd.Timestamp("2026-10-29")

SOURCE_VALUE_COLUMN = "DEXINUS"
CLEAN_VALUE_COLUMN = "fred_usd_inr_inr_per_usd"
EXPECTED_COLUMNS = ["observation_date", SOURCE_VALUE_COLUMN]
MISSING_TOKENS = {"", ".", "-", "NA", "N/A", "NAN", "NULL"}


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"FRED source file not found: {SOURCE}")

    raw = pd.read_csv(SOURCE, dtype="string", keep_default_na=False)
    if set(raw.columns) != set(EXPECTED_COLUMNS) or len(raw.columns) != len(EXPECTED_COLUMNS):
        raise ValueError(f"Unexpected FRED columns: {raw.columns.tolist()}; expected {EXPECTED_COLUMNS}")
    raw_rows = len(raw)
    if raw.empty:
        raise ValueError("FRED source file contains no observations")

    data = raw[EXPECTED_COLUMNS].copy()
    data["date"] = pd.to_datetime(
        data["observation_date"].str.strip(), format="%Y-%m-%d", errors="coerce"
    )
    if data["date"].isna().any():
        raise ValueError(
            f"Invalid source dates ({int(data['date'].isna().sum())}): "
            f"{data.loc[data['date'].isna(), 'observation_date'].head(5).tolist()}"
        )

    rate_text = data[SOURCE_VALUE_COLUMN].str.strip()
    missing = rate_text.str.upper().isin(MISSING_TOKENS)
    numeric = pd.to_numeric(rate_text.mask(missing), errors="coerce")
    bad_numeric = ~missing & numeric.isna()
    if bad_numeric.any():
        raise ValueError(
            "Unexpected FRED numeric value(s): "
            f"{rate_text.loc[bad_numeric].unique().tolist()[:5]}"
        )
    if (~numeric.dropna().map(lambda x: float('-inf') < x < float('inf'))).any():
        raise ValueError("Non-finite USD/INR exchange rate found")
    if (numeric.dropna() <= 0).any():
        raise ValueError("Nonpositive USD/INR exchange rate found")
    data[CLEAN_VALUE_COLUMN] = numeric.astype("float64")

    duplicate_dates = int(data["date"].duplicated().sum())
    conflicts = data.groupby("date")[CLEAN_VALUE_COLUMN].nunique(dropna=False).gt(1)
    if conflicts.any():
        raise ValueError(
            "Conflicting rates on duplicate observation dates: "
            f"{conflicts[conflicts].index.strftime('%Y-%m-%d').tolist()[:5]}"
        )
    data = data.sort_values("date").drop_duplicates("date", keep="first")
    unique_source_rows = len(data)
    source_date_min = data["date"].min().date().isoformat()
    source_date_max = data["date"].max().date().isoformat()

    in_period = data["date"].between(START_DATE, END_DATE)
    out_of_range = int((~in_period).sum())
    clean = data.loc[in_period, ["date", CLEAN_VALUE_COLUMN]].reset_index(drop=True)
    if clean.empty:
        raise ValueError("No FRED USD/INR observations in the study period")

    calendar_days = clean["date"].diff().dt.days
    long_gaps = [
        f"{day:%Y-%m-%d} ({int(gap)} days)"
        for day, gap in zip(clean.loc[calendar_days.gt(4), "date"], calendar_days[calendar_days.gt(4)])
    ]
    valid = clean.dropna(subset=[CLEAN_VALUE_COLUMN])
    changes = valid[CLEAN_VALUE_COLUMN].diff().abs().dropna()
    jumps = []
    if len(changes) > 20:
        median_change = changes.median()
        mad = (changes - median_change).abs().median()
        if pd.notna(mad) and mad > 0:
            flagged = changes[changes > median_change + 15 * mad]
            jumps = [
                f"{clean.loc[idx, 'date']:%Y-%m-%d} (change: {change:.6f})"
                for idx, change in flagged.items()
            ]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(OUTPUT, index=False, date_format="%Y-%m-%d", na_rep="")

    report_rows = [
        {"metric": "dataset", "value": "FRED USD/INR daily exchange rate (DEXINUS)"},
        {"metric": "source", "value": str(SOURCE.relative_to(PROJECT_ROOT))},
        {"metric": "processed", "value": str(OUTPUT.relative_to(PROJECT_ROOT))},
        {"metric": "source_series", "value": "FRED DEXINUS (Federal Reserve H.10)"},
        {"metric": "source_columns", "value": "; ".join(raw.columns.tolist())},
        {"metric": "raw_rows", "value": raw_rows},
        {"metric": "valid_unique_dated_source_rows", "value": unique_source_rows},
        {"metric": "source_date_min", "value": source_date_min},
        {"metric": "source_date_max", "value": source_date_max},
        {"metric": "processed_rows", "value": len(clean)},
        {"metric": "processed_date_min", "value": clean["date"].min().date().isoformat()},
        {"metric": "processed_date_max", "value": clean["date"].max().date().isoformat()},
        {"metric": "duplicate_dates_removed", "value": duplicate_dates},
        {"metric": "out_of_range_observations_excluded", "value": out_of_range},
        {"metric": "missing_rates_preserved", "value": int(clean[CLEAN_VALUE_COLUMN].isna().sum())},
        {"metric": "long_calendar_gaps_over_4_days", "value": "; ".join(long_gaps) if long_gaps else "none"},
        {"metric": "large_movements_flagged", "value": "; ".join(jumps) if jumps else "none"},
        {"metric": "unit", "value": "INR per USD"},
        {"metric": "date_semantics", "value": "FRED source observation date, not verified publication timestamp"},
        {"metric": "publication_alignment", "value": "NOT DONE: verify actual H.10 release availability before historical ML merges"},
        {"metric": "imputation", "value": "NONE"},
    ]
    pd.DataFrame(report_rows, columns=["metric", "value"]).to_csv(
        REPORT, index=False, encoding="utf-8"
    )

    print(f"Saved: {OUTPUT.relative_to(PROJECT_ROOT)} ({len(clean)} rows)")
    print(f"Duplicate dates removed: {duplicate_dates}; out-of-range excluded: {out_of_range}")
    print(f"Missing rates preserved: {int(clean[CLEAN_VALUE_COLUMN].isna().sum())}")
    print(f"Long calendar gaps flagged: {len(long_gaps)}; large movements flagged: {len(jumps)}")
    print(f"Quality report: {REPORT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
