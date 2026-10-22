"""Step c - streaming features per (CFT machine, device, tester fixture, signal).

Port of Trace Sentinel's sentinel/features.py (read-only reference) to the WP1 data. Same 15 features,
same maths; what changed:
  group key      (equipmentid, deviceid, fixture, signal) instead of (cal machine, fixture group, signal)
  machine move   median move of the OTHER warm fixtures of the same machine AND device (up to 9 peers
                 instead of 3). A machine runs several devices, and each device has its own centre.
  noise sigma    shared by the fixtures of one (machine, device, signal)
  reject         the tester's status (step b), out-of-band rejects only; |v| > 100 is not used
  no recal       there are no recalibration records, so no resets from them. Instead, a group that has
                 not tested for GAP_H hours (device changeover) restarts its averages and CUSUM at
                 its centre; the centre itself is kept.
  time           real testtime; the CUSUM onset is a timestamp.
  noise infl.    units are NOT independent here (lag-1 autocorrelation of the residual ~0.3; 50-unit
                 averages wander 0.4-4.7x more than independent units would). Fed with per-unit z,
                 the k = 0.5 CUSUM sat above 10 for a third of healthy time. So each machine x device
                 x signal learns `infl` = observed spread of a fixture's 50-unit residual average /
                 the spread independent units would give, and the CUSUM uses z / infl. Learnt only
                 while the fixture looks normal, like the centre, so a drift cannot inflate it away.
"""
from collections import deque
import math

import numpy as np
import pandas as pd

from load import SIGNALS

FEATS = ["d_s", "d_m", "d_l", "abs_d_s", "abs_d_m", "trend", "toward", "cusum", "headroom", "eta_log",
         "near_g", "near_diff", "rej_diff", "rej_w200", "warm"]

A = lambda span: 2.0 / (span + 1)
AS, AM, AL, AB, ASIG, AR = A(30), A(100), A(300), A(1500), A(1000), A(200)
A50, AINF = A(50), A(5000)
INFL0, INFL_MIN, INFL_MAX = 2.0, 1.0, 6.0
WARM = 120          # units before a group's centre is trusted
K_CUSUM = 0.5
CUSUM_CAP = 40.0
FREEZE_MAX = 600
GAP_H = 12.0        # idle hours after which a group restarts at its centre (changeover)
NS_H = 3600 * 10**9


class GroupState:
    __slots__ = ("n", "s", "m", "l", "base", "near", "rej", "cp", "cn", "w", "wsum", "warmbuf", "fz",
                 "cp0", "cn0", "last_t", "e50")

    def __init__(self):
        self.n = 0
        self.s = self.m = self.l = self.base = None
        self.near = self.rej = 0.0
        self.cp = self.cn = 0.0
        self.fz = 0                      # units the centre has been frozen for
        self.cp0 = self.cn0 = None       # time when each CUSUM side was last at zero
        self.w = deque(maxlen=200)       # reject flags, for the count rule
        self.wsum = 0
        self.warmbuf = []
        self.last_t = None
        self.e50 = 0.0                   # 50-unit average of the residual (for infl)

    def restart(self):
        """Averages and CUSUM back to the centre; keeps the centre and the reject window."""
        if self.base is not None:
            self.s = self.m = self.l = self.base
        self.cp = self.cn = 0.0
        self.fz = 0
        self.cp0 = self.cn0 = None

    def push_rej(self, isrej):
        if len(self.w) == self.w.maxlen:
            self.wsum -= self.w[0]
        self.w.append(isrej)
        self.wsum += isrej


