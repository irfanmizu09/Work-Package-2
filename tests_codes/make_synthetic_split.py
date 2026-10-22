"""Synthetic stand-in for data/explain/{train,test} (CSV). Mimics DATASET.md conventions."""
import sys, os
import numpy as np
import pandas as pd

out = sys.argv[1] if len(sys.argv) > 1 else "synth/explain"
rng = np.random.default_rng(1)
n = 150_000
t = pd.date_range("2026-05-01", "2026-08-12", periods=n)
df = pd.DataFrame({
    "serialno": np.arange(n), "testtime": t,
    "equipmentid": rng.choice([9990163, 20190405, 1890933], n),
    "deviceid": rng.choice(["A", "B", "C"], n, p=[.5, .3, .2]),
    "fixture": rng.integers(1, 11, n), "attempt_no": 1,
})
pos = np.arange(n) / n
prod = df.deviceid.map({"A": 0.0, "B": 0.25, "C": -0.2})
mu = np.log(1.5) + prod + 0.05 * (df.fixture - 5) / 5
mu = mu - np.where(pos > 0.8, 0.05, 0)                                   # mild post-split shift
mu = mu + np.where((df.equipmentid == 20190405) & (df.fixture == 4) & (pos > 0.85), (pos - 0.85) * 6, 0)
leak = np.exp(rng.normal(mu, 0.30))
df["leakrate"] = leak
df["failed"] = (leak > 5.0 * np.exp(prod)).astype(int)
df["leak_failed"] = df["failed"]
df.loc[rng.random(n) < 0.03, "failed"] = 1                               # unrelated failures (~3%, like real data)
df["p1press_dev"] = np.abs(rng.normal(0, 1, n) + 0.8 * (np.log(leak) - mu))
df["p5press_dev"] = np.abs(rng.normal(0, 1, n))
df["p2output_dev"] = np.where(rng.random(n) < 0.0155, np.nan, np.abs(rng.normal(0, 1, n)))
df["tempoutput_dev"] = 0.0                                               # constant column, should be ignored
sent = rng.random(n) < 0.004
df.loc[sent, "leakrate"] = 9999.0
df["leakrate_missing"] = sent
# retests: ~5% of units get a second attempt row (must be excluded from baseline and scoring)
re = df.sample(frac=0.05, random_state=2).copy()
re["attempt_no"] = 2
df = pd.concat([df, re]).sort_values("testtime").reset_index(drop=True)
# causal recent fixture failure rate (previous 50 on machine+fixture, excludes own row)
df["fx_recent_fail"] = (df.groupby(["equipmentid", "fixture"]).failed
                        .transform(lambda s: s.shift().rolling(50, min_periods=10).mean()))
cut = pd.Timestamp("2026-07-23")
for name, part in (("train", df[df.testtime < cut]), ("test", df[df.testtime >= cut])):
    os.makedirs(f"{out}/{name}", exist_ok=True)
    part.to_csv(f"{out}/{name}/part0.csv", index=False)
print(len(df), "rows written to", out)
