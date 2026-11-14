from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "data/raw/currency/ECB_EUR_INR_Exchange_Rate_Daily_2020_2026.csv"
OUTPUT = PROJECT_ROOT / "data/interim/ECB_EUR_INR_Exchange_Rate_Daily_2020_2026_Clean.csv"
REPORT = PROJECT_ROOT / "reports/quality/ECB_EUR_INR_Exchange_Rate_Daily_2020_2026_Quality.csv"
START_DATE = pd.Timestamp("2020-01-01")
END_DATE = pd.Timestamp("2026-10-29")


def main():
    raw = pd.read_csv(SOURCE, dtype="string", keep_default_na=False)
    required = {"date", "base", "quote", "rate"}
    if not required.issubset(raw.columns):
        raise ValueError(f"Missing required columns: {required - set(raw.columns)}")

    data = raw.loc[:, ["date", "base", "quote", "rate"]].copy()
    data["base"] = data["base"].str.strip().str.upper()
    data["quote"] = data["quote"].str.strip().str.upper()
    if not ((data["base"] == "EUR") & (data["quote"] == "INR")).all():
        raise ValueError("Unexpected currency direction: expected EUR -> INR throughout")

    dates = pd.to_datetime(data["date"], format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        raise ValueError(f"Found {int(dates.isna().sum())} invalid dates")
    data["date"] = dates

    tokens = data["rate"].str.strip().replace({"": pd.NA, ".": pd.NA, "-": pd.NA})
    if tokens.dropna().str.contains(",", regex=False).any():
        raise ValueError("Comma-formatted rate found: inspect source convention before parsing")
    rates = pd.to_numeric(tokens, errors="coerce")
    bad_numeric = tokens.notna() & rates.isna()
    if bad_numeric.any():
        raise ValueError(f"Unrecognized numeric values: {tokens[bad_numeric].unique().tolist()[:5]}")
    if (rates.dropna() <= 0).any():
        raise ValueError("EUR/INR exchange rates must be positive")
    data["rate"] = rates.astype("float64")

    duplicates_in_raw = int(data["date"].duplicated().sum())
    conflicts = data.groupby("date")["rate"].nunique(dropna=False) > 1
    if conflicts.any():
        raise ValueError(f"Conflicting EUR/INR rates for dates: {conflicts[conflicts].index.tolist()[:5]}")
    data = data.sort_values("date").drop_duplicates(subset="date", keep="first")
    data = data.loc[data["date"].between(START_DATE, END_DATE)].copy()

    gap_days = data["date"].diff().dt.days
    long_gaps = [
        {"next_observation": d.date().isoformat(), "calendar_days": int(n)}
        for d, n in zip(data.loc[gap_days > 4, "date"], gap_days[gap_days > 4])
    ]

    clean = data[["date", "rate"]].rename(columns={"rate": "eur_inr_inr_per_eur"})
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(OUTPUT, index=False, date_format="%Y-%m-%d", na_rep="")

    report_rows = [
        {"metric": "dataset", "value": "ECB EUR/INR via Frankfurter"},
        {"metric": "source", "value": str(SOURCE.relative_to(PROJECT_ROOT))},
        {"metric": "processed", "value": str(OUTPUT.relative_to(PROJECT_ROOT))},
        {"metric": "source_columns", "value": "; ".join(raw.columns.tolist())},
        {"metric": "source_rows", "value": len(raw)},
        {"metric": "source_date_min", "value": dates.min().date().isoformat()},
        {"metric": "source_date_max", "value": dates.max().date().isoformat()},
        {"metric": "processed_rows", "value": len(clean)},
        {"metric": "processed_date_min", "value": clean["date"].min().date().isoformat()},
        {"metric": "processed_date_max", "value": clean["date"].max().date().isoformat()},
        {"metric": "duplicate_dates_removed", "value": duplicates_in_raw},
        {
            "metric": "missing_rates_preserved",
            "value": int(clean["eur_inr_inr_per_eur"].isna().sum())
        },
        {
            "metric": "out_of_range_observations_excluded",
            "value": int(len(raw) - duplicates_in_raw - len(clean))
        },
        {
            "metric": "long_calendar_gaps_over_4_days",
            "value": "; ".join(
                f'{gap["next_observation"]} ({gap["calendar_days"]} days)'
                for gap in long_gaps
            ) if long_gaps else "none"
        },
        {"metric": "rate_unit", "value": "INR per EUR"},
        {
            "metric": "date_semantics",
            "value": "ECB reference fixing date, not independently verified publication timestamp"
        },
        {
            "metric": "publication_alignment",
            "value": (
                "PENDING: ECB rates normally published around 16:00 "
                "Europe/Frankfurt on TARGET working days."
            )
        },
        {"metric": "imputation", "value": "NONE"},
    ]

    REPORT.parent.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(report_rows).to_csv(
        REPORT,
        index=False,
        encoding="utf-8"
    )

    print(f"Saved {OUTPUT.relative_to(PROJECT_ROOT)} ({len(clean)} rows)")
    print(f"Duplicates removed: {duplicates_in_raw}")
    print(f"Missing rates preserved: {clean['eur_inr_inr_per_eur'].isna().sum()}")
    print(f"Gaps over 4 calendar days flagged for calendar review: {len(long_gaps)}")
    print(f"Quality report: {REPORT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
