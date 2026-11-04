# Uncertainty and Geopolitics Data – Collection and Cleaning Notes

**Project:** EUR to INR Transfer Outlook
**Category:** Uncertainty and geopolitics (extends plan factor group 6 – Global risk mood)
**Board item:** DATA-6: EPU and GPR loader
**Date:** 2026-10-28
**Status:** Steps 1–4 (choose, collect, inspect, clean) done. Step 5 (align to ECB days) waits for the EUR/INR loader (DATA-1).

---

## 1. Why this category

When uncertainty or geopolitical tension rises, investors move money out of emerging-market currencies such as the rupee. These indices measure that mood from newspaper coverage, so they may help predict short-term EUR/INR moves.

---

## 2. Data sources (decision table – needs team approval)

| Feature name | Series | Source / ID | Why linked to EUR/INR | Starts | Frequency | Publication lag | Use rule (leakage) |
|---|---|---|---|---|---|---|---|
| `us_epu` | US Economic Policy Uncertainty | FRED `USEPUINDXD` | US uncertainty moves the dollar, which drives USD/INR | 1985 | Daily (7 days a week) | 1 day | Use the t−1 value |
| `in_epu` | India Economic Policy Uncertainty | FRED `INDEPUINDXM` | Indian policy uncertainty affects the rupee | 2003 | Monthly | ~1 month | Usable from the 1st of the next month |
| `eu_epu` | Europe Economic Policy Uncertainty | FRED `EUEPUINDXM` | Euro-side uncertainty affects EUR | 1987 | Monthly | ~1 month | Usable from the 1st of the next month |
| `gpr` | Global Geopolitical Risk (daily, Recent index) | matteoiacoviello.com/gpr.htm – daily Excel file, column `GPRD` | Geopolitical stress causes emerging-market sell-offs | 1985 | Daily | 1 day; updated weekly (Mondays); recent values revised | Use the t−1 value; commit the dated snapshot |
| `gpr_india` | India-specific Geopolitical Risk | matteoiacoviello.com/gpr.htm – monthly Excel file, column `GPRC_IND` | Geopolitical risk specific to India affects the rupee directly | 1985 | Monthly | ~10 days after month end; revised | Usable from the 1st of the next month |

Sources:
- EPU: Baker, Bloom and Davis, via FRED (fred.stlouisfed.org)
- GPR: Caldara and Iacoviello (2022), "Measuring Geopolitical Risk", American Economic Review. Data downloaded from https://www.matteoiacoviello.com/gpr.htm on 2026-10-28.

---

## 3. Key concept: the t−1 rule (avoiding data leakage)

- **t** = the day we make a prediction; **t−1** = the day before.
- The model predicts from the ECB reference rate, published at about 16:00 Frankfurt time on day t.
- A feature for day t may only use information that was public **before** that moment.
- US EPU and GPR for day t are only complete after the US day ends (early morning of day t+1 in Berlin), so on day t we must use the **day t−1** value.
- Monthly series are only published after the month ends, so January's value may only be used **from February onward** (shift by one full month).
- Using future information by mistake makes the model look great in testing and fail in real life. This is called **data leakage**.

---

## 4. How the data was collected

### Setup
- Python 3.11.9 in a project virtual environment (`.venv`), packages: pandas, requests, python-dotenv, matplotlib, openpyxl, xlrd, python-calamine, jupyter, ipykernel.
- FRED API key stored only in `.env` (`FRED_API_KEY=...`). `.env` is listed in `.gitignore` and is never committed. Teammates use `.env.example` as a template.

### Files
| File | Content |
|---|---|
| `data/raw/fred_USEPUINDXD.csv` | Raw US EPU from the FRED API (unchanged) |
| `data/raw/fred_INDEPUINDXM.csv` | Raw India EPU from the FRED API (unchanged) |
| `data/raw/fred_EUEPUINDXM.csv` | Raw Europe EPU from the FRED API (unchanged) |
| `data/raw/gpr_daily_2026-10-28.xls` | Daily GPR Excel file, downloaded by hand (dated snapshot) |
| `data/raw/gpr_monthly_2026-10-28.xls` | Monthly GPR Excel file incl. country indices, downloaded by hand (dated snapshot) |
| `data/processed/<name>_clean.csv` | Cleaned versions (git-ignored, rebuilt by the script) |
| `data/processed/uncertainty_overview.png` | Overview chart of all five series |

### Scripts
- `collect_uncertainty.py` – downloads the FRED series, reads both GPR Excel files, cleans everything, saves raw and clean files, prints a report.
- `inspect_uncertainty.py` – counts zero values, finds the date of each maximum, and saves the overview chart.

To rebuild: activate `.venv`, then run `python collect_uncertainty.py` followed by `python inspect_uncertainty.py`.

---

## 5. Cleaning rules (applied to every series)

