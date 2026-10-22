"""Step d - labels.

Two kinds, because the real data has no record of when a fixture actually drifted:

1. reject_label   (real data) the run-up to a reject cluster: a row is positive when its stream
                  (machine, device, fixture, signal) has >= `cluster` out-of-band rejects among its next
                  `horizon` units, itself included. Port of Trace Sentinel's label_from_rejects.
2. drift episodes (injected) a known drift is added to REAL healthy data from a known time:
                  step (30-70 % tol at once) or ramp (6-28 % tol per hour, capped at 170), towards the
                  side the stream already leans to. Ranges are Trace Sentinel's simulator values.
                  scope "fixture" = one tester fixture, "machine" = every fixture of that machine and
                  device at once (step g). Injected values beyond +-100 become out-of-band rejects; a P2
                  reject means P4 is not measured on that unit (the tester stops). An episode ends
                  like the floor works today: after MAX_REJ drift rejects ("recalibrated"), or after
                  MAX_H hours. Label: positive while the drift has moved the unit >= MIN_OFFSET % tol.
"""
import numpy as np
import pandas as pd

from load import SIGNALS

STEP = (30.0, 70.0)        # % tol            "large": Trace Sentinel's simulator ranges
RAMP = (6.0, 28.0)         # % tol per hour
SMALL_STEP = (10.0, 30.0)  # "small": below the reference's range, to find the detection limit
SMALL_RAMP = (1.0, 6.0)
SIZES = {"large": (STEP, RAMP), "small": (SMALL_STEP, SMALL_RAMP)}
RAMP_CAP = 170.0
MAX_REJ = 5
MAX_H = 14.0
MIN_OFFSET = 10.0
WARM_UNITS = 360           # stream must have this many measured units before the start (3 x WARM)
QUIET_H = 24.0             # no real reject in the stream from QUIET_H before the start to MAX_H after
GAP_H = 24.0               # episodes on the same machine are at least this far apart


def reject_label(meta, horizon=200, cluster=3):
    """Vectorised label_from_rejects on features.replay() meta."""
    y = np.zeros(len(meta), dtype=np.int8)
    for _, idx in meta.groupby(["equipmentid", "deviceid", "fixture", "signal"], sort=False).indices.items():
        idx = idx[np.argsort(meta.testtime.values[idx], kind="stable")]
        cs = np.concatenate([[0], np.cumsum(meta.rej.values[idx].astype(int))])
        j = np.arange(len(idx))
        y[idx] = (cs[np.minimum(len(idx), j + horizon)] - cs[j]) >= cluster
    return y


def make_episodes(d, scope="fixture", per_machine_day=0.5, seed=0, signals=SIGNALS, sizes=("large",)):
    """Draw drift episodes on healthy, warm streams of a load.load() table; each episode takes one of
    `sizes` at random."""
    rng = np.random.default_rng(seed)
    days = (d.testtime.max() - d.testtime.min()).total_seconds() / 86400
    eps = []
    for m, dm in d.groupby("equipmentid"):
        busy = []                                             # start times already used on this machine
        for _ in range(int(rng.poisson(per_machine_day * days))):
            for _try in range(30):
                s = signals[rng.integers(len(signals))]
                dm_s = dm[dm[f"v_{s}"].notna() & dm[f"band_ok_{s}"]]
                if dm_s.empty:
                    continue
                dv = dm_s.deviceid.value_counts().index[0] if rng.random() < .5 else rng.choice(dm_s.deviceid.unique())
                g = dm_s[dm_s.deviceid == dv]
                fixes = g.fixture.value_counts()
                fixes = fixes[fixes >= 2 * WARM_UNITS]
                if fixes.empty:
                    continue
                fix = int(rng.choice(fixes.index)) if scope == "fixture" else -1
                st = g if scope == "machine" else g[g.fixture == fix]
                t0 = st.testtime.iloc[WARM_UNITS:].sample(1, random_state=int(rng.integers(1 << 31))).iloc[0]
                if any(abs((t0 - b).total_seconds()) < GAP_H * 3600 for b in busy):
                    continue
                win = (st.testtime >= t0 - pd.Timedelta(hours=QUIET_H)) & (st.testtime < t0 + pd.Timedelta(hours=MAX_H))
                if st.loc[win, f"kind_{s}"].eq("out_of_band").any() or (st.testtime > t0).sum() < 20:
                    continue
                lean = np.sign(np.nanmedian(st.loc[st.testtime < t0, f"v_{s}"].tail(300))) or 1.0
                mode = "step" if rng.random() < .5 else "ramp"
                size = sizes[rng.integers(len(sizes))]
                rate = float(rng.uniform(*SIZES[size][0 if mode == "step" else 1]))
                eps.append(dict(scope=scope, size=size, equipmentid=m, deviceid=dv, fixture=fix, signal=s, mode=mode,
                                rate=round(rate, 1), sign=lean, start=t0))
                busy.append(t0)
                break
    e = pd.DataFrame(eps)
    if len(e):
        e.insert(0, "ep_id", np.arange(len(e)))
    return e


