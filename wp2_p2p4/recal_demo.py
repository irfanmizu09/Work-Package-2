"""Step 1 check - after a recalibration: keep the old centre, or re-learn it from the next 60 units?

No real recalibration records exist, so drift episodes are injected (labels.py) and each episode's end
is taken as the recalibration. Two worlds after the recal:
  A  same centre    the fixture returns exactly to where it was before the drift
  B  new centre     the fixture settles at a new centre, +-NEW_C % tol away (drawn per episode), for the
                    rest of the sample
Three engines: none (today: no recal input), keep (restart, old centre), relearn (centre from the next
60 measured units). Per recal, in the RECAL_H hours after it, on the recalibrated stream:
  unscored   units that got no score (relearn: the 60 learning units)
  |shift|    median |level - centre| in % tol over the scored units (how wrong the centre is)
  raises     warnings / alarms raised (all false: the fixture is healthy after the recal)
Detector: CUSUM with the thresholds tuned at 0.5 false alarms / machine / day (out/eval_all_s0.json).

    python recal_demo.py [--machine 9990675 --start 2026-05-01 --end 2026-06-01]
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

import detectors as dt
import features as fx
import labels as lb
import load

pd.set_option("display.width", 200)
RECAL_H = 24.0
NEW_C = (10.0, 25.0)


def thresholds():
    with open(os.path.join(load.OUT, "baseline", "eval_all_s0.json")) as f:
        return next(r for r in json.load(f)["cusum"]["curve"] if r["budget"] == 0.5)["thresholds"]


def worlds(machine, start, end, seed):
    d = load.load("train", [machine], start, end)
    eps = lb.make_episodes(d, "fixture", per_machine_day=1.0, seed=seed, sizes=("large", "small"))
    dA, eps = lb.apply(d, eps)
    rec = pd.DataFrame({"time": pd.to_datetime(eps.end) + pd.Timedelta(seconds=1), "equipmentid": eps.equipmentid,
                        "deviceid": eps.deviceid, "fixture": eps.fixture, "signal": eps.signal})
    rng = np.random.default_rng(seed + 1)
    dB = dA.copy()
    newc = []
    for e, r in zip(eps.itertuples(), rec.itertuples()):
        c = float(rng.choice([-1, 1]) * rng.uniform(*NEW_C))
        newc.append(c)
        m = (dB.equipmentid == e.equipmentid) & (dB.fixture == e.fixture) & (dB.testtime >= r.time)
        dB.loc[m, f"v_{e.signal}"] += c          # NaN stays NaN; the new centre holds to the end of the sample
    eps["new_centre"] = newc
    return dA, dB, eps, rec


def after(meta, ev, eps, rec):
    """Per recal: numbers over the RECAL_H hours after it on its stream."""
    out = []
    t = meta.testtime.to_numpy()
    for e, r in zip(eps.itertuples(), rec.itertuples()):
        k = (meta.equipmentid == e.equipmentid) & (meta.deviceid == e.deviceid) & (meta.fixture == e.fixture) \
            & (meta.signal == e.signal)
        w = k.to_numpy() & (t >= np.datetime64(r.time)) & (t < np.datetime64(r.time + pd.Timedelta(hours=RECAL_H)))
        x = meta[w]
        evw = ev[(ev.equipmentid == e.equipmentid) & (ev.deviceid == e.deviceid) & (ev.fixture == e.fixture)
                 & (ev.signal == e.signal) & (ev.testtime >= r.time)
                 & (ev.testtime < r.time + pd.Timedelta(hours=RECAL_H)) & ev["to"].isin(["warning", "alarm"])]
        out.append(dict(scored=len(x), shift=float(np.median(np.abs(x.level - x.base))) if len(x) else np.nan,
                        warn=int((evw["to"] == "warning").sum()), alarm=int((evw["to"] == "alarm").sum())))
    return pd.DataFrame(out)


def units_after(d, eps, rec):
    """Measured units of each recalibrated stream in the RECAL_H hours after its recal."""
    n = []
    for e, r in zip(eps.itertuples(), rec.itertuples()):
        m = (d.equipmentid == e.equipmentid) & (d.deviceid == e.deviceid) & (d.fixture == e.fixture) \
            & (d.testtime >= r.time) & (d.testtime < r.time + pd.Timedelta(hours=RECAL_H)) & d[f"v_{e.signal}"].notna()
        n.append(int(m.sum()))
    return np.array(n)


def main(machine, start, end, seed):
    th = thresholds()
    det = dt.Cusum(**th)
    dA, dB, eps, rec = worlds(machine, start, end, seed)
    print(f"machine {machine}, {start}..{end}: {len(dA):,} first passes, {len(eps)} injected episodes "
          f"= {len(eps)} recalibrations (episode end); CUSUM warn {th['warn']:.2f} alarm {th['alarm']:.2f}\n")
    rows, per = [], {}
    for world, d in (("A same centre", dA), ("B new centre", dB)):
        n_units = units_after(d, eps, rec)
        days = (d.testtime.max() - d.testtime.min()).total_seconds() / 86400
        for mode in ("none", "keep", "relearn"):
            fe = fx.FeatureEngine(recal_mode=mode if mode != "none" else "keep")
            meta, F = fx.replay(d, fe=fe, recals=None if mode == "none" else rec)
            resets = meta.recal.to_numpy() if "recal" in meta else None
            ev, _ = dt.alarm_events(meta, det.scores(F), det.thresholds, 3, resets=resets)
            a = after(meta, ev, eps, rec)
            a["unscored"] = n_units - a.scored
            per[(world, mode)] = a
            raises = ev[ev["to"].isin(["warning", "alarm"])]
            rows.append({"world": world, "engine": mode,
                         "unscored units (median)": float(a.unscored.median()),
                         "|shift| % tol (median)": round(float(a["shift"].median()), 1),
                         "recals with a raise": f"{int(((a.warn + a.alarm) > 0).sum())}/{len(a)}",
                         "warnings": int(a.warn.sum()), "alarms": int(a.alarm.sum()),
                         "all alarms / day": round(float((raises["to"] == "alarm").sum()) / days, 2),
                         "closed 'recalibrated'": int((ev.get("reason", pd.Series(dtype=str)) == "recalibrated").sum())})
    tab = pd.DataFrame(rows)
    print(f"In the {RECAL_H:.0f} h after each recalibration, on the recalibrated stream (false raises: it is healthy):")
    print(tab.to_string(index=False))
    b = per[("B new centre", "keep")].assign(new_centre=eps.new_centre.round(1))
    b["relearn_alarms"] = per[("B new centre", "relearn")].alarm
    print("\nWorld B per recal (keep vs relearn):")
    print(b[["new_centre", "scored", "shift", "warn", "alarm", "relearn_alarms"]].round(1).to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--machine", type=int, default=9990675)
    ap.add_argument("--start", default="2026-05-01")
    ap.add_argument("--end", default="2026-06-01")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    main(a.machine, a.start, a.end, a.seed)
