from pathlib import Path
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "data/raw/currency/ECB_USD_INR_Exchange_Rate_Daily_2020_2026.csv"
OUTPUT = PROJECT_ROOT / "data/interim/ECB_USD_INR_Exchange_Rate_Daily_2020_2026_Clean.csv"
REPORT = PROJECT_ROOT / "reports/quality/ECB_USD_INR_Exchange_Rate_Daily_2020_2026_Quality.csv"
START_DATE = pd.Timestamp("2020-01-01")
END_DATE = pd.Timestamp("2026-10-29")


def main():
    raw = pd.read_csv(SOURCE, dtype="string", keep_default_na=False)
    required = ["date", "base", "quote", "rate"]
    missing_columns = set(required) - set(raw.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")
    if raw.empty:
        raise ValueError("The source USD/INR file contains no observations")

    data = raw.loc[:, required].copy()
    data["base"] = data["base"].str.strip().str.upper()
    data["quote"] = data["quote"].str.strip().str.upper()
    if not ((data["base"] == "USD") & (data["quote"] == "INR")).all():
        raise ValueError("Unexpected currency pair: expected USD -> INR on every row")

    dates = pd.to_datetime(data["date"].str.strip(), format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        raise ValueError(f"Found {int(dates.isna().sum())} invalid source dates")
    data["date"] = dates
    source_date_min = dates.min().date().isoformat()
    source_date_max = dates.max().date().isoformat()

    rate_text = data["rate"].str.strip().replace(
        {"": pd.NA, ".": pd.NA, "-": pd.NA, "NA": pd.NA, "N/A": pd.NA}
    )
    if rate_text.dropna().str.contains(",", regex=False).any():
        raise ValueError("Comma-formatted USD/INR rates found: verify source convention")
    rates = pd.to_numeric(rate_text, errors="coerce")
    unexpected = rate_text.notna() & rates.isna()
    if unexpected.any():
        raise ValueError(f"Unrecognized rates: {rate_text[unexpected].unique().tolist()[:5]}")
    if (rates.dropna() <= 0).any():
        raise ValueError("USD/INR rates must be positive")
    data["rate"] = rates.astype("float64")

    duplicate_dates = int(data["date"].duplicated().sum())
    conflicts = data.groupby("date")["rate"].nunique(dropna=False).gt(1)
    if conflicts.any():
        bad_dates = conflicts[conflicts].index.strftime("%Y-%m-%d").tolist()[:5]
        raise ValueError(f"Conflicting USD/INR values for dates: {bad_dates}")
    data = data.sort_values("date").drop_duplicates("date", keep="first")

    in_range = data["date"].between(START_DATE, END_DATE)
    out_of_range_observations = int((~in_range).sum())
    data = data.loc[in_range].copy().reset_index(drop=True)
    if data.empty:
        raise ValueError("No USD/INR observations remain within the requested date range")

    gap_days = data["date"].diff().dt.days
    long_gaps = [
        f"{day.date().isoformat()} ({int(length)} days)"
        for day, length in zip(data.loc[gap_days.gt(4), "date"], gap_days[gap_days.gt(4)])
    ]
    valid = data.loc[data["rate"].notna(), ["date", "rate"]].copy()
    changes = valid["rate"].diff().abs()
    median_change = changes.median()
    mad = (changes - median_change).abs().median()
    if pd.notna(mad) and mad > 0:
        flagged = changes.gt(median_change + 15 * mad)
        large_movements = [
            f"{day.date().isoformat()} (change: {change:.6f})"
            for day, change in zip(valid.loc[flagged, "date"], changes[flagged])
        ]
    else:
        large_movements = []

    clean = data[["date", "rate"]].rename(columns={"rate": "usd_inr_inr_per_usd"})
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(OUTPUT, index=False, date_format="%Y-%m-%d", na_rep="")

    report_rows = [
        {"metric": "dataset", "value": "Frankfurter ECB-provider USD/INR cross rate"},
        {"metric": "source", "value": str(SOURCE.relative_to(PROJECT_ROOT))},
        {"metric": "processed", "value": str(OUTPUT.relative_to(PROJECT_ROOT))},
        {"metric": "source_columns", "value": "; ".join(raw.columns.tolist())},
        {"metric": "source_rows", "value": len(raw)},
        {"metric": "source_date_min", "value": source_date_min},
        {"metric": "source_date_max", "value": source_date_max},
        {"metric": "processed_rows", "value": len(clean)},
        {"metric": "processed_date_min", "value": clean["date"].min().date().isoformat()},
        {"metric": "processed_date_max", "value": clean["date"].max().date().isoformat()},
        {"metric": "duplicate_dates_removed", "value": duplicate_dates},
        {"metric": "missing_rates_preserved", "value": int(clean["usd_inr_inr_per_usd"].isna().sum())},
        {"metric": "out_of_range_observations_excluded", "value": out_of_range_observations},
        {"metric": "long_calendar_gaps_over_4_days", "value": "; ".join(long_gaps) if long_gaps else "none"},
        {"metric": "large_movements_flagged", "value": "; ".join(large_movements) if large_movements else "none"},
        {"metric": "rate_unit", "value": "INR per USD"},
        {"metric": "date_semantics", "value": "Source observation/fixing date; not a verified publication timestamp"},
        {"metric": "publication_alignment", "value": "PENDING: verify historical publication availability before ML merging"},
        {"metric": "cross_rate_note", "value": "Derived USD/INR = (EUR/INR) / (EUR/USD); verify against matching source dates and rates"},
        {"metric": "calendar_note", "value": "ECB holidays may produce longer gaps; do not fabricate dates"},
        {"metric": "imputation", "value": "NONE"},
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(report_rows).to_csv(REPORT, index=False, encoding="utf-8")

    print(f"Saved {OUTPUT.relative_to(PROJECT_ROOT)} ({len(clean)} rows)")
    print(f"Duplicate dates removed: {duplicate_dates}")
    print(f"Missing rates preserved: {clean['usd_inr_inr_per_usd'].isna().sum()}")
    print(f"Out-of-range observations excluded: {out_of_range_observations}")
    print(f"Long calendar gaps (>4 days): {len(long_gaps)}")
    print(f"Large movements flagged: {len(large_movements)}")
    print(f"Quality report: {REPORT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
