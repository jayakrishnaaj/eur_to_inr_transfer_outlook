from __future__ import annotations
import csv
import math
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/raw/interest_rates/FRED_EuroArea_ECB_Deposit_Facility_Rate_2020_2026.csv'
OUTPUT = ROOT / 'data/interim/FRED_EuroArea_ECB_Deposit_Facility_Rate_2020_2026_Clean.csv'
REPORT = ROOT / 'reports/quality/FRED_EuroArea_ECB_Deposit_Facility_Rate_2020_2026_Quality.csv'
START = date(2020, 1, 1)
END = date(2026, 10, 29)
COLUMN = 'ecb_deposit_rate_pct'
EXPECTED_HEADERS = ['observation_date', 'ECBDFR']
MISSING_TOKENS = {'', '.', '-', 'NA', 'N/A', 'NULL', 'NAN'}


def parse_rate(token: str | None, row_number: int) -> float | None:
    text = '' if token is None else str(token).strip()
    if text.upper() in MISSING_TOKENS:
        return None
    try:
        value = float(text.replace(',', ''))
    except ValueError as exc:
        raise ValueError(f'Row {row_number}: invalid ECBDFR value {token!r}') from exc
    if not math.isfinite(value):
        raise ValueError(f'Row {row_number}: non-finite ECBDFR value {token!r}')
    return value


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f'Raw source not found: {SOURCE}')

    selected: dict[date, float | None] = {}
    raw_rows = 0
    duplicates_removed = 0
    outside_study_period = 0

    with SOURCE.open('r', encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != EXPECTED_HEADERS:
            raise ValueError(f'Unexpected FRED columns: {reader.fieldnames!r}')
        for line, record in enumerate(reader, start=2):
            if None in record:  # malformed line with extra columns
                raise ValueError(f'Row {line}: more values than expected')
            if not any((cell or '').strip() for cell in record.values()):
                continue
            raw_rows += 1
            raw_date = record['observation_date']
            try:
                observed_date = date.fromisoformat((raw_date or '').strip())
            except (TypeError, ValueError) as exc:
                raise ValueError(f'Row {line}: invalid date {raw_date!r}') from exc
            rate = parse_rate(record['ECBDFR'], line)
            if not START <= observed_date <= END:
                outside_study_period += 1
                continue
            if observed_date in selected:
                if selected[observed_date] != rate:
                    raise ValueError(f'Conflicting duplicate rate for {observed_date}: '
                                     f'{selected[observed_date]} vs {rate}')
                duplicates_removed += 1
            else:
                selected[observed_date] = rate

    if not selected:
        raise ValueError(f'No ECBDFR observations from {START} through {END}')

    observations = sorted(selected.items())
    calendar_dates = {START + timedelta(days=offset)
                      for offset in range((END - START).days + 1)}
    missing_days = sorted(calendar_dates - set(selected))
    missing_values = [day for day, rate in observations if rate is None]
    rates = [rate for _, rate in observations if rate is not None]

    changes: list[tuple[date, float, float, float]] = []
    previous_valid_rate: float | None = None
    previous_valid_date: date | None = None
    for day, rate in observations:
        if rate is None:
            continue
        if previous_valid_rate is not None and rate != previous_valid_rate:
            changes.append((day, previous_valid_rate, rate, rate - previous_valid_rate))
        previous_valid_rate = rate
        previous_valid_date = day

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['date', COLUMN])
        for day, rate in observations:
            writer.writerow([day.isoformat(), '' if rate is None else f'{rate:.10g}'])

    metrics = [
        ('dataset', 'FRED Euro Area ECB Deposit Facility Rate (ECBDFR)'),
        ('source', SOURCE.relative_to(ROOT).as_posix()),
        ('processed', OUTPUT.relative_to(ROOT).as_posix()),
        ('series', 'ECBDFR'),
        ('frequency', 'daily (calendar-day observations in uploaded source)'),
        ('unit', 'percent'),
        ('study_start', START.isoformat()),
        ('study_end', END.isoformat()),
        ('raw_rows', raw_rows),
        ('rows_excluded_outside_study_period', outside_study_period),
        ('processed_rows', len(observations)),
        ('processed_start', observations[0][0].isoformat()),
        ('processed_end', observations[-1][0].isoformat()),
        ('exact_duplicates_removed', duplicates_removed),
        ('missing_calendar_day_count', len(missing_days)),
        ('missing_calendar_days', '; '.join(d.isoformat() for d in missing_days) or 'none'),
        ('missing_rate_value_count', len(missing_values)),
        ('missing_rate_dates', '; '.join(d.isoformat() for d in missing_values) or 'none'),
        ('min_rate_pct', min(rates) if rates else ''),
        ('max_rate_pct', max(rates) if rates else ''),
        ('observed_rate_change_count', len(changes)),
        ('observed_rate_changes', '; '.join(
            f'{day.isoformat()}: {old:g}% -> {new:g}% ({delta:+g} pp)'
            for day, old, new, delta in changes) or 'none'),
        ('date_semantics', 'Observation/effective date in source, not announcement or publication timestamp'),
        ('imputation', 'NONE'),
        ('outlier_removal', 'NONE'),
        ('coverage_status', 'COMPLETE' if not missing_days else 'PARTIAL'),
        ('availability_warning', 'Historical point-in-time availability and revisions are not established; verify before as-of ML merge'),
        ('change_warning', 'When a missing-rate day precedes a changed value, its exact effective change date cannot be inferred'),
        ('attribution_warning', 'Confirm FRED/ECB attribution and redistribution terms for publication'),
    ]
    with REPORT.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['metric', 'value'])
        writer.writerows(metrics)

    print(f'Saved: {OUTPUT.relative_to(ROOT)} ({len(observations)} daily records)')
    print(f'Missing days: {len(missing_days)}; missing values: {len(missing_values)}; '
          f'duplicates removed: {duplicates_removed}; observed changes: {len(changes)}')
    print(f'Quality report: {REPORT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