class MachineSignal:
    """All fixtures of one machine for one device and signal, plus their shared noise scale."""

    def __init__(self):
        self.g = {}
        self.sigma = None
        self.v50 = None                  # mean square of the fixtures' e50 while normal

    def infl(self, sig):
        if self.v50 is None:
            return INFL0
        return max(INFL_MIN, min(INFL_MAX, math.sqrt(self.v50 / (sig * sig * A50 / (2 - A50)))))

    def common(self, F):
        """Machine-wide move at the three speeds: the median move of the other (warm) fixtures away
        from their centres. The median keeps one drifting neighbour from dragging the reference."""
        peers = [st for H, st in self.g.items() if H != F and st.n >= WARM and st.base is not None]
        if not peers:
            return 0.0, 0.0, 0.0, 0
        return (float(np.median([p.s - p.base for p in peers])), float(np.median([p.m - p.base for p in peers])),
                float(np.median([p.l - p.base for p in peers])), len(peers))


class FeatureEngine:
    def __init__(self, near_pct=80.0):
        self.near_pct = near_pct
        self.ms = {}                      # (machine, device, signal) -> MachineSignal

    def update(self, machine, device, fixture, signal, v, isrej, t):
        """Add one measured value (% of tolerance) at time t (ns). Returns (features, extras) or None
        while the group warms up."""
        key = (machine, device, signal)
        msig = self.ms.get(key)
        if msig is None:
            msig = self.ms[key] = MachineSignal()
        st = msig.g.get(fixture)
        if st is None:
            st = msig.g[fixture] = GroupState()
        if st.last_t is not None and t - st.last_t > GAP_H * NS_H:
            st.restart()
        st.last_t = t
        st.n += 1
        a = abs(v)
        # warm-up: learn the group's centre (robust: median of the first WARM values)
        if st.base is None:
            st.warmbuf.append(v)
            if len(st.warmbuf) >= WARM:
                wb = np.array(st.warmbuf)
                st.base = float(np.median(wb))
                st.s = st.m = st.l = st.base
                if msig.sigma is None:
                    msig.sigma = max(3.0, float(np.median(np.abs(wb - st.base))) * 1.4826)
                st.warmbuf = []
            st.push_rej(isrej)
            return None
        sig = msig.sigma or 20.0
        cs, cm0, cl, npeer = msig.common(fixture)
        r = v - st.base - cm0                               # residual after own centre and machine move
        # noise scale from all fixtures of the machine (clipped so gross outliers do not inflate it)
        msig.sigma = (1 - ASIG) * sig + ASIG * min(abs(r), 4 * sig) * 1.2533
        sig = max(msig.sigma, 1.0)
        rc = max(-4 * sig, min(4 * sig, r))
        vc = st.base + cm0 + rc                             # clipped value for the means
        st.e50 += A50 * (rc - st.e50)
        infl = msig.infl(sig)
        st.s += AS * (vc - st.s)
        st.m += AM * (vc - st.m)
        st.l += AL * (vc - st.l)
        st.near += AM * ((a >= self.near_pct and not isrej) - st.near)
        st.rej += AR * (isrej - st.rej)
        st.push_rej(isrej)
        cm = cm0                                  # common() excludes this fixture, so it is unchanged
        d_s = (st.s - st.base - cs) / sig
        d_m = (st.m - st.base - cm) / sig
        d_l = (st.l - st.base - cl) / sig
        z = max(-4.0, min(4.0, (v - st.base - cm) / (sig * infl)))
        st.cp = min(CUSUM_CAP, max(0.0, st.cp + z - K_CUSUM))
        st.cn = min(CUSUM_CAP, max(0.0, st.cn - z - K_CUSUM))
        # classic CUSUM change point: the shift began after the last time the statistic sat at zero
        if st.cp == 0.0:
            st.cp0 = t
        if st.cn == 0.0:
            st.cn0 = t
        # the centre keeps learning while the group looks normal; it freezes while the group looks
        # displaced, but a shift that outlasts FREEZE_MAX units becomes the new centre
        if abs(d_m) < 0.35 and max(st.cp, st.cn) < 4:
            st.base += AB * (vc - cm - st.base)
            st.fz = 0
            if st.n >= 2 * WARM:
                if msig.v50 is None:                 # start from the prior INFL0
                    msig.v50 = sig * sig * A50 / (2 - A50) * INFL0 ** 2
                msig.v50 += AINF * (st.e50 * st.e50 - msig.v50)
        else:
            st.fz += 1
            if st.fz > FREEZE_MAX:
                st.base += AB * 4 * (vc - cm - st.base)
                st.cp *= 0.98; st.cn *= 0.98
        trend = (d_s - d_l) / 135.0 * 100        # sigma per 100 units
        level = st.m                              # where the group sits now, % tol
        toward = 1.0 if (d_m * (1 if level >= 0 else -1)) > 0 else -1.0
        headroom = max(0.0, 100.0 - abs(level))
        slope_pct = abs(st.s - st.l) / 135.0      # % tol per unit
        moving_out = (st.s - st.l) * (1 if level >= 0 else -1) > 0
        eta = headroom / slope_pct if (moving_out and slope_pct > 1e-3) else 1e5
        near_o = rej_o = 0.0
        k = 0
        for H, o in msig.g.items():
            if H != fixture and o.base is not None:
                near_o += o.near; rej_o += o.rej; k += 1
        k = max(k, 1)
        # trend towards the NEARER limit. The reference uses trend * toward, which flips the sign for
        # a drift on the negative side (moving down towards -100 came out negative).
        f = [d_s, d_m, d_l, abs(d_s), abs(d_m), trend * (1.0 if level >= 0 else -1.0), toward, max(st.cp, st.cn), headroom / 100,
             math.log10(min(eta, 1e5) + 1), st.near, st.near - near_o / k, st.rej - rej_o / k, float(st.wsum),
             min(1.0, st.n / (3 * WARM))]
        extra = (st.cp0 if st.cp >= st.cn else st.cn0, level, None if eta >= 1e5 else eta, sig, st.base,
                 st.m - st.base - cm, cm, npeer, infl)
        return f, extra


