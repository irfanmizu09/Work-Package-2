"""Step a - loader for P2 / P4 output early warning.

One row per FIRST-PASS test (attempt_no == 1). Per signal s in (p2, p4):
  v_s       signed error in % of tolerance: 100 * error / OutputTol. 100 = at the limit.
            NaN (never 0) when the signal was not measured or the reading is a placeholder.
  why_s     why v_s is NaN: ok / not_tested / not_measured / placeholder / no_limits
  fail_s    1 = the tester failed the unit with a P2 (P4) OUTPUT status
            (Error Percent, V_Out High/Low, Error Invalid, High Rail).
Plus status_cat: p2_output / p4_output / p2p4_pressure (stab, fill timeout, mensor, pressure tol:
pneumatic, not output, kept OUT of the output label) / other_fail / good.

Limits: there is no DPSCFTLimits file on disk, but WP1 used it to build
  p*_rel_dev = (output - target) / target   and   p*_dev_tol = (output - target) / tol,
so target and tol are solved back per device (exact: one value per device). If the real limits
file turns up, pass it to limits(path=...) and it is used instead.

Serial numbers never leave this module: they are replaced by unit_key, a keyed hash whose salt
lives in out/.salt (git-ignored).
"""
import hashlib
import os
import secrets

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
DATA_DIRS = [os.path.join(HERE, "..", "wp1_data", "wp1_data", "explain"),
             os.path.join(HERE, "..", "wp1_data", "explain"),
             r"C:\cft_project\students\wp2\wp1_data\explain"]
SIGNALS = ("p2", "p4")
KEYS = ["testtime", "equipmentid", "deviceid", "fixture"]
PLACEHOLDERS = [65535, 65534, 9999, 999, -999, -9999]

# Status families. Output patterns are checked first: "V_Out_HighP2: P2-Mensor Out of Tol" starts
# with the tester's output verdict, so it counts as an output failure.
OUTPUT_RE = {s: rf"{s}\s*error\s*(?:percent|invalid)|v_out_(?:high|low){s}\b|{s}\s*high\s*rail"
             for s in SIGNALS}
PRESSURE_RE = r"p[24]\s*-*\s*(?:stab|timeout|mensor)|p[24]\s*pressure\s*tol"


def data_dir():
    for d in DATA_DIRS:
        if os.path.isdir(os.path.join(d, "train")):
            return os.path.abspath(d)
    raise FileNotFoundError("explain/{train,test} not found in: " + "; ".join(DATA_DIRS))


def read(split, columns, filters=None):
    """Column subset of one split; `filters` are pyarrow row filters (pushed down, so cheap)."""
    return pd.read_parquet(os.path.join(data_dir(), split), columns=columns, filters=filters)


def limits(path=None, refresh=False):
    """Per device and signal: target, tol. Cached in out/limits.csv."""
    cache = os.path.join(OUT, "limits.csv")
    if path:
        return _limits_file(path)
    if os.path.exists(cache) and not refresh:
        return pd.read_csv(cache)
    rows = []
    for split in ("train", "test"):              # device metadata, not labels: both splits are fine
        for s in SIGNALS:
            d = read(split, ["deviceid", f"{s}output", f"{s}_rel_dev", f"{s}_dev_tol"],
                     filters=[(f"{s}_tested", "=", True)])
            o, rel, dt = d[f"{s}output"], d[f"{s}_rel_dev"], d[f"{s}_dev_tol"]
            ok = dt.abs().gt(0.05) & rel.notna() & o.ne(0) & o.abs().lt(60000)
            tgt = o[ok] / (1 + rel[ok])
            tol = (o[ok] - tgt) / dt[ok]
            rows.append(pd.DataFrame({"deviceid": d.deviceid[ok], "signal": s, "target": tgt, "tol": tol}))
    r = pd.concat(rows)
    g = r.groupby(["deviceid", "signal"]).agg(target=("target", "median"), tol=("tol", "median"),
                                              target_sd=("target", "std"), tol_sd=("tol", "std"),
                                              n=("tol", "size")).reset_index()
    g["target"], g["tol"] = g.target.round(4), g.tol.round(4)
    os.makedirs(OUT, exist_ok=True)
    g.to_csv(cache, index=False)
    return g


def _limits_file(path):
    raise NotImplementedError("send the DPSCFTLimits file and its format; the recovered table is used meanwhile")


def _salt():
    p = os.path.join(OUT, ".salt")
    if not os.path.exists(p):
        os.makedirs(OUT, exist_ok=True)
        with open(p, "w") as f:
            f.write(secrets.token_hex(16))
    with open(p) as f:
        return bytes.fromhex(f.read().strip())


def unit_keys(serials):
    salt = _salt()
    return [hashlib.blake2b(str(int(x)).encode(), key=salt, digest_size=8).hexdigest() for x in serials]


def status_cat(status):
    s = status.astype("string").str.lower().fillna("")
    cat = np.select([s.str.contains(OUTPUT_RE["p2"], regex=True),
                     s.str.contains(OUTPUT_RE["p4"], regex=True),
                     s.str.contains(PRESSURE_RE, regex=True),
                     s.eq("good")],
                    ["p2_output", "p4_output", "p2p4_pressure", "good"], "other_fail")
    return pd.Series(cat, index=status.index)


# Step b: device periods where the tester's limit did not match the limits snapshot
# (check_reject_rule.py on all of train). Headroom / units-to-limit are wrong there.
BAND_EXCEPTIONS = [  # device, signal, from, to (None = open)
    ("31MPP3-2", "p2", None, None),                # rejects at 64-119 % of snapshot tol, high side
    ("85MPP36-01", "p2", None, "2026-06-08"),      # limit ~80 % of snapshot tol until the week of Jun 8
]


