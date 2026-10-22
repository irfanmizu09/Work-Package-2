"""Step f - evaluation like Trace Sentinel's train.py, on the WP1 split.

Slices (never re-split; tune is carved from the END of train by time; one first pass per serial, so
serials are disjoint - checked):
  fit   train, testtime <  T_TUNE        trees are trained here
  tune  train, testtime >= T_TUNE        thresholds are chosen here, per false-alarm budget
  test  WP1 test split                    scored once per budget, reported
The feature state streams through all three in time order (as it would live).

Truth: drift episodes injected into real healthy data (labels.py), half "large" (Trace Sentinel's
ranges) and half "small" (steps 10-30 % tol, ramps 1-6 % tol/h). Real reject clusters (>= 3
out-of-band rejects within 200 units of one fixture, not injected) are scored too, as the only
evidence from real faults.
Numbers per episode (as train.py): detected (alarm during the episode or GRACE_H after), alarm before
the first reject, delay in units of that fixture and in hours, avoidable rejects (drift rejects after
the alarm). Outside episodes and real clusters: false alarms per machine per day. A raise inside a
real cluster window is not counted as false, so the false-alarm figure is an upper bound only for
faults nobody recorded.
"""
import argparse
import json
import os
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

import detectors as dt
import features as fx
import labels as lb
import load

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
T_TUNE = pd.Timestamp("2026-07-02")
BUDGETS = (0.1, 0.25, 0.5, 1.0, 2.0)      # false alarms per machine per day offered as operating points
GRACE_H, PRE_H, CLUSTER_PRE_H = 3.0, 6.0, 24.0
MAX_NEG = 3_000_000                        # negatives kept for fitting the trees (all positives kept)


# ------------------------------------------------------------------ data
def _replay_one(d):
    return fx.replay(d)


def build(machines=None, seed=0, workers=8, per_machine_day=0.5, refresh=False):
    tag = ("all" if machines is None else "m" + "-".join(map(str, machines))) + f"_s{seed}"
    fp, ep_p, rj_p = (os.path.join(load.OUT, f"{n}_{tag}.{x}") for n, x in
                      (("feat", "parquet"), ("eps", "parquet"), ("injrej", "parquet")))
    if not refresh and all(os.path.exists(p) for p in (fp, ep_p, rj_p)):
        meta = pd.read_parquet(fp)
        F = meta[fx.FEATS].to_numpy()
        return meta.drop(columns=fx.FEATS), F, pd.read_parquet(ep_p), pd.read_parquet(rj_p), tag
    t0 = time.time()
    tr, te = load.load("train", machines), load.load("test", machines)
    assert tr.testtime.max() < te.testtime.min()
    fit_keys = set(tr.unit_key[tr.testtime < T_TUNE])
    assert not fit_keys & set(tr.unit_key[tr.testtime >= T_TUNE]) and not fit_keys & set(te.unit_key), "serial overlap"
    d = pd.concat([tr, te], ignore_index=True)
    print(f"  loaded {len(d):,} first passes ({time.time() - t0:.0f}s)", flush=True)
    eps = lb.make_episodes(d, "fixture", per_machine_day=per_machine_day, seed=seed, sizes=("large", "small"))
    d2, eps = lb.apply(d, eps)
    print(f"  injected {len(eps)} episodes ({time.time() - t0:.0f}s)", flush=True)
    parts = [g for _, g in d2.groupby("equipmentid")]
    with Pool(min(workers, len(parts))) as pool:
        res = pool.map(_replay_one, sorted(parts, key=len, reverse=True))
    meta = pd.concat([r[0] for r in res], ignore_index=True)
    F = np.vstack([r[1] for r in res])
    o = np.argsort(meta.testtime.to_numpy(), kind="stable")
    meta, F = meta.iloc[o].reset_index(drop=True), F[o]
    print(f"  replayed {len(meta):,} feature rows ({time.time() - t0:.0f}s)", flush=True)
    y, ep = lb.drift_label(meta, d2)
    meta["y"], meta["ep"] = y, ep
    meta["real_cluster"] = ((lb.reject_label(meta) == 1) & (ep < 0)).astype(np.int8)
    rj = pd.concat([d2.loc[(d2[f"ep_{s}"] >= 0) & (d2[f"kind_{s}"] == "out_of_band"), [f"ep_{s}", "testtime"]]
                    .rename(columns={f"ep_{s}": "ep_id"}) for s in load.SIGNALS])
    pd.concat([meta, pd.DataFrame(F, columns=fx.FEATS)], axis=1).to_parquet(fp)
    eps.to_parquet(ep_p)
    rj.to_parquet(rj_p)
    print(f"  cached {fp} ({time.time() - t0:.0f}s)", flush=True)
    return meta, F, eps, rj, tag


