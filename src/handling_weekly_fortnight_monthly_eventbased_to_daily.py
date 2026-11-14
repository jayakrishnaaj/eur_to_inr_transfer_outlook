import argparse
import csv
import io
import json
import re
import shutil
import sqlite3
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel

MISSING = {'', '-', '—', '–', '…', '..', 'NA', 'N/A', 'null', 'None'}
POLICY_COLS = ['bank_rate', 'repo_rate', 'reverse_repo_rate', 'sdf_rate', 'msf_rate', 'crr_rate', 'slr_rate']


def clean(x):
    if x is None: return None
    if isinstance(x, datetime): return x.date().isoformat()
    if isinstance(x, date): return x.isoformat()
    s = str(x).strip()
    return None if s in MISSING else s


def when(x, dayfirst=False):
    if x is None: return None
    if isinstance(x, datetime): return x.date()
    if isinstance(x, date): return x
    if isinstance(x, (int, float)):
        if 20000 < x < 80000: return from_excel(x).date()
        return None
    s = clean(x)
    if s is None: return None
    for fmt in (['%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y'] if dayfirst else ['%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y']):
        try: return datetime.strptime(s[:10], fmt).date()
        except ValueError: pass
    return None


def month_date(year, month, lag=0):
    y, m = int(year), int(month)
    n = y * 12 + m - 1 + lag
    return date(n // 12, n % 12 + 1, 1)


def month_from_name(x):
    if isinstance(x, (int, float)) or (isinstance(x, str) and x.isdigit()): return int(x)
    return datetime.strptime(str(x).strip()[:3], '%b').month


def excel_rows(source, entry, sheet_name=None):
    with tempfile.TemporaryFile(suffix='.xlsx') as content:
        with source.open(entry) as f:
            shutil.copyfileobj(f,content)
        content.seek(0)
        wb = load_workbook(content, read_only=True, data_only=True)
        try:
            ws = wb[sheet_name] if sheet_name else wb.active
            ws.reset_dimensions()
            for row in ws.iter_rows(values_only=True):
                yield row
        finally: wb.close()


class DailyWriter:
    def __init__(self, path, start, end):
        self.path, self.start, self.end = path, start, end
        self.tmp = tempfile.TemporaryDirectory(prefix='daily_spool_')
        self.db = sqlite3.connect(str(Path(self.tmp.name) / 'observed.db'))
        self.db.execute('CREATE TABLE obs (series TEXT, day TEXT, payload TEXT, PRIMARY KEY(series,day))')
        self.pending = []
        self.count = 0

    def add(self, series, day, values):
        if day is None or day > self.end: return
        vals = {str(k):clean(v) for k, v in values.items() if clean(v) is not None}
        if not vals: return
        self.pending.append((json.dumps(series, ensure_ascii=False),day.isoformat(),json.dumps(vals,ensure_ascii=False)))
        if len(self.pending) >= 2000: self.flush()

    def flush(self):
        if self.pending:
            self.db.executemany('INSERT OR REPLACE INTO obs VALUES(?,?,?)',self.pending)
            self.db.commit()
            self.pending.clear()

    def finish(self, dims, value_cols, *, allow_partial=True):
        self.flush()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        cur = self.db.execute('SELECT series,day,payload FROM obs ORDER BY series,day')
        with self.path.open('w', encoding='utf-8-sig', newline='') as out:
            writer = csv.writer(out)
            writer.writerow(['date','observation_date',*dims,*value_cols])
            current_series, entries = None, []
            def dump(key, records):
                if not records: return
                series_vals = json.loads(key)
                carry = {}
                for i,(ds,payload) in enumerate(records):
                    d = date.fromisoformat(ds)
                    carry.update(json.loads(payload))
                    next_d = date.fromisoformat(records[i+1][0]) if i+1 < len(records) else self.end+timedelta(days=1)
                    begin = max(d,self.start)
                    stop = min(next_d,self.end+timedelta(days=1))
                    while begin < stop:
                        writer.writerow([begin.isoformat(),ds,*series_vals,*[carry.get(col,'') for col in value_cols]])
                        self.count += 1
                        begin += timedelta(days=1)
            for series,ds,payload in cur:
                if current_series is not None and series != current_series:
                    dump(current_series,entries)
                    entries = []
                current_series = series
                entries.append((ds,payload))
            if current_series is not None: dump(current_series,entries)
        self.db.close()
        self.tmp.cleanup()
        print(f'  -> {self.path} ({self.count:,} daily rows)')


def handle_reserve_money(zf, entry, out, start, end, **opts):
    columns=['reserve_money','currency_in_circulation','bankers_deposits','other_deposits',
             'net_rbi_credit_government','rbi_credit_banks','rbi_credit_commercial_sector',
             'net_foreign_exchange_assets','government_currency_liabilities',
             'net_non_monetary_liabilities']
    writer=DailyWriter(out,start,end)
    for idx,row in enumerate(excel_rows(zf,entry,'Report(i)'),start=1):
        if idx < 8: continue
        d=when(row[1] if len(row)>1 else None)
        if d: writer.add([],d,{col:row[j] if len(row)>j else None for col,j in zip(columns,range(2,12))})
    writer.finish([],columns)


def handle_worldbank(zf, entry, outdir, start, end, monthly_lag=0, **opts):
    for sheet,first_data,header_row in [('Monthly Prices',7,5),('Monthly Indices',10,6)]:
        names={}
        seen=set()
        writer=DailyWriter(outdir / f'WorldBank_{sheet.replace(" ","_")}_Daily.csv',start,end)
        for i,row in enumerate(excel_rows(zf,entry,sheet),start=1):
            if i==header_row:
                names={j:clean(v) or f'index_{j}' for j,v in enumerate(row) if j>0}
            if sheet=='Monthly Indices' and header_row < i < first_data:
                for j,v in enumerate(row):
                    if j and clean(v): names[j]=clean(v)
            if i<first_data: continue
            period=clean(row[0]) if row else None
            match=re.fullmatch(r'(\d{4})M(\d{2})',period or '')
            if not match: continue
            d=month_date(*match.groups(),lag=monthly_lag)
            vals={f'{names.get(j,f"col_{j+1}")}__c{j+1}':v for j,v in enumerate(row) if j>0}
            writer.add([],d,vals)
            seen.update(vals)
        writer.finish([],sorted(seen))


def handle_eurostat(zf,entry,out,start,end,monthly_lag=0,**opts):
    rows=excel_rows(zf,entry,'Sheet 1')
    dates={}
    writer=DailyWriter(out,start,end)
    for n,row in enumerate(rows,start=1):
        if n==9:
            for j,v in enumerate(row):
                s=clean(v)
                if s and re.fullmatch(r'\d{4}-\d{2}',s):
                    dates[j]=month_date(*s.split('-'),lag=monthly_lag)
        elif n>=11:
            geo=clean(row[0]) if row else None
            if not geo:continue
            for j,dt in dates.items():
                val=row[j] if j<len(row) else None
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    writer.add([geo],dt,{'rate':val})
    writer.finish(['geo'],['rate'])


def handle_mospi(zf,entry,out,start,end,monthly_lag=0,all_india_general=False,**opts):
    rows=excel_rows(zf,entry)
    hdr=[str(c).strip().lower() if c is not None else f'unnamed_{i}' for i,c in enumerate(next(rows))]
    if 'month_code' in hdr:
        yearcol='year'; monthcol='month_code'; values=['index','inflation','status']
    else:
        yearcol='year'; monthcol='month'; values=[c for c in ['index','inflation','imputation','status'] if c in hdr]
    dims=[c for c in hdr if c not in set([yearcol,monthcol,'month_code','month',*values]) and not c.startswith('unnamed_')]
    writer=DailyWriter(out,start,end)
    for row in rows:
        r={hdr[i]: row[i] if i<len(row) else None for i in range(len(hdr))}
        try: d=month_date(r[yearcol],month_from_name(r[monthcol]),lag=monthly_lag)
        except (ValueError,TypeError): continue
        if all_india_general:
            if clean(r.get('state')) != 'All India':continue
            if 'division' in r and clean(r['division'])!='CPI (General)': continue
            if 'division' not in r and 'group' in r and clean(r['group'])!='General': continue
        key=[clean(r.get(c)) or '' for c in dims]
        writer.add(key,d,{c:r.get(c) for c in values})
    writer.finish(dims,values)


def handle_policy_xlsx(zf,entry,out,start,end,**opts):
    writer=DailyWriter(out,start,end)
    for n,row in enumerate(excel_rows(zf,entry,'Report 1'),start=1):
        if n<9:continue
        d=when(row[1] if len(row)>1 else None)
        if d: writer.add([],d,{name:row[j] if len(row)>j else None for j,name in enumerate(POLICY_COLS,2)})
    writer.finish([],POLICY_COLS)


def handle_policy_csv(zf,entry,out,start,end,**opts):
    data=csv.DictReader(io.TextIOWrapper(zf.open(entry),encoding='utf-8-sig'))
    writer=DailyWriter(out,start,end)
    rows=0
    value_rows=0
    for r in data:
        d=when(r.get('c1'),dayfirst=True)
        if d is None:continue
        rows+=1
        values={name:r.get(f'c{j}') for j,name in enumerate(POLICY_COLS,2)}
        if any(clean(v) is not None for v in values.values()):value_rows+=1
        writer.add([],d,values)
    if value_rows==0:
        writer.db.close();writer.tmp.cleanup()
        print(f'  !! {Path(entry).name}: {rows} effective dates but zero populated rate fields. '
              'Use the XLSX policy rates file instead; no daily CSV written.')
    else: writer.finish([],POLICY_COLS)


def handle_weekly_clean(csv_path,out,start,end):
    writer=DailyWriter(out,start,end)
    with open(csv_path,encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        values=[c for c in reader.fieldnames if c!='date']
        for r in reader:
            writer.add([],when(r['date']),{k:r[k] for k in values})
    writer.finish([],values)


class DirectorySource:
    def open(self, entry):
        return Path(entry).open('rb')


def main():
    project_root = Path(__file__).resolve().parent.parent
    p=argparse.ArgumentParser()
    p.add_argument('--raw',type=Path,default=project_root/'data'/'raw',
                   help='Source directory; subfolders are searched recursively')
    p.add_argument(
    '--out',
    type=Path,
    default=project_root / 'data' / 'interim',
    help='Destination for daily CSV files'
)
    p.add_argument('--start',default='2020-01-01',help='First daily output date, YYYY-MM-DD')
    p.add_argument('--end',default=date.today().isoformat(),help='Last daily output date')
    p.add_argument('--monthly-lag',type=int,default=0,help='Shift monthly obs by N calendar months (proxy only)')
    p.add_argument('--only',help='Process only matching filename (substring)')
    p.add_argument('--all-india-general',action='store_true',help='Filter MOSPI to All India General CPI')
    p.add_argument(
    '--weekly-clean',
    type=Path,
    default=project_root / 'data' / 'interim' / 'RBI_India_Forex_Reserves_Weekly_Clean.csv',
    help='Cleaned weekly RBI forex CSV'
)
    a=p.parse_args()
    start,end=date.fromisoformat(a.start),date.fromisoformat(a.end)
    if start>end:p.error('--start must not be after --end')
    out=Path(a.out)
    kwargs=dict(start=start,end=end,monthly_lag=a.monthly_lag,all_india_general=a.all_india_general)
    handlers={
       'WorldBank_Global_Commodity_Prices_Monthly.xlsx':handle_worldbank,
       'Eurostat_EuroArea_HICP_Inflation_Annual_2020_2026.xlsx':handle_eurostat,
       'Eurostat_EuroArea_HICP_Inflation_Monthly_2020_2026.xlsx':handle_eurostat,
       'MOSPI_India_CPI_2012_Base_Current_2026.xlsx':handle_mospi,
       'MOSPI_India_CPI_2012_Base_Historical_Through_2026.xlsx':handle_mospi,
       'MOSPI_India_CPI_2024_Base_Current_2026.xlsx':handle_mospi,
       'MOSPI_India_CPI_2024_Base_Historical_Through_2026.xlsx':handle_mospi,
       'RBI_India_Reserve_Money_Components.xlsx':handle_reserve_money,
       'RBI_India_Monetary_Policy_Rates.csv':handle_policy_csv,
       'RBI_India_Monetary_Policy_Rates_And_Reserve_Requirements.xlsx':handle_policy_xlsx,
    }
    if not a.raw.is_dir():
        p.error(f'Source folder does not exist: {a.raw}')
    source=DirectorySource()
    files=sorted(path for path in a.raw.rglob('*') if path.is_file()
                 and path.name in handlers
                 and (not a.only or a.only.lower() in path.name.lower()))
    if not files:
        print(f'No matching source files found under {a.raw}')
    for entry in files:
        name=entry.name
        print('Processing',entry)
        if name.startswith('WorldBank_'):
            handlers[name](source,entry,out,**kwargs)
        else:
            handlers[name](source,entry,out/(entry.stem+'_Daily.csv'),**kwargs)
    weekly = a.weekly_clean

if weekly.is_file():
    print("Processing weekly forex reserves:", weekly)

    handle_weekly_clean(
        weekly,
        out / (weekly.stem + "_Daily.csv"),
        start,
        end
    )
else:
    print(f"WARNING: Weekly forex reserves CSV not found: {weekly}")

if __name__=='__main__': main()
