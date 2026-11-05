from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT_ROOT / 'data/raw/energy/FRED_US_Henry_Hub_Natural_Gas_Price_Daily_2020_2026.csv'
OUTPUT = PROJECT_ROOT / 'data/interim/FRED_US_Henry_Hub_Natural_Gas_Price_Daily_2020_2026_Clean.csv'
REPORT = PROJECT_ROOT / 'reports/quality/FRED_US_Henry_Hub_Natural_Gas_Price_Daily_2020_2026_Quality.csv'
START_DATE = pd.Timestamp('2020-01-01')
END_DATE = pd.Timestamp('2026-10-29')
VALUE_COLUMN = 'henry_hub_usd_per_mmbtu'
EXPECTED_COLUMNS = ['observation_date', 'DHHNGSP']
MISSING_MARKERS = {'', '.', '-', 'NA', 'N/A', 'NULL', 'NAN'}


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f'Source CSV not found: {SOURCE}')

    # Read source fields as strings so erroneous values cannot be silently changed.
    raw = pd.read_csv(SOURCE, dtype='string', keep_default_na=False, encoding='utf-8-sig')
    if raw.columns.tolist() != EXPECTED_COLUMNS:
        raise ValueError(f'Unexpected source columns: {raw.columns.tolist()}')
    if raw.empty:
        raise ValueError('Source CSV contains no observations')

    source_dates = pd.to_datetime(
        raw['observation_date'].str.strip(), format='%Y-%m-%d', errors='coerce'
    )
    if source_dates.isna().any():
        bad_dates = raw.loc[source_dates.isna(), 'observation_date'].head(5).tolist()
        raise ValueError(f'Invalid observation date(s): {bad_dates}')

    tokens = raw['DHHNGSP'].str.strip()
    missing_mask = tokens.str.upper().isin(MISSING_MARKERS)
    # FRED uses periods for missing observations; retain them as NaN.
    numeric = pd.to_numeric(tokens.mask(missing_mask), errors='coerce').astype('float64')
    invalid = ~missing_mask & (numeric.isna() | ~np.isfinite(numeric))
    if invalid.any():
        raise ValueError(f'Unexpected nonnumeric/non-finite price(s): {tokens.loc[invalid].head(5).tolist()}')
    if (numeric.dropna() <= 0).any():
        raise ValueError('Nonpositive Henry Hub price(s) found; investigate source')

    data = pd.DataFrame({'date': source_dates, VALUE_COLUMN: numeric})
    # Validate all duplicates before date-range filtering; NaN vs numeric is a conflict.
    conflicts = data.groupby('date')[VALUE_COLUMN].nunique(dropna=False).gt(1)
    if conflicts.any():
        examples = conflicts[conflicts].index.strftime('%Y-%m-%d').tolist()[:5]
        raise ValueError(f'Conflicting values on duplicate dates: {examples}')
    duplicate_dates = int(data['date'].duplicated().sum())
    data = data.sort_values('date').drop_duplicates('date', keep='first')

    source_date_min = data['date'].min().date().isoformat()
    source_date_max = data['date'].max().date().isoformat()
    in_range = data['date'].between(START_DATE, END_DATE)
    out_of_range = int((~in_range).sum())
    data = data.loc[in_range, ['date', VALUE_COLUMN]].reset_index(drop=True)
    if data.empty:
        raise ValueError('No observations in the selected study period')

    # Calculate movements over consecutive nonmissing observations; never delete them.
    valid = data.dropna(subset=[VALUE_COLUMN])
    differences = valid[VALUE_COLUMN].diff().abs().dropna()
    jump_dates = []
    threshold = None
    if len(valid) > 20 and not differences.empty:
        median = differences.median()
        mad = (differences - median).abs().median()
        if pd.notna(mad) and mad > 0:
            threshold = float(median + 15 * mad)
            jump_dates = data.loc[differences.index[differences > threshold], 'date'].dt.strftime('%Y-%m-%d').tolist()

    gap_days = data['date'].diff().dt.days
    long_gaps = [
        f'{date:%Y-%m-%d} ({int(days)} days)'
        for date, days in zip(data.loc[gap_days.gt(4), 'date'], gap_days[gap_days.gt(4)])
    ]
    missing_count = int(data[VALUE_COLUMN].isna().sum())
    valid_count = int(data[VALUE_COLUMN].notna().sum())

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(OUTPUT, index=False, date_format='%Y-%m-%d', na_rep='', float_format='%.10g')

    report_rows = [
        {'metric': 'dataset', 'value': 'FRED Henry Hub Natural Gas Spot Price (DHHNGSP)'},
        {'metric': 'source', 'value': str(SOURCE.relative_to(PROJECT_ROOT))},
        {'metric': 'processed', 'value': str(OUTPUT.relative_to(PROJECT_ROOT))},
        {'metric': 'series_id', 'value': 'DHHNGSP'},
        {'metric': 'provider', 'value': 'FRED (original source: EIA)'},
        {'metric': 'source_columns', 'value': '; '.join(raw.columns)},
        {'metric': 'unit', 'value': 'USD per million British thermal units (MMBtu)'},
        {'metric': 'raw_rows', 'value': len(raw)},
        {'metric': 'source_date_min', 'value': source_date_min},
        {'metric': 'source_date_max', 'value': source_date_max},
        {'metric': 'processed_rows', 'value': len(data)},
        {'metric': 'processed_date_min', 'value': data['date'].min().date().isoformat()},
        {'metric': 'processed_date_max', 'value': data['date'].max().date().isoformat()},
        {'metric': 'duplicate_dates_removed', 'value': duplicate_dates},
        {'metric': 'out_of_range_observations_excluded', 'value': out_of_range},
        {'metric': 'missing_values_preserved', 'value': missing_count},
        {'metric': 'valid_price_count', 'value': valid_count},
        {'metric': 'minimum_price', 'value': float(valid[VALUE_COLUMN].min()) if valid_count else 'not available'},
        {'metric': 'maximum_price', 'value': float(valid[VALUE_COLUMN].max()) if valid_count else 'not available'},
        {'metric': 'large_movement_threshold_usd_per_mmbtu', 'value': threshold if threshold is not None else 'not calculated'},
        {'metric': 'large_movement_dates_flagged', 'value': '; '.join(jump_dates) if jump_dates else 'none'},
        {'metric': 'gaps_over_4_calendar_days', 'value': '; '.join(long_gaps) if long_gaps else 'none'},
        {'metric': 'date_semantics', 'value': 'Source observation date, not verified publication date'},
        {'metric': 'publication_alignment', 'value': 'NOT DONE: verify historical public availability before as-of ML merges'},
        {'metric': 'imputation', 'value': 'NONE'},
        {'metric': 'outlier_deletion', 'value': 'NONE'},
    ]
    pd.DataFrame(report_rows, columns=['metric', 'value']).to_csv(REPORT, index=False, encoding='utf-8')

    print(f'Saved: {OUTPUT.relative_to(PROJECT_ROOT)} ({len(data)} rows)')
    print(f'Missing prices preserved: {missing_count}; valid prices: {valid_count}')
    print(f'Duplicate dates removed: {duplicate_dates}; out-of-range excluded: {out_of_range}')
    print(f'Long gaps over 4 calendar days: {len(long_gaps)}; large movements flagged: {len(jump_dates)}')
    print(f'Quality report: {REPORT.relative_to(PROJECT_ROOT)}')


if __name__ == '__main__':
    main()