def real_clusters(meta, gap=200, n=3):
    """Real (not injected) reject clusters per fixture stream."""
    out = []
    for key, idx in dt.key_groups(meta):
        r = idx[(meta.rej.to_numpy()[idx]) & (meta.ep.to_numpy()[idx] < 0)]
        if len(r) < n:
            continue
        pos = np.searchsorted(idx, r) if np.all(np.diff(idx) > 0) else np.array([np.flatnonzero(idx == x)[0] for x in r])
        start = 0
        for j in range(1, len(r) + 1):
            if j == len(r) or pos[j] - pos[j - 1] > gap:
                if j - start >= n:
                    tt = meta.testtime.to_numpy()[r[start:j]]
                    out.append((*key, tt[0], tt[n - 1], tt[-1], j - start))
                start = j
    return pd.DataFrame(out, columns=[*dt.KEY, "first_t", "nth_t", "last_t", "n_rej"])


# ------------------------------------------------------------------ scoring
class Scorer:
    """Episode / cluster / false-alarm numbers for one slice."""

    def __init__(self, meta, eps, rj, clusters):
        self.meta = meta.reset_index(drop=True)
        self.groups = dt.key_groups(self.meta)
        t = self.meta.testtime.to_numpy()
        self.ktimes = {k: t[idx] for k, idx in self.groups}
        t0, t1 = self.meta.testtime.min(), self.meta.testtime.max()
        self.eps = eps[(eps.start >= t0) & (eps.start <= t1)].reset_index(drop=True)
        self.clusters = clusters[(clusters.first_t >= t0) & (clusters.first_t <= t1)].reset_index(drop=True)
        self.rejt = {k: np.sort(g.testtime.to_numpy()) for k, g in rj.groupby("ep_id")}
        self.machines = self.meta.equipmentid.nunique()
        self.days = max(1e-9, (t1 - t0).total_seconds() / 86400)

    def events(self, scores, thr, persist):
        return dt.alarm_events_fast(self.meta, scores, thr, persist, groups=self.groups)

    def score(self, ev, detail=False):
        raises = ev[ev["to"].isin(["warning", "alarm"])].reset_index(drop=True)
        rk = {k: (g.testtime.to_numpy(), g["to"].to_numpy(), g.index.to_numpy())
              for k, g in raises.groupby(dt.KEY, sort=False)}
        covered = np.zeros(len(raises), bool)
        H = lambda h: np.timedelta64(int(h * 3600), "s")
        rows = []
        for e in self.eps.itertuples():
            key = (e.equipmentid, e.deviceid, e.fixture, e.signal)
            ts, to, ix = rk.get(key, (np.array([], "datetime64[ns]"), np.array([]), np.array([], int)))
            s0, s1 = np.datetime64(e.start), np.datetime64(e.end) + H(GRACE_H)
            covered[ix[(ts >= s0 - H(PRE_H)) & (ts <= s1)]] = True
            w = (ts >= s0) & (ts <= s1)
            ta = ts[w & (to == "alarm")].min() if (w & (to == "alarm")).any() else None
            tw = ts[w].min() if w.any() else None
            kt = self.ktimes.get(key, np.array([], "datetime64[ns]"))
            units = lambda x: int(np.searchsorted(kt, x) - np.searchsorted(kt, s0)) if x is not None else np.nan
            hours = lambda x: (x - s0) / np.timedelta64(1, "h") if x is not None else np.nan
            rt = self.rejt.get(e.ep_id, np.array([], "datetime64[ns]"))
            rows.append(dict(ep_id=e.ep_id, size=e.size, mode=e.mode, n_rej=e.n_rej, detected=ta is not None,
                             warned=tw is not None,
                             before_1st=ta is not None and (len(rt) == 0 or ta < rt[0]),
                             delay_units=units(ta), delay_h=hours(ta), warn_delay_units=units(tw),
                             avoidable=int((rt > ta).sum()) if ta is not None else 0))
        crow = []
        for c in self.clusters.itertuples():
            key = (c.equipmentid, c.deviceid, c.fixture, c.signal)
            ts, to, ix = rk.get(key, (np.array([], "datetime64[ns]"), np.array([]), np.array([], int)))
            c0, c1 = np.datetime64(c.first_t) - H(CLUSTER_PRE_H), np.datetime64(c.last_t)
            covered[ix[(ts >= c0) & (ts <= c1 + H(GRACE_H))]] = True
            w = (ts >= c0) & (ts <= c1) & (to == "alarm")
            ta = ts[w].min() if w.any() else None
            crow.append(dict(detected=ta is not None, before_1st=ta is not None and ta < np.datetime64(c.first_t),
                             before_nth=ta is not None and ta < np.datetime64(c.nth_t)))
        r, cr = pd.DataFrame(rows), pd.DataFrame(crow)
        fa = raises[~covered]
        md = self.machines * self.days
        s = {"false_alarms_mday": round(float((fa["to"] == "alarm").sum()) / md, 3),
             "false_warnings_mday": round(float((fa["to"] == "warning").sum()) / md, 3)}
        for name, q in (("all", r), ("large", r[r["size"] == "large"] if len(r) else r),
                        ("small", r[r["size"] == "small"] if len(r) else r)):
            if not len(q):
                continue
            wr = q[q.n_rej > 0]
            s.update({f"{name}_episodes": len(q), f"{name}_detected_pct": round(100 * q.detected.mean(), 1),
                      f"{name}_before_1st_pct": round(100 * wr.before_1st.mean(), 1) if len(wr) else None,
                      f"{name}_median_delay_units": float(q.delay_units.median()) if q.detected.any() else None,
                      f"{name}_median_delay_h": round(float(q.delay_h.median()), 2) if q.detected.any() else None,
                      f"{name}_avoidable_pct": round(100 * q.avoidable.sum() / q.n_rej.sum(), 1) if q.n_rej.sum() else None})
        if len(cr):
            s.update({"real_clusters": len(cr), "real_detected_pct": round(100 * cr.detected.mean(), 1),
                      "real_before_1st_pct": round(100 * cr.before_1st.mean(), 1),
                      "real_before_3rd_pct": round(100 * cr.before_nth.mean(), 1)})
        return (s, r) if detail else s


