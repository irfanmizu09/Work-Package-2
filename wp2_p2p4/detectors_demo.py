"""Step e check on a sample: train the trees on week 1, score week 2 with all detectors.

Thresholds are the reference's defaults here (count 3 rejects, CUSUM 6 / 10, trees 0.5 / 0.8);
tuning them to a false-alarm budget is step f. Row-level PR-AUC is quoted with its base rate.
Rows of a REAL reject cluster that no injected episode explains are left out of training (they may
be real drifts, so they are neither positive nor negative examples).
"""
import argparse

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

import detectors as dt
import features as fx
import labels as lb
import load

pd.set_option("display.width", 250)
GRACE_H, PRE_H = 3.0, 6.0          # an alarm counts for an episode until 3 h after it ends; 6 h before = not false


def episode_scores(meta, ev, eps, days, machines):
    raises = ev[ev["to"].isin(["warning", "alarm"])]
    covered = np.zeros(len(raises), bool)
    rows = []
    for e in eps.itertuples():
        k = (raises.equipmentid == e.equipmentid) & (raises.deviceid == e.deviceid) & (raises.signal == e.signal)
        if e.fixture >= 0:
            k &= raises.fixture == e.fixture
        w = k & (raises.testtime >= e.start) & (raises.testtime <= e.end + pd.Timedelta(hours=GRACE_H))
        covered |= (k & (raises.testtime >= e.start - pd.Timedelta(hours=PRE_H))
                    & (raises.testtime <= e.end + pd.Timedelta(hours=GRACE_H))).to_numpy()
        al = raises[w & (raises["to"] == "alarm")].testtime.min()
        an = raises[w].testtime.min()
        sk = (meta.equipmentid == e.equipmentid) & (meta.deviceid == e.deviceid) & (meta.signal == e.signal)
        if e.fixture >= 0:
            sk &= meta.fixture == e.fixture
        units = lambda tx: int((sk & (meta.testtime >= e.start) & (meta.testtime < tx)).sum()) if pd.notna(tx) else None
        rows.append(dict(detected=pd.notna(al), warned=pd.notna(an),
                         before_1st=pd.notna(al) and (pd.isna(e.first_rej) or al < e.first_rej),
                         has_rej=e.n_rej > 0, delay=units(al), warn_delay=units(an)))
    r = pd.DataFrame(rows)
    fa = raises[~covered]
    wr = r[r.has_rej]
    return {"episodes": len(r), "detected": f"{r.detected.mean():.0%}", "warned": f"{r.warned.mean():.0%}",
            "alarm before 1st reject": f"{wr.before_1st.mean():.0%} of {len(wr)}" if len(wr) else "-",
            "median delay (units)": r.delay.median(), "median warn delay": r.warn_delay.median(),
            "false alarms /machine/day": round((fa["to"] == "alarm").sum() / (machines * days), 2),
            "false warnings /machine/day": round((fa["to"] == "warning").sum() / (machines * days), 2)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--machines", default="9990675,9990771,20190405")
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-06-15")
    ap.add_argument("--cut", default="2026-06-08")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    d = load.load("train", [int(x) for x in a.machines.split(",")], a.start, a.end)
    eps = lb.make_episodes(d, "fixture", per_machine_day=1.0, seed=a.seed)
    d2, eps = lb.apply(d, eps)
    meta, F = fx.replay(d2)
    y, ep = lb.drift_label(meta, d2)
    real_cluster = (lb.reject_label(meta) == 1) & (ep < 0)

    cut = pd.Timestamp(a.cut)
    fit = (meta.testtime < cut).to_numpy() & ~real_cluster
    te = (meta.testtime >= cut).to_numpy()
    eps_te = eps[eps.start >= cut]
    print(f"{len(eps)} injected episodes ({len(eps) - len(eps_te)} in week 1 for training, {len(eps_te)} in week 2 for scoring)")
    print(f"training rows {fit.sum():,} (positives {int(y[fit].sum()):,}, base rate {y[fit].mean():.2%}; "
          f"{int(real_cluster.sum())} real-cluster rows left out)")
    tree = dt.Trained().fit(F[fit], y[fit])

    mt = meta[te].reset_index(drop=True)
    days = (mt.testtime.max() - mt.testtime.min()).total_seconds() / 86400
    machines = mt.equipmentid.nunique()
    print(f"\nWEEK 2: {te.sum():,} rows, positives {int(y[te].sum()):,} = base rate {y[te].mean():.2%}, "
          f"{machines} machines x {days:.1f} days")
    res, pr = {}, {}
    for det in (dt.CountRule(), dt.Cusum(), tree):
        sc = det.scores(F[te])
        pr[det.kind] = round(average_precision_score(y[te], sc), 3)
        ev, _ = dt.alarm_events(mt, sc, det.thresholds, persist=1 if det.kind == "count-rule" else 3)
        res[det.kind] = episode_scores(mt, ev, eps_te, days, machines)
    print(f"\nRow-level PR-AUC (base rate {y[te].mean():.4f} = a random score):", pr)
    print("\nEpisode-level, DEFAULT thresholds (not tuned yet):")
    print(pd.DataFrame(res).to_string())

    imp = pd.Series(np.abs(np.corrcoef(np.c_[F[fit], y[fit]].T)[-1, :-1]), index=fx.FEATS)
    print("\n|correlation| of each feature with the training label (rough view of what the trees can use):")
    print(imp.sort_values(ascending=False).round(2).to_string())
