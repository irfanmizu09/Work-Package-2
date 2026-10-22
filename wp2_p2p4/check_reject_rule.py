"""Step b - does a tolerance band reproduce the tester's P2 / P4 OUTPUT rejects?

Truth: fail_s = the unit's status is a P2 (P4) output failure (load.OUTPUT_RE).
Candidate rules, on units where the signal was measured (v_s set):
  R1  |error| / tol > 1                 Trace Sentinel's rule (|v| > 100)
  R2  |output - target| / tol > 1       what WP1's p*_dev_tol measures
  R3  per-device best band on |v|       the threshold that best separates rejects from passes on
                                        that device (tells whether the band is just narrower/wider)
Also: where do the output rejects WITHOUT a usable value go (why_s), and what do they say?
"""
import argparse

import numpy as np
import pandas as pd

import load

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)


def confusion(pred, y):
    tp, fp = int((pred & y).sum()), int((pred & ~y).sum())
    fn, tn = int((~pred & y).sum()), int((~pred & ~y).sum())
    return dict(TP=tp, FP=fp, FN=fn, TN=tn,
                precision=round(tp / (tp + fp), 3) if tp + fp else np.nan,
                recall=round(tp / (tp + fn), 3) if tp + fn else np.nan)


def best_band(a, y):
    """Threshold on |v| maximising F1 for one device; returns (thr, f1)."""
    if y.sum() == 0:
        return np.nan, np.nan
    cand = np.unique(a[y])
    best = (np.nan, -1.0)
    for t in cand:
        p = a >= t
        tp = (p & y).sum()
        f1 = 2 * tp / (p.sum() + y.sum())
        if f1 > best[1]:
            best = (t, f1)
    return best[0], round(best[1], 3)


def check(d, s, top=12):
    y_all = d[f"fail_{s}"].eq(1)
    tested = d[f"why_{s}"].ne("not_tested")
    print(f"\n{'=' * 30} {s.upper()} {'=' * 30}")
    print(f"tested units {tested.sum():,}; {s.upper()} output rejects (status) {int(y_all.sum()):,} "
          f"= base rate {y_all[tested].mean():.4%} of tested")

    print(f"\nWhere the output rejects sit (why_{s}):")
    print(pd.crosstab(d.loc[tested, f"why_{s}"], y_all[tested].map({True: "reject", False: "no reject"}),
                      margins=True).to_string())

    ok = d[f"why_{s}"].eq("ok")
    v, y = d.loc[ok, f"v_{s}"].abs(), y_all[ok]
    dev = (100 * (d.loc[ok, f"output_{s}"] - d.loc[ok, f"target_{s}"]) / d.loc[ok, f"tol_{s}"]).abs()
    rows = {"R1 |error|/tol > 1": confusion(v > 100, y),
            "R2 |output-target|/tol > 1": confusion(dev > 100, y)}
    print(f"\nConfusion on measured units ({ok.sum():,}; rejects {int(y.sum()):,}, base rate {y.mean():.4%}):")
    print(pd.DataFrame(rows).T.to_string())

    fp = ok & (d[f"v_{s}"].abs() > 100) & ~y_all
    if fp.any():
        print(f"\nR1 false positives by status family: {d.loc[fp, 'status_cat'].value_counts().to_dict()}")
    fn = ok & (d[f"v_{s}"].abs() <= 100) & y_all
    print(f"\nR1 misses: {int(fn.sum()):,} rejects with |v| <= 100. |v| of those:",
          d.loc[fn, f"v_{s}"].abs().quantile([0, .1, .5, .9, 1]).round(1).to_dict() if fn.any() else "-")
    print("  their statuses:", d.loc[fn, "status"].value_counts().head(top).to_dict())
    nan = ~ok & tested & y_all
    print(f"\nRejects with NO usable value: {int(nan.sum()):,}; statuses:",
          d.loc[nan, "status"].value_counts().head(top).to_dict())
    print("  raw output of those:", d.loc[nan, f"output_{s}"].value_counts().head(6).to_dict())

    per = []
    for dv, g in d[ok].groupby("deviceid"):
        a, yy = g[f"v_{s}"].abs().to_numpy(), g[f"fail_{s}"].eq(1).to_numpy()
        thr, f1 = best_band(a, yy)
        per.append(dict(device=dv, n=len(g), rejects=int(yy.sum()),
                        R1_recall=round((a[yy] > 100).mean(), 2) if yy.any() else np.nan,
                        R1_fp=int(((a > 100) & ~yy).sum()),
                        max_pass=round(a[~yy].max(), 1) if (~yy).any() else np.nan,
                        min_reject=round(a[yy].min(), 1) if yy.any() else np.nan,
                        best_thr=thr, best_f1=f1))
    per = pd.DataFrame(per).sort_values("rejects", ascending=False)
    print(f"\nPer device (|v| in % of tol; best_thr = band that best separates on that device):")
    print(per.head(top * 2).to_string(index=False))
    return per


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Check the P2/P4 reject rule against the tester's status")
    ap.add_argument("--split", default="train")
    ap.add_argument("--machines", default="9990675,9990771,20190405", help="'' = all machines")
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-06-15")
    a = ap.parse_args()
    machines = [int(m) for m in a.machines.split(",")] if a.machines else None
    d = load.load(a.split, machines, a.start or None, a.end or None, raw=True)
    print(f"{a.split}: {len(d):,} first-pass tests, {d.equipmentid.nunique()} machines, "
          f"{d.testtime.min():%Y-%m-%d} .. {d.testtime.max():%Y-%m-%d}")
    for s in load.SIGNALS:
        check(d, s)