def tune(sc, scores, budget, warn_budget, persist):
    """Lowest alarm threshold whose false alarms stay within budget on this slice; then the lowest
    warning threshold within its own budget (as train.py: false alarms fall as the threshold rises)."""
    pos = scores[scores > 0]
    if not len(pos):
        return {"warn": None, "alarm": 1.0}
    # quantile levels spaced geometrically towards 1: the trees put most of their range into the top
    # 1 % of scores, where an even spacing (as in train.py) left almost no candidate thresholds
    grid = np.unique(np.quantile(pos, 1 - np.geomspace(0.7, 5e-5, 96)))

    def lowest(ok):
        lo, hi = 0, len(grid) - 1
        if not ok(grid[hi]):
            return float(grid[hi])
        while lo < hi:
            mid = (lo + hi) // 2
            if ok(grid[mid]):
                hi = mid
            else:
                lo = mid + 1
        return float(grid[lo])

    a = lowest(lambda th: sc.score(sc.events(scores, {"warn": None, "alarm": th}, persist))["false_alarms_mday"] <= budget)
    w = lowest(lambda th: th >= a or sc.score(sc.events(scores, {"warn": min(th, a), "alarm": a}, persist))
               ["false_warnings_mday"] <= warn_budget)
    return {"warn": min(w, a), "alarm": a}


