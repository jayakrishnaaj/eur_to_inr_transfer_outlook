from __future__ import annotations
import csv
import math
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT_ROOT / 'data/raw/interest_rates/RBI_India_Monetary_Policy_Rates_And_Reserve_Requirements.xlsx'
OUTPUT = PROJECT_ROOT / 'data/interim/RBI_India_Monetary_Policy_Rates_And_Reserve_Requirements_Clean.csv'
EVENT_OUTPUT = PROJECT_ROOT / 'reports/quality/RBI_India_Monetary_Policy_Rates_And_Reserve_Requirements_source_events.csv'
REPORT = PROJECT_ROOT / 'reports/quality/RBI_India_Monetary_Policy_Rates_And_Reserve_Requirements_Quality.csv'
START, END = date(2020, 1, 1), date(2026, 10, 29)
SHEET_XML = 'xl/worksheets/sheet1.xml'  # Verified: workbook's 'Report 1' worksheet
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
MISSING = {'', '-', '.', 'NA', 'N/A', 'NULL'}


def excel_date(token: str, row: int) -> date:
    """Source column B contains Excel 1900-system day serials."""
    try:
        serial = float(token)
        if not math.isfinite(serial) or not serial.is_integer() or serial < 61:
            raise ValueError
        return (datetime(1899, 12, 30) + timedelta(days=int(serial))).date()
    except (ValueError, OverflowError) as exc:
        raise ValueError(f'Row {row}: invalid Excel effective-date serial {token!r}') from exc


def repo_rate(token: str, row: int) -> float | None:
    text = str(token).strip()
    if text.upper() in MISSING:
        return None  # RBI note: '-' indicates no change; NOT a missing daily state.
    try:
        rate = float(text)
    except ValueError as exc:
        raise ValueError(f'Row {row}: invalid repo rate {token!r}') from exc
    if not math.isfinite(rate) or not -10 <= rate <= 30:
        raise ValueError(f'Row {row}: implausible repo rate {token!r}')
    return rate


def source_rows(path: Path):
    """Read workbook without loading the whole XLSX or requiring artifact_tool."""
    with ZipFile(path) as archive:
        names = set(archive.namelist())
        if SHEET_XML not in names:
            raise ValueError(f'Missing expected worksheet XML: {SHEET_XML}')
        shared = []
        if 'xl/sharedStrings.xml' in names:
            with archive.open('xl/sharedStrings.xml') as stream:
                root = ET.parse(stream).getroot()
                shared = [''.join(node.text or '' for node in si.iter(NS + 't'))
                          for si in root.findall(NS + 'si')]
        with archive.open(SHEET_XML) as stream:
            for _, element in ET.iterparse(stream, events=('end',)):
                if element.tag != NS + 'row':
                    continue
                row_number = int(element.attrib['r'])
                cells = {}
                for cell in element.findall(NS + 'c'):
                    match = re.match(r'([A-Z]+)', cell.attrib.get('r', ''))
                    if not match:
                        continue
                    value_node = cell.find(NS + 'v')
                    inline_node = cell.find(NS + 'is')
                    raw = (''.join(inline_node.itertext()) if inline_node is not None
                           else value_node.text if value_node is not None else '') or ''
                    if cell.attrib.get('t') == 's' and raw:
                        raw = shared[int(raw)]
                    cells[match.group(1)] = raw.strip()
                yield row_number, cells
                element.clear()


