"""
WP2 - Near-threshold detection, v3: unit flags + fixture drift monitor.

Two outputs for Tab 1:
  1. UNIT FLAGS   passed units in the risky tail of their own product x machine x fixture baseline
                  (percentile rule + Isolation Forest; from near_threshold_v2.py)
  2. FIXTURE DRIFT  a streaming EWMA + CUSUM monitor per machine+fixture+leak channel (P1/P3/P5), fed
                  with each passing unit's normal-score z of that channel. Status: normal / watch / investigate.

Built to run live later: the monitor keeps its state between tests (FixtureMonitor.update), so
"replay history" and "score new tests as they arrive" are the same code. Fit baselines once, save the
bundle, then score new data with --load-model.

Usage
  python near_threshold_v3.py data/explain --save-model wp2_model.joblib      # fit + replay + report
  python near_threshold_v3.py --train T --test NEW --load-model wp2_model.joblib   # score without refit
All paths can be folders, files or globs (see near_threshold_v2.py).

Design choices (best practice)
  * Baselines are fitted on train only and never see test. Never re-split.
  * Drift monitor uses PASSING first attempts only: failures are the thing we validate against.
  * Alert budget is not agreed with Sensata yet, so the report shows flag volume and lift at several
    cut-offs; pick one together with the engineers instead of guessing.
  * Validation = does an alert come BEFORE leak failures (lead time), compared with how often a
    fixture is under alert anyway. A detector that is always on has perfect "recall" and no value.
"""
import argparse
import os
import sys
from collections import defaultdict
import joblib
import numpy as np
import pandas as pd

import near_threshold_v2 as nt

CFG = nt.CFG

# ---- Drift monitor parameters (tune with engineers; defaults are textbook values) ---------------
EWMA_LAMBDA = 0.10      # smoothing: smaller = slower, catches smaller drifts
EWMA_L = 3.0            # control limit in EWMA standard deviations -> 'watch'
CUSUM_K = 0.5           # allowance: detect shifts of about 1 sigma
CUSUM_H = 5.0           # decision interval -> 'investigate'
Z_CLIP = 4.0            # winsorise z so one wild reading cannot trigger an alert alone
WARMUP = 30             # observations before a fixture can alert
COOLDOWN = 100          # observations before the same fixture can raise another alert
LEAD_WINDOW = 200       # validation: look this many tests back from a failure for an alert
EPISODE_GAP = 100       # a leak failure starts a new episode if none occurred in the previous N tests


class FixtureMonitor:
    """Streaming state for one machine+fixture. update(z) -> status after this observation."""

    def __init__(self):
        self.n, self.ewma, self.cusum, self.cool = 0, 0.0, 0.0, 0

    def update(self, z):
        z = float(np.clip(z, -Z_CLIP, Z_CLIP))
        self.n += 1
        self.ewma = EWMA_LAMBDA * z + (1 - EWMA_LAMBDA) * self.ewma
        self.cusum = max(0.0, self.cusum + z - CUSUM_K)          # one-sided: only upward leak drift matters
        if self.cool > 0:
            self.cool -= 1
        ewma_lim = EWMA_L * np.sqrt(EWMA_LAMBDA / (2 - EWMA_LAMBDA))
        status = "normal"
        if self.n >= WARMUP:
            if self.cusum > CUSUM_H:
                status = "investigate"
            elif self.ewma > ewma_lim:
                status = "watch"
        alert = None
        if status != "normal" and self.cool == 0:
            alert = status
            self.cool = COOLDOWN
            if status == "investigate":
                self.cusum = 0.0                                 # restart after an investigate alert
        return status, alert


