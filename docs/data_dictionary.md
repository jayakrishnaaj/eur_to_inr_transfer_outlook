# Data dictionary – `data/final/features_ecb_clean.csv`

One row per ECB fixing (ECB working day with a EUR/INR rate), 3 Feb 2020 – 29 Oct 2026. Every feature shows only what was public before the fixing at about 14:10 CET on that day (the "Available from" column). Built by `src/merge_data.py` and `src/clean_final.py`.

Descriptions of Rosa's and Abhay's columns are written from the merge plan and column names; owners, please correct anything that is off.

| Column | Meaning | Unit | Source | Available from | Owner |
|---|---|---|---|---|---|
| `date` | ECB working day of the fixing | date | - | - | - |
| `eur_inr` | TARGET: ECB reference rate, rupees per euro, fixed ~14:10 CET that day | INR per EUR | ECB (Frankfurter) | same day (target) | Abhay |
| `eur_inr_prev` | Previous ECB fixing of EUR/INR | INR per EUR | ECB | previous fixing | Abhay |
| `eur_usd_usd_per_eur` | ECB reference rate EUR/USD (previous fixing) | USD per EUR | ECB | previous fixing (same moment as target) | Abhay |
| `usd_inr_inr_per_usd` | ECB reference rate USD/INR (previous fixing) | INR per USD | ECB | previous fixing (same moment as target) | Abhay |
| `brent_usd_per_barrel` | Brent crude oil price | USD per barrel | FRED DCOILBRENTEU | +1 day | Abhay |
| `us_10y_treasury_yield_pct` | US 10-year government bond yield | % | FRED DGS10 | +1 day | Abhay |
| `broad_usd_index_2006_100` | Broad US dollar index | index, 2006=100 | FRED DTWEXBGS | +1 day | Abhay |
| `rbi_repo_rate_pct` | RBI policy repo rate | % | RBI | same day (announced before it applies) | Abhay |
| `ecb_deposit_rate_pct` | ECB deposit facility rate | % | FRED ECBDFR | same day (announced before it applies) | Abhay |
| `rate_gap_in_ea` | RBI repo rate minus ECB deposit rate | percentage points | derived | as its inputs | Abhay |
| `fpi_equity_1w` | Net foreign portfolio investment in Indian equities, last 1 week | INR crore | NSDL | publication date | Rosa |
| `fpi_equity_4w` | Same, last 4 weeks | INR crore | NSDL | publication date | Rosa |
| `fpi_debt_1w` | Net foreign portfolio investment in Indian debt, last 1 week | INR crore | NSDL | publication date | Rosa |
| `fpi_debt_4w` | Same, last 4 weeks | INR crore | NSDL | publication date | Rosa |
| `fpi_total_1w` | Net FPI equity + debt, last 1 week | INR crore | NSDL | publication date | Rosa |
| `fpi_total_4w` | Same, last 4 weeks | INR crore | NSDL | publication date | Rosa |
| `fpi_equity_day_since_fix` | Net FPI equity flows published since the previous fixing (weekend reports added to the next ECB day) | INR crore | NSDL | publication date, summed since previous fixing | Rosa |
| `fpi_debt_day_since_fix` | Same for debt | INR crore | NSDL | publication date, summed since previous fixing | Rosa |
| `fpi_total_day_since_fix` | Same for equity + debt | INR crore | NSDL | publication date, summed since previous fixing | Rosa |
| `ea_esi` | Euro-area Economic Sentiment Indicator | index (long-run avg = 100) | Eurostat / EC | publication date | Rosa |
| `ea_gdp_yoy` | Euro-area GDP growth, year on year | % | Eurostat | publication date | Rosa |
| `ea_hicp_yoy` | Euro-area inflation (HICP), year on year | % | Eurostat | publication date | Rosa |
| `ea_unemployment` | Euro-area unemployment rate | % | Eurostat | publication date | Rosa |
| `in_cpi_yoy` | India CPI inflation, year on year | % | MOSPI | publication date | Rosa |
| `in_gdp_yoy` | India GDP growth, year on year | % | MOSPI | publication date | Rosa |
| `in_iip_yoy` | India industrial production (IIP), year on year | % | MOSPI | publication date | Rosa |
| `ea_esi_chg` | Change of ea_esi since the previous release | index points | derived | publication date | Rosa |
| `ea_gdp_yoy_chg` | Change of ea_gdp_yoy since the previous release | pp | derived | publication date | Rosa |
| `ea_hicp_yoy_chg` | Change of ea_hicp_yoy since the previous release | pp | derived | publication date | Rosa |
| `ea_unemployment_chg` | Change of ea_unemployment since the previous release | pp | derived | publication date | Rosa |
| `in_cpi_yoy_chg` | Change of in_cpi_yoy since the previous release | pp | derived | publication date | Rosa |
| `in_gdp_yoy_chg` | Change of in_gdp_yoy since the previous release | pp | derived | publication date | Rosa |
| `in_iip_yoy_chg` | Change of in_iip_yoy since the previous release | pp | derived | publication date | Rosa |
| `in_ea_inflation_gap` | India CPI inflation minus euro-area inflation | pp | derived | as its inputs | Rosa |
| `in_ea_growth_gap` | India GDP growth minus euro-area GDP growth | pp | derived | as its inputs | Rosa |
| `vix` | CBOE VIX volatility index (US market fear) | index points | FRED VIXCLS | publication date | Rosa |
| `baa_spread` | Moody's Baa corporate bond spread over Treasuries | pp | FRED | publication date | Rosa |
| `vix_chg_1w` | Change of VIX over 1 week | index points | derived | as its input | Rosa |
| `vix_avg_4w` | Average VIX over 4 weeks | index points | derived | as its input | Rosa |
| `baa_spread_chg_1w` | Change of Baa spread over 1 week | pp | derived | as its input | Rosa |
| `baa_spread_avg_4w` | Average Baa spread over 4 weeks | pp | derived | as its input | Rosa |
| `ea_current_account_eur_bn` | Euro-area current account balance | EUR bn | ECB | publication date | Rosa |
| `ea_current_account_eur_bn_chg` | Change since the previous release | EUR bn | derived | publication date | Rosa |
| `ea_goods_balance_eur_bn` | Euro-area goods trade balance | EUR bn | ECB / Eurostat | publication date | Rosa |
| `ea_goods_balance_eur_bn_chg` | Change since the previous release | EUR bn | derived | publication date | Rosa |
| `india_exports_usd_bn` | India merchandise exports, monthly | USD bn | Ministry of Commerce | publication date | Rosa |
| `india_exports_usd_bn_chg` | Change since the previous release | USD bn | derived | publication date | Rosa |
| `india_imports_usd_bn` | India merchandise imports, monthly | USD bn | Ministry of Commerce | publication date | Rosa |
| `india_imports_usd_bn_chg` | Change since the previous release | USD bn | derived | publication date | Rosa |
| `india_trade_balance_usd_bn` | India trade balance (exports minus imports) | USD bn | derived | publication date | Rosa |
| `india_trade_balance_usd_bn_chg` | Change since the previous release | USD bn | derived | publication date | Rosa |
| `india_trade_balance_usd_bn_avg_3m` | Average trade balance over the last 3 releases | USD bn | derived | publication date | Rosa |
| `total_inr_cr` | India total foreign exchange reserves | INR crore | RBI (weekly) | week end + 8 days | Rosa |
| `total_usd_mn` | India total foreign exchange reserves | USD mn | RBI (weekly) | week end + 8 days | Rosa |
| `fca_usd_mn` | Foreign currency assets in the reserves | USD mn | RBI (weekly) | week end + 8 days | Rosa |
| `gold_usd_mn` | Gold in the reserves | USD mn | RBI (weekly) | week end + 8 days | Rosa |
| `sdr_usd_mn` | Special Drawing Rights in the reserves | USD mn | RBI (weekly) | week end + 8 days | Rosa |
| `imf_rtp_usd_mn` | Reserve tranche position at the IMF | USD mn | RBI (weekly) | week end + 8 days | Rosa |
| `ex_gold_usd_mn` | Reserves excluding gold | USD mn | derived | week end + 8 days | Rosa |
| `total_chg_1w` | Change of total reserves over 1 week | USD mn | derived | week end + 8 days | Rosa |
| `total_chg_4w` | Change of total reserves over 4 weeks | USD mn | derived | week end + 8 days | Rosa |
| `fca_chg_1w` | Change of foreign currency assets over 1 week | USD mn | derived | week end + 8 days | Rosa |
| `fca_chg_4w` | Change of foreign currency assets over 4 weeks | USD mn | derived | week end + 8 days | Rosa |
| `ex_gold_chg_1w` | Change of reserves ex gold over 1 week | USD mn | derived | week end + 8 days | Rosa |
| `ex_gold_chg_4w` | Change of reserves ex gold over 4 weeks | USD mn | derived | week end + 8 days | Rosa |
| `gpr` | Geopolitical Risk index, daily (news about wars, threats, terrorism) | index (avg 1985-2019 = 100) | Caldara & Iacoviello | +1 day (open question: file updated weekly on Mondays) | Jayakrishna |
| `us_epu` | US Economic Policy Uncertainty, daily (newspaper-based) | index | FRED USEPUINDXD | +1 day | Jayakrishna |
| `gpr_india` | Geopolitical risk involving India, monthly | share of articles (%) | Caldara & Iacoviello | month end + 7 days | Jayakrishna |
| `in_epu` | India Economic Policy Uncertainty, monthly | index | FRED INDEPUINDXM | month end + 7 days | Jayakrishna |
| `eu_epu` | Europe Economic Policy Uncertainty, monthly | index | FRED EUEPUINDXM | month end + 7 days | Jayakrishna |
| `weekday` | Day of the week (0 = Monday ... 4 = Friday) | 0-4 | derived from date | known in advance | Jayakrishna |
| `day_of_month` | Day of the month | 1-31 | derived from date | known in advance | Jayakrishna |
| `month` | Month | 1-12 | derived from date | known in advance | Jayakrishna |
| `is_de_holiday` | 1 = German public holiday (ECB open, Germany closed, e.g. Ascension, 3 Oct) | 0/1 | holidays package | known in advance | Jayakrishna |
| `is_in_holiday` | 1 = Indian public holiday | 0/1 | holidays package | known in advance | Jayakrishna |
| `is_payday_window` | 1 = one of the last 3 German working days of the month | 0/1 | derived | known in advance | Jayakrishna |
| `is_diwali` | 1 = Diwali | 0/1 | holidays package | known in advance | Jayakrishna |
| `days_to_diwali` | Calendar days until the next Diwali | days | holidays package | known in advance | Jayakrishna |
| `is_december` | 1 = December | 0/1 | derived | known in advance | Jayakrishna |
| `is_india_fy_end` | 1 = 25-31 March (end of India's financial year) | 0/1 | derived | known in advance | Jayakrishna |
| `days_to_ecb_decision` | Calendar days until the next scheduled ECB rate decision | days | ECB calendar | known in advance | Jayakrishna |
| `days_to_rbi_decision` | Calendar days until the next scheduled RBI MPC decision | days | RBI calendar | known in advance | Jayakrishna |
| `days_to_fomc_decision` | Calendar days until the next scheduled Fed (FOMC) decision | days | Fed calendar | known in advance | Jayakrishna |
| `days_to_us_cpi` | Calendar days until the next US CPI release | days | FRED release 10 | known in advance | Jayakrishna |
| `days_to_us_jobs` | Calendar days until the next US jobs report | days | FRED release 50 | known in advance | Jayakrishna |
| `last_ecb_decision_bp` | Size of the last ECB decision (+ hike, - cut, 0 hold) | basis points | ECB / FRED ECBDFR | next day from 21 Jul 2022 (announced 14:15 CET, after the fixing); same day before | Jayakrishna |
| `last_rbi_decision_bp` | Size of the last RBI repo rate decision | basis points | RBI press releases | same day (announced ~10:00 IST) | Jayakrishna |
| `last_fomc_decision_bp` | Size of the last Fed decision (upper target) | basis points | Fed / FRED DFEDTARU | next day (announced ~20:00 CET) | Jayakrishna |
| `is_ecb_decision_day_since_fix` | 1 = an ECB decision since the previous fixing | 0/1 | ECB | date known in advance | Jayakrishna |
| `is_rbi_decision_day_since_fix` | 1 = an RBI decision since the previous fixing (surprise meetings count from when announced) | 0/1 | RBI | scheduled: in advance; surprise: when announced | Jayakrishna |
| `is_fomc_decision_day_since_fix` | 1 = a Fed decision since the previous fixing (surprise meetings count from the next day) | 0/1 | Fed | scheduled: in advance; surprise: next day | Jayakrishna |
| `is_us_cpi_day_since_fix` | 1 = a US CPI release since the previous fixing | 0/1 | FRED release 10 | known in advance | Jayakrishna |
| `is_us_jobs_day_since_fix` | 1 = a US jobs report since the previous fixing | 0/1 | FRED release 50 | known in advance | Jayakrishna |
| `is_india_budget_day_since_fix` | 1 = an India Union Budget since the previous fixing | 0/1 | indiabudget.gov.in | known in advance | Jayakrishna |
