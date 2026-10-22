"""Step e - detectors and the alarm tracker.

Port of Trace Sentinel's sentinel/detectors.py (read-only reference). All detectors read the same
streaming features (features.py) and return one score per feature row.
  count-rule  the floor's practice: alarm when a fixture has 3 rejects in its last 200 units.
              Kept as the baseline to beat.
  cusum       CUSUM on the fixture's departure from its own centre, only when moving towards the
              limit. No training; two thresholds.
  trained     gradient-boosted trees (scikit-learn HistGradientBoosting) on the 15 features, trained
              on rows labelled by injected drift episodes.
The alarm tracker turns scores into warning / alarm / clear events with persistence, so one noisy
unit cannot raise an alarm and a score hovering at a threshold cannot flap.
The reference's z-rule (its replay demo's stand-in) is not ported: it is not a floor practice here.
"""
import numpy as np
import pandas as pd

from features import FEATS

FI = {f: i for i, f in enumerate(FEATS)}
KEY = ["equipmentid", "deviceid", "fixture", "signal"]


class CountRule:
    kind, needs_training = "count-rule", False

    def __init__(self, n_rejects=3):
        self.n = n_rejects
        self.thresholds = {"warn": None, "alarm": 1.0}

    def scores(self, F):
        return F[:, FI["rej_w200"]] / self.n


class Cusum:
    kind, needs_training = "cusum", False

    def __init__(self, warn=6.0, alarm=10.0):
        self.thresholds = {"warn": warn, "alarm": alarm}

    def scores(self, F):
        # only shifts that move the fixture towards its limit count
        return F[:, FI["cusum"]] * (F[:, FI["toward"]] > 0) * F[:, FI["warm"]]


class Trained:
    kind, needs_training = "trained", True

    def __init__(self, model=None, warn=0.5, alarm=0.8):
        self.model = model
        self.thresholds = {"warn": warn, "alarm": alarm}

    def fit(self, F, y, seed=0):
        from sklearn.ensemble import HistGradientBoostingClassifier
        pos = max(1, int(y.sum()))
        w = np.where(y == 1, min(20.0, (len(y) - pos) / pos), 1.0)
        self.model = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06, max_leaf_nodes=31,
                                                    l2_regularization=1.0, random_state=seed)
        self.model.fit(F, y, sample_weight=w)
        return self

    def scores(self, F):
        if len(F) == 0:
            return np.zeros(0)
        return self.model.predict_proba(F)[:, 1] * (F[:, FI["warm"]] >= 0.34)


class AlarmTracker:
    """Per key: ok -> warning -> alarm. Raise after `persist` consecutive scores over the threshold;
    clear after `clear_n` consecutive scores under 80 % of the warning threshold (alarm is latched)."""

    def __init__(self, warn, alarm, persist=3, clear_n=60):
        self.warn, self.alarm, self.persist, self.clear_n = warn, alarm, persist, clear_n
        self.st = {}

    def reset(self, key):
        self.st.pop(key, None)

    def level(self, key):
        return self.st.get(key, {"level": "ok"})["level"]

    def update(self, key, score):
        s = self.st.setdefault(key, {"level": "ok", "hi": 0, "wa": 0, "lo": 0})
        hi = score >= self.alarm
        wa = self.warn is not None and score >= self.warn
        s["hi"] = s["hi"] + 1 if hi else 0
        s["wa"] = s["wa"] + 1 if (wa or hi) else 0
        low_thr = (self.warn if self.warn is not None else self.alarm) * 0.8
        s["lo"] = s["lo"] + 1 if score < low_thr else 0
        prev = s["level"]
        if s["hi"] >= self.persist:
            s["level"] = "alarm"
        elif s["wa"] >= self.persist and prev == "ok":
            s["level"] = "warning"
        elif s["lo"] >= self.clear_n and prev != "ok":
            s["level"] = "ok"
        return None if s["level"] == prev else (prev, s["level"])


def alarm_events(meta, scores, thresholds, persist=3, clear_n=60):
    """Run the tracker over meta (time order). Returns level changes and each row's level."""
    tr = AlarmTracker(thresholds.get("warn"), thresholds["alarm"], persist=persist, clear_n=clear_n)
    keys = list(zip(*(meta[k].to_numpy() for k in KEY)))
    t = meta.testtime.to_numpy()
    ev, level = [], np.empty(len(meta), dtype=object)
    for i in range(len(meta)):
        ch = tr.update(keys[i], scores[i])
        if ch:
            ev.append((t[i], *keys[i], ch[0], ch[1], scores[i], i))
        level[i] = tr.level(keys[i])
    return pd.DataFrame(ev, columns=["testtime", *KEY, "from", "to", "score", "row"]), level


def _run(b):
    """Length of the run of True ending at each position."""
    pos = np.arange(len(b))
    return pos - np.maximum.accumulate(np.where(~b, pos, -1))


def key_groups(meta):
    """[(key, row indices in time order)] once per table; reused for every threshold."""
    g = meta.groupby(KEY, sort=False).indices
    t = meta.testtime.to_numpy()
    return [(k, idx[np.argsort(t[idx], kind="stable")]) for k, idx in g.items()]


def alarm_events_fast(meta, scores, thresholds, persist=3, clear_n=60, groups=None):
    """Same events as alarm_events, but jumps from event to event with run lengths instead of
    stepping through every row (tuning runs the tracker hundreds of times)."""
    warn, alarm = thresholds.get("warn"), thresholds["alarm"]
    groups = groups if groups is not None else key_groups(meta)
    t = meta.testtime.to_numpy()
    low = (warn if warn is not None else alarm) * 0.8
    ev = []
    for key, idx in groups:
        s = scores[idx]
        hi = s >= alarm
        wa = hi | (s >= warn) if warn is not None else hi
        if not wa.any():
            continue
        A = np.flatnonzero(_run(hi) >= persist)
        W = np.flatnonzero(_run(wa) >= persist)
        C = np.flatnonzero(_run(s < low) >= clear_n)
        nxt = lambda arr, p: arr[k] if (k := np.searchsorted(arr, p)) < len(arr) else np.inf
        p, level = 0, "ok"
        while True:
            if level == "ok":
                a, w = nxt(A, p), nxt(W, p)
                if a == np.inf and w == np.inf:
                    break
                i, new = (int(a), "alarm") if a <= w else (int(w), "warning")
            elif level == "warning":
                a, c = nxt(A, p), nxt(C, p)
                if a == np.inf and c == np.inf:
                    break
                i, new = (int(a), "alarm") if a <= c else (int(c), "ok")
            else:
                c = nxt(C, p)
                if c == np.inf:
                    break
                i, new = int(c), "ok"
            ev.append((t[idx[i]], *key, level, new, s[i], idx[i]))
            level, p = new, i + 1
    out = pd.DataFrame(ev, columns=["testtime", *KEY, "from", "to", "score", "row"])
    return out.sort_values("row", kind="stable").reset_index(drop=True)


def make(kind, **kw):
    return {"count-rule": CountRule, "cusum": Cusum, "trained": Trained}[kind](**kw)