def band_ok(device, time, s):
    ok = np.ones(len(device), bool)
    for dv, sig, t0, t1 in BAND_EXCEPTIONS:
        if sig != s:
            continue
        m = (device == dv).to_numpy().copy()
        if t0:
            m &= (time >= pd.Timestamp(t0)).to_numpy()
        if t1:
            m &= (time < pd.Timestamp(t1)).to_numpy()
        ok &= ~m
    return ok


def fail_step(status):
    """Test step (P1..P7) a failure status names, NaN when it names none (prior op, serial code,
    master temperature, atmos...)."""
    s = status.astype("string").str.lower().fillna("")
    return pd.to_numeric(s.str.extract(r"p\s*(\d)", expand=False), errors="coerce").astype("float64")


def load(split, machines=None, start=None, end=None, lim=None, raw=False):
    """First-pass P2/P4 table for one split, optionally limited to machines and a time window.
    raw=True also keeps status text, tolerance, target, output and error (for checks, not for features)."""
    f = [("attempt_no", "=", 1)]
    if machines is not None:
        f.append(("equipmentid", "in", list(machines)))
    if start is not None:
        f.append(("testtime", ">=", pd.Timestamp(start)))
    if end is not None:
        f.append(("testtime", "<", pd.Timestamp(end)))
    cols = ["serialno", *KEYS, "failed", "status"] + \
           [f"{s}{c}" for s in SIGNALS for c in ("press", "output", "error", "_tested")]
    d = read(split, cols, filters=f)
    lim = limits() if lim is None else lim
    out = d[KEYS + ["failed"]].copy()
    out.insert(0, "unit_key", unit_keys(d.serialno))
    out["status_cat"] = status_cat(d.status)
    step = fail_step(d.status)
    for s in SIGNALS:
        tol = d.deviceid.map(lim[lim.signal == s].set_index("deviceid").tol)
        o, e = d[f"{s}output"], d[f"{s}error"]
        # a unit that failed before (or without naming) this step still carries a P2/P4 value, but it
        # is a reading without test pressure (~660 counts vs ~3250 on 62MPP03-04), not a measurement
        aborted = (d.failed == 1) & (out.status_cat != f"{s}_output") & ~(step > int(s[1]))
        why = np.select([~d[f"{s}_tested"].astype(bool),
                         o.eq(0) & e.eq(0),
                         o.isin(PLACEHOLDERS) | e.isin(PLACEHOLDERS) | o.eq(0) | o.isna() | e.isna(),
                         aborted,
                         ~(tol > 0)],
                        ["not_tested", "not_measured", "placeholder", "aborted", "no_limits"], "ok")
        out[f"press_{s}"] = d[f"{s}press"].astype("float32")
        out[f"v_{s}"] = np.where(why == "ok", 100 * e / tol, np.nan).astype("float32")
        out[f"why_{s}"] = why
        out[f"fail_{s}"] = (out.status_cat == f"{s}_output").astype("int8")
        # step b: the status is the reject truth; split it by whether the reject has a reading
        out[f"kind_{s}"] = np.select([out[f"fail_{s}"].eq(0), out[f"v_{s}"].notna()],
                                     ["", "out_of_band"], "no_reading")
        out[f"band_ok_{s}"] = band_ok(d.deviceid, d.testtime, s)
        if raw:
            out[f"tol_{s}"] = tol
            out[f"target_{s}"] = d.deviceid.map(lim[lim.signal == s].set_index("deviceid").target)
            out[f"output_{s}"], out[f"error_{s}"] = o, e
    if raw:
        out["status"] = d.status
    return out.sort_values(KEYS[:2] + ["fixture"], kind="stable").reset_index(drop=True)


def summary(d):
    """Plain-language check of a loaded table (no serials)."""
    print(f"{len(d):,} first-pass tests | {d.testtime.min()} .. {d.testtime.max()} | "
          f"machines {d.equipmentid.nunique()} | devices {d.deviceid.nunique()} | fixtures {d.fixture.nunique()}")
    print(f"failed (any reason): {d.failed.mean():.2%}")
    print("status family:", d.status_cat.value_counts().to_dict())
    for s in SIGNALS:
        v = d[f"v_{s}"]
        print(f"\n{s.upper()}: why v is (not) set -> {d[f'why_{s}'].value_counts().to_dict()}")
        if v.notna().any():
            q = v.quantile([.001, .01, .05, .25, .5, .75, .95, .99, .999]).round(1)
            print(f"  v_{s} (% of tol) quantiles: {q.to_dict()}")
            print(f"  |v| > 100: {(v.abs() > 100).mean():.3%} of measured | status {s}_output: "
                  f"{d[f'fail_{s}'].mean():.3%} of all rows")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Load first-pass P2/P4 data (sample by default)")
    ap.add_argument("--split", default="train")
    ap.add_argument("--machines", default="9990675,9990771,20190405")
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-06-15")
    a = ap.parse_args()
    lim = limits()
    for s in SIGNALS:
        l = lim[lim.signal == s]
        print(f"limits {s.upper()}: {len(l)} devices, max sd target {l.target_sd.max():.2g}, tol {l.tol_sd.max():.2g}")
    d = load(a.split, [int(m) for m in a.machines.split(",")] if a.machines else None, a.start, a.end, lim)
    summary(d)
    print("\nper machine (rows, P2 measured, P4 measured, P2 / P4 output fails):")
    print(d.groupby("equipmentid").agg(rows=("v_p2", "size"), p2=("v_p2", "count"), p4=("v_p4", "count"),
                                       fail_p2=("fail_p2", "sum"), fail_p4=("fail_p4", "sum")).to_string())
