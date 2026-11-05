from __future__ import annotations

import csv
import math
import re
from collections import Counter
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'data/raw/inflation/MOSPI_India_CPI_2024_Base_Historical_Through_2026.xlsx'
OUTPUT = ROOT / 'data/interim/MOSPI_India_CPI_2024_Base_Historical_Through_2026_Clean.csv'
REPORT = ROOT / 'reports/quality/MOSPI_India_CPI_2024_Base_Historical_Through_2026_Quality.csv'
START, END = date(2020, 1, 1), date(2026, 10, 1)

SHEET_XML = 'xl/worksheets/sheet1.xml'
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
FIELDS = [
    'base_year', 'series', 'year', 'month', 'state', 'sector', 'division',
    'group', 'class', 'sub_class', 'item', 'code', 'index', 'inflation', 'imputation',
]
COLUMNS = [
    'date', 'india_cpi_2024base_back_index',
    'india_cpi_2024base_back_annual_inflation_pct',
]
MONTHS = {name.lower(): i for i, name in enumerate(
    ['January', 'February', 'March', 'April', 'May', 'June',
     'July', 'August', 'September', 'October', 'November', 'December'], 1
)}
MISSING = {'', '-', '.', ':', 'NA', 'N/A', 'NULL', 'NAN'}
CELL_RE = re.compile(r'^([A-Z]+)\d+$')


def iter_excel_rows(path: Path):
    """Stream values from this workbook's first worksheet without loading it all."""
    with ZipFile(path) as book:
        if SHEET_XML not in book.namelist():
            raise ValueError(f'Worksheet XML missing: {SHEET_XML}')
        if 'xl/sharedStrings.xml' in book.namelist():
            raise ValueError('Unexpected shared-string workbook layout; update the reader')
        with book.open(SHEET_XML) as handle:
            for _, elem in ET.iterparse(handle, events=('end',)):
                if elem.tag != NS + 'row':
                    continue
                values = {}
                for cell in elem.findall(NS + 'c'):
                    match = CELL_RE.fullmatch(cell.get('r', ''))
                    if match is None:
                        continue
                    cell_value = cell.find(NS + 'v')
                    inline = cell.find(NS + 'is')
                    if inline is not None:
                        text = ''.join(inline.itertext())
                    elif cell_value is not None and cell_value.text is not None:
                        text = cell_value.text
                    else:
                        text = ''
                    values[match.group(1)] = text.strip()
                yield int(elem.get('r', '0')), values
                elem.clear()


def parse_number(value: str, location: str) -> float | None:
    text = str(value).strip()
    if text.upper() in MISSING:
        return None
    if text.startswith('(') and text.endswith(')'):
        text = '-' + text[1:-1]
    try:
        parsed = float(text.replace(',', ''))
    except ValueError as exc:
        raise ValueError(f'Invalid numeric value in {location}: {value!r}') from exc
    if not math.isfinite(parsed):
        raise ValueError(f'Non-finite numeric value in {location}: {value!r}')
    return parsed


