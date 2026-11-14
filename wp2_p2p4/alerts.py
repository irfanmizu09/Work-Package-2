"""Step g - the alert list: which machine / device / fixture / signal is drifting, and since when.

  python alerts.py --train     fit the trees on the fit slice (as evaluate.py), tune the thresholds on the
                               tune slice at --budget, save out/model_<tag>.joblib
  python alerts.py             score REAL data (no injected drift) of one split and time window with the
                               saved model; write out/alerts_<split>_<tag>.csv, one row per warning / alarm
  --detector cusum             no training needed; thresholds from out/eval_<tag>.json at --budget

Columns: raised, level, equipmentid, deviceid, fixture, signal, drift_start (CUSUM change point: the
shift began after it), shift_pct (% tol from the fixture's own centre, machine-wide move removed),
level_pct (where the fixture sits now), units_to_limit (at the current trend; empty when not moving
out), score, band_ok (False = device period whose limit differs from the snapshot, step b), cleared.
The features need ~120 units per fixture to warm up, so the window should start a day or more before
the period of interest; rows before --report-from are scored but not listed.
"""
import argparse
import json
import os

import joblib
import numpy as np
import pandas as pd

import detectors as dt
import evaluate as ev
import features as fx
import load

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)


def tag_of(machines, seed):
    return ("all" if machines is None else "m" + "-".join(map(str, machines))) + f"_s{seed}"


def train(machines=None, seed=0, budget=0.5, persist=3, workers=8):
    """Same fit / tune slices as evaluate.run; keeps the trees and the thresholds for one budget."""
    meta, F, eps, rj, tag = ev.build(machines, seed, workers)
    t_test = load.read("test", ["testtime"]).testtime.min()
    sl = np.select([meta.testtime < ev.T_TUNE, meta.testtime < t_test], ["fit", "tune"], "test")
    ok, y = meta.band_ok.to_numpy(), meta.y.to_numpy()
    fit = (sl == "fit") & ok & (meta.real_cluster.to_numpy() == 0)
    rng = np.random.default_rng(seed)
    neg = np.flatnonzero(fit & (y == 0))
    keep = np.sort(np.r_[np.flatnonzero(fit & (y == 1)), rng.choice(neg, min(ev.MAX_NEG, len(neg)), replace=False)])
    tree = dt.Trained().fit(F[keep], y[keep], seed=seed)
    tu = (sl == "tune") & ok
    sc = ev.Scorer(meta[tu], eps, rj, ev.real_clusters(meta))
    th = ev.tune(sc, tree.scores(F[tu]), budget, max(2.0, 2 * budget), persist)
    path = os.path.join(load.OUT, f"model_{tag}.joblib")
    joblib.dump({"kind": "trained", "feats": fx.FEATS, "model": tree.model, "thresholds": th, "persist": persist,
                 "budget": budget, "trained_on": tag, "fit_rows": int(len(keep)), "fit_to": str(ev.T_TUNE)}, path)
    print(f"trees fitted on {len(keep):,} rows; thresholds at {budget} false alarms/machine/day: {th}")
    print(f"saved {path}")
    return path


def detector(kind, tag, budget):
    if kind == "trained":
        art = joblib.load(os.path.join(load.OUT, f"model_{tag}.joblib"))
        return dt.Trained(art["model"], **art["thresholds"]), art["persist"]
    with open(os.path.join(load.OUT, f"eval_{tag}.json")) as f:
        row = next(r for r in json.load(f)["cusum"]["curve"] if r["budget"] == budget)
    return dt.Cusum(**row["thresholds"]), 3


def alerts(d, det, persist=3, report_from=None):
    """Alert table for a load.load() table (real data)."""
    meta, F = fx.replay(d)
    scores = det.scores(F)
    evs = dt.alarm_events_fast(meta, scores, det.thresholds, persist)
    clears = evs[evs["to"] == "ok"]
    raises = evs[evs["to"].isin(["warning", "alarm"])]
    r = meta.loc[raises.row.to_numpy()].reset_index(drop=True)
    out = pd.DataFrame({"raised": raises.testtime.to_numpy(), "level": raises["to"].to_numpy(),
                        **{k: r[k] for k in dt.KEY},
                        "drift_start": r.onset, "shift_pct": r.shift_pct.round(1), "level_pct": r.level.round(1),
                        "units_to_limit": r.eta_units.round(0), "score": raises.score.round(3).to_numpy(),
                        "band_ok": r.band_ok})
    # when the alert went back to ok (empty = still open at the end of the window)
    out["cleared"] = pd.NaT
    for key, g in clears.groupby(dt.KEY, sort=False):
        m = (out[dt.KEY] == pd.Series(key, index=dt.KEY)).all(axis=1).to_numpy()
        t = g.testtime.to_numpy()
        k = np.searchsorted(t, out.loc[m, "raised"].to_numpy())
        out.loc[m, "cleared"] = [t[i] if i < len(t) else pd.NaT for i in k]
    if report_from is not None:
        out = out[out.raised >= pd.Timestamp(report_from)]
    return out.sort_values("raised").reset_index(drop=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Step g: train and save the model, or list the alerts")
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--detector", default="trained", choices=["trained", "cusum"])
    ap.add_argument("--machines", default="9990675,9990771,20190405", help="'' = all machines")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--budget", type=float, default=0.5, help="false alarms per machine per day")
    ap.add_argument("--split", default="test")
    ap.add_argument("--start", default=None, help="window start (default: start of the split)")
    ap.add_argument("--end", default=None)
    ap.add_argument("--report-from", default=None, help="list alerts raised from this time (after warm-up)")
    a = ap.parse_args()
    machines = [int(m) for m in a.machines.split(",")] if a.machines else None
    tag = tag_of(machines, a.seed)
    if a.train:
        train(machines, a.seed, a.budget)
    else:
        det, persist = detector(a.detector, tag, a.budget)
        d = load.load(a.split, machines, a.start, a.end)
        al = alerts(d, det, persist, a.report_from)
        path = os.path.join(load.OUT, f"alerts_{a.split}_{a.detector}_{tag}.csv")
        al.to_csv(path, index=False)
        print(f"{len(d):,} first passes | {a.detector} thresholds {det.thresholds} | "
              f"{(al.level == 'alarm').sum()} alarms, {(al.level == 'warning').sum()} warnings")
        print(al.head(20).to_string(index=False))
        print(f"\nsaved {path}")