def write_quality(metrics: list[tuple[str, object]]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['metric', 'value'])
        for key, value in metrics:
            writer.writerow([key, value])


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f'Source workbook not found: {SOURCE}')

    dated_rows = 0
    source_years: Counter[int] = Counter()
    explicit = []
    headers = {}
    footnote_confirmed = False

    for row_number, cells in source_rows(SOURCE):
        if row_number in (6, 7):
            headers[row_number] = cells
            continue
        if row_number == 270:
            footnote_confirmed = 'Indicates no change' in cells.get('B', '')
        if not 9 <= row_number <= 268:
            continue
        raw_date = cells.get('B', '')
        if not raw_date:
            continue
        effective = excel_date(raw_date, row_number)
        dated_rows += 1
        source_years[effective.year] += 1
        rate = repo_rate(cells.get('D', ''), row_number)
        if rate is not None:
            explicit.append({'date': effective, 'rate': rate, 'excel_row': row_number})

    if ('Effective Date' not in headers.get(6, {}).get('B', '')
            or headers.get(7, {}).get('D', '').strip() != 'Repo'):
        raise ValueError('Unexpected worksheet headers: expected Effective Date in B6, Repo in D7')
    if not footnote_confirmed:
        raise ValueError('Missing RBI footnote confirming that dash means no change')
    if not explicit:
        raise ValueError('No explicit repo-rate entries found')

    explicit.sort(key=lambda e: (e['date'], e['excel_row']))
    duplicates = [d for d, count in Counter(e['date'] for e in explicit).items() if count > 1]
    if duplicates:
        raise ValueError(f'Duplicate explicit repo effective dates: {duplicates}')

    prior = [event for event in explicit if event['date'] <= START]
    if not prior:
        raise ValueError('No explicit repo-rate entry on/before study start')
    initial = prior[-1]
    study_events = [event for event in explicit if START < event['date'] <= END]
    ledger = []
    prev_rate = initial['rate']
    for event in study_events:
        change = event['rate'] != prev_rate
        ledger.append({**event, 'previous_rate': prev_rate, 'changed': change})
        prev_rate = event['rate']

    # Full source event audit, including the historical event used to establish initial state.
    EVENT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_OUTPUT.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['effective_date', 'rbi_repo_rate_pct', 'original_excel_row',
                         'in_study_period', 'rate_changed_from_prior_entry'])
        previous = None
        for event in explicit:
            changed = '' if previous is None else str(event['rate'] != previous).lower()
            writer.writerow([event['date'].isoformat(), f"{event['rate']:.10g}",
                             event['excel_row'],
                             str(START <= event['date'] <= END).lower(), changed])
            previous = event['rate']

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    event_index = 0
    current = initial['rate']
    day = START
    count = 0
    with OUTPUT.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['date', 'rbi_repo_rate_pct'])
        while day <= END:
            while event_index < len(study_events) and study_events[event_index]['date'] <= day:
                current = study_events[event_index]['rate']
                event_index += 1
            writer.writerow([day.isoformat(), f'{current:.10g}'])
            count += 1
            day += timedelta(days=1)

    changes = [event for event in ledger if event['changed']]
    metrics = [
        ('dataset', 'RBI repo rate — daily prevailing effective policy rate'),
        ('source', SOURCE.relative_to(PROJECT_ROOT).as_posix()),
        ('processed', OUTPUT.relative_to(PROJECT_ROOT).as_posix()),
        ('source_events', EVENT_OUTPUT.relative_to(PROJECT_ROOT).as_posix()),
        ('worksheet', 'Report 1'),
        ('source_date_column', 'B'),
        ('source_repo_column', 'D'),
        ('source_dated_rows', dated_rows),
        ('source_rows_by_year', '; '.join(f'{y}: {n}' for y, n in sorted(source_years.items()))),
        ('source_explicit_repo_entries', len(explicit)),
        ('study_period_start', START.isoformat()),
        ('study_period_end', END.isoformat()),
        ('daily_processed_rows', count),
        ('missing_daily_rates', 0),
        ('initial_event_date', initial['date'].isoformat()),
        ('initial_repo_rate_pct', initial['rate']),
        ('explicit_repo_entries_in_study', len(study_events)),
        ('actual_repo_rate_changes_in_study', len(changes)),
        ('unchanged_explicit_repo_entries_in_study', len(study_events) - len(changes)),
        ('duplicate_explicit_repo_dates', 0),
        ('rate_changes', '; '.join(
            f"{e['date'].isoformat()}: {e['previous_rate']:.10g} -> {e['rate']:.10g}"
            for e in changes)),
        ('last_repo_rate_pct', current),
        ('source_dash_meaning', 'No change (RBI source footnote)'),
        ('unit', 'percent'),
        ('frequency', 'daily calendar dates; previous effective rate remains in force'),
        ('date_semantics', 'Policy effective date, not policy announcement date'),
        ('imputation', 'NONE; daily expansion of a known effective-date policy state'),
        ('publication_alignment', 'UNVERIFIED: effective dates do not establish announcement timestamps or historical as-of availability'),
        ('coverage_caution', 'Study window ending 2026-10-29 exceeds last source event; rate carried forward as prevailing state, not a new source observation'),
    ]
    write_quality(metrics)
    print(f'Saved: {OUTPUT} ({count} daily records, {START} through {END})')
    print(f'Initial event: {initial["date"]}, repo rate {initial["rate"]:.10g}%')
    print(f'Source rows: {dated_rows}; explicit entries: {len(explicit)}')
    print(f'In-window entries: {len(study_events)}; actual changes: {len(changes)}')
    print(f'Last prevailing rate: {current:.10g}%')
    print(f'Event ledger: {EVENT_OUTPUT}')
    print(f'Quality report: {REPORT}')


if __name__ == '__main__':
    main()
