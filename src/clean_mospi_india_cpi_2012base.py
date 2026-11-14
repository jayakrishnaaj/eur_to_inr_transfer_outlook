from __future__ import annotations
from collections import Counter
from datetime import datetime
from pathlib import Path
import math
import re
import pandas as pd
from openpyxl import load_workbook

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / 'data/raw/inflation/MOSPI_India_CPI_2012_Base_Current_2026.xlsx'
OUTPUT = PROJECT_ROOT / 'data/interim/MOSPI_India_CPI_2012_Base_Current_2026_Clean.csv'
REPORT = PROJECT_ROOT / 'reports/quality/MOSPI_India_CPI_2012_Base_Current_2026_Quality.csv'
START_DATE = pd.Timestamp('2020-01-01')
END_DATE = pd.Timestamp('2026-10-29')
SHEET_NAME = 'Sheet1'
EXPECTED_HEADERS = [
    'baseyear', 'year', 'month_code', 'month', 'state', 'sector',
    'group', 'subgroup', 'index', 'inflation', 'status',
]
VALUE_COLUMNS = [
    'india_cpi_2012base_index',
    'india_cpi_2012base_annual_inflation_pct',
]
TARGET = ('All India', 'Combined', 'General', 'General-Overall')
MISSING_TOKENS = {'', '.', '-', ':', 'NA', 'N/A', 'NULL', 'NAN'}
NUMBER_RE = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)\Z')


def parse_number(value: object, row_number: int, field: str) -> float:
    if value is None:
        return math.nan
    if isinstance(value, bool):
        raise ValueError(f'Row {row_number}: Boolean value in {field}')
    text = str(value).strip()
    if text.upper() in MISSING_TOKENS:
        return math.nan
    if not NUMBER_RE.fullmatch(text):
        raise ValueError(f'Row {row_number}: Invalid {field}: {value!r}')
    number = float(text)
    if not math.isfinite(number):
        raise ValueError(f'Row {row_number}: Non-finite {field}: {value!r}')
    return number


