# EUR to INR Transfer Outlook

Can a model tell someone in Germany, better than a coin flip, whether waiting up to
5 working days will get more rupees for their euros?

## Team
- Jayakrishna
- Rosa
- Abey

## Setup (Windows)
```
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```
Create a file `.env` in the main folder with your own FRED API key
(see `.env.example`): `FRED_API_KEY=your_key`

## How to run
Run all commands from the main project folder:
```
python src/collect_uncertainty.py
python src/fill_decisions.py
python src/collect_events.py
python src/collect_seasonality.py
```

## Folder structure
| Folder | Content |
|---|---|
| `data/raw/` | data exactly as downloaded, never edited |
| `data/external/` | hand-made files (event and meeting dates) |
| `data/interim/` | cleaned data |
| `data/processed/` | final feature tables for the models |
| `src/` | Python scripts |
| `notebooks/` | Jupyter notebooks |
| `app/` | dashboard |
| `reports/` | figures and proposal |
| `tests/` | leakage and data checks |
| `docs/` | notes and decisions |

## Links
- Website: (to be added)
- Screencast: (to be added)