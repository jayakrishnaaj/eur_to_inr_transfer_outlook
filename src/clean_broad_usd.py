from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW = PROJECT_ROOT / "data" / "raw" / "currency" / "FRED_US_Broad_Dollar_Index.csv"
OUT = PROJECT_ROOT / "data" / "interim" / "FRED_US_Broad_Dollar_Index_Clean.csv"
REPORT = PROJECT_ROOT / "reports" / "quality" / "FRED_US_Broad_Dollar_Index_Quality.csv"
START = pd.Timestamp('2020-01-01')


def main():
    df = pd.read_csv(RAW, dtype='string', keep_default_na=True)
    expected = {'observation_date', 'DTWEXBGS'}
    if set(df.columns) != expected:
        raise ValueError(f'Unexpected columns: {list(df.columns)}')

    raw_rows = len(df)
    df['date'] = pd.to_datetime(df['observation_date'], format='%Y-%m-%d', errors='coerce')
    if df['date'].isna().any():
        raise ValueError(f"Found {df['date'].isna().sum()} unparseable dates; inspect the raw file.")

    text_values = df['DTWEXBGS'].str.strip().str.replace(',', '', regex=False)
    missing_tokens = {'', '.', '-', 'NA', 'N/A', 'nan'}
    invalid = text_values.notna() & ~text_values.isin(missing_tokens) & pd.to_numeric(text_values, errors='coerce').isna()
    if invalid.any():
        raise ValueError(f'Unexpected non-numeric values: {text_values[invalid].unique().tolist()}')
    df['broad_usd_index_2006_100'] = pd.to_numeric(text_values, errors='coerce')
    if (df['broad_usd_index_2006_100'].dropna() <= 0).any():
        raise ValueError('Index values should be positive; inspect nonpositive values.')

    conflicts = df.groupby('date')['broad_usd_index_2006_100'].nunique(dropna=False)
    if (conflicts > 1).any():
        raise ValueError(f'Conflicting values on dates: {conflicts[conflicts > 1].index.tolist()}')
    duplicates = int(df['date'].duplicated().sum())
    df = df.sort_values('date').drop_duplicates('date', keep='first')

    df = df.loc[df['date'] >= START, ['date', 'broad_usd_index_2006_100']]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False, date_format='%Y-%m-%d', na_rep='')

    vals = df['broad_usd_index_2006_100'].dropna()
    changes = vals.diff().abs().dropna()
    median_change = changes.median()
    mad = (changes - median_change).abs().median()
    jumps = changes[changes > median_change + 15 * mad] if mad > 0 else changes.iloc[0:0]
    report = pd.DataFrame([
        {'metric':'source', 'value':'FRED DTWEXBGS (Federal Reserve H.10)'},
        {'metric':'raw_rows', 'value':raw_rows},
        {'metric':'rows_exported', 'value':len(df)},
        {'metric':'duplicate_dates_removed', 'value':duplicates},
        {'metric':'missing_index_values', 'value':int(df.iloc[:,1].isna().sum())},
        {'metric':'start_observation_date', 'value':df['date'].min().date().isoformat()},
        {'metric':'end_observation_date', 'value':df['date'].max().date().isoformat()},
        {'metric':'flagged_jump_dates', 'value':','.join(df.loc[jumps.index, 'date'].dt.strftime('%Y-%m-%d'))},
        {'metric':'publication_alignment', 'value':'NOT DONE: H.10 daily observations published in weekly releases; map to actual release timestamps at merge stage'},
    ])
    report.to_csv(REPORT, index=False)
    print(f'Saved: {OUT} ({len(df)} rows)')
    print(f'Missing retained: {int(df.iloc[:,1].isna().sum())}; duplicates removed: {duplicates}')
    print(f'Large movements to review (not deleted): {df.loc[jumps.index,"date"].dt.date.tolist()}')
    print(f'Quality report: {REPORT}')

if __name__ == '__main__':
    main()