def month_labels(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    return [d.strftime('%Y-%m') for d in pd.date_range(start, end, freq='MS')]


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f'Source workbook not found: {SOURCE}')

    workbook = load_workbook(SOURCE, read_only=True, data_only=True)
    raw_rows = 0
    source_year_counts: Counter[int] = Counter()
    selected_all = []
    status_counts: Counter[str] = Counter()
    try:
        if SHEET_NAME not in workbook.sheetnames:
            raise ValueError(f'Missing sheet {SHEET_NAME!r}; found {workbook.sheetnames}')
        sheet = workbook[SHEET_NAME]
        rows = sheet.iter_rows(values_only=True)
        header = next(rows, None)
        if header is None or [str(x).strip() if x is not None else '' for x in header[:11]] != EXPECTED_HEADERS:
            raise ValueError(f'Unexpected source columns: {header[:11] if header else header!r}')

        for row_number, row in enumerate(rows, start=2):
            if not any(x is not None for x in row):
                continue
            raw_rows += 1
            cells = list(row[:11]) + [None] * max(0, 11 - len(row))
            base, year_raw, month_raw, month_name, region, sector, group, subgroup, idx, inflation, status = cells[:11]
            try:
                year = int(str(year_raw).strip())
                month = int(str(month_raw).strip())
                dt = pd.Timestamp(year=year, month=month, day=1)
            except (TypeError, ValueError) as exc:
                raise ValueError(f'Invalid year/month at source row {row_number}: {year_raw!r}, {month_raw!r}') from exc
            source_year_counts[year] += 1
            if tuple(str(x).strip() for x in (region, sector, group, subgroup)) != TARGET:
                continue
            if str(base).strip() != '2012':
                raise ValueError(f'Unexpected CPI base at row {row_number}: {base!r}')
            cpi = parse_number(idx, row_number, 'index')
            rate = parse_number(inflation, row_number, 'inflation')
            if not math.isnan(cpi) and cpi <= 0:
                raise ValueError(f'Nonpositive CPI index at row {row_number}: {cpi}')
            if not math.isnan(rate) and rate < -100:
                raise ValueError(f'Inflation below -100% at row {row_number}: {rate}')
            status_value = '' if status is None else str(status).strip()
            status_counts[status_value or '(missing)'] += 1
            selected_all.append({
                'date': dt,
                VALUE_COLUMNS[0]: cpi,
                VALUE_COLUMNS[1]: rate,
                '_status': status_value,
            })
    finally:
        workbook.close()

    if not selected_all:
        raise ValueError('All India / Combined / General / General-Overall not found')
    original_selected_rows = len(selected_all)
    data = pd.DataFrame(selected_all)
    conflict = data.groupby('date')[VALUE_COLUMNS + ['_status']].nunique(dropna=False).gt(1).any(axis=1)
    if conflict.any():
        raise ValueError('Conflicting duplicate months: ' + ', '.join(conflict[conflict].index.strftime('%Y-%m').tolist()[:5]))
    duplicate_count = int(data['date'].duplicated().sum())
    data = data.sort_values('date').drop_duplicates('date', keep='first')
    source_min = data['date'].min().strftime('%Y-%m')
    source_max = data['date'].max().strftime('%Y-%m')
    out_of_range = int((~data['date'].between(START_DATE, END_DATE)).sum())
    clean = data.loc[data['date'].between(START_DATE, END_DATE), ['date', *VALUE_COLUMNS]].reset_index(drop=True)
    recorded_months = set(clean['date'].dt.strftime('%Y-%m'))
    missing_months = [m for m in month_labels(START_DATE, END_DATE) if m not in recorded_months]

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    report_rows = [
        {'metric': 'dataset', 'value': 'MoSPI India CPI 2012 Base, All India Combined General'},
        {'metric': 'source', 'value': str(SOURCE.relative_to(PROJECT_ROOT))},
        {'metric': 'processed', 'value': str(OUTPUT.relative_to(PROJECT_ROOT)) if not clean.empty else 'NOT GENERATED: no study-period observations'},
        {'metric': 'worksheet', 'value': SHEET_NAME},
        {'metric': 'selected_series', 'value': ' / '.join(TARGET)},
        {'metric': 'base_year', 'value': '2012'},
        {'metric': 'frequency', 'value': 'monthly'},
        {'metric': 'raw_rows', 'value': raw_rows},
        {'metric': 'source_year_counts', 'value': '; '.join(f'{k}: {v}' for k,v in sorted(source_year_counts.items()))},
        {'metric': 'source_selected_rows', 'value': original_selected_rows},
        {'metric': 'source_selected_date_min', 'value': source_min},
        {'metric': 'source_selected_date_max', 'value': source_max},
        {'metric': 'duplicates_removed', 'value': duplicate_count},
        {'metric': 'out_of_range_observations_excluded', 'value': out_of_range},
        {'metric': 'processed_rows', 'value': len(clean)},
        {'metric': 'processed_date_min', 'value': clean['date'].min().date().isoformat() if not clean.empty else ''},
        {'metric': 'processed_date_max', 'value': clean['date'].max().date().isoformat() if not clean.empty else ''},
        {'metric': 'missing_index_values', 'value': int(clean[VALUE_COLUMNS[0]].isna().sum())},
        {'metric': 'missing_inflation_values', 'value': int(clean[VALUE_COLUMNS[1]].isna().sum())},
        {'metric': 'missing_calendar_months', 'value': '; '.join(missing_months) if missing_months else 'none'},
        {'metric': 'source_status_counts', 'value': '; '.join(f'{k}: {v}' for k, v in sorted(status_counts.items()))},
        {'metric': 'unit_index', 'value': '2012=100'},
        {'metric': 'unit_inflation', 'value': 'percent year-on-year'},
        {'metric': 'date_semantics', 'value': 'First day of reference month, not publication date'},
        {'metric': 'publication_alignment', 'value': 'PENDING: verify historical release availability before ML merge'},
        {'metric': 'imputation', 'value': 'NONE'},
        {'metric': 'outlier_deletion', 'value': 'NONE'},
        {'metric': 'coverage_status', 'value': 'NO_STUDY_PERIOD_DATA' if clean.empty else ('PARTIAL' if missing_months else 'COMPLETE')},
    ]
    pd.DataFrame(report_rows, columns=['metric','value']).to_csv(REPORT, index=False, encoding='utf-8')
    if clean.empty:
        if OUTPUT.exists():
            OUTPUT.unlink()  
        raise ValueError(f'No observations within study period. Quality report: {REPORT}')

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(OUTPUT, index=False, date_format='%Y-%m-%d', float_format='%.10g', na_rep='')
    print(f'Saved: {OUTPUT.relative_to(PROJECT_ROOT)} ({len(clean)} monthly observations)')
    print(f'Source selected series: {source_min} through {source_max}')
    print(f'Missing values: index={int(clean[VALUE_COLUMNS[0]].isna().sum())}, inflation={int(clean[VALUE_COLUMNS[1]].isna().sum())}')
    print(f'Missing study-period months (not fabricated): {len(missing_months)}')
    print(f'Duplicate months removed: {duplicate_count}')
    print(f'Quality report: {REPORT.relative_to(PROJECT_ROOT)}')


if __name__ == '__main__':
    main()
