from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "data/raw/energy/FRED_Global_Brent_Crude_Oil_Price_Daily_2020_2026.csv"
OUTPUT = PROJECT_ROOT / "data/interim/FRED_Global_Brent_Crude_Oil_Price_Daily_2020_2026_Clean.csv"
REPORT = PROJECT_ROOT / "reports/quality/FRED_Global_Brent_Crude_Oil_Price_Daily_2020_2026_Quality.csv"
START_DATE = pd.Timestamp("2020-01-01")
END_DATE = pd.Timestamp("2026-10-29")
SOURCE_COLUMN = "DCOILBRENTEU"
VALUE_COLUMN = "brent_usd_per_barrel"
MISSING_MARKERS = {"", ".", "-", "NA", "N/A", "NAN", "NULL"}


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Source file not found: {SOURCE}")

    raw = pd.read_csv(SOURCE, dtype="string", keep_default_na=False)
    required = {"observation_date", SOURCE_COLUMN}
    if set(raw.columns) != required:
        raise ValueError(f"Unexpected FRED columns: {raw.columns.tolist()}; expected {sorted(required)}")
    if raw.empty:
        raise ValueError("Source CSV contains no observations")

    dates = pd.to_datetime(raw["observation_date"].str.strip(), format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        raise ValueError(
            "Unparseable observation dates: "
            f"{raw.loc[dates.isna(), 'observation_date'].head(5).tolist()}"
        )

    tokens = raw[SOURCE_COLUMN].str.strip()
    is_missing = tokens.str.upper().isin(MISSING_MARKERS)
    parsed = pd.to_numeric(tokens.mask(is_missing), errors="coerce").astype("float64")
    malformed = ~is_missing & parsed.isna()
    if malformed.any():
        raise ValueError(f"Unexpected numeric values: {tokens.loc[malformed].unique().tolist()[:5]}")
    if (~np.isfinite(parsed.dropna().to_numpy())).any():
        raise ValueError("Non-finite Brent prices detected (infinity is not valid)")
    if (parsed.dropna() <= 0).any():
        raise ValueError("Nonpositive Brent price detected; review source observations")

    data = pd.DataFrame({"date": dates, VALUE_COLUMN: parsed})
    duplicate_dates = int(data["date"].duplicated().sum())
    conflicting = data.groupby("date")[VALUE_COLUMN].nunique(dropna=False).gt(1)
    if conflicting.any():
        raise ValueError(
            "Conflicting duplicate Brent observations: "
            f"{conflicting[conflicting].index.strftime('%Y-%m-%d').tolist()[:5]}"
        )
    data = data.sort_values("date").drop_duplicates("date", keep="first").reset_index(drop=True)
    unique_source_rows = len(data)
    source_date_min = data["date"].min().date().isoformat()
    source_date_max = data["date"].max().date().isoformat()

    in_range = data["date"].between(START_DATE, END_DATE)
    out_of_range = int((~in_range).sum())
    clean = data.loc[in_range, ["date", VALUE_COLUMN]].reset_index(drop=True)
    if clean.empty:
        raise ValueError("No observations within the selected study period")

    missing_count = int(clean[VALUE_COLUMN].isna().sum())
    valid = clean.dropna(subset=[VALUE_COLUMN]).copy()
    values = valid[VALUE_COLUMN]
    changes = values.diff().abs().dropna()
    if not changes.empty:
        median_change = changes.median()
        mad = (changes - median_change).abs().median()
        flagged = changes[changes > median_change + 15 * mad] if mad > 0 else changes.iloc[0:0]
    else:
        flagged = changes
    jump_dates = clean.loc[flagged.index, "date"].dt.strftime("%Y-%m-%d").tolist()

    gaps = clean["date"].diff().dt.days
    gap_labels = [
        f"{day:%Y-%m-%d} ({int(days)} days)"
        for day, days in zip(clean.loc[gaps.gt(4), "date"], gaps[gaps.gt(4)])
    ]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(OUTPUT, index=False, date_format="%Y-%m-%d", na_rep="")

    report_rows = [
        {"metric": "dataset", "value": "FRED Global Brent Crude Oil Price Daily"},
        {"metric": "series_id", "value": SOURCE_COLUMN},
        {"metric": "source", "value": str(SOURCE.relative_to(PROJECT_ROOT))},
        {"metric": "source_url", "value": "https://fred.stlouisfed.org/series/DCOILBRENTEU"},
        {"metric": "processed", "value": str(OUTPUT.relative_to(PROJECT_ROOT))},
        {"metric": "raw_rows", "value": len(raw)},
        {"metric": "unique_dated_source_rows", "value": unique_source_rows},
        {"metric": "source_date_min", "value": source_date_min},
        {"metric": "source_date_max", "value": source_date_max},
        {"metric": "processed_rows", "value": len(clean)},
        {"metric": "processed_date_min", "value": clean["date"].min().date().isoformat()},
        {"metric": "processed_date_max", "value": clean["date"].max().date().isoformat()},
        {"metric": "duplicate_dates_removed", "value": duplicate_dates},
        {"metric": "out_of_range_observations_excluded", "value": out_of_range},
        {"metric": "missing_values_preserved", "value": missing_count},
        {"metric": "valid_price_count", "value": len(valid)},
        {"metric": "min_valid_usd_per_barrel", "value": float(values.min()) if not values.empty else "not available"},
        {"metric": "max_valid_usd_per_barrel", "value": float(values.max()) if not values.empty else "not available"},
        {"metric": "gaps_over_4_calendar_days", "value": "; ".join(gap_labels) if gap_labels else "none"},
        {"metric": "large_movements_flagged", "value": "; ".join(jump_dates) if jump_dates else "none"},
        {"metric": "rate_unit", "value": "USD per barrel"},
        {"metric": "date_semantics", "value": "FRED source observation date, not a verified publication timestamp"},
        {"metric": "publication_alignment", "value": "NOT DONE: verify source release timing and revisions before as-of historical ML merges"},
        {"metric": "revision_note", "value": "Historical FRED observations may be revised; this file is not a vintage-aware snapshot"},
        {"metric": "imputation", "value": "NONE"},
        {"metric": "outlier_deletion", "value": "NONE"},
    ]
    pd.DataFrame(report_rows, columns=["metric", "value"]).to_csv(REPORT, index=False, encoding="utf-8")

    print(f"Saved: {OUTPUT.relative_to(PROJECT_ROOT)} ({len(clean)} rows)")
    print(f"Duplicate dates removed: {duplicate_dates}; out-of-range excluded: {out_of_range}")
    print(f"Missing prices preserved: {missing_count}")
    print(f"Gaps over 4 calendar days: {len(gap_labels)}; large movements flagged: {len(jump_dates)}")
    print(f"Quality report: {REPORT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
