"""Step c check: replay a sample through the feature engine and show what the features do.

1. real data: streams, warm-up, speed, feature ranges, how big the machine-wide move is
2. a +40 % tol step on ONE fixture from mid-window: departure / CUSUM must rise on that fixture only
3. the same step on EVERY fixture of that machine + device: the machine-move removal cancels it
   (the blind spot that step g has to cover)
"""
import argparse
import time

import numpy as np
import pandas as pd

import features as fx
import load

pd.set_option("display.width", 250)


def stream_view(meta, F, m, dv, sig, fix, t0):
    k = (meta.equipmentid == m) & (meta.deviceid == dv) & (meta.signal == sig)
    q = meta[k].assign(d_m=F[k.to_numpy(), fx.FEATS.index("d_m")], cusum=F[k.to_numpy(), fx.FEATS.index("cusum")])
    q["phase"] = np.where(q.testtime < t0, "before", "after")
    q["where"] = np.where(q.fixture == fix, f"fixture {fix}", "other fixtures")
    return q.groupby(["where", "phase"]).agg(units=("v", "size"), v=("v", "mean"), shift_pct=("shift_pct", "mean"),
                                             machine_move=("machine_move", "mean"), d_m=("d_m", "mean"),
                                             cusum_p95=("cusum", lambda x: x.quantile(.95))).round(2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--machines", default="9990675,9990771,20190405")
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-06-15")
    a = ap.parse_args()
    d = load.load("train", [int(x) for x in a.machines.split(",")], a.start, a.end)

    t0 = time.time()
    meta, F = fx.replay(d)
    dt = time.time() - t0
    n_in = int(d.v_p2.notna().sum() + d.v_p4.notna().sum())
    print(f"1. REAL DATA: {n_in:,} measured values -> {len(meta):,} feature rows "
          f"({n_in - len(meta):,} spent warming up) in {dt:.1f}s = {1e6 * dt / n_in:.0f} us per value")
    g = meta.groupby(["equipmentid", "deviceid", "signal"])
    print(f"   streams (machine x device x fixture x signal): "
          f"{meta.groupby(['equipmentid', 'deviceid', 'fixture', 'signal']).ngroups}, "
          f"in {g.ngroups} machine x device x signal sets")
    cu = F[:, fx.FEATS.index("cusum")]
    print(f"   healthy CUSUM: share of time > 10: {(cu > 10).mean():.3f}, > 20: {(cu > 20).mean():.3f}, "
          f"at cap: {(cu >= fx.CUSUM_CAP).mean():.3f}")
    print(f"   noise inflation infl per machine x device x signal (median): "
          f"{meta.groupby(['equipmentid', 'deviceid', 'signal']).infl.median().describe()[['min', '50%', 'max']].round(2).to_dict()}")
    print("   feature ranges (1% / 50% / 99%):")
    print(pd.DataFrame(F, columns=fx.FEATS).quantile([.01, .5, .99]).T.round(2).to_string())
    s = g.agg(units=("v", "size"), fixtures=("fixture", "nunique"), sigma=("sigma", "median"),
              move_p05=("machine_move", lambda x: x.quantile(.05)), move_p95=("machine_move", lambda x: x.quantile(.95)))
    print("\n   machine-wide move (% tol) per machine x device x signal, 5th..95th percentile:")
    print(s.sort_values("units", ascending=False).head(10).round(1).to_string())

    # pick the busiest P2 stream set with >= 5 fixtures for the injection checks
    best = s[s.fixtures >= 5].sort_values("units", ascending=False).index[0]
    m, dv, sig = best
    sel = (d.equipmentid == m) & (d.deviceid == dv)
    fix = int(d.loc[sel, "fixture"].value_counts().index[0])
    tmid = d.loc[sel, "testtime"].quantile(.5)
    tt = d.testtime.to_numpy()
    on = (d.equipmentid == m).to_numpy() & (d.deviceid == dv).to_numpy() & (tt >= np.datetime64(tmid))
    one = on & (d.fixture == fix).to_numpy()
    ds = d.sort_values(["testtime", "equipmentid", "fixture"], kind="stable")      # replay order
    pos = {k: np.asarray(ds.index) for k in ("idx",)}["idx"]
    one_o, all_o = one[pos], on[pos]

    print(f"\n2. +40 % tol STEP ON ONE FIXTURE: machine {m}, device {dv}, {sig.upper()}, fixture {fix}, from {tmid:%m-%d %H:%M}")
    meta1, F1 = fx.replay(d, inject=lambda s_, i: 40.0 if (s_ == sig and one_o[i]) else 0.0)
    print(stream_view(meta1, F1, m, dv, sig, fix, tmid).to_string())

    print(f"\n3. SAME STEP ON EVERY FIXTURE of machine {m} / {dv}")
    meta2, F2 = fx.replay(d, inject=lambda s_, i: 40.0 if (s_ == sig and all_o[i]) else 0.0)
    print(stream_view(meta2, F2, m, dv, sig, fix, tmid).to_string())