1. Convert dates to real datetime values; sort by date.
2. Convert values to numbers. FRED marks missing values with `.`, which becomes NaN.
3. Drop missing values.
4. Remove duplicate dates (keep the last value).
5. Remove impossible values (an index cannot be negative).
6. Use lowercase column names and a DatetimeIndex named `date` (the interface agreed in the plan).

**Not done in cleaning (on purpose):** no lag is applied yet and no gaps are filled. Aligning to the ECB calendar and applying the t−1 and one-month rules happens in step 5, once the EUR/INR rates exist.

---

## 6. Results after cleaning

| Series | Date range | Rows | Min | Max | Largest gap |
|---|---|---|---|---|---|
| `us_epu` | 1985-01-01 to 2026-10-27 | 15,275 | 3.3 | 1049.0 | 1 day |
| `in_epu` | 2003-01-01 to 2026-09-01 | 285 | 23.4 | 323.8 | 31 days (one month) |
| `eu_epu` | 1987-01-01 to 2026-09-01 | 477 | 33.8 | 779.3 | 31 days (one month) |
| `gpr` | 1985-01-01 to 2026-10-26 | 15,272 | 3.6 | 1045.6 | 2 days (see decision below) |
| `gpr_india` | 1985-01-01 to 2026-09-01 | 501 | 0.0 | 1.1 | 31 days (one month) |

How to read "largest gap": for daily series, 1 day means no missing days; for monthly series, 31 days is simply the longest month, so no missing months.

---

## 7. Data quality findings and decisions (for DATA-5)

1. **All five series are complete** in their own frequency: no missing days or months.
2. **India EPU starts in 2003**, later than EUR/INR (1999). Rows before 2003 will be empty for this feature.
3. **Monthly series end in September 2026**; October is not yet published (publication lag about one month).
4. **Daily GPR ends on 26 October 2026** (weekly Monday update); the most recent values are preliminary and may be revised.
5. **GPR zero values – decision:** two isolated zeros on 1997-10-19 and 2025-02-09, both Sundays. Interpreted as missing newspaper coverage, not "zero risk", and removed. This creates a 2-day gap (Saturday to Monday), which is expected; the alignment step uses the previous available day.
6. **`gpr_india` uses a different scale (0.0 to 1.1)** because country indices measure the share of articles, not an index normalised to 100. Not an error. Its zero values are plausible (months with no such articles about India) and are kept.
7. **The largest spikes match real events**, which confirms correct date parsing:
   - `gpr` maximum on 2001-09-25 (after 9/11); visible bumps for the 1991 Gulf War, the 2003 Iraq war and the 2022 invasion of Ukraine.
   - `gpr_india` maximum in May 1998 (India's nuclear tests); bumps for the 2001–02 India–Pakistan standoff, the November 2008 Mumbai attacks and the May 2025 India–Pakistan conflict.
   - `eu_epu` maximum in April 2025 (large US tariff announcements).
8. **Levels shift over time:** GPR is permanently higher after 2001, US EPU sits on a higher plateau since 2020, and Europe EPU trends upward over the whole period. Raw levels therefore mean different things in different years.

---

## 8. Implications for feature engineering (FEAT-1)

Because the "normal level" changes over time, describe uncertainty **relative to its recent past**, not as raw levels:

- Change over 5 days, e.g. `us_epu.pct_change(5)`, `gpr.pct_change(5)`
- Value relative to its own rolling average (e.g. value / 60-day mean)
- Spike flag: value above its rolling 90th percentile
- Difference between India and Europe EPU (`in_epu − eu_epu`), after the one-month shift
- Relative features also make the unusual scale of `gpr_india` irrelevant

Also check for near-duplicates (correlation above 0.95), e.g. US EPU versus VIX from factor group 6.

All rolling windows must look backward only, and these features must pass the leakage unit test.

---

## 9. Status and next steps

| Step | Status |
|---|---|
| 1. Choose the data | Done – table above, needs team approval on Monday |
| 2. Collect | Done – all five series in `data/raw/` |
| 3. Inspect | Done – ranges, gaps, zeros, spikes and chart checked |
| 4. Clean | Done – including the GPR zero decision |
| 5. Align to ECB days and apply t−1 / one-month rules | Next – needs the EUR/INR loader (DATA-1) |
| 6. Engineer features | Later – FEAT-1 |
| 7. Leakage unit test | Later – FEAT-1 |
| 8. Document and commit | In progress – this file; commit pending |

**Next actions**
1. Commit on a branch with a message such as `DATA-6: collect and clean EPU and GPR data` (scripts, raw files, docs). Do not commit `.env`, `test_fred.py` or `data/processed/`.
2. Add `DATA-6` to the board on projektmgmt.ovgu.de.
3. Agree with Person B (loader owner) on one shared `src/eurinr/data/fred.py`, then move the loader code there.
4. Ask the owner of DATA-1 when the EUR/INR loader will be ready, since step 5 depends on it.
5. Repeat the same process for the next categories: event calendar, seasonality, text and sentiment (GDELT), remittances.
