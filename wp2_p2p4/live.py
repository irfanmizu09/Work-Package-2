"""Live pipeline for the local app (app.py): raw tester rows in, row flags and drift alerts out.

Same steps as the offline scripts, one chunk of rows at a time, in time order:
  coerce     raw export -> clean types; unreadable values, missing keys and duplicates are flagged
  clean      load.prepare (step a): first passes only, v = 100 * error / tol, or the reason there is none
  features   features.FeatureEngine (step c), state kept between chunks
  score      saved trees (alerts.py --train) or CUSUM (step e)
  alarm      detectors.AlarmTracker per machine / device / fixture / signal (step e)
  recal      recalibration events (recal.py) queued with add_recals(); each is applied before the first
             unit tested at or after its time (as features.replay), or by apply_due(now): the fixture's
             streams restart and re-learn their centre, the tracker resets, open alerts close as
             "recalibrated"

Two kinds of output:
  flags      one row per problem with ONE unit: which columns, which values, what it means
  events     drift alerts for a FIXTURE (warning, alarm, back to normal), and machine-wide notes when
             several fixtures of one machine and device are in alert at the same time

Serial numbers stay in memory: they are shown on screen by the app and never written to disk here.
"""
from collections import deque
import glob
import json
import os

import joblib
import numpy as np
import pandas as pd

import detectors as dt
import features as fx
import load

RAW_COLUMNS = load.COLUMNS + ["attempt_no"]
NUMERIC = ["equipmentid", "fixture", "attempt_no", "failed"] + \
          [f"{s}{c}" for s in load.SIGNALS for c in ("press", "output", "error")]
KEY_COLS = ["testtime", "equipmentid", "deviceid", "fixture"]

# 99th percentile of healthy rows (step c sample, walkthrough report); a feature past it is a "why"
HEALTHY = {"abs_d_m": (0.48, "departure from its own normal", "σ"),
           "cusum": (7.2, "CUSUM (small shift that keeps going)", ""),
           "trend": (0.29, "still moving towards the limit", "σ / 100 units"),
           "near_g": (0.01, "share of recent units at 80-100 % of tolerance", ""),
           "rej_w200": (1, "rejects in the last 200 units", "")}
LOW = {"headroom": (0.53, "room left to the limit", ""),
       "eta_log": (2.8, "log10 units to the limit", "")}


# ------------------------------------------------------------------ detector
def models():
    """Saved models (alerts.py --train), newest first."""
    return sorted(glob.glob(os.path.join(load.OUT, "model_*.joblib")), key=os.path.getmtime, reverse=True)


def detector(path=None):
    """(detector, persist, description). path=None -> CUSUM with the tuned thresholds if an evaluation
    exists, else the defaults."""
    if path:
        art = joblib.load(path)
        return dt.Trained(art["model"], **art["thresholds"]), art["persist"], \
            f"trained trees ({art['trained_on']}, budget {art['budget']} false alarms / machine / day)"
    th = {"warn": 6.0, "alarm": 10.0}
    for p in sorted(glob.glob(os.path.join(load.OUT, "eval_*.json"))):
        with open(p) as f:
            row = next((r for r in json.load(f)["cusum"]["curve"] if r["budget"] == 0.5), None)
        if row:
            th = row["thresholds"]
            break
    return dt.Cusum(**th), 3, "CUSUM (no training)"


# ------------------------------------------------------------------ raw data
def missing_columns(raw):
    return [c for c in RAW_COLUMNS if c not in raw.columns]


FLAG_COLS = ["testtime", "serialno", "equipmentid", "deviceid", "fixture", "signal", "flag", "columns", "values",
             "effect", "kind"]


def _flag(rows, d, idx, flag, signal, columns, values, effect, kind):
    r = d.loc[idx]
    rows.append(pd.DataFrame({**{c: r[c].to_numpy() for c in FLAG_COLS[:5]}, "signal": signal, "flag": flag,
                              "columns": columns, "values": list(values), "effect": effect, "kind": kind}))


def _num(x):
    return "empty" if x != x else f"{x:g}"


def _flags(rows):
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=FLAG_COLS)


