from __future__ import annotations
import csv
import json
import math
import re
from collections import Counter
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'data/raw/inflation/MOSPI_India_CPI_2024_Base_Historical_Through_2026.xlsx'
OUTPUT = ROOT / 'data/interim/MOSPI_India_CPI_2024_Base_Historical_Through_2026.csv'
REPORT = ROOT / 'reports/quality/MOSPI_India_CPI_2024_Base_Historical_Through_2026.csv'
SHEET_XML = 'xl/worksheets/sheet1.xml'
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
FIELDS = ['base_year', 'series', 'year', 'month', 'state', 'sector',
          'division', 'group', 'class', 'sub_class', 'item', 'code',
          'index', 'inflation', 'imputation']
MONTHS = {name.lower(): i for i, name in enumerate([
    'January', 'February', 'March', 'April', 'May', 'June', 'July',
    'August', 'September', 'October', 'November', 'December'], 1)}
MISSING = {'', '-', '.', 'NA', 'N/A', 'NULL'}


def iter_excel_rows(path: Path):
    """Stream the A:O data rows from this OOXML workbook without loading all cells."""
    with ZipFile(path) as book:
        if SHEET_XML not in book.namelist():
            raise ValueError(f'Expected worksheet XML missing: {SHEET_XML}')
        # Important: this particular export uses inline cell values, no shared strings.
        if 'xl/sharedStrings.xml' in book.namelist():
            raise ValueError('Unexpected shared-string table; review export parser')
        with book.open(SHEET_XML) as handle:
            for _, elem in ET.iterparse(handle, events=('end',)):
                if elem.tag != NS + 'row':
                    continue
                row = {}
                for cell in elem.findall(NS + 'c'):
                    ref = cell.attrib.get('r', '')
                    col = re.match(r'[A-Z]+', ref)
                    if col is None:
                        continue
                    value = cell.find(NS + 'v')
                    inline = cell.find(NS + 'is')
                    if inline is not None:
                        text = ''.join(inline.itertext())
                    elif value is not None and value.text is not None:
                        text = value.text
                    else:
                        text = ''
                    row[col.group(0)] = text.strip()
                yield int(elem.attrib.get('r', 0)), row
                elem.clear()


def number(token: str | None, context: str):
    value = '' if token is None else str(token).strip()
    if value.upper() in MISSING:
        return None
    if value.startswith('(') and value.endswith(')'):
        value = '-' + value[1:-1]
    try:
        parsed = float(value.replace(',', ''))
    except ValueError as exc:
        raise ValueError(f'Unexpected numeric value at {context}: {token!r}') from exc
    if not math.isfinite(parsed):
        raise ValueError(f'Nonfinite number at {context}: {token!r}')
    return parsed


def main():
    if not SOURCE.is_file():
        raise FileNotFoundError(f'Raw workbook missing: {SOURCE}')

    counts_by_year = Counter()
    selected = {}
    rows_scanned = 0
    exact_duplicate_months = 0
    for row_num, raw in iter_excel_rows(SOURCE):
        if row_num == 1:
            observed = [raw.get(chr(65 + i), '') for i in range(len(FIELDS))]
            if observed != FIELDS:
                raise ValueError(f'Unexpected source headers: {observed!r}')
            continue
        rows_scanned += 1
        counts_by_year[raw.get('C', '')] += 1
        if not (raw.get('E') == 'All India' and
                raw.get('F') == 'Combined' and
                raw.get('G') == 'CPI (General)' and
                all(not raw.get(col, '') for col in 'HIJK')):
            continue
        if raw.get('A') != '2024' or raw.get('B') != 'Back':
            raise ValueError(f'Wrong CPI base year/series at Excel row {row_num}: '
                             f'{raw.get("A")!r}/{raw.get("B")!r}')
        try:
            year = int(raw['C'])
            month = MONTHS[raw['D'].lower()]
            reference_date = date(year, month, 1)
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f'Invalid reference month at Excel row {row_num}: {raw!r}') from exc
        idx = number(raw.get('M'), f'M{row_num}')
        infl = number(raw.get('N'), f'N{row_num}')
        if idx is None or idx <= 0:
            raise ValueError(f'CPI index must be positive at Excel row {row_num}')
        values = (idx, infl)
        if reference_date in selected:
            if selected[reference_date] != values:
                raise ValueError(f'Conflicting duplicate month: {reference_date}')
            exact_duplicate_months += 1
        selected[reference_date] = values

    start = date(2020, 1, 1)
    end = date(2026, 10, 1)
    observations = [(d, *values) for d, values in sorted(selected.items())
                    if start <= d <= end]
    if not observations:
        raise ValueError('No observations during the requested 2020–2026 period')

    first, last = observations[0][0], observations[-1][0]
    missing_months = []
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        d = date(y, m, 1)
        if d not in selected:
            missing_months.append(d.isoformat())
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    if missing_months:
        raise ValueError(f'Missing reference months within source coverage: {missing_months}')

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'india_cpi_2024base_back_index',
                         'india_cpi_2024base_back_annual_inflation_pct'])
        for d, idx, infl in observations:
            writer.writerow([d.isoformat(), f'{idx:.2f}',
                             '' if infl is None else f'{infl:.2f}'])

    missing_infl = [d.isoformat() for d, _, v in observations if v is None]
    report = {
        'dataset': 'India CPI 2024-base Back (retrospective historical series)',
        'source_file': SOURCE.name,
        'source_sheet': 'CPI Data',
        'source_rows_scanned': rows_scanned,
        'source_rows_by_year': dict(sorted(counts_by_year.items())),
        'selection': 'All India / Combined / CPI (General), no subcategory',
        'source_series': 'Back',
        'reference_month_first': first.isoformat(),
        'reference_month_last': last.isoformat(),
        'processed_rows': len(observations),
        'duplicate_identical_months_removed': exact_duplicate_months,
        'missing_months_inside_coverage': missing_months,
        'missing_cpi_index': 0,
        'missing_annual_inflation_count': len(missing_infl),
        'missing_annual_inflation_months': missing_infl,
        'units': {'india_cpi_2024base_back_index': '2024=100',
                  'india_cpi_2024base_back_annual_inflation_pct': 'percent year-on-year'},
        'imputation': 'none',
        'date_meaning': 'first day of reference month, not publication date',
        'availability_warning': 'Back series is retrospective and must not be used as if known at historical observation dates.',
        'coverage_warning': 'This Back workbook ends December 2024; 2025–2026 require a separate source.',
        'base_year_warning': 'Do not directly concatenate 2012-base and 2024-base CPI index levels.'
    }
    # Save quality report as CSV
    with REPORT.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['metric', 'value'])

        for key, value in report.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            writer.writerow([key, value])

    print(f'Saved: {OUTPUT} ({len(observations)} monthly rows)')
    print(f'Period: {first} to {last}; missing inflation: {len(missing_infl)}')
    print(f'Quality report: {REPORT}')


if __name__ == '__main__':
    main()