def replay(scored, monitors):
    """Feed scored passing units, in time order, through one monitor PER machine+fixture+leak channel.
    A unit's drift_status is the worst status among its channels; drift_channel says which one."""
    c = CFG
    scored = scored.sort_values(c["time"]).copy()
    mach, fix = scored[c["machine"]].values, scored[c["fixture"]].values
    times = scored[c["time"]].values
    zs = {ch: scored[ch + "_z"].values for ch in nt.LEAK_CHANNELS}
    rank = {"no_baseline": -1, "normal": 0, "watch": 1, "investigate": 2}
    status, wchan, ew, cu, events = [], [], [], [], []
    for i in range(len(scored)):
        worst, wc, e_max, c_max = "no_baseline", "", np.nan, np.nan
        for ch, z in zs.items():
            zi = z[i]
            if np.isnan(zi):
                continue
            m = monitors[(mach[i], fix[i], ch)]
            s, alert = m.update(zi)
            if alert:
                events.append(dict(machine=mach[i], fixture=fix[i], channel=ch, time=times[i], level=alert))
            if rank[s] > rank[worst]:
                worst, wc = s, ch
            e_max = m.ewma if np.isnan(e_max) else max(e_max, m.ewma)
            c_max = m.cusum if np.isnan(c_max) else max(c_max, m.cusum)
        status.append(worst); wchan.append(wc); ew.append(e_max); cu.append(c_max)
    scored["drift_status"], scored["drift_channel"], scored["ewma"], scored["cusum"] = status, wchan, ew, cu
    return scored, pd.DataFrame(events, columns=["machine", "fixture", "channel", "time", "level"])


# ---- Validation -----------------------------------------------------------------------------------
def budget_table(scored, test_all):
    """Flag volume and lift at several cut-offs: the menu to agree an alert budget with engineers."""
    fn = nt.future_fail(test_all)
    v = scored.join(fn[["fail_next", "full"]]).query("full")
    base = v.fail_next.mean()
    rows = []
    for cut in (0.95, 0.98, 0.99, 0.995, 0.999):
        f = v.leak_pctl >= cut
        rows.append((f"any channel percentile >= {cut}", f.mean(), v.loc[f, "fail_next"].mean()))
    rows.append(("Isolation Forest flag", v.if_flag.mean(), v.loc[v.if_flag, "fail_next"].mean()))
    for s in ("watch", "investigate"):
        f = v.drift_status == s
        rows.append((f"fixture drift = {s}", f.mean(), v.loc[f, "fail_next"].mean()))
    t = pd.DataFrame(rows, columns=["rule", "share of passing units flagged", "leak-fail rate next tests"])
    t["lift vs base"] = (t["leak-fail rate next tests"] / base).round(1)
    print(f"\nALERT BUDGET MENU (base leak-failure rate over next {nt.LOOKAHEAD} tests: {base:.5f})")
    print(t.round(5).to_string(index=False))


def lead_time(test_all, alerts):
    """Do drift alerts precede leak-failure episodes, and is that better than being under alert anyway?"""
    c = CFG
    ycol = c["leak_failed"] if c["leak_failed"] in test_all else c["failed"]
    caught, leads, episodes, covered, total = 0, [], 0, 0, 0
    for (m, f), g in test_all.groupby([c["machine"], c["fixture"]]):
        g = g.sort_values(c["time"])
        n = len(g)
        t = g[c["time"]].values
        fail_pos = np.flatnonzero((g[ycol] == 1).values)
        a = alerts[(alerts.machine == m) & (alerts.fixture == f)]
        apos = np.sort(np.searchsorted(t, a.time.values)) if len(a) else np.array([], dtype=int)
        mark = np.zeros(n + 1, int)
        mark[apos[apos < n]] = 1
        cs = np.concatenate([[0], np.cumsum(mark)])
        # baseline: share of time points that have an alert in their previous LEAD_WINDOW tests
        idx = np.arange(LEAD_WINDOW, n)
        if len(idx):
            covered += int(((cs[idx] - cs[idx - LEAD_WINDOW]) > 0).sum()); total += len(idx)
        last = -10**9
        for p in fail_pos:
            if p - last > EPISODE_GAP:                              # first failure of a new episode
                episodes += 1
                prior = apos[(apos < p) & (apos >= p - LEAD_WINDOW)]
                if len(prior):
                    caught += 1; leads.append(p - prior.min())
            last = p
    print(f"\nLEAD TIME (leak-failure episodes in the test period, alert within previous {LEAD_WINDOW} tests)")
    if episodes == 0:
        print("  no leak-failure episodes in the test period; cannot evaluate lead time"); return
    cov = covered / total if total else float("nan")
    print(f"  episodes: {episodes};  preceded by a drift alert: {caught} ({caught / episodes:.0%})")
    print(f"  median lead: {np.median(leads):.0f} tests" if leads else "  median lead: n/a")
    print(f"  chance level (random time point has an alert in prior {LEAD_WINDOW} tests): {cov:.0%}")
    print("  -> only meaningful if the caught share is clearly above chance level")
    print(f"  alerts raised: {len(alerts)} ({(alerts.level == 'investigate').sum()} investigate)")


