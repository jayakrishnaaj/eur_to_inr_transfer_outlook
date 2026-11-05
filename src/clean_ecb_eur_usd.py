from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT_ROOT / "data/raw/currency/ECB_EUR_USD_Exchange_Rate_Daily_2020_2026.csv"
OUTPUT = PROJECT_ROOT / "data/interim/ECB_EUR_USD_Exchange_Rate_Daily_2020_2026_Clean.csv"
REPORT = PROJECT_ROOT / "reports/quality/ECB_EUR_USD_Exchange_Rate_Daily_2020_2026_Quality.csv"
START_DATE = pd.Timestamp("2020-01-01")
END_DATE = pd.Timestamp("2026-10-29")


def main():
    # Read all fields as text so malformed source values are not silently converted.
    raw = pd.read_csv(SOURCE, dtype="string", keep_default_na=False)
    expected = ["date", "base", "quote", "rate"]
    missing_columns = set(expected) - set(raw.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")
    if raw.empty:
        raise ValueError("The ECB EUR/USD source file contains no observations")

    data = raw.loc[:, expected].copy()
    data["base"] = data["base"].str.strip().str.upper()
    data["quote"] = data["quote"].str.strip().str.upper()
    if not ((data["base"] == "EUR") & (data["quote"] == "USD")).all():
        raise ValueError("Unexpected currency direction: expected EUR -> USD throughout")

    # Validate and retain parsed source dates for accurate raw date reporting.
    dates = pd.to_datetime(data["date"].str.strip(), format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        raise ValueError(f"Found {int(dates.isna().sum())} invalid dates")
    data["date"] = dates

    # Preserve genuine missing rates; reject unexpected numeric conventions.
    tokens = data["rate"].str.strip().replace(
        {"": pd.NA, ".": pd.NA, "-": pd.NA, "NA": pd.NA, "N/A": pd.NA}
    )
    if tokens.dropna().str.contains(",", regex=False).any():
        raise ValueError("Comma-formatted rate found: verify source convention")
    rates = pd.to_numeric(tokens, errors="coerce")
    invalid_numeric = tokens.notna() & rates.isna()
    if invalid_numeric.any():
        raise ValueError(
            f"Unrecognized numeric values: {tokens[invalid_numeric].unique().tolist()[:5]}"
        )
    if (rates.dropna() <= 0).any():
        raise ValueError("EUR/USD exchange rates must be positive")
    data["rate"] = rates.astype("float64")

    # Remove identical duplicate dates, but reject conflicting rates.
    duplicate_dates = int(data["date"].duplicated().sum())
    conflicts = data.groupby("date")["rate"].nunique(dropna=False).gt(1)
    if conflicts.any():
        raise ValueError(
            f"Conflicting EUR/USD rates on dates: {conflicts[conflicts].index.strftime('%Y-%m-%d').tolist()[:5]}"
        )
    data = data.sort_values("date").drop_duplicates("date", keep="first")

    # Count excluded *unique observations* before filtering to the project window.
    in_range = data["date"].between(START_DATE, END_DATE)
    out_of_range_observations = int((~in_range).sum())
    data = data.loc[in_range].copy().reset_index(drop=True)
    if data.empty:
        raise ValueError("No EUR/USD observations fall within the requested date range")

    # Flag calendar gaps; do not fabricate missing dates or rates.
    gap_days = data["date"].diff().dt.days
    long_gaps = [
        {"next_date": day.date().isoformat(), "gap_days": int(days)}
        for day, days in zip(data.loc[gap_days.gt(4), "date"], gap_days[gap_days.gt(4)])
    ]

    # Flag unusually large changes between consecutive available observations.
    # Missing-rate boundaries are not bridged when calculating differences.
    changes = data["rate"].diff().abs()
    valid_changes = changes.dropna()
    median_change = valid_changes.median()
    mad = (valid_changes - median_change).abs().median()
    jump_mask = (
        changes.gt(median_change + 15 * mad)
        if pd.notna(mad) and mad > 0
        else pd.Series(False, index=data.index)
    )
    jumps = [
        {"date": day.date().isoformat(), "absolute_change": float(change)}
        for day, change in zip(data.loc[jump_mask, "date"], changes[jump_mask])
    ]

    clean = data[["date", "rate"]].rename(columns={"rate": "eur_usd_usd_per_eur"})
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(OUTPUT, index=False, date_format="%Y-%m-%d", na_rep="")

    report_rows = [
        {"metric": "dataset", "value": "ECB EUR/USD reference rate via Frankfurter"},
        {"metric": "source", "value": str(SOURCE.relative_to(PROJECT_ROOT))},
        {"metric": "processed", "value": str(OUTPUT.relative_to(PROJECT_ROOT))},
        {"metric": "source_columns", "value": "; ".join(raw.columns.tolist())},
        {"metric": "source_rows", "value": len(raw)},
        {"metric": "source_date_min", "value": dates.min().date().isoformat()},
        {"metric": "source_date_max", "value": dates.max().date().isoformat()},
        {"metric": "processed_rows", "value": len(clean)},
        {"metric": "processed_date_min", "value": clean["date"].min().date().isoformat()},
        {"metric": "processed_date_max", "value": clean["date"].max().date().isoformat()},
        {"metric": "duplicate_dates_removed", "value": duplicate_dates},
        {"metric": "missing_rates_preserved", "value": int(clean["eur_usd_usd_per_eur"].isna().sum())},
        {"metric": "out_of_range_observations_excluded", "value": out_of_range_observations},
        {
            "metric": "long_calendar_gaps_over_4_days",
            "value": "; ".join(
                f'{gap["next_date"]} ({gap["gap_days"]} days)' for gap in long_gaps
            ) if long_gaps else "none",
        },
        {
            "metric": "large_movements_flagged",
            "value": "; ".join(
                f'{jump["date"]} (change: {jump["absolute_change"]:.6f})' for jump in jumps
            ) if jumps else "none",
        },
        {"metric": "rate_unit", "value": "USD per EUR"},
        {
            "metric": "date_semantics",
            "value": "ECB reference fixing date, not independently verified publication timestamp",
        },
        {
            "metric": "publication_alignment",
            "value": (
                "PENDING: ECB publication availability must be verified; "
                "ECB reference rates are generally published around 16:00 Europe/Frankfurt "
                "on TARGET working days."
            ),
        },
        {"metric": "imputation", "value": "NONE"},
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(report_rows).to_csv(REPORT, index=False, encoding="utf-8")

    print(f"Saved {OUTPUT.relative_to(PROJECT_ROOT)} ({len(clean)} rows)")
    print(f"Duplicate dates removed: {duplicate_dates}")
    print(f"Missing rates preserved: {clean['eur_usd_usd_per_eur'].isna().sum()}")
    print(f"Out-of-range observations excluded: {out_of_range_observations}")
    print(f"Gaps over 4 calendar days flagged: {len(long_gaps)}")
    print(f"Large movements flagged (not deleted): {len(jumps)}")
    print(f"Quality report: {REPORT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
