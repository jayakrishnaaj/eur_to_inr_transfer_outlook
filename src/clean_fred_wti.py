from pathlib import Path
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT_ROOT / "data" / "raw" / "energy" / "FRED_US_WTI_Crude_Oil_Price_Daily_2020_2026.csv"
OUTPUT = PROJECT_ROOT / "data" / "interim" / "FRED_US_WTI_Crude_Oil_Price_Daily_2020_2026_Clean.csv"
REPORT = PROJECT_ROOT / "reports" / "quality" / "FRED_US_WTI_Crude_Oil_Price_Daily_2020_2026_Quality.csv"
START_DATE = pd.Timestamp("2020-01-01")
END_DATE = pd.Timestamp("2026-10-29")
SERIES_ID = "DCOILWTICO"
VALUE_COLUMN = "wti_usd_per_barrel"
MISSING_MARKERS = {"", ".", "-", "NA", "N/A", "NULL", "NAN"}


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Missing raw source: {SOURCE}")

    raw = pd.read_csv(SOURCE, dtype="string", keep_default_na=False, encoding="utf-8-sig")
    expected_columns = ["observation_date", SERIES_ID]
    if raw.columns.tolist() != expected_columns:
        raise ValueError(f"Unexpected FRED columns: {raw.columns.tolist()}; expected {expected_columns}")
    if raw.empty:
        raise ValueError("Source CSV has no observations")

    # Strict observation-date parsing: invalid or blank dates must be investigated.
    raw_dates = raw["observation_date"].str.strip()
    dates = pd.to_datetime(raw_dates, format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        examples = raw_dates.loc[dates.isna()].head(5).tolist()
        raise ValueError(f"Unparseable observation dates: {examples}")

    # Missing source markers remain missing; reject malformed and non-finite numbers.
    tokens = raw[SERIES_ID].str.strip()
    missing = tokens.str.upper().isin(MISSING_MARKERS)
    nonmissing = tokens.where(~missing, pd.NA)
    if nonmissing.dropna().str.contains(",", regex=False).any():
        raise ValueError("Comma-formatted WTI price: verify source numeric convention")
    values = pd.to_numeric(nonmissing, errors="coerce").astype("float64")
    malformed = nonmissing.notna() & values.isna()
    if malformed.any():
        raise ValueError(f"Unexpected WTI price text: {tokens.loc[malformed].unique().tolist()[:5]}")
    if (~np.isfinite(values.dropna())).any():
        raise ValueError("Non-finite WTI prices (Infinity/-Infinity) found")
    # No positive-price requirement: WTI spot prices can be zero or negative.

    data = pd.DataFrame({"date": dates, VALUE_COLUMN: values})
    duplicate_dates = int(data["date"].duplicated().sum())
    conflicts = data.groupby("date")[VALUE_COLUMN].nunique(dropna=False).gt(1)
    if conflicts.any():
        examples = conflicts[conflicts].index.strftime("%Y-%m-%d").tolist()[:5]
        raise ValueError(f"Conflicting WTI prices on duplicate dates: {examples}")

    data = data.sort_values("date").drop_duplicates("date", keep="first").reset_index(drop=True)
    source_date_min = data["date"].min().date().isoformat()
    source_date_max = data["date"].max().date().isoformat()
    in_range = data["date"].between(START_DATE, END_DATE)
    out_of_range = int((~in_range).sum())
    data = data.loc[in_range, ["date", VALUE_COLUMN]].reset_index(drop=True)
    if data.empty:
        raise ValueError("No WTI observations in the selected study period")

    valid = data.dropna(subset=[VALUE_COLUMN]).copy()
    missing_count = int(data[VALUE_COLUMN].isna().sum())
    negative = valid.loc[valid[VALUE_COLUMN] < 0]
    zero = valid.loc[valid[VALUE_COLUMN] == 0]

    # Flag calendar gaps; do not insert dates or fill values.
    intervals = data["date"].diff().dt.days
    gap_rows = data.loc[intervals.gt(4), "date"]
    long_gaps = [
        f"{dt:%Y-%m-%d} ({int(intervals.loc[idx])} days)"
        for idx, dt in gap_rows.items()
    ]

    # Robust movement screen across consecutive nonmissing observations.
    differences = valid[VALUE_COLUMN].diff().abs().dropna()
    threshold = None
    jump_dates: list[str] = []
    if not differences.empty:
        median_change = differences.median()
        mad = (differences - median_change).abs().median()
        if pd.notna(mad) and mad > 0:
            threshold = float(median_change + 15 * mad)
            jump_dates = valid.loc[
                differences.index[differences > threshold], "date"
            ].dt.strftime("%Y-%m-%d").tolist()

    min_value = float(valid[VALUE_COLUMN].min()) if not valid.empty else "not available"
    max_value = float(valid[VALUE_COLUMN].max()) if not valid.empty else "not available"
    min_date = (
        valid.loc[valid[VALUE_COLUMN].idxmin(), "date"].date().isoformat()
        if not valid.empty else "not available"
    )
    max_date = (
        valid.loc[valid[VALUE_COLUMN].idxmax(), "date"].date().isoformat()
        if not valid.empty else "not available"
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(OUTPUT, index=False, date_format="%Y-%m-%d", na_rep="", float_format="%.15g")

    report_rows = [
        {"metric": "dataset", "value": "FRED DCOILWTICO / EIA Cushing WTI Spot Price FOB"},
        {"metric": "source", "value": str(SOURCE.relative_to(PROJECT_ROOT))},
        {"metric": "processed", "value": str(OUTPUT.relative_to(PROJECT_ROOT))},
        {"metric": "series_id", "value": SERIES_ID},
        {"metric": "unit", "value": "USD per barrel"},
        {"metric": "raw_rows", "value": len(raw)},
        {"metric": "source_unique_dated_rows", "value": len(raw) - duplicate_dates},
        {"metric": "source_date_min", "value": source_date_min},
        {"metric": "source_date_max", "value": source_date_max},
        {"metric": "processed_rows", "value": len(data)},
        {"metric": "processed_date_min", "value": data["date"].min().date().isoformat()},
        {"metric": "processed_date_max", "value": data["date"].max().date().isoformat()},
        {"metric": "duplicate_dates_removed", "value": duplicate_dates},
        {"metric": "out_of_range_observations_excluded", "value": out_of_range},
        {"metric": "missing_values_preserved", "value": missing_count},
        {"metric": "nonmissing_price_count", "value": len(valid)},
        {"metric": "minimum_price_usd_per_barrel", "value": min_value},
        {"metric": "minimum_price_date", "value": min_date},
        {"metric": "maximum_price_usd_per_barrel", "value": max_value},
        {"metric": "maximum_price_date", "value": max_date},
        {"metric": "negative_prices_retained", "value": len(negative)},
        {"metric": "negative_price_dates", "value": "; ".join(negative["date"].dt.strftime("%Y-%m-%d")) or "none"},
        {"metric": "zero_prices_retained", "value": len(zero)},
        {"metric": "zero_price_dates", "value": "; ".join(zero["date"].dt.strftime("%Y-%m-%d")) or "none"},
        {"metric": "gaps_over_4_calendar_days", "value": "; ".join(long_gaps) or "none"},
        {"metric": "large_movement_threshold_usd_per_barrel", "value": threshold if threshold is not None else "not applicable"},
        {"metric": "large_movement_dates_flagged", "value": "; ".join(jump_dates) or "none"},
        {"metric": "date_semantics", "value": "FRED observation date; not independently verified release timestamp"},
        {"metric": "publication_alignment", "value": "PENDING: verify EIA/FRED historical information availability before as-of ML merges"},
        {"metric": "transformation_warning", "value": "Avoid log(price) or percentage returns across zero/negative prices; use appropriately justified transformations"},
        {"metric": "imputation", "value": "NONE"},
        {"metric": "outlier_deletion", "value": "NONE"},
    ]
    pd.DataFrame(report_rows, columns=["metric", "value"]).to_csv(
        REPORT, index=False, encoding="utf-8"
    )

    print(f"Saved: {OUTPUT.relative_to(PROJECT_ROOT)} ({len(data)} rows)")
    print(f"Duplicate dates removed: {duplicate_dates}; out-of-range excluded: {out_of_range}")
    print(f"Missing prices: {missing_count}; negative prices: {len(negative)}; zero prices: {len(zero)}")
    print(f"Gaps over 4 days: {len(long_gaps)}; large movements flagged: {len(jump_dates)}")
    print(f"Quality report: {REPORT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
