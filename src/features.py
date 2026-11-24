from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "processed" / "data_daily_base.csv"
END, START = "2026-10-29", "2020-02-01"
TRAIN_END, VAL_END = "2023-12-31", "2024-12-31"
HORIZON = 5   # rate days ahead

def load_data(path=DATA_PATH):
    df = pd.read_csv(path, parse_dates=["date"])
    return df[df["date"] <= END].sort_values("date").reset_index(drop=True)


def add_target(d):
    d = d.copy()
    d["target_5d"] = 100 * np.log(d["eur_inr"].shift(-HORIZON) / d["eur_inr"])
    return d


def add_split(d):
    d = d.copy()
    d["period"] = np.select([d["date"] <= TRAIN_END, d["date"] <= VAL_END],
                            ["train", "val"], default="test")
    return d

def features_target(df):
    return pd.DataFrame(index=df.index)

def features_fundamentals(df):
    return pd.DataFrame(index=df.index)

def features_markets(df):
    return pd.DataFrame(index=df.index)

def features_events(df):
    return pd.DataFrame(index=df.index)

def build_features(df):

    feats = pd.concat([features_target(df), features_fundamentals(df), features_markets(df), features_events(df)], axis=1)
    full = pd.concat([df[["date", "eur_inr"]], feats], axis=1)

    d = full[full["eur_inr"].notna() & (full["date"] >= START)].reset_index(drop=True)
    return add_split(add_target(d))