def apply(d, eps):
    """Copy of d with the episodes added. New columns per signal: off_s (% tol injected), ep_s (episode
    id or -1). Episodes get end, n_aff, n_rej, first_rej, units_to_first_rej."""
    d = d.sort_values(["testtime", "equipmentid", "fixture"], kind="stable").reset_index(drop=True).copy()
    for s in SIGNALS:
        d[f"off_{s}"] = np.float32(0)
        d[f"ep_{s}"] = -1
    eps = eps.copy()
    info = []
    for e in eps.itertuples():
        s = e.signal
        m = (d.equipmentid == e.equipmentid) & (d.deviceid == e.deviceid) & (d.testtime >= e.start) \
            & (d.testtime < e.start + pd.Timedelta(hours=MAX_H)) & d[f"v_{s}"].notna()
        if e.fixture >= 0:
            m &= d.fixture == e.fixture
        idx = np.flatnonzero(m.to_numpy())
        hours = (d.testtime.values[idx] - np.datetime64(e.start)) / np.timedelta64(1, "h")
        off = np.full(len(idx), e.rate) if e.mode == "step" else np.minimum(RAMP_CAP, e.rate * hours)
        off = e.sign * off
        newv = d[f"v_{s}"].values[idx] + off
        rej = np.abs(newv) > 100
        cut = np.flatnonzero(np.cumsum(rej) >= MAX_REJ)       # recalibrated after the MAX_REJ-th reject
        keep = slice(None) if not len(cut) else slice(0, cut[0] + 1)
        idx, off, newv, rej = idx[keep], off[keep], newv[keep], rej[keep]
        d.loc[idx, f"v_{s}"] = newv.astype("float32")
        d.loc[idx, f"off_{s}"] = off.astype("float32")
        d.loc[idx, f"ep_{s}"] = e.ep_id
        r = idx[rej]
        d.loc[r, f"kind_{s}"] = "out_of_band"
        d.loc[r, f"fail_{s}"] = 1
        if s == "p2":                                         # tester stops after a P2 reject
            d.loc[r, "v_p4"] = np.nan
            d.loc[r, "why_p4"] = "after_p2_reject"
        info.append(dict(ep_id=e.ep_id, end=d.testtime.values[idx[-1]] if len(idx) else e.start,
                         n_aff=len(idx), n_rej=int(rej.sum()),
                         first_rej=d.testtime.values[r[0]] if len(r) else pd.NaT,
                         units_to_first_rej=int(np.argmax(rej)) if rej.any() else None))
    return d, eps.merge(pd.DataFrame(info), on="ep_id") if info else eps


def drift_label(meta, d_inj):
    """1 where the row belongs to an injected episode and the drift has moved it >= MIN_OFFSET."""
    long = pd.concat([d_inj[["unit_key", f"ep_{s}", f"off_{s}"]].rename(columns={f"ep_{s}": "ep", f"off_{s}": "off"})
                      .assign(signal=s) for s in SIGNALS])
    m = meta[["unit_key", "signal"]].merge(long, on=["unit_key", "signal"], how="left")
    ep = m.ep.fillna(-1).astype(int).to_numpy()
    y = ((ep >= 0) & (m.off.abs().to_numpy() >= MIN_OFFSET)).astype(np.int8)
    return y, ep
