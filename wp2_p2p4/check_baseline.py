"""Regression check: does out/eval_<tag>.csv still equal the saved baseline (out/baseline/)?

    python check_baseline.py               compare out/eval_all_s0.csv with out/baseline/eval_all_s0.csv
    python check_baseline.py --run         re-run evaluate.py (cached features, no recal events) first

With no recalibration events the production-loop changes must not move a single number.
"""
import argparse
import os
import sys

import pandas as pd

import load


def compare(tag="all_s0"):
    new = pd.read_csv(os.path.join(load.OUT, f"eval_{tag}.csv"))
    old = pd.read_csv(os.path.join(load.OUT, "baseline", f"eval_{tag}.csv"))
    if list(new.columns) != list(old.columns) or new.shape != old.shape:
        print(f"DIFFERENT SHAPE: baseline {old.shape}, new {new.shape}")
        return False
    diff = ~((new == old) | (new.isna() & old.isna()))
    if diff.any().any():
        r, c = diff.to_numpy().nonzero()
        for i, j in list(zip(r, c))[:20]:
            print(f"  row {i} ({old.detector[i]}, budget {old.budget[i]}) {old.columns[j]}: "
                  f"{old.iat[i, j]} -> {new.iat[i, j]}")
        print(f"DIFFERENT: {int(diff.sum().sum())} cells")
        return False
    print(f"IDENTICAL: eval_{tag}.csv matches the baseline ({old.shape[0]} rows x {old.shape[1]} columns)")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--tag", default="all_s0")
    a = ap.parse_args()
    if a.run:
        import evaluate
        name, seed = a.tag.rsplit("_s", 1)
        evaluate.run(None if name == "all" else [int(m) for m in name[1:].split("-")], int(seed))
    sys.exit(0 if compare(a.tag) else 1)
