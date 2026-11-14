from __future__ import annotations
import argparse
import calendar
import csv
import math
import re
from collections import Counter
from datetime import date
from pathlib import Path

from zipfile import ZipFile
from xml.etree import ElementTree as ET
from posixpath import normpath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / 'data/raw/inflation/MOSPI_India_CPI_2024_Base_Current_2026.xlsx'
OUTPUT = PROJECT_ROOT / 'data/interim/MOSPI_India_CPI_2024_Base_Current_2026_Clean.csv'
REPORT = PROJECT_ROOT / 'reports/quality/MOSPI_India_CPI_2024_Base_Current_2026_Quality.csv'
SHEET_NAME = 'CPI Data'
START_DATE, END_DATE = date(2020, 1, 1), date(2026, 10, 1)
EXPECTED_HEADERS = [
    'base_year', 'series', 'year', 'month', 'state', 'sector',
    'division', 'group', 'class', 'sub_class', 'item', 'code',
    'index', 'inflation', 'imputation',
]
TARGET = ('All India', 'Combined', 'CPI (General)')
VALUE_COLUMNS = [
    'india_cpi_2024base_index',
    'india_cpi_2024base_annual_inflation_pct',
]
MISSING_TOKENS = {'', '-', '.', ':', 'NA', 'N/A', 'NULL', 'NAN'}
NUMBER_RE = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)\Z')


def text(value: object) -> str:
    return '' if value is None else str(value).strip()


def parse_number(value: object, row_number: int, field: str) -> float | None:
    if value is None or text(value).upper() in MISSING_TOKENS:
        return None
    if isinstance(value, bool):
        raise ValueError(f'Row {row_number}: Boolean {field} is not a number')
    token = text(value)
    if not NUMBER_RE.fullmatch(token):
        raise ValueError(f'Row {row_number}: Invalid {field}: {value!r}')
    number = float(token)
    if not math.isfinite(number):
        raise ValueError(f'Row {row_number}: Non-finite {field}: {value!r}')
    return number


def parse_month(value: object, row_number: int) -> int:
    label = text(value)
    if label.isdigit() and 1 <= int(label) <= 12:
        return int(label)
    matches = {name.lower(): i for i, name in enumerate(calendar.month_name) if i}
    matches.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if i})
    if label.lower() not in matches:
        raise ValueError(f'Row {row_number}: Invalid month: {value!r}')
    return matches[label.lower()]


def calendar_months(start: date, end: date) -> list[date]:
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def iter_worksheet_rows(source: Path, sheet_name: str):
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    rel_ns = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
    pkg_ns = '{http://schemas.openxmlformats.org/package/2006/relationships}'
    with ZipFile(source) as archive:
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        sheet_node = next((s for s in workbook.findall(f'{ns}sheets/{ns}sheet')
                           if s.get('name') == sheet_name), None)
        if sheet_node is None:
            raise ValueError(f'Missing worksheet {sheet_name!r}')
        rid = sheet_node.get(f'{rel_ns}id')
        rels = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        link = next((r for r in rels.findall(f'{pkg_ns}Relationship')
                     if r.get('Id') == rid), None)
        if link is None:
            raise ValueError(f'Missing worksheet relationship for {sheet_name!r}')
        target = link.get('Target').lstrip('/')
        sheet_path = normpath(target if target.startswith('xl/') else 'xl/' + target)
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            tree = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            shared = [''.join(t.text or '' for t in si.iter(f'{ns}t'))
                      for si in tree.findall(f'{ns}si')]
        with archive.open(sheet_path) as stream:
            for _event, element in ET.iterparse(stream, events=('end',)):
                if element.tag != f'{ns}row':
                    continue
                row_no = int(element.get('r'))
                cells = [None] * len(EXPECTED_HEADERS)
                for c in element.findall(f'{ns}c'):
                    address = c.get('r', '')
                    match = re.match(r'([A-Z]+)', address)
                    if match is None:
                        continue
                    col = 0
                    for letter in match.group(1):
                        col = col * 26 + (ord(letter) - 64)
                    col -= 1
                    if col >= len(cells):
                        continue
                    v = c.find(f'{ns}v')
                    if c.get('t') == 'inlineStr':
                        inline = c.find(f'{ns}is')
                        val = '' if inline is None else ''.join(t.text or '' for t in inline.iter(f'{ns}t'))
                    else:
                        val = None if v is None else v.text
                        if c.get('t') == 's' and val is not None:
                            val = shared[int(val)]
                    cells[col] = val
                yield row_no, cells
                element.clear()


