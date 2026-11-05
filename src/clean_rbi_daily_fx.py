from pathlib import Path
import json
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT_ROOT / "data" / "raw" / "currency" / "RBI_INR_Exchange_Rates_Daily.xlsx"
DEST = PROJECT_ROOT / "data" / "interim" / "RBI_INR_Exchange_Rates_Daily_Clean.csv"
REPORT = PROJECT_ROOT / "reports" / "quality" / "RBI_INR_Exchange_Rates_Daily_Quality.csv"
START = pd.Timestamp('2020-01-01')


raw = pd.read_excel(
    SOURCE,
    sheet_name="Daily Foreign Exchange Spot Rat",
    header=5,
    usecols="B:F",
    dtype=str,
    keep_default_na=False,
    engine="openpyxl"
)

# Validate the headers already detected by Pandas.
expected = [
    'Date',
    'US Dollar',
    'Pound Sterling',
    'Euro',
    'Japanese Yen'
]

raw.columns = raw.columns.str.strip()

if raw.columns.tolist() != expected:
    raise ValueError(
        f'Unexpected RBI columns: {raw.columns.tolist()}'
    )

# Remove the numbering row (1, 2, 3, 4, 5).
numbering_row = raw.iloc[0].str.strip().tolist()

if numbering_row != ['1', '2', '3', '4', '5']:
    raise ValueError(
        f'Unexpected first data row: {numbering_row}'
    )

source = raw.iloc[1:].copy()

# Assign standardized internal column names.
source.columns = [
    'date_raw',
    'usd_raw',
    'gbp_raw',
    'eur_raw',
    'jpy_100_raw'
]


# Parse Excel dates.
source['date'] = pd.to_datetime(
    source['date_raw'].str.strip(),
    errors='coerce'
)

# Identify non-observation rows.
invalid_rows = source[
    source['date'].isna() &
    source['date_raw'].str.strip().ne('')
].copy()

# RBI explanatory notes are metadata, not observations.
notes_rows = invalid_rows[
    invalid_rows['date_raw'].str.strip().str.startswith(
        'Notes :',
        na=False
    )
]

# Reject any unexpected non-date rows.
unexpected_rows = invalid_rows.drop(notes_rows.index)

if not unexpected_rows.empty:
    raise ValueError(
        'Unrecognized non-date rows: '
        f'{unexpected_rows["date_raw"].tolist()}'
    )

# Retain actual observations from the project start date.
source = source.loc[
    source['date'].notna() &
    source['date'].ge(START)
].copy()

# Record the number of explanatory rows excluded.
excluded_notes_rows = len(notes_rows)
if source.empty:
    raise ValueError(
        'No valid RBI observations found after applying the start-date filter.'
    )


rename = {'usd_raw':'rbi_usd_inr_inr_per_usd', 'gbp_raw':'rbi_gbp_inr_inr_per_gbp',
          'eur_raw':'rbi_eur_inr_inr_per_eur', 'jpy_100_raw':'rbi_jpy_inr_inr_per_100_jpy'}
for original, clean in rename.items():
    raw_values = source[original].str.strip().str.replace(',','',regex=False)
    missing_tokens = raw_values.isin(['','-','.','NA','N/A'])
    parsed = pd.to_numeric(raw_values.where(~missing_tokens),errors='coerce')
    invalid = parsed.isna() & ~missing_tokens
    if invalid.any():
        raise ValueError(f'Unrecognized numeric values in {original}: {raw_values[invalid].unique().tolist()}')
    if (parsed.dropna() <= 0).any():
        raise ValueError(f'Non-positive exchange rate found in {original}')
    source[clean] = parsed

cols = list(rename.values())
source = source[['date'] + cols].sort_values('date')
# Dates with identical values may be deduplicated. Conflicting rows require investigation.
duplicate_dates = int(source.duplicated('date').sum())
conflicts = source.groupby('date')[cols].nunique(dropna=False).gt(1).any(axis=1)
if conflicts.any():
    conflicting_dates = (
        conflicts[conflicts]
        .index
        .strftime('%Y-%m-%d')
        .tolist()
    )

    raise ValueError(
        f'Conflicting duplicate exchange-rate dates: {conflicting_dates}'
    )
source = source.drop_duplicates('date',keep='first').reset_index(drop=True)
long_gaps = source.loc[source.date.diff().dt.days.gt(4),'date'].dt.strftime('%Y-%m-%d').tolist()
DEST.parent.mkdir(parents=True,exist_ok=True)
REPORT.parent.mkdir(parents=True,exist_ok=True)
source.to_csv(DEST,index=False,date_format='%Y-%m-%d',float_format='%.4f')
report_rows = [
    {'metric': 'source',
     'value': 'RBI Daily Foreign Exchange Spot Rates'},

    {'metric': 'raw_rows',
     'value': len(raw)},

    {'metric': 'rows_exported',
     'value': len(source)},

    {'metric': 'excluded_explanatory_rows',
     'value': excluded_notes_rows},

    {'metric': 'duplicate_dates_removed',
     'value': duplicate_dates},

    {'metric': 'missing_usd_inr_values',
     'value': int(source['rbi_usd_inr_inr_per_usd'].isna().sum())},

    {'metric': 'missing_gbp_inr_values',
     'value': int(source['rbi_gbp_inr_inr_per_gbp'].isna().sum())},

    {'metric': 'missing_eur_inr_values',
     'value': int(source['rbi_eur_inr_inr_per_eur'].isna().sum())},

    {'metric': 'missing_jpy_inr_values',
     'value': int(source['rbi_jpy_inr_inr_per_100_jpy'].isna().sum())},

    {'metric': 'start_observation_date',
     'value': str(source['date'].min().date())},

    {'metric': 'end_observation_date',
     'value': str(source['date'].max().date())},

    {'metric': 'flagged_gap_dates',
     'value': '; '.join(long_gaps) if long_gaps else 'none'},

    {'metric': 'imputation',
     'value': 'NONE'},

    {'metric': 'publication_alignment',
     'value': (
         'NOT DONE: RBI observation dates represent source dates; '
         'historical publication availability must be verified.'
     )},

    {'metric': 'jpy_unit',
     'value': 'INR per 100 JPY'}
]

pd.DataFrame(report_rows).to_csv(
    REPORT,
    index=False,
    encoding='utf-8'
)
print(
    f'Wrote {DEST}: {len(source)} rows, '
    f'{duplicate_dates} duplicate dates removed'
)

print('Missing values:')
for column in cols:
    print(f'  {column}: {source[column].isna().sum()}')

print(
    f'Gaps > 4 calendar days: {len(long_gaps)} '
    '(investigate, not automatically fill)'
)

print(f'Quality report: {REPORT}')
