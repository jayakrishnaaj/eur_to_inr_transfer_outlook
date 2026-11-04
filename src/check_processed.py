"""
Quick quality check of every cleaned table before merging.

Usage:
    python check_processed.py                 # checks data/processed/*.csv
    python check_processed.py path/to/folder  # or another folder / single file

For each CSV it reports: date range, duplicate or unreadable dates, gaps,
missing values per column, columns that aren't numeric, and suspicious jumps.
Ends with READY or CHECK for each file.
"""

import sys
from pathlib import Path

import pandas as pd

DATE_NAMES = ("date", "week_start", "reporting_date", "week_end")
TEXT_OK = ("_period", "source", "_obs_date", "week_end")   # text/date columns that are fine


def check(path: Path) -> bool:
    df = pd.read_csv(path)
    print(f"\n=== {path.name}  ({len(df)} rows, {df.shape[1]} columns)")
    problems = []

    # 1) date column
    dcol = next((c for c in df.columns if c.lower() in DATE_NAMES), df.columns[0])
    dates = pd.to_datetime(df[dcol], errors="coerce")
    bad = dates.isna().sum()
    if bad:
        problems.append(f"{bad} unreadable dates in '{dcol}'")
    dups = dates[dates.duplicated()].dropna()
    if len(dups):
        problems.append(f"{len(dups)} duplicate dates, e.g. {dups.iloc[0]:%Y-%m-%d}")
    d = dates.dropna().sort_values()
    if d.empty:
        print("  no valid dates - skipped")
        return False
    step = int(d.diff().dt.days.mode().iloc[0]) if len(d) > 1 else 0
    freq = {1: "daily", 7: "weekly"}.get(step, f"every {step} days")
    print(f"  dates: '{dcol}' {d.min():%Y-%m-%d} .. {d.max():%Y-%m-%d} ({freq})")
    # allowed spacing: daily trading data skips weekends + holidays (up to 4 days)
    allowed = {1: 4, 7: 7}.get(step, step * 1.5)
    gaps = d[d.diff().dt.days > allowed]
    if len(gaps):
        problems.append(f"{len(gaps)} gaps in the dates, e.g. before {gaps.iloc[0]:%Y-%m-%d}")

    # 2) columns: type, missing values, jumps
    rows = []
    for c in df.columns:
        if c == dcol:
            continue
        s = df[c]
        miss = s.isna().mean() * 100
        if any(t in c for t in TEXT_OK):
            continue
        num = pd.to_numeric(s, errors="coerce")
        not_num = (num.isna() & s.notna()).sum()
        jumps = 0
        x = num.dropna()
        if len(x) > 20:
            diff = x.diff().abs().dropna()
            mad = (diff - diff.median()).abs().median()
            if mad > 0:
                jumps = int((diff > diff.median() + 15 * mad).sum())
        flag = []
        if not_num:
            flag.append(f"{not_num} non-numeric values (e.g. {s[num.isna() & s.notna()].iloc[0]!r})")
        if miss > 20:
            flag.append(f"{miss:.0f}% missing")
        if jumps:
            flag.append(f"{jumps} big jumps - plot it")
        rows.append((c, f"{miss:5.1f}%", "; ".join(flag) or "ok"))
        if not_num or miss > 50:
            problems.append(f"column '{c}': {'; '.join(flag)}")

    w = max((len(r[0]) for r in rows), default=10)
    print(f"  {'column':{w}}  missing  status")
    for c, m, f in rows:
        print(f"  {c:{w}}  {m}  {f}")

    if problems:
        print("  CHECK:\n   - " + "\n   - ".join(problems))
        return False
    print("  READY")
    return True


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/processed")
    files = [target] if target.is_file() else sorted(target.glob("*.csv"))
    if not files:
        sys.exit(f"No CSV files found in {target}")
    results = {f.name: check(f) for f in files}
    print("\n=== summary")
    for name, ok in results.items():
        print(f"  {'READY' if ok else 'CHECK'}  {name}")