def monthly_dates(start: date, end: date):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield date(year, month, 1)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f'Source workbook missing: {SOURCE}')

    all_year_counts = Counter()
    selected = {}
    duplicate_count = 0
    total_rows = 0
    selected_source_rows = 0
    header_checked = False
    status_counts = Counter()

    for row_number, raw in iter_excel_rows(SOURCE):
        if row_number == 1:
            observed = [raw.get(chr(65 + i), '') for i in range(len(FIELDS))]
            if observed != FIELDS:
                raise ValueError(f'Unexpected workbook headers: {observed!r}')
            header_checked = True
            continue
        if not raw or all(not str(v).strip() for v in raw.values()):
            continue
        total_rows += 1
        all_year_counts[raw.get('C', '')] += 1
        if (raw.get('E') != 'All India' or raw.get('F') != 'Combined'
                or raw.get('G') != 'CPI (General)'):
            continue
        # Reject rows representing detailed categories rather than CPI (General).
        if any(raw.get(col, '') not in ('', None) for col in 'HIJKL'):
            continue
        selected_source_rows += 1
        if raw.get('A') != '2024' or raw.get('B') != 'Back':
            raise ValueError(f'Wrong base year / series on Excel row {row_number}')
        try:
            year = int(raw.get('C', ''))
            month = MONTHS[raw.get('D', '').lower()]
            reference_month = date(year, month, 1)
        except (ValueError, KeyError) as exc:
            raise ValueError(f'Invalid year/month on Excel row {row_number}') from exc

        index = parse_number(raw.get('M', ''), f'M{row_number}')
        inflation = parse_number(raw.get('N', ''), f'N{row_number}')
        if index is not None and index <= 0:
            raise ValueError(f'Nonpositive CPI index at row {row_number}')
        if inflation is not None and inflation < -100:
            raise ValueError(f'Inflation below -100% at row {row_number}')
        status_counts[raw.get('O', '') or '(missing)'] += 1
        record = (index, inflation)
        if reference_month in selected:
            if selected[reference_month] != record:
                raise ValueError(f'Conflicting duplicate month: {reference_month}')
            duplicate_count += 1
        else:
            selected[reference_month] = record

    if not header_checked:
        raise ValueError('Expected header row was not found')
    if not selected:
        raise ValueError('No All India / Combined / CPI (General) Back observations found')

    dates = sorted(selected)
    study_dates = [d for d in dates if START <= d <= END]
    if not study_dates:
        raise ValueError('No observations in requested study period')
    first, last = study_dates[0], study_dates[-1]
    missing_inside = [d.isoformat() for d in monthly_dates(first, last) if d not in selected]
    missing_study = [d.isoformat() for d in monthly_dates(START, END) if d not in selected]
    missing_index = [d.isoformat() for d in study_dates if selected[d][0] is None]
    missing_inflation = [d.isoformat() for d in study_dates if selected[d][1] is None]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for d in study_dates:
            idx, infl = selected[d]
            writer.writerow([d.isoformat(), '' if idx is None else f'{idx:.10g}',
                             '' if infl is None else f'{infl:.10g}'])

    report = [
        ('dataset', 'India CPI 2024-base, historical Back series'),
        ('source_file', SOURCE.name),
        ('processed_file', OUTPUT.name),
        ('worksheet', 'CPI Data'),
        ('base_year', '2024'),
        ('series', 'Back'),
        ('selection', 'All India / Combined / CPI (General); no subcategory'),
        ('source_data_rows', total_rows),
        ('source_rows_by_year', '; '.join(f'{y}: {n}' for y, n in sorted(all_year_counts.items()))),
        ('source_selected_rows', selected_source_rows),
        ('source_selected_start', dates[0].isoformat()),
        ('source_selected_end', dates[-1].isoformat()),
        ('study_period_start', START.isoformat()),
        ('study_period_end', END.isoformat()),
        ('processed_rows', len(study_dates)),
        ('processed_start', first.isoformat()),
        ('processed_end', last.isoformat()),
        ('duplicate_months_removed', duplicate_count),
        ('out_of_range_selected_months_excluded', len(dates) - len(study_dates)),
        ('missing_months_inside_source_coverage', '; '.join(missing_inside) or 'none'),
        ('missing_study_period_months', '; '.join(missing_study) or 'none'),
        ('missing_index_values', len(missing_index)),
        ('missing_index_months', '; '.join(missing_index) or 'none'),
        ('missing_inflation_values', len(missing_inflation)),
        ('missing_inflation_months', '; '.join(missing_inflation) or 'none'),
        ('source_imputation_flags', '; '.join(f'{k}: {v}' for k, v in sorted(status_counts.items()))),
        ('unit_index', '2024=100'),
        ('unit_inflation', 'percent year-on-year'),
        ('date_semantics', 'First day of reference month, not publication date'),
        ('imputation', 'NONE applied by cleaning script'),
        ('publication_alignment', 'UNRESOLVED: historical back-series values are retrospective; do not assume contemporaneous availability for ML'),
        ('base_year_warning', 'Do not concatenate 2012-base and 2024-base index levels without validated linking method'),
        ('coverage_status', 'PARTIAL' if missing_study else 'COMPLETE'),
    ]
    with REPORT.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['metric', 'value'])
        writer.writerows(report)

    print(f'Saved {OUTPUT} ({len(study_dates)} monthly rows; {first} .. {last})')
    print(f'Missing index values: {len(missing_index)}; inflation values: {len(missing_inflation)}')
    print(f'Duplicate months removed: {duplicate_count}; missing months inside source coverage: {len(missing_inside)}')
    print(f'Missing months in full study period: {len(missing_study)} (not fabricated)')
    print(f'Quality report: {REPORT}')


if __name__ == '__main__':
    main()
