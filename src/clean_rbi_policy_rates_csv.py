from __future__ import annotations
import csv
import math
from collections import Counter
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / 'data/raw/interest_rates/RBI_India_Monetary_Policy_Rates.csv'
EVENT_OUTPUT = PROJECT_ROOT / 'reports/quality/RBI_India_Monetary_Policy_Rates_Effective_Dates_Audit.csv'
REPORT = PROJECT_ROOT / 'reports/quality/RBI_India_Monetary_Policy_Rates_Quality.csv'
RATE_OUTPUT = PROJECT_ROOT / 'data/interim/RBI_India_Monetary_Policy_Rates_Clean.csv'
START, END = date(2020, 1, 1), date(2026, 10, 29)
EXPECTED = ['src_file', 'tab', 'period', 'row_no', 'c1', 'c2', 'c3', 'c4', 'c5', 'c6', 'c7', 'c8']
MISSING = {'', '.', '-', 'NA', 'N/A', 'NULL', 'NAN'}
RATE_FIELDS = ('c2', 'c3', 'c4', 'c5', 'c6', 'c7', 'c8')


def parse_numeric(token: str, csv_line: int, column: str) -> float | None:
    raw = (token or '').strip()
    if raw.upper() in MISSING:
        return None
    if raw.startswith('(') and raw.endswith(')'):
        raw = '-' + raw[1:-1]
    try:
        value = float(raw.replace(',', ''))
    except ValueError as exc:
        raise ValueError(f'Line {csv_line}: invalid {column} rate: {token!r}') from exc
    if not math.isfinite(value):
        raise ValueError(f'Line {csv_line}: nonfinite {column} rate: {token!r}')
    return value


def write_metric_report(metrics: list[tuple[str, object]]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open('w', newline='', encoding='utf-8') as output:
        writer = csv.writer(output)
        writer.writerow(['metric', 'value'])
        for key, value in metrics:
            writer.writerow([key, value])


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f'Source CSV missing: {SOURCE}')

    raw_count = 0
    non_dated_rows = 0
    dated = []
    year_counts: Counter[int] = Counter()
    valid_rate_counts: Counter[str] = Counter()
    with SOURCE.open('r', encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != EXPECTED:
            raise ValueError(f'Unexpected source schema: {reader.fieldnames!r}')
        for csv_line, row in enumerate(reader, 2):
            raw_count += 1
            if None in row or any(row[field] is None for field in EXPECTED):
                raise ValueError(f'Malformed CSV row at line {csv_line}')
            value = row['c1'].strip()
            try:
                event_date = datetime.strptime(value, '%d-%m-%Y').date()
            except ValueError:
                non_dated_rows += 1
                continue 
            source_row = row['row_no'].strip()
            if not source_row.isdigit():
                raise ValueError(f'Invalid original row number at CSV line {csv_line}: {source_row!r}')
            policy_values = {col: parse_numeric(row[col], csv_line, col) for col in RATE_FIELDS}
            for col, rate in policy_values.items():
                if rate is not None:
                    valid_rate_counts[col] += 1
            dated.append((event_date, source_row, row, policy_values))
            year_counts[event_date.year] += 1

    if not dated:
        raise ValueError('No valid effective dates found')
    dated.sort(key=lambda item: (item[0], int(item[1])))
    date_counts = Counter(item[0] for item in dated)
    duplicate_dates = sum(n - 1 for n in date_counts.values() if n > 1)
    study = [item for item in dated if START <= item[0] <= END]
    repo_count = valid_rate_counts['c3']
    all_rate_count = sum(valid_rate_counts.values())

    EVENT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_OUTPUT.open('w', newline='', encoding='utf-8') as out:
        writer = csv.writer(out)
        writer.writerow(['effective_date', 'source_row_no', 'source_tab', 'source_period',
                         'rbi_repo_rate_pct', 'rate_information_status'])
        for effective, source_row, row, vals in study:
            repo = vals['c3']
            writer.writerow([effective.isoformat(), source_row, row['tab'], row['period'],
                             '' if repo is None else format(repo, '.10g'),
                             'NO_RATE_VALUES_IN_SOURCE_ROW' if all(v is None for v in vals.values())
                             else 'HAS_SOME_RATE_VALUES'])

    metrics = [
        ('dataset', 'RBI monetary policy rates - flattened table export'),
        ('source_file', SOURCE.name),
        ('source_schema', ','.join(EXPECTED)),
        ('source_tab', 'Report 1'),
        ('study_period_start', START.isoformat()),
        ('study_period_end', END.isoformat()),
        ('raw_csv_rows', raw_count),
        ('non_dated_metadata_or_note_rows', non_dated_rows),
        ('dated_effective_date_rows', len(dated)),
        ('study_period_dated_rows', len(study)),
        ('source_first_effective_date', dated[0][0].isoformat()),
        ('source_last_effective_date', dated[-1][0].isoformat()),
        ('duplicate_effective_dates', duplicate_dates),
        ('dated_rows_with_all_rate_cells_missing', sum(all(v is None for v in vals.values()) for _, _, _, vals in dated)),
        ('repo_rate_numeric_observations_c3', repo_count),
        ('numeric_observations_all_rate_columns', all_rate_count),
        ('numeric_observations_by_column', '; '.join(f'{c}={valid_rate_counts[c]}' for c in RATE_FIELDS)),
        ('dated_rows_by_year', '; '.join(f'{year}={n}' for year, n in sorted(year_counts.items()))),
        ('source_missing_token_semantics', 'Dash is source no-change marker; blank rate cells are not usable values'),
        ('source_event_audit_file', str(EVENT_OUTPUT.relative_to(PROJECT_ROOT))),
        ('daily_rate_csv_created', 'NO' if repo_count == 0 else 'NO - source must be reviewed separately'),
        ('imputation', 'NONE'),
        ('publication_alignment', 'UNVERIFIED - effective dates do not establish publication dates'),
        ('quality_status', 'BLOCKED_NO_REPO_RATES' if repo_count == 0 else 'REVIEW_REQUIRED'),
        ('recommended_action', 'Use separately verified original RBI workbook and its daily repo-rate series; do not treat this dates-only CSV as independent numeric data'),
    ]
    write_metric_report(metrics)
    print(f'Raw rows: {raw_count}; dated source rows: {len(dated)}; in-period dates: {len(study)}')
    print(f'Numeric repo readings: {repo_count}; numeric rates in any column: {all_rate_count}')
    print(f'Effective-date audit: {EVENT_OUTPUT}')
    print(f'Quality report: {REPORT}')
    if repo_count == 0:
        print('BLOCKED: no numeric repo-rate observations. No rate-series CSV generated.')
        if RATE_OUTPUT.exists():
            print(f'WARNING: existing output at {RATE_OUTPUT} was NOT modified or validated.')
        return
    print('REVIEW REQUIRED: source contains repo observations, but does not establish a daily prevailing-rate series.')


if __name__ == '__main__':
    main()
