from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "data" / "raw" / "currency" / "CBOE_US_VIX_Volatility_Index.csv"
OUTPUT = PROJECT_ROOT / "data" / "interim" / "CBOE_US_VIX_Volatility_Index_Clean.csv"
REPORT = PROJECT_ROOT / "reports" / "quality" / "CBOE_US_VIX_Volatility_Index_Quality.csv"
FIGURE = PROJECT_ROOT / "reports" / "figures" / "CBOE_US_VIX_Volatility_Index_daily_closes.png"
START_DATE = pd.Timestamp("2020-01-01")
END_DATE = pd.Timestamp("2026-10-29")

SOURCE_COLUMNS = ["observation_date", "VIXCLS"]
VALUE_COLUMN = "vix_index"
MISSING_TOKENS = {"", ".", "-", "NA", "N/A", "NAN", "NULL"}


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Source CSV not found: {SOURCE}")

    raw = pd.read_csv(SOURCE, dtype="string", keep_default_na=False)
    if raw.columns.tolist() != SOURCE_COLUMNS:
        raise ValueError(f"Unexpected source columns: {raw.columns.tolist()}")
    if raw.empty:
        raise ValueError("The VIX source CSV contains no observations")
    raw_rows = len(raw)

    dates = pd.to_datetime(
        raw["observation_date"].str.strip(), format="%Y-%m-%d", errors="coerce"
    )
    if dates.isna().any():
        raise ValueError(f"Invalid observation dates: {int(dates.isna().sum())}")

    text_values = raw["VIXCLS"].str.strip()
    missing = text_values.str.upper().isin(MISSING_TOKENS)
    numeric = pd.to_numeric(text_values.mask(missing), errors="coerce")
    invalid = ~missing & numeric.isna()
    if invalid.any():
        raise ValueError(
            "Unrecognized VIX values: "
            f"{text_values.loc[invalid].unique().tolist()[:5]}"
        )
    if (~numeric.dropna().map(lambda value: float('-inf') < value < float('inf'))).any():
        raise ValueError("Non-finite VIX value found")
    if (numeric.dropna() <= 0).any():
        raise ValueError("Nonpositive VIX value found: inspect source")

    data = pd.DataFrame({"date": dates, VALUE_COLUMN: numeric.astype("float64")})

    duplicate_dates = int(data["date"].duplicated().sum())
    conflicts = data.groupby("date")[VALUE_COLUMN].nunique(dropna=False).gt(1)
    if conflicts.any():
        bad_dates = conflicts[conflicts].index.strftime("%Y-%m-%d").tolist()[:5]
        raise ValueError(f"Conflicting VIX values on duplicate dates: {bad_dates}")
    data = data.sort_values("date").drop_duplicates("date", keep="first")
    unique_source_rows = len(data)
    source_date_min = data["date"].min().date().isoformat()
    source_date_max = data["date"].max().date().isoformat()

    in_period = data["date"].between(START_DATE, END_DATE)
    out_of_range = int((~in_period).sum())
    data = data.loc[in_period, ["date", VALUE_COLUMN]].reset_index(drop=True)
    if data.empty:
        raise ValueError("No VIX observations within the selected study period")

    day_gaps = data["date"].diff().dt.days
    long_gaps = [
        f"{day:%Y-%m-%d} ({int(days)} days)"
        for day, days in zip(
            data.loc[day_gaps.gt(4), "date"], day_gaps[day_gaps.gt(4)]
        )
    ]
    valid = data.dropna(subset=[VALUE_COLUMN])
    changes = valid[VALUE_COLUMN].diff().abs().dropna()
    median_change = changes.median()
    mad = (changes - median_change).abs().median()
    threshold = float(median_change + 15 * mad) if pd.notna(mad) and mad > 0 else None
    jump_dates = (
        data.loc[changes[changes.gt(threshold)].index, "date"]
        .dt.strftime("%Y-%m-%d")
        .tolist()
        if threshold is not None
        else []
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    FIGURE.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(OUTPUT, index=False, date_format="%Y-%m-%d", na_rep="")

    missing_count = int(data[VALUE_COLUMN].isna().sum())
    report_rows = [
        {"metric": "dataset", "value": "Cboe VIX daily close (FRED VIXCLS)"},
        {"metric": "source", "value": str(SOURCE.relative_to(PROJECT_ROOT))},
        {"metric": "processed", "value": str(OUTPUT.relative_to(PROJECT_ROOT))},
        {"metric": "figure", "value": str(FIGURE.relative_to(PROJECT_ROOT))},
        {"metric": "source_columns", "value": "; ".join(raw.columns)},
        {"metric": "series_id", "value": "VIXCLS"},
        {"metric": "unit", "value": "VIX index points"},
        {"metric": "frequency", "value": "US trading-day closes"},
        {"metric": "raw_rows", "value": raw_rows},
        {"metric": "valid_unique_source_rows", "value": unique_source_rows},
        {"metric": "source_date_min", "value": source_date_min},
        {"metric": "source_date_max", "value": source_date_max},
        {"metric": "processed_rows", "value": len(data)},
        {"metric": "processed_date_min", "value": data["date"].min().date().isoformat()},
        {"metric": "processed_date_max", "value": data["date"].max().date().isoformat()},
        {"metric": "duplicate_dates_removed", "value": duplicate_dates},
        {"metric": "out_of_range_observations_excluded", "value": out_of_range},
        {"metric": "missing_vix_values_preserved", "value": missing_count},
        {"metric": "long_calendar_gaps_over_4_days", "value": "; ".join(long_gaps) if long_gaps else "none"},
        {"metric": "large_movement_threshold_index_points", "value": threshold if threshold is not None else "not computed"},
        {"metric": "large_movement_dates_flagged", "value": "; ".join(jump_dates) if jump_dates else "none"},
        {"metric": "date_semantics", "value": "US trading-day closing observation, not verified publication timestamp"},
        {"metric": "publication_alignment", "value": "PENDING: apply as-of availability timing before historical ML merges; same-day 16:00 Europe/Frankfurt predictions cannot assume the US close is known"},
        {"metric": "gap_interpretation", "value": "Review US market holiday calendars; no dates created"},
        {"metric": "imputation", "value": "NONE"},
        {"metric": "outlier_deletion", "value": "NONE"},
        {"metric": "sharing_note", "value": "Check Cboe/FRED licensing and redistribution permissions before publishing data"},
    ]
    pd.DataFrame(report_rows, columns=["metric", "value"]).to_csv(
        REPORT, index=False, encoding="utf-8"
    )

    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(data["date"], data[VALUE_COLUMN], linewidth=1)
    ax.set(
        title="VIX daily closing index — source observations",
        xlabel="Observation date",
        ylabel="VIX index points",
    )
    fig.tight_layout()
    fig.savefig(FIGURE, dpi=150)
    plt.close(fig)

    print(f"Saved: {OUTPUT.relative_to(PROJECT_ROOT)} ({len(data)} rows)")
    print(f"Duplicate dates removed: {duplicate_dates}; out-of-range excluded: {out_of_range}")
    print(f"Missing VIX values preserved: {missing_count}")
    print(f"Long gaps (>4 days): {len(long_gaps)}; large movements flagged: {len(jump_dates)}")
    print(f"Quality report: {REPORT.relative_to(PROJECT_ROOT)}")
    print(f"Chart: {FIGURE.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