def report(scored, test_all, alerts):
    c = CFG
    ycol = c["leak_failed"] if c["leak_failed"] in test_all else c["failed"]
    if ycol != c["leak_failed"]:
        print(f"\n!! WARNING: no '{c['leak_failed']}' column, so validation uses ALL failures ('{ycol}'). "
              f"Build a leak-failure label from status_family first; results will be diluted.")
    nt.validate(test_all, scored)
    budget_table(scored, test_all)
    lead_time(test_all, alerts)
    if len(alerts):
        print("\nFixtures / leak channels with the most drift alerts:")
        print(alerts.groupby(["machine", "fixture", "channel"]).size().sort_values(ascending=False).head(8).to_string())


# ---- Main -------------------------------------------------------------------------------------------
def parse():
    ap = argparse.ArgumentParser(description="WP2 near-threshold + fixture drift")
    ap.add_argument("data", nargs="?", default=None, help="folder with train/ and test/ subfolders")
    ap.add_argument("--train", default=None); ap.add_argument("--test", default=None)
    ap.add_argument("--out", default="wp2_scored_test_units.csv")
    ap.add_argument("--alerts-out", default="wp2_drift_alerts.csv")
    ap.add_argument("--save-model", default=None, help="save baselines + monitor state (joblib)")
    ap.add_argument("--load-model", default=None, help="skip fitting; score --test with a saved model")
    a = ap.parse_args()
    folder = a.data or nt.DEFAULT_DATA_FOLDER
    train = a.train or os.path.join(folder, "train")
    test = a.test or os.path.join(folder, "test")
    return a, train, test


if __name__ == "__main__":
    a, train_path, test_path = parse()
    test = nt.prep(nt.read_path(test_path, "test"))
    if a.load_model:
        bundle = joblib.load(a.load_model)
        models, feats, monitors = bundle["models"], bundle["feats"], bundle["monitors"]
        print(f"loaded {len(models)} baselines and {len(monitors)} monitor states from {a.load_model}")
    else:
        train = nt.prep(nt.read_path(train_path, "train"))
        train = train[(train[CFG["failed"]] == 0) & (train[CFG["attempt"]] == 1)]      # baselines need only these
        feats = nt.feature_cols(train)
        print(f"{len(train):,} train / {len(test):,} test rows; {len(feats)} _dev features")
        models = nt.fit_groups(train, feats)
        print(f"{len(models)} group baselines fitted (min {nt.MIN_GROUP_N} normal units each)")
        monitors = defaultdict(FixtureMonitor)
    monitors = defaultdict(FixtureMonitor, monitors)
    scored = nt.score(test, models, feats)
    scored, alerts = replay(scored, monitors)
    report(scored, test, alerts)
    scored.to_csv(a.out, index=False)
    alerts.to_csv(a.alerts_out, index=False)
    print(f"\nSaved {a.out} and {a.alerts_out}")
    if a.save_model:
        joblib.dump(dict(models=models, feats=feats, monitors=dict(monitors)), a.save_model)
        print(f"Saved model bundle to {a.save_model}")