# ------------------------------------------------------------------ run
def run(machines=None, seed=0, workers=8, refresh=False, persist=3):
    t0 = time.time()
    meta, F, eps, rj, tag = build(machines, seed, workers, refresh=refresh)
    t_test = load.read("test", ["testtime"]).testtime.min()
    sl = np.select([meta.testtime < T_TUNE, meta.testtime < t_test], ["fit", "tune"], "test")
    ok = meta.band_ok.to_numpy()
    clusters = real_clusters(meta)
    print(f"\n[{tag}] {len(meta):,} feature rows, {meta.equipmentid.nunique()} machines; "
          f"{len(eps)} injected episodes; {len(clusters)} real reject clusters")
    for s in ("fit", "tune", "test"):
        k = (sl == s) & ok
        print(f"  {s:<5} rows {k.sum():>10,}  {meta.testtime[k].min():%m-%d}..{meta.testtime[k].max():%m-%d}  "
              f"episodes {int(((eps.start >= meta.testtime[k].min()) & (eps.start <= meta.testtime[k].max())).sum()):>4}  "
              f"positives {int(meta.y[k].sum()):>7,} = base rate {meta.y[k].mean():.3%}")

    fit = (sl == "fit") & ok & (meta.real_cluster.to_numpy() == 0)
    y = meta.y.to_numpy()
    rng = np.random.default_rng(seed)
    neg = np.flatnonzero(fit & (y == 0))
    keep = np.sort(np.r_[np.flatnonzero(fit & (y == 1)), rng.choice(neg, min(MAX_NEG, len(neg)), replace=False)])
    tree = dt.Trained().fit(F[keep], y[keep], seed=seed)
    print(f"  trees fitted on {len(keep):,} rows ({time.time() - t0:.0f}s)", flush=True)

    sc = {s: Scorer(meta[(sl == s) & ok], eps, rj, clusters) for s in ("tune", "test")}
    Fs = {s: F[(sl == s) & ok] for s in ("tune", "test")}
    ys = y[(sl == "test") & ok]
    results, curves = {}, []
    cr = dt.CountRule()
    s_te = cr.scores(Fs["test"])
    results["count-rule"] = {"thresholds": cr.thresholds, "pr_auc": round(average_precision_score(ys, s_te), 4),
                             "test": sc["test"].score(sc["test"].events(s_te, cr.thresholds, 1))}
    for det in (dt.Cusum(), tree):
        s_tu, s_te = det.scores(Fs["tune"]), det.scores(Fs["test"])
        results[det.kind] = {"pr_auc": round(average_precision_score(ys, s_te), 4), "curve": []}
        for b in BUDGETS:
            th = tune(sc["tune"], s_tu, b, max(2.0, 2 * b), persist)
            st = sc["test"].score(sc["test"].events(s_te, th, persist))
            results[det.kind]["curve"].append({"budget": b, "thresholds": th, **st})
            curves.append({"detector": det.kind, "budget": b, **{k: round(v, 3) for k, v in th.items() if v is not None}, **st})
            print(f"  {det.kind:<8} budget {b:<4} tuned {th}  ({time.time() - t0:.0f}s)", flush=True)
    results["base_rate_test"] = round(float(ys.mean()), 5)
    curves.insert(0, {"detector": "count-rule", "budget": None, **results["count-rule"]["test"]})
    tab = pd.DataFrame(curves)
    with open(os.path.join(load.OUT, f"eval_{tag}.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)
    tab.to_csv(os.path.join(load.OUT, f"eval_{tag}.csv"), index=False)
    report(tab, results)
    print(f"\ndone in {time.time() - t0:.0f}s; saved out/eval_{tag}.json and .csv")
    return tab, results


def report(tab, results):
    print(f"\nTEST SLICE, scored once. Row-level PR-AUC (base rate {results['base_rate_test']}): "
          + ", ".join(f"{k} {results[k]['pr_auc']}" for k in ("count-rule", "cusum", "trained")))
    cols = {"detector": "detector", "budget": "budget", "false_alarms_mday": "FA/m/day",
            "false_warnings_mday": "FW/m/day", "all_detected_pct": "det %", "all_before_1st_pct": "pre-rej %",
            "all_median_delay_units": "delay u", "all_median_delay_h": "delay h", "all_avoidable_pct": "avoid %",
            "large_detected_pct": "large det %", "small_detected_pct": "small det %",
            "small_before_1st_pct": "small pre-rej %", "real_clusters": "real cl.", "real_detected_pct": "real det %",
            "real_before_1st_pct": "real pre-1st %", "real_before_3rd_pct": "real pre-3rd %"}
    print(tab[[c for c in cols if c in tab]].rename(columns=cols).to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Step f: tune on the end of train, score the test split once")
    ap.add_argument("--machines", default="9990675,9990771,20190405", help="'' = all machines")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--refresh", action="store_true", help="rebuild the cached features")
    a = ap.parse_args()
    run([int(m) for m in a.machines.split(",")] if a.machines else None, a.seed, a.workers, a.refresh)
