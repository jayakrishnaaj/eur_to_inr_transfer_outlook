from __future__ import annotations
import csv
import json
import math
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from statistics import median

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT_ROOT / 'data/raw/interest_rates/FRED_US_10Y_Treasury_Yield_Daily_2020_2026.csv'
OUTPUT = PROJECT_ROOT / 'data/interim/FRED_US_10Y_Treasury_Yield_Daily_2020_2026_Clean.csv'
REPORT = PROJECT_ROOT / 'reports/quality/FRED_US_10Y_Treasury_Yield_Daily_2020_2026_Quality.csv'
DETAIL_REPORT = PROJECT_ROOT / 'reports/quality/FRED_US_10Y_Treasury_Yield_Daily_2020_2026_Quality.json'
START_DATE = date(2020, 1, 1)
END_DATE = date(2026, 10, 29)
VALUE_COLUMN = 'us_10y_treasury_yield_pct'
EXPECTED_COLUMNS = ['observation_date', 'DGS10']
MISSING_TOKENS = {'', '.', '-', 'NA', 'N/A', 'NULL', 'NAN'}


def parse_yield(token: str | None, line: int) -> float | None:
    if token is None:
        raise ValueError(f'CSV line {line}: DGS10 field is absent')
    raw = token.strip()
    if raw.upper() in MISSING_TOKENS:
        return None
    # No forced positivity: negative yields are possible and should be flagged, not discarded.
    try:
        value = float(raw.replace(',', ''))
    except ValueError as exc:
        raise ValueError(f'CSV line {line}: invalid DGS10 value {token!r}') from exc
    if not math.isfinite(value):
        raise ValueError(f'CSV line {line}: non-finite DGS10 value {token!r}')
    return value


def iso_list(items) -> str:
    return '; '.join(str(item) for item in items) if items else 'none'


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f'Source file not found: {SOURCE}')

    records: list[tuple[date, float | None]] = []
    with SOURCE.open('r', newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EXPECTED_COLUMNS:
            raise ValueError(f'Expected CSV columns {EXPECTED_COLUMNS}, got {reader.fieldnames!r}')
        for line, row in enumerate(reader, start=2):
            if None in row or row.get('observation_date') is None:
                raise ValueError(f'CSV line {line}: missing or extra fields')
            try:
                day = date.fromisoformat(row['observation_date'].strip())
            except ValueError as exc:
                raise ValueError(f'CSV line {line}: invalid date {row["observation_date"]!r}') from exc
            records.append((day, parse_yield(row.get('DGS10'), line)))

    if not records:
        raise ValueError('Source CSV contains no observations')

    unique: dict[date, float | None] = {}
    duplicates_removed = 0
    for day, yield_pct in records:
        if day in unique:
            if unique[day] != yield_pct:
                raise ValueError(f'Conflicting source values for {day}: {unique[day]} vs {yield_pct}')
            duplicates_removed += 1
        else:
            unique[day] = yield_pct

    filtered = sorted((day, value) for day, value in unique.items() if START_DATE <= day <= END_DATE)
    if not filtered:
        raise ValueError('No source observations in the study period')

    first, last = filtered[0][0], filtered[-1][0]
    missing_dates = [day.isoformat() for day, value in filtered if value is None]
    negative_dates = [day.isoformat() for day, value in filtered if value is not None and value < 0]
    available = [(day, value) for day, value in filtered if value is not None]
    intervals = Counter((nxt[0] - current[0]).days for current, nxt in zip(filtered, filtered[1:]))

    # Missing *rows* are distinguished from present rows with blank DGS10 values.
    # DGS10 is a business-day series: weekends are not expected observations.
    present_dates = {day for day, _ in filtered}
    missing_weekday_rows = []
    day = first
    while day <= last:
        if day.weekday() < 5 and day not in present_dates:
            missing_weekday_rows.append(day.isoformat())
        day += timedelta(days=1)

    # Compare successive available reported values. Changes may span a holiday or weekend;
    # the detected date is the date of the new observation, not necessarily an overnight move.
    jumps = []
    jump_threshold = None
    if len(available) > 20:
        abs_changes = [abs(available[i][1] - available[i - 1][1])
                       for i in range(1, len(available))]
        med = median(abs_changes)
        mad = median(abs(change - med) for change in abs_changes)
        if mad > 0:
            jump_threshold = med + 15 * mad
            for i, change in enumerate(abs_changes, start=1):
                if change > jump_threshold:
                    jumps.append({
                        'previous_observation_date': available[i - 1][0].isoformat(),
                        'observation_date': available[i][0].isoformat(),
                        'change_percentage_points': round(available[i][1] - available[i - 1][1], 6),
                    })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['date', VALUE_COLUMN])
        for day, yield_pct in filtered:
            writer.writerow([day.isoformat(), '' if yield_pct is None else f'{yield_pct:.12g}'])

    details = {
        'dataset': 'FRED DGS10 - US 10-year Treasury constant maturity yield',
        'source': 'Federal Reserve Board H.15 via FRED',
        'series_id': 'DGS10',
        'source_file': str(SOURCE),
        'processed_file': str(OUTPUT),
        'frequency': 'business-day observations, with missing values on certain holidays',
        'unit': 'percent per annum',
        'date_semantics': 'observation date, not verified release timestamp',
        'study_start': START_DATE.isoformat(),
        'study_end': END_DATE.isoformat(),
        'source_rows': len(records),
        'source_unique_dates': len(unique),
        'duplicates_removed': duplicates_removed,
        'out_of_period_unique_dates': len(unique) - len(filtered),
        'processed_rows': len(filtered),
        'processed_start': first.isoformat(),
        'processed_end': last.isoformat(),
        'source_ends_before_study_end': last < END_DATE,
        'missing_values': len(missing_dates),
        'missing_value_dates': missing_dates,
        'nonmissing_values': len(available),
        'missing_weekday_rows_within_coverage': missing_weekday_rows,
        'missing_weekday_row_count': len(missing_weekday_rows),
        'negative_value_dates': negative_dates,
        'min_yield_pct': min((v for _, v in available), default=None),
        'max_yield_pct': max((v for _, v in available), default=None),
        'date_interval_counts_days': {str(k): v for k, v in sorted(intervals.items())},
        'jump_warning_threshold_percentage_points': jump_threshold,
        'jump_warning_count': len(jumps),
        'jump_warnings': jumps,
        'imputation': 'NONE',
        'outlier_deletion': 'NONE',
        'publication_alignment': 'PENDING: verify H.15 release times and historical vintages before point-in-time ML merge',
        'license_review': 'Check source redistribution and attribution terms before public publication',
    }

    with REPORT.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['metric', 'value'])
        for key, value in details.items():
            if isinstance(value, (dict, list)):
                cell = json.dumps(value, ensure_ascii=False)
            elif value is None:
                cell = ''
            else:
                cell = value
            writer.writerow([key, cell])

    DETAIL_REPORT.write_text(json.dumps(details, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Saved: {OUTPUT} ({len(filtered)} observations; {first} through {last})')
    print(f'Missing yield values preserved: {len(missing_dates)}')
    print(f'Duplicate source records removed: {duplicates_removed}')
    print(f'Missing weekday date rows within source coverage: {len(missing_weekday_rows)}')
    print(f'Large successive-observation movements flagged: {len(jumps)}')
    if last < END_DATE:
        print(f'WARNING: last source observation {last} precedes requested end {END_DATE}; no rows fabricated')
    print(f'Quality reports: {REPORT} and {DETAIL_REPORT}')


if __name__ == '__main__':
    main()