def coerce(raw, rows):
    """Clean types without dropping anything; every value that could not be read is flagged."""
    d = raw[RAW_COLUMNS].copy()
    d["testtime"] = pd.to_datetime(d.testtime, errors="coerce")
    for c in NUMERIC:
        x = pd.to_numeric(d[c], errors="coerce")
        bad = x.isna() & raw[c].notna()
        if bad.any():
            _flag(rows, d.assign(**{c: raw[c]}), d.index[bad], "unreadable value", "", c,
                  [f"{c} = {v!r}" for v in raw.loc[bad, c]], "treated as missing", "data")
        d[c] = x
    for s in load.SIGNALS:
        t = d[f"{s}_tested"]
        if t.dtype != bool:
            txt = t.astype("string").str.strip().str.lower()
            d[f"{s}_tested"] = txt.isin(["true", "1", "1.0", "yes", "y"]).to_numpy()
    d["deviceid"] = d.deviceid.astype("string").str.strip()
    d["status"] = d.status.astype("string")
    return d


# ------------------------------------------------------------------ engine
class Live:
    def __init__(self, det, persist=3, lim=None, report_from=None, group_min=3, keep_units=3000):
        self.det, self.persist = det, persist
        self.lim = load.limits() if lim is None else lim
        self.fe = fx.FeatureEngine()
        self.tr = dt.AlarmTracker(det.thresholds.get("warn"), det.thresholds["alarm"], persist)
        self.report_from = pd.Timestamp(report_from) if report_from is not None else None
        self.group_min, self.keep_units = group_min, keep_units
        self.hist = {}                # stream key -> recent units (time, serial, v, output, error, status)
        self.last = {}                # stream key -> (features, extras) of its latest reading
        self.open = {}                # stream key -> index in self.alerts of its open alert
        self.groups = set()           # (machine, device, signal) with a machine-wide note active
        self.seen = set()             # (serial, testtime, machine, fixture) for duplicates
        self.alerts, self.events = [], []
        self.n = {"rows": 0, "first_pass": 0, "readings": 0, "scored": 0}
        self.clock = None
        self.pending = []             # recal events not applied yet: (t ns, machine, device, fixture, signal, finding, note)
        self.recal_log = []           # recal events applied: what was reset and closed

    # ------------------------------------------------------------------ recalibration
    def add_recals(self, ev):
        """Queue recal events (recal.read() table, or the same columns). Each is applied before the first
        unit tested at or after its time, as features.replay does, or by apply_due(). An event older than
        the data already fed is applied at once (logged late; units in between kept the old state)."""
        if ev is None or len(ev) == 0:
            return []
        ev = ev.sort_values("time", kind="stable")
        t = pd.to_datetime(ev.time).to_numpy().astype("datetime64[ns]").astype("int64")
        dev = [None if (x is None or x != x or str(x).strip() in ("", "*")) else str(x).strip() for x in ev.deviceid]
        get = lambda c: ev[c].fillna("").astype(str).to_numpy() if c in ev else [""] * len(ev)
        new = list(zip(t, ev.equipmentid.astype(int), dev, ev.fixture.astype(int), ev.signal.astype(str),
                       get("finding"), get("note")))
        self.pending = sorted(self.pending + new, key=lambda r: r[0])
        if self.clock is not None:
            return self.apply_due(self.clock)
        return []

    def apply_due(self, now):
        """Apply every queued event with time <= now. Call it when no more rows older than `now` can
        arrive (the app's "Mark recalibrated" button, the shadow runner's watermark)."""
        now = pd.Timestamp(now).value
        out = []
        while self.pending and self.pending[0][0] <= now:
            r = self.pending.pop(0)
            out += self._recal_alerts(r, self.fe.recal(*r[1:5]))
        self.events.extend(out)
        return out

    def _recal_alerts(self, r, keys):
        """Tracker and alert side of one applied recal: reset each stream, close its open alert."""
        t, machine, dev, fixture, signal, finding, note = r
        ts = pd.Timestamp(int(t))
        quiet = self.report_from is not None and ts < self.report_from
        out, closed = [], []
        for k in keys:
            key = (int(k[0]), str(k[1]), int(k[2]), k[3])
            self.tr.reset(key)
            i = self.open.pop(key, None)
            if i is not None:
                a = self.alerts[i]
                a["cleared"], a["cleared_reason"] = ts, "recalibrated"
                closed.append(key)
                if not quiet:
                    out.append({"type": "cleared", "time": ts, "key": key, "alert": a, "reason": "recalibrated"})
            g = (key[0], key[1], key[3])
            if sum((o[0], o[1], o[3]) == g for o in self.open) < 2:
                self.groups.discard(g)
        self.recal_log.append({"time": ts, "equipmentid": machine, "deviceid": dev or "", "fixture": fixture,
                               "signal": signal, "finding": finding, "note": note, "streams_reset": len(keys),
                               "alerts_closed": len(closed)})
        if not quiet:
            out.insert(0, {"type": "recal", "time": ts, "key": (machine, dev, fixture, signal), "finding": finding,
                           "note": note, "streams": [tuple(k) for k in keys], "closed": closed})
        return out

    # one chunk of raw rows, any size, in time order after the previous chunk
    def feed(self, raw):
        rows = []
        if len(raw) == 0:
            return _flags(rows), []
        d = coerce(raw, rows)
        self.n["rows"] += len(d)
        nokey = d[KEY_COLS].isna().any(axis=1)
        if nokey.any():
            _flag(rows, d, d.index[nokey], "missing key", "", ", ".join(KEY_COLS),
                  [", ".join(c for c in KEY_COLS if pd.isna(d.at[i, c])) + " empty" for i in d.index[nokey]],
                  "row skipped", "data")
        d = d[~nokey]
        dup_key = list(zip(d.serialno, d.testtime, d.equipmentid, d.fixture))
        dup = np.array([k in self.seen or self.seen.add(k) for k in dup_key], bool)
        if dup.any():
            _flag(rows, d, d.index[dup], "duplicate row", "", "serialno, testtime, equipmentid, fixture",
                  ["same unit, time, machine and fixture as an earlier row"] * int(dup.sum()), "row skipped", "data")
        d = d[~dup]
        rep = d.attempt_no.ne(1)
        if rep.any():
            _flag(rows, d, d.index[rep], "repeat test", "", "attempt_no",
                  [f"attempt_no = {a:g}" if a == a else "attempt_no empty" for a in d.attempt_no[rep]],
                  "not used for drift (first passes only)", "data")
        d = d[~rep]
        self.n["first_pass"] += len(d)
        if len(d) == 0:
            return _flags(rows), []
        p = load.prepare(d, self.lim, raw=True)
        p["serialno"] = d.serialno
        self._row_flags(p, rows)
        return _flags(rows), self._drift(p)

    def _row_flags(self, p, rows):
        for s in load.SIGNALS:
            S, why, v = s.upper(), p[f"why_{s}"], p[f"v_{s}"]
            o, e = p[f"output_{s}"], p[f"error_{s}"]
            for w, text, cols, effect in (
                    ("placeholder", "placeholder value", f"{s}output, {s}error", "no reading"),
                    ("not_measured", "not measured", f"{s}output, {s}error", "no reading"),
                    ("aborted", "failed before this step", "failed, status", "no reading (value read without test pressure)"),
                    ("no_limits", "no tolerance known", "deviceid", "no reading (device not in the limits table)")):
                m = why.eq(w)
                if not m.any():
                    continue
                if w == "aborted":
                    vals = [f"failed = 1, status = {t!r}" for t in p.status[m]]
                elif w == "no_limits":
                    vals = [f"deviceid = {x}" for x in p.deviceid[m]]
                else:
                    vals = [f"{s}output = {_num(a)}, {s}error = {_num(b)}" for a, b in zip(o[m], e[m])]
                _flag(rows, p, p.index[m], text, S, cols, vals, effect, "data")
            rej = p[f"fail_{s}"].eq(1)
            if rej.any():
                vals = [f"status = {t!r}, v = {x:+.0f} % tol" if x == x else f"status = {t!r}, no reading"
                        for t, x in zip(p.status[rej], v[rej])]
                _flag(rows, p, p.index[rej], f"{S} output reject", S, f"status, {s}error", vals,
                      "unit rejected by the tester", "reading")
            near = v.abs().between(80, 100) & ~rej
            if near.any():
                _flag(rows, p, p.index[near], "near the limit", S, f"{s}error",
                      [f"v = {x:+.0f} % tol ({s}error = {b:g}, tol = {t:g})" for x, b, t in
                       zip(v[near], e[near], p[f"tol_{s}"][near])], "passed, but close to the limit", "reading")
            over = v.abs().gt(100) & ~rej
            if over.any():
                _flag(rows, p, p.index[over], "over the limit, other status", S, f"{s}error, status",
                      [f"v = {x:+.0f} % tol, status = {t!r}" for x, t in zip(v[over], p.status[over])],
                      "tester named another failure first", "reading")

    def _drift(self, p):
        p = p.sort_values(["testtime", "equipmentid", "fixture"], kind="stable")
        t = p.testtime.to_numpy().astype("datetime64[ns]").astype("int64")
        col = {k: p[k].to_numpy() for k in ("serialno", "equipmentid", "deviceid", "fixture", "status")}
        sv = {s: [p[c].to_numpy() for c in (f"v_{s}", f"kind_{s}", f"band_ok_{s}", f"output_{s}", f"error_{s}")]
              for s in load.SIGNALS}
        todo, F = [], []
        for i in range(len(p)):
            while self.pending and self.pending[0][0] <= t[i]:      # recal before the first unit at/after it
                r = self.pending.pop(0)
                todo.append(("recal", r, self.fe.recal(*r[1:5])))
            for s in load.SIGNALS:
                v, kind, bo, o, e = (a[i] for a in sv[s])
                if v != v:
                    continue
                key = (int(col["equipmentid"][i]), str(col["deviceid"][i]), int(col["fixture"][i]), s)
                self.n["readings"] += 1
                unit = (t[i], col["serialno"][i], float(v), o, e, col["status"][i])
                out = self.fe.update(key[0], key[1], key[2], s, float(v), kind == "out_of_band", t[i])
                todo.append((key, t[i], None if out is None else out[1], bool(bo), unit))
                if out is not None:
                    F.append(out[0])
        if not todo:
            return []
        F = np.array(F, dtype=float).reshape(-1, len(fx.FEATS))
        self.n["scored"] += len(F)
        scores, F = iter(self.det.scores(F)), iter(F)
        events = []
        for item in todo:
            if item[0] == "recal":
                events += self._recal_alerts(item[1], item[2])
                continue
            key, ti, ex, bo, unit = item
            # history in time order, so an alert lists only the units tested up to its own raise
            h = self.hist.get(key)
            if h is None:
                h = self.hist[key] = deque(maxlen=self.keep_units)
            h.append(unit)
            if ex is None:                       # still warming up
                continue
            f, sc = next(F), next(scores)
            self.last[key] = (f, ex, bo, sc)
            ch = self.tr.update(key, sc)
            if ch:
                ev = self._event(key, ti, ch, f, ex, bo, sc)
                if ev:
                    events.append(ev)
                g = self._group(key, ti)
                if g:
                    events.append(g)
        self.clock = pd.Timestamp(int(p.testtime.max().value))
        self.events.extend(events)
        return events

    def _event(self, key, ti, ch, f, ex, bo, sc):
        t = pd.Timestamp(int(ti))
        quiet = self.report_from is not None and t < self.report_from
        if ch[1] == "ok":
            i = self.open.pop(key, None)
            if i is not None:
                self.alerts[i]["cleared"] = t
            return None if quiet or i is None else {"type": "cleared", "time": t, "key": key, "alert": self.alerts[i]}
        onset, level, eta, sigma, base, shift, mm, npeer, infl = ex
        F = dict(zip(fx.FEATS, map(float, f)))
        onset = pd.Timestamp(int(onset)) if onset is not None else None
        units = [u for u in self.hist[key] if onset is None or u[0] >= onset.value]
        a = {"level": ch[1], "raised": t, "equipmentid": key[0], "deviceid": key[1], "fixture": key[2],
             "signal": key[3], "drift_start": onset, "shift_pct": shift, "level_pct": level, "machine_move": mm,
             "sigma": sigma, "units_to_limit": eta, "score": float(sc), "band_ok": bo, "features": F,
             "units": units, "cleared": None, "why": why(F), "peers": npeer}
        if quiet:
            if ch[1] in ("warning", "alarm"):
                self.open[key] = len(self.alerts)
                self.alerts.append({**a, "hidden": True})
            return None
        if key in self.open:                       # warning -> alarm: the warning row ends here
            self.alerts[self.open[key]]["escalated"] = t
        self.open[key] = len(self.alerts)
        self.alerts.append(a)
        return {"type": "alert", "time": t, "key": key, "alert": a, "escalated": ch[0] == "warning"}

    def _group(self, key, ti):
        """Machine-wide note: group_min or more fixtures of one machine, device and signal in alert."""
        g = (key[0], key[1], key[3])
        on = sorted(k[2] for k in self.open if (k[0], k[1], k[3]) == g)
        if len(on) >= self.group_min and g not in self.groups:
            self.groups.add(g)
            t = pd.Timestamp(int(ti))
            if self.report_from is not None and t < self.report_from:
                return None
            lv = [self.last[(g[0], g[1], fx_, g[2])][1][1] for fx_ in on]
            return {"type": "machine-wide", "time": t, "key": g, "fixtures": on, "levels": lv}
        if len(on) < 2:
            self.groups.discard(g)
        return None

    def open_alerts(self):
        rows = []
        for key, i in self.open.items():
            a = self.alerts[i]
            f, ex, bo, sc = self.last[key]
            rows.append({"equipmentid": key[0], "deviceid": key[1], "fixture": key[2], "signal": key[3].upper(),
                         "level": self.tr.level(key), "since": a["raised"], "level_pct": round(ex[1], 1),
                         "shift_pct": round(ex[5], 1), "units_to_limit": None if ex[2] is None else round(ex[2]),
                         "score": round(float(sc), 3)})
        return pd.DataFrame(rows)

    def alert_table(self, serials=False):
        cols = ["raised", "level", "equipmentid", "deviceid", "fixture", "signal", "drift_start", "shift_pct",
                "level_pct", "units_to_limit", "score", "band_ok", "cleared"]
        rows = [{**{c: a[c] for c in cols}, "cleared_by": a.get("cleared_reason") or ("back to normal" if a["cleared"] is not None else ""),
                 "units_since_start": len(a["units"]), "why": "; ".join(w[0] for w in a["why"])}
                for a in self.alerts if not a.get("hidden")]
        t = pd.DataFrame(rows, columns=cols + ["cleared_by", "units_since_start", "why"])
        for c in ("shift_pct", "level_pct", "units_to_limit", "score"):
            t[c] = pd.to_numeric(t[c]).round(3 if c == "score" else 1)
        t["signal"] = t.signal.str.upper()
        return t