META = ["unit_key", "testtime", "equipmentid", "deviceid", "fixture", "signal", "v", "rej", "band_ok",
        "onset", "level", "eta_units", "sigma", "base", "shift_pct", "machine_move", "n_peers", "infl"]


def replay(d, fe=None, signals=SIGNALS, near_pct=80.0, inject=None):
    """Run a load.load() table through the engine in test order. Returns (meta, F).
    inject(signal, i) -> offset in % tol added to v (drift injection, step d); None = real data."""
    fe = fe or FeatureEngine(near_pct)
    d = d.sort_values(["testtime", "equipmentid", "fixture"], kind="stable")
    t = d.testtime.to_numpy().astype("datetime64[ns]").astype("int64")     # parquet stores us
    cols = {k: d[k].to_numpy() for k in ("unit_key", "equipmentid", "deviceid", "fixture")}
    sv = {s: (d[f"v_{s}"].to_numpy(dtype=float), (d[f"kind_{s}"] == "out_of_band").to_numpy(),
              d[f"band_ok_{s}"].to_numpy()) for s in signals}
    rows, F = [], []
    for i in range(len(d)):
        for s in signals:
            v, rj, bo = sv[s][0][i], sv[s][1][i], sv[s][2][i]
            if v != v:          # NaN: not measured / aborted / placeholder
                continue
            if inject is not None:
                v = v + inject(s, i)
            out = fe.update(cols["equipmentid"][i], cols["deviceid"][i], cols["fixture"][i], s, v, bool(rj), t[i])
            if out is None:
                continue
            f, ex = out
            rows.append((cols["unit_key"][i], t[i], cols["equipmentid"][i], cols["deviceid"][i], cols["fixture"][i],
                         s, v, bool(rj), bool(bo)) + ex)
            F.append(f)
    meta = pd.DataFrame(rows, columns=META)
    meta["testtime"] = pd.to_datetime(meta.testtime)
    meta["onset"] = pd.to_datetime(meta.onset)
    return meta, (np.array(F, dtype=float) if F else np.zeros((0, len(FEATS))))
