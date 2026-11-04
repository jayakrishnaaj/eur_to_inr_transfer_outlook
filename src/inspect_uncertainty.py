import pandas as pd
import matplotlib.pyplot as plt

names = ["us_epu", "in_epu", "eu_epu", "gpr", "gpr_india"]
data = {n: pd.read_csv(f"data/interim/{n}_clean.csv", index_col="date", parse_dates=True)[n]
        for n in names}

for n, s in data.items():
    zeros = (s == 0).sum()
    print(f"{n:10s} zeros: {zeros:4d} | max on {s.idxmax().date()} | "
          f"zero dates: {list(s[s == 0].index.date[:5])}")

fig, axes = plt.subplots(len(names), 1, figsize=(10, 12), sharex=True)
for ax, (n, s) in zip(axes, data.items()):
    ax.plot(s.index, s.values, linewidth=0.6)
    ax.set_title(n)
plt.tight_layout()
plt.savefig("reports/figures/uncertainty_overview.png")
plt.show()