def why(F):
    """Features outside the healthy range, in plain words: [(short, long)]."""
    out = []
    for k, (lim, text, unit) in HEALTHY.items():
        x = F[k]
        if x > lim:
            out.append((f"{k} {x:.2f}", f"{text}: {x:.2f}{(' ' + unit) if unit else ''} (healthy ≤ {lim})"))
    for k, (lim, text, unit) in LOW.items():
        if F[k] < lim:
            val = f"{F[k] * 100:.0f} %" if k == "headroom" else f"{10 ** F[k]:.0f} units"
            ref = f"{lim * 100:.0f} %" if k == "headroom" else f"{10 ** lim:.0f} units"
            out.append((f"{k} {F[k]:.2f}", f"{text}: {val} (healthy ≥ {ref})"))
    return out


def message(a):
    """Plain-language alert text: (title, lines)."""
    s = a["signal"].upper()
    title = (f"{'ALARM' if a['level'] == 'alarm' else 'Warning'}: machine {a['equipmentid']} · device "
             f"{a['deviceid']} · fixture {a['fixture']} · {s} is drifting")
    eta = a["units_to_limit"]
    lines = [f"Sits at {a['level_pct']:+.0f} % of tolerance (limit ±100); moved {a['shift_pct']:+.1f} % from its "
             f"own normal (σ {a['sigma']:.1f}); the machine as a whole moved {a['machine_move']:+.1f} %.",
             (f"About {eta:,.0f} units to the limit at the current trend." if eta is not None else
              "Not heading out at the moment (no units-to-limit)."),
             f"Drift began around {a['drift_start']:%d %b %H:%M}; {len(a['units'])} units tested on this fixture since."
             if a["drift_start"] is not None else f"{len(a['units'])} recent units on this fixture.",
             f"Model score {a['score']:.3f}."]
    if not a["band_ok"]:
        lines.append("Note: this device's limit differs from the limits table in this period (step b).")
    return title, lines


SIGNAL_COLUMNS = {s: f"{s}error (→ v = 100 × {s}error / tol), {s}output, {s}_tested, status, attempt_no; "
                     f"stream keyed by equipmentid, deviceid, fixture" for s in load.SIGNALS}
