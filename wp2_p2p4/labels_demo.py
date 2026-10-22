"""Step d check on a sample: reject-cluster labels on real data, then injected drift episodes."""
import argparse

import numpy as np
import pandas as pd

import features as fx
import labels as lb
import load

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--machines", default="9990675,9990771,20190405")
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-06-15")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    d = load.load("train", [int(x) for x in a.machines.split(",")], a.start, a.end)

    print("1. REJECT-CLUSTER LABEL on real data (>= 3 out-of-band rejects in the stream's next 200 units)")
    meta, F = fx.replay(d)
    y = lb.reject_label(meta)
    for s in load.SIGNALS:
        k = (meta.signal == s).to_numpy()
        print(f"   {s.upper()}: rows {k.sum():,}, out-of-band rejects {int(meta.rej[k].sum())}, "
              f"positive rows {int(y[k].sum()):,} = base rate {y[k].mean():.3%}")
    pos = meta[y == 1].groupby(["equipmentid", "deviceid", "fixture", "signal"]).size()
    print(f"   streams with any positive: {len(pos)} of {meta.groupby(['equipmentid', 'deviceid', 'fixture', 'signal']).ngroups}")
    if len(pos):
        print(pos.sort_values(ascending=False).head(8).rename("positive rows").to_string())

    print(f"\n2. INJECTED DRIFT on healthy real streams (one fixture each; seed {a.seed})")
    eps = lb.make_episodes(d, "fixture", seed=a.seed)
    d2, eps = lb.apply(d, eps)
    meta2, F2 = fx.replay(d2)
    y2, ep = lb.drift_label(meta2, d2)
    show = eps.assign(start=eps.start.dt.strftime("%m-%d %H:%M"),
                      hours=((eps.end - eps.start) / pd.Timedelta(hours=1)).round(1))
    print(show[["ep_id", "equipmentid", "deviceid", "fixture", "signal", "mode", "rate", "sign", "start",
                "hours", "n_aff", "n_rej", "units_to_first_rej"]].to_string(index=False))
    print(f"\n   {len(eps)} episodes: {int((eps.n_rej > 0).sum())} reached a reject, "
          f"{int((eps.n_rej >= lb.MAX_REJ).sum())} ended by '{lb.MAX_REJ} rejects -> recalibrate'; "
          f"{int(eps.n_rej.sum())} injected rejects")
    print(f"   positive rows {int(y2.sum()):,} of {len(y2):,} = base rate {y2.mean():.3%}")

    fd = pd.DataFrame(F2, columns=fx.FEATS)
    grp = np.where(y2 == 1, "drift (label 1)", np.where(ep >= 0, "episode, < 10 % moved", "healthy"))
    print("\n   do the features see it? median per row type:")
    print(fd.assign(row=grp).groupby("row")[["d_s", "d_m", "abs_d_m", "trend", "cusum", "headroom", "rej_w200"]]
          .median().round(2).to_string())
