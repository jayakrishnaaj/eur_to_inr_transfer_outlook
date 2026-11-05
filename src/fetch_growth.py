import io
import json
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

START = "2019-01-01"
TODAY = pd.Timestamp.today().normalize()
YEARS = ",".join(str(y) for y in range(2018, TODAY.year + 1))

# days after the end of the month/quarter until the number is published
LAG_DAYS = {"in_cpi_yoy": 14, "in_iip_yoy": 30, "in_gdp_yoy": 62,
            "ea_hicp_yoy": 18, "ea_unemployment": 32, "ea_esi": 1, "ea_gdp_yoy": 47}

# MoSPI's server needs this setting, otherwise Python refuses to connect
MOSPI_SSL = ssl.create_default_context()
MOSPI_SSL.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)


def download(url, ssl_context=None):
    """Download a URL, try again up to 3 times if it fails."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=90, context=ssl_context) as r:
                return r.read()
        except Exception as e:
            print(f"   try {attempt + 1} failed ({e})")
            time.sleep(5)
    raise RuntimeError(f"could not download {url}")


def mospi(path, **params):
    """Get all rows of a MoSPI query (max 100 rows per page)."""
    rows, page = [], 1
    while page <= 60:
        url = f"https://api.mospi.gov.in{path}?" + urllib.parse.urlencode(
            dict(params, Format="JSON", limit=100, page=page))
        data = json.loads(download(url, MOSPI_SSL)).get("data") or []
        rows += data
        if len(data) < 100:
            break
        page += 1
    return pd.DataFrame(rows)


def month_date(df):
    """Turn MoSPI 'year' + 'month' (e.g. 2024, 'March') into a date."""
    return pd.to_datetime(df["year"].astype(str) + "-" + df["month"].str[:3], format="%Y-%b")


def growth_from_index(d, col):
    """Fill a missing growth rate from the index (same month one year earlier)."""
    d = d.groupby("date").first().asfreq("MS")
    d[col] = d[col].fillna(d["index"].pct_change(12, fill_method=None) * 100)
    return d.dropna(subset=[col]).reset_index()


# ---------------- India ----------------
def india_cpi():
    # base 2012 (up to 2025): All India, Combined, group "General"
    old = mospi("/api/cpi/getCPIIndex", base_year=2012, series="Current", year=YEARS,
                state_code=99, sector_code=3)
    old = old[old["group"] == "General"]
    # base 2024 (from 2026): codes 1 = All India, 3 = Combined, 0 = CPI (General)
    new = mospi("/api/cpi/getCPIData", base_year=2024, series="Current", year=YEARS,
                state_code=1, sector_code=3, division_code=0)
    parts = []
    for df in (old, new):
        d = pd.DataFrame({"date": month_date(df),
                          "inflation": pd.to_numeric(df["inflation"], errors="coerce"),
                          "index": pd.to_numeric(df["index"], errors="coerce")})
        parts.append(growth_from_index(d, "inflation"))
    d = pd.concat(parts).drop_duplicates("date", keep="last")   # newer base wins
    return d["date"], d["inflation"]


def india_iip():
    parts = []
    for base in ("2011-12", "2022-23"):                       # newer base wins
        df = mospi("/api/iip/getIipData", base_year=base, frequency="Monthly",
                   type="General", year=YEARS)
        if df.empty:
            continue
        d = pd.DataFrame({"date": month_date(df),
                          "growth": pd.to_numeric(df["growth_rate"], errors="coerce"),
                          "index": pd.to_numeric(df["index"], errors="coerce")})
        parts.append(growth_from_index(d, "growth"))
    d = pd.concat(parts).drop_duplicates("date", keep="last")
    return d["date"], d["growth"]


def india_gdp():
    fin_years = ",".join(f"{y}-{str(y + 1)[2:]}" for y in range(2018, TODAY.year + 1))
    parts = []
    for base in ("2011-12", "2022-23"):                       # newer base wins
        df = mospi("/api/nas/getNASData", base_year=base, series="Current",
                   frequency_code="Quarterly", indicator_code=22, year=fin_years)
        if df.empty:
            continue
        # Indian financial year: Q1 = Apr-Jun, Q2 = Jul-Sep, Q3 = Oct-Dec, Q4 = Jan-Mar
        quarter = df["quarter"].astype(str)                  # "Q1" or "Apr-Jun"
        q = quarter.str.extract(r"(\d)")[0].fillna(
            quarter.str[:3].str.lower().map({"apr": "1", "jul": "2", "oct": "3", "jan": "4"})).astype(int)
        year = df["year"].str[:4].astype(int) + (q == 4)
        month = (1 + 3 * q).where(q < 4, 1)
        parts.append(pd.DataFrame({"date": pd.to_datetime(dict(year=year, month=month, day=1)),
                                   "growth": pd.to_numeric(df["constant_price"], errors="coerce")}))
    d = pd.concat(parts).dropna().drop_duplicates("date", keep="last")   # latest revision
    return d["date"], d["growth"]


# ---------------- Euro area ----------------
def ecb(key):
    url = f"https://data-api.ecb.europa.eu/service/data/{key}?startPeriod=2019-01&format=csvdata"
    return pd.read_csv(io.BytesIO(download(url)))[["TIME_PERIOD", "OBS_VALUE"]]


def euro_hicp():
    new = ecb("HICP/M.U2.N.000000.4D0.ANR")                   # current dataset
    old = ecb("ICP/M.U2.N.000000.4.ANR")                      # old dataset, ends Dec 2025
    d = pd.concat([old, new]).drop_duplicates("TIME_PERIOD", keep="last")
    return pd.to_datetime(d["TIME_PERIOD"]), d["OBS_VALUE"]


def eurostat(dataset, **filters):
    """Eurostat JSON API for the euro area (21 countries)."""
    url = (f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset}?"
           + urllib.parse.urlencode(dict(filters, geo="EA21", sinceTimePeriod="2019-01")))
    js = json.loads(download(url))
    periods = js["dimension"]["time"]["category"]["index"]       # {"2019-01": 0, ...}
    values = {p: js["value"].get(str(i)) for p, i in periods.items()}
    s = pd.Series(values).dropna()
    dates = pd.PeriodIndex(s.index.str.replace("-Q", "Q"), freq="Q" if "Q" in s.index[0] else "M")
    return dates.to_timestamp(), s.values


# ---------------- put it together ----------------
SERIES = {   # name: (function, monthly or quarterly)
    "in_cpi_yoy": (india_cpi, "M"),
    "in_iip_yoy": (india_iip, "M"),
    "in_gdp_yoy": (india_gdp, "Q"),
    "ea_hicp_yoy": (euro_hicp, "M"),
    "ea_unemployment": (lambda: eurostat("une_rt_m", s_adj="SA", age="TOTAL", unit="PC_ACT", sex="T"), "M"),
    "ea_esi": (lambda: eurostat("ei_bssi_m_r2", indic="BS-ESI-I", s_adj="SA"), "M"),
    "ea_gdp_yoy": (lambda: eurostat("namq_10_gdp", unit="CLV_PCH_SM", s_adj="SCA", na_item="B1GQ"), "Q"),
}

tables = []
for name, (get, freq) in SERIES.items():
    try:
        dates, values = get()
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        continue
    t = pd.DataFrame({"period_start": pd.to_datetime(dates), "value": pd.to_numeric(values)})
    t = t[t["period_start"] >= START].sort_values("period_start")
    end = t["period_start"] + (pd.offsets.MonthEnd(0) if freq == "M" else pd.offsets.QuarterEnd(0))
    t["period"] = t["period_start"].dt.to_period(freq).astype(str)
    t["available_from"] = end + pd.Timedelta(days=LAG_DAYS[name])
    t["series"] = name
    tables.append(t)
    print(f"ok    {name:16s} {t['period'].iloc[0]} .. {t['period'].iloc[-1]}")

raw = pd.concat(tables)
Path("data/raw").mkdir(parents=True, exist_ok=True)
raw.to_csv("data/raw/growth_raw.csv", index=False)


def as_of(dates, date_col):
    """For each date: the newest value of each series that was published by then."""
    out = pd.DataFrame({date_col: dates})
    for name, t in raw.groupby("series"):
        m = pd.merge_asof(out[[date_col]], t.sort_values("available_from"),
                          left_on=date_col, right_on="available_from")
        out[name] = m["value"].values
        out[f"{name}_period"] = m["period"].values
    return out


Path("data/processed").mkdir(parents=True, exist_ok=True)
as_of(pd.date_range(START, TODAY, freq="D"), "date").to_csv("data/processed/growth_daily.csv", index=False)
as_of(pd.date_range(START, TODAY, freq="W-MON"), "week_start").to_csv("data/processed/growth_weekly.csv", index=False)
print("saved data/processed/growth_daily.csv and growth_weekly.csv")