def main(source: Path = SOURCE, output: Path = OUTPUT, report: Path = REPORT) -> None:
    if not source.is_file():
        raise FileNotFoundError(f'Workbook not found: {source}')

    rows = iter(iter_worksheet_rows(source, SHEET_NAME))
    first = next(rows, None)
    if first is None or [text(v) for v in first[1]] != EXPECTED_HEADERS:
        raise ValueError(f'Unexpected column layout: {first[1] if first else "empty sheet"!r}')

    raw_rows = 0
    year_counts: Counter[str] = Counter()
    selected_all: list[tuple[date, float | None, float | None, str]] = []
    imputation_counts: Counter[str] = Counter()

    for excel_row, values in rows:
        if not any(v is not None and text(v) for v in values):
            continue
        raw_rows += 1
        rec = dict(zip(EXPECTED_HEADERS, values))
        if text(rec['base_year']) != '2024' or text(rec['series']) != 'Current':
            raise ValueError(f'Row {excel_row}: Expected 2024 / Current series')
        year_counts[text(rec['year'])] += 1
        if tuple(text(rec[field]) for field in ('state', 'sector', 'division')) != TARGET:
            continue
        if any(text(rec[field]) for field in ('group', 'class', 'sub_class', 'item', 'code')):
            raise ValueError(f'Row {excel_row}: General CPI row has detailed category fields')
        try:
            year = int(text(rec['year']))
            dt = date(year, parse_month(rec['month'], excel_row), 1)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'Row {excel_row}: Invalid year/month: {rec["year"]!r}, {rec["month"]!r}') from exc
        idx = parse_number(rec['index'], excel_row, 'index')
        infl = parse_number(rec['inflation'], excel_row, 'annual inflation')
        if idx is not None and idx <= 0:
            raise ValueError(f'Row {excel_row}: CPI index must be positive')
        if infl is not None and infl < -100:
            raise ValueError(f'Row {excel_row}: Inflation cannot be below -100%')
        imputation = text(rec['imputation'])
        imputation_counts[imputation or '(blank)'] += 1
        selected_all.append((dt, idx, infl, imputation))

    if not selected_all:
        raise ValueError('No All India / Combined / CPI (General) observations found')

    by_date: dict[date, tuple[float | None, float | None, str]] = {}
    duplicates = 0
    for dt, idx, infl, imputation in selected_all:
        value = (idx, infl, imputation)
        if dt in by_date:
            if by_date[dt] != value:
                raise ValueError(f'Conflicting duplicate monthly CPI record: {dt}')
            duplicates += 1
        else:
            by_date[dt] = value

    chosen = {dt: v for dt, v in by_date.items() if START_DATE <= dt <= END_DATE}
    dates = sorted(chosen)
    if not dates:
        raise ValueError('No observations in the requested study period')
    missing_source_span = sorted(set(calendar_months(dates[0], dates[-1])) - set(dates))
    missing_study = sorted(set(calendar_months(START_DATE, END_DATE)) - set(dates))
    out_of_range = sum(not (START_DATE <= dt <= END_DATE) for dt in by_date)

    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['date', *VALUE_COLUMNS])
        for dt in dates:
            idx, infl, _ = chosen[dt]
            writer.writerow([dt.isoformat(), '' if idx is None else f'{idx:.10g}',
                             '' if infl is None else f'{infl:.10g}'])

    report_rows = [
        ('dataset', 'MoSPI India CPI, 2024 base, Current, All India Combined General'),
        ('source', str(source)),
        ('processed', str(output)),
        ('worksheet', SHEET_NAME),
        ('source_series', 'Current'),
        ('base_year', '2024'),
        ('selected_scope', ' / '.join(TARGET)),
        ('frequency', 'monthly'),
        ('raw_rows', raw_rows),
        ('source_year_counts', '; '.join(f'{y}: {n}' for y, n in sorted(year_counts.items()))),
        ('selected_rows_before_deduplication', len(selected_all)),
        ('selected_source_date_min', min(by_date).isoformat()),
        ('selected_source_date_max', max(by_date).isoformat()),
        ('exact_duplicate_months_removed', duplicates),
        ('out_of_range_months_excluded', out_of_range),
        ('processed_rows', len(dates)),
        ('processed_date_min', dates[0].isoformat()),
        ('processed_date_max', dates[-1].isoformat()),
        ('missing_index_values', sum(chosen[d][0] is None for d in dates)),
        ('missing_inflation_values', sum(chosen[d][1] is None for d in dates)),
        ('missing_months_within_source_coverage', '; '.join(d.isoformat() for d in missing_source_span) or 'none'),
        ('missing_study_period_months', '; '.join(d.isoformat() for d in missing_study) or 'none'),
        ('source_imputation_flag_counts', '; '.join(f'{k}: {v}' for k, v in sorted(imputation_counts.items()))),
        ('unit_index', '2024=100'),
        ('unit_inflation', 'percent, year-on-year'),
        ('date_semantics', 'First day of reference month, not release date'),
        ('imputation_performed_by_cleaner', 'NONE'),
        ('outlier_deletion', 'NONE'),
        ('coverage_status', 'COMPLETE' if not missing_study else 'PARTIAL'),
        ('publication_alignment', 'UNVERIFIED: check release dates before leakage-safe modeling'),
        ('base_transition', 'Do not concatenate 2012-base and 2024-base CPI levels without validated linking'),
    ]
    with report.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['metric', 'value'])
        writer.writerows(report_rows)

    print(f'Saved: {output} ({len(dates)} months, {dates[0]} to {dates[-1]})')
    print(f'Missing values: index={sum(chosen[d][0] is None for d in dates)}, '
          f'inflation={sum(chosen[d][1] is None for d in dates)}')
    print(f'Duplicates removed: {duplicates}; missing internal months: {len(missing_source_span)}')
    print(f'Quality report: {report}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Clean 2024-base current CPI general monthly observations')
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--report', type=Path, default=REPORT)
    args = parser.parse_args()
    main(args.source, args.output, args.report)
