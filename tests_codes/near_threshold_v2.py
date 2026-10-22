"""
WP2 - Near-threshold detection, v2 (built against DATASET.md / USING_THE_DATA.md).

What it does
  Flags units that PASSED but sit in the risky tail of their own product x machine x fixture
  LeakRate distribution, or look multivariate-odd to an Isolation Forest fitted on that same group.

Which data
  data/explain/{train,test}  -- same split as data/predict but with the readings. WP2 needs the
  readings, so this is a post-test SCREENING model (it cannot predict before a test happens).
  Say "explain feature set" in the writeup. Never re-split: baselines are fitted on train only.

Usage  (a path can be a folder, a single .parquet/.csv file, or a glob like "data/explain/train/*.parquet")
  python near_threshold_v2.py data/explain                       # folder holding train/ and test/
  python near_threshold_v2.py --train D:\\cft\\train --test D:\\cft\\test
  python near_threshold_v2.py --train train.parquet --test test.parquet --out my_results.csv
  (or set DEFAULT_DATA_FOLDER below and just run: python near_threshold_v2.py)
  Edit the CFG block once you check the real column names.
"""
import argparse
import difflib
import glob
import os
import re
import sys
import time
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

# ---- Where the data is (used when no path is given on the command line) -------------------------
DEFAULT_DATA_FOLDER = r"C:\cft_project\students\wp2\wp1_data\explain"     # must contain train/ and test/ subfolders

# ---- EDIT ME after you see the real schema -----------------------------------------------------
CFG = dict(
    serial="serialno", time="testtime", product="deviceid", machine="equipmentid", fixture="fixture",
    failed="failed",              # 1 = unit failed this test
    status="status",              # text verdict; used to BUILD the leak-failure label if leak_failed is absent
    leak_failed="leak_failed",    # 1 = failed for a LEAK reason (built from `status` when the column is missing)
    attempt="attempt_no",         # 1 = first test, 2+ = retest
    recent_fail="fx_recent_fail", # causal failure rate of previous 50 units on machine+fixture
)
LEAK_CHANNELS = ["p1leakrate", "p3leakrate", "p5leakrate"]   # one per pneumatic port test; higher = leakier = worse
LEAK_STATUS_REGEX = "leak"      # status strings matching this (case-insensitive) count as leak failures.
                                # CHECK the table printed at start-up and widen the regex if needed.
                                # Possible wider version (ask the process engineer first): P1/P3/P5 fill time-outs
                                # and stability failures may also be leak-related:
                                #   LEAK_STATUS_REGEX = r"leak|P[135]\s*--\s*(TimeOut|Stab)"
# Constant-within-product columns listed in DATASET.md section 4: carry no per-unit information
CONSTANT_COLS = {"tempoutput", "tempoutputmaster", "atmospress2", "scidc23",
                 "atmosoutput2", "atmoserror2", "cycletime", "atmospress"}
MIN_GROUP_N = 500       # need this many normal training units to trust a baseline
PCTL = 0.99             # "risky top percentile"
IF_Q = 0.99             # Isolation Forest cut-off taken from the group's own training scores
IF_MAX_TRAIN = 5_000     # each tree sees only 256 samples anyway, so more rows just costs time
LOOKAHEAD = 50          # validation window: next N tests on the same machine+fixture
SENTINELS = {65535, 65534, 9999, 999, -999, -9999}


# ---- Load ---------------------------------------------------------------------------------------
def find_files(path):
    """`path` may be a single .parquet/.csv file, a folder (searched recursively), or a glob pattern."""
    path = os.path.expanduser(path)
    if os.path.isfile(path):
        files = [path]
    elif os.path.isdir(path):
        files = glob.glob(os.path.join(path, "**", "*"), recursive=True)
    else:
        files = glob.glob(path, recursive=True)
    return sorted(f for f in files if os.path.isfile(f) and f.lower().endswith((".parquet", ".csv")))


def wanted_columns(names):
    c = CFG
    keep = {c[k] for k in ("serial", "time", "product", "machine", "fixture", "failed", "status",
                           "leak_failed", "attempt", "recent_fail")}
    for ch in LEAK_CHANNELS:
        keep |= {ch, ch + "_missing"}
    return [n for n in names if n in keep or n.endswith("_dev")]


def read_one(f):
    must = [CFG[k] for k in ("time", "product", "machine", "fixture", "failed", "attempt")] + LEAK_CHANNELS
    if f.lower().endswith(".parquet"):
        import pyarrow.parquet as pq
        names = pq.ParquetFile(f).schema.names
        # if a required name is wrong, read everything so check_columns() can show the full column list
        df = pd.read_parquet(f, columns=wanted_columns(names) if all(m in names for m in must) else None)
    else:
        df = pd.read_csv(f)
        if all(m in df.columns for m in must):
            df = df[wanted_columns(df.columns)]
    f64 = df.select_dtypes("float64").columns
    df[f64] = df[f64].astype("float32")                           # halves memory on 5M rows
    return df


def read_path(path, label):
    files = find_files(path)
    if not files:
        sys.exit(f"No .parquet or .csv files found for {label}: {path}")
    print(f"{label}: {len(files)} file(s) from {path}")
    return pd.concat([read_one(f) for f in files], ignore_index=True)


def parse_args():
    ap = argparse.ArgumentParser(description="WP2 near-threshold detection")
    ap.add_argument("data", nargs="?", default=None,
                    help="folder that contains train/ and test/ subfolders (e.g. data/explain)")
    ap.add_argument("--train", default=None, help="train data: a file, folder or glob (overrides DATA)")
    ap.add_argument("--test", default=None, help="test data: a file, folder or glob (overrides DATA)")
    ap.add_argument("--out", default="wp2_scored_test_units.csv", help="where to save the scored test units")
    a = ap.parse_args()
    if a.train and a.test:
        return a.train, a.test, a.out
    folder = a.data or DEFAULT_DATA_FOLDER
    return os.path.join(folder, "train"), os.path.join(folder, "test"), a.out


def check_columns(df):
    """Stop with a readable message (and suggestions) if a column named in CFG is not in the data."""
    wants = {f"CFG['{k}']": CFG[k] for k in ("time", "product", "machine", "fixture", "failed", "attempt")}
    wants.update({f"LEAK_CHANNELS[{i}]": ch for i, ch in enumerate(LEAK_CHANNELS)})
    missing = {k: v for k, v in wants.items() if v not in df.columns}
    if not missing:
        return
    cols = list(df.columns)
    print("\nCOLUMN NAMES DO NOT MATCH THE DATA. Fix the CFG block / LEAK_CHANNELS near the top of near_threshold_v2.py.")
    for k, v in missing.items():
        near = difflib.get_close_matches(v, cols, n=5, cutoff=0.4)
        print(f"  {k} = '{v}' not found.  Possible matches: {near or 'none'}")
    print(f"\nAll {len(cols)} columns in the file:\n  " + ", ".join(cols))
    sys.exit(1)


_PRINTED = False


def prep(df):
    global _PRINTED
    c = CFG
    check_columns(df)
    df = df.copy()
    df[c["time"]] = pd.to_datetime(df[c["time"]])
    for ch in LEAK_CHANNELS:                                         # sentinels are FLAGGED, not removed
        x = df[ch].astype("float32")
        bad = x.isin(SENTINELS)
        if ch + "_missing" in df:
            bad |= df[ch + "_missing"].fillna(True).astype(bool)
        df[ch + "_clean"] = x.where(~bad)                            # null, never zero
    df["leak_ok"] = df[[ch + "_clean" for ch in LEAK_CHANNELS]].notna().any(axis=1)
    if c["leak_failed"] not in df.columns and c["status"] in df.columns:
        is_leak = df[c["status"]].astype(str).str.contains(LEAK_STATUS_REGEX, case=False, na=False)
        df[c["leak_failed"]] = ((df[c["failed"]] == 1) & is_leak).astype(int)
        if not _PRINTED:
            fs = df.loc[df[c["failed"]] == 1, c["status"]].astype(str).value_counts()
            print(f"\nBuilt '{c['leak_failed']}' from `{c['status']}` using regex '{LEAK_STATUS_REGEX}': "
                  f"{int(df[c['leak_failed']].sum()):,} of {int((df[c['failed']] == 1).sum()):,} failures.")
            print("Top failure statuses (* = counted as LEAK failure). Widen LEAK_STATUS_REGEX if a leak status lacks *:")
            for st, n in fs.head(15).items():
                print(f"  {'*' if re.search(LEAK_STATUS_REGEX, st, re.I) else ' '} {n:>9,}  {st}")
    _PRINTED = True
    return df.sort_values(c["time"]).reset_index(drop=True)


def feature_cols(train):
    """Two-sided *_dev columns that are informative. Never fillna(0): null != normal."""
    cols = []
    for col in train.columns:
        base = col[:-4] if col.endswith("_dev") else None
        if base and base not in CONSTANT_COLS and train[col].notna().mean() > 0.5:
            cols.append(col)
    return cols


# ---- Per-group detector -----------------------------------------------------------------------
def fit_groups(train, feats):
    """Baselines on first-attempt PASSING units. Falls back from machine-level to product x fixture.
    Each group keeps one reference distribution PER LEAK CHANNEL (P1/P3/P5 behave differently), and an
    Isolation Forest on only those features that really have data in that group (some products never
    exercise P2/P4, so their *_dev columns are entirely null: null is not zero, so we drop them)."""
    c = CFG
    base = train[(train[c["failed"]] == 0) & (train[c["attempt"]] == 1) & train.leak_ok]
    levels = (("mpf", [c["machine"], c["product"], c["fixture"]]), ("pf", [c["product"], c["fixture"]]))
    total = sum(base.groupby(keys).ngroups for _, keys in levels)
    models, done, t0 = {}, 0, time.time()
    for level, keys in levels:
        for k, g in base.groupby(keys):
            done += 1
            if done % 100 == 0:
                print(f"  fitting baselines: {done:,}/{total:,} groups, {len(models):,} kept, "
                      f"{time.time() - t0:.0f}s", flush=True)
            if len(g) < MIN_GROUP_N:
                continue
            refs = {}
            for ch in LEAK_CHANNELS:
                v = g[ch + "_clean"].dropna().values
                if len(v) >= MIN_GROUP_N:
                    refs[ch] = np.sort(v)
            if not refs:
                continue
            gf = [f for f in feats if g[f].notna().mean() >= 0.5]
            if gf:
                med = g[gf].median()
                X = g[gf].fillna(med)
                if len(X) > IF_MAX_TRAIN:
                    X = X.sample(IF_MAX_TRAIN, random_state=0)
                sc = RobustScaler().fit(X)
                iso = IsolationForest(n_estimators=100, random_state=0).fit(sc.transform(X))
                thr = np.quantile(-iso.score_samples(sc.transform(X)), IF_Q)
            else:                                                    # no usable side features: percentile rule only
                med = sc = iso = None
                thr = np.inf
            models[(level, k)] = dict(refs=refs, feats=gf, med=med, sc=sc, iso=iso, thr=thr)
    print(f"  fitting baselines: done, {len(models):,} groups kept of {total:,} in {time.time() - t0:.0f}s", flush=True)
    return models


def pctl_midrank(ref, x):
    """Empirical percentile of x within the sorted reference (mid-rank, so ties/lumps are handled fairly)."""
    return (np.searchsorted(ref, x, "left") + np.searchsorted(ref, x, "right")) / 2 / len(ref)


def score(test, models, feats):
    """Per passing first-attempt unit: percentile and normal-score z for each leak channel, plus an
    Isolation Forest score. z = norm.ppf(percentile) is ~N(0,1) when behaviour is normal, which is exactly
    what the EWMA/CUSUM drift monitor in v3 assumes, whatever the shape of the leak distribution."""
    c = CFG
    t = test[(test[c["failed"]] == 0) & (test[c["attempt"]] == 1) & test.leak_ok].copy()
    pcols = [ch + "_pctl" for ch in LEAK_CHANNELS]
    zcols = [ch + "_z" for ch in LEAK_CHANNELS]
    for col in pcols + zcols:
        t[col] = np.nan
    t["if_score"], t["if_flag"], t["baseline"] = np.nan, False, ""
    for level, keys in (("pf", [c["product"], c["fixture"]]), ("mpf", [c["machine"], c["product"], c["fixture"]])):
        for k, g in t.groupby(keys):                              # mpf runs last and overrides pf
            m = models.get((level, k))
            if m is None:
                continue
            if m["iso"] is not None:
                s = -m["iso"].score_samples(m["sc"].transform(g[m["feats"]].fillna(m["med"])))
            else:
                s = np.full(len(g), np.nan)
            t.loc[g.index, pcols + zcols] = np.nan
            for ch, ref in m["refs"].items():
                x = g[ch + "_clean"].values
                ok = ~np.isnan(x)
                if ok.any():
                    p = pctl_midrank(ref, x[ok])
                    t.loc[g.index[ok], ch + "_pctl"] = p
                    t.loc[g.index[ok], ch + "_z"] = norm.ppf(np.clip(p, 1e-3, 1 - 1e-3))
            t.loc[g.index, "if_score"] = s
            t.loc[g.index, "if_flag"] = (s > m["thr"]) if m["iso"] is not None else False
            t.loc[g.index, "baseline"] = level
    arr = t[pcols].to_numpy(dtype=float)
    none = np.isnan(arr).all(axis=1)
    t["leak_pctl"] = np.where(none, np.nan, np.nanmax(np.where(np.isnan(arr), -1, arr), axis=1))
    t["worst_channel"] = np.where(none, "", np.array(LEAK_CHANNELS)[np.argmax(np.where(np.isnan(arr), -1, arr), axis=1)])
    # Bonferroni: three channels each tested at the cut-off would triple the flag rate, so tighten it
    cut = 1 - (1 - PCTL) / len(LEAK_CHANNELS)
    t["pctl_flag"] = (arr >= cut).any(axis=1)
    t["near_threshold"] = t.pctl_flag | t.if_flag
    return t


# ---- Validation ---------------------------------------------------------------------------------
def future_fail(test_all):
    """Failure RATE over the same machine+fixture's next LOOKAHEAD tests (not 'any failure': with a ~3%
    fail rate nearly every window contains one, which would make the comparison meaningless).
    Uses leak failures only if a leak_failed column exists, since WP2 is about leak behaviour."""
    c = CFG
    ycol = c["leak_failed"] if c["leak_failed"] in test_all else c["failed"]
    parts = []
    for _, g in test_all.groupby([c["machine"], c["fixture"]]):
        g = g.sort_values(c["time"])
        f = (g[ycol] == 1).astype(int).values
        cs = np.concatenate([[0], np.cumsum(f)])
        i = np.arange(len(g))
        end = np.minimum(i + 1 + LOOKAHEAD, len(g))
        out = pd.DataFrame({"fail_next": (cs[end] - cs[i + 1]) / LOOKAHEAD,
                            "full": (i + 1 + LOOKAHEAD) <= len(g)}, index=g.index)
        parts.append(out)
    return pd.concat(parts)


def validate(test_all, scored):
    c = CFG
    fn = future_fail(test_all)
    v = scored.join(fn[["fail_next", "full"]]).query("full")
    print(f"\nScored {len(scored):,} passing first-attempt test units; "
          f"{scored.near_threshold.mean():.2%} flagged "
          f"(baseline level: {scored.baseline.value_counts().to_dict()})")

    # Did the flag predict trouble? Raw comparison is confounded: bad fixtures are bad AND flagged.
    raw = v.groupby("near_threshold").fail_next.agg(["mean", "size"])
    print(f"\nMean failure rate of the same machine+fixture over its next {LOOKAHEAD} tests:\n{raw.round(4)}")

    # Control: within strata of the recent failure rate (already known without WP2), does the flag add lift?
    if c["recent_fail"] in v and v[c["recent_fail"]].notna().any():
        v = v.assign(stratum=pd.qcut(v[c["recent_fail"]].rank(method="first"), 4,
                                     labels=["Q1 low", "Q2", "Q3", "Q4 high"]))
        tab = (v.pivot_table(index="stratum", columns="near_threshold", values="fail_next",
                             aggfunc="mean", observed=True).round(4))
        tab["lift"] = (tab[True] / tab[False]).round(2)
        print("\nSame, split by how bad the fixture already looked (fx_recent_fail quartile).")
        print("Lift well above 1 inside a stratum = WP2 adds information beyond 'this fixture is bad':")
        print(tab)

    # The test period has a lower failure rate than train (DATASET.md section 2 rule 3):
    # watch whether flag rate is stable week to week, or just tracks that shift.
    wk = scored.groupby(scored[c["time"]].dt.to_period("W")).near_threshold.agg(["mean", "size"])
    print("\nFlag rate per week (should hover near 1-2% on healthy data):")
    print(wk.round(4).to_string())

    print("\nTop machine/fixture by flag count:")
    print(scored[scored.near_threshold].groupby([c["machine"], c["fixture"]]).size()
          .sort_values(ascending=False).head(8).to_string())


if __name__ == "__main__":
    train_path, test_path, out_csv = parse_args()
    train = prep(read_path(train_path, "train"))
    train = train[(train[CFG["failed"]] == 0) & (train[CFG["attempt"]] == 1)]      # baselines need only these
    test = prep(read_path(test_path, "test"))
    feats = feature_cols(train)
    print(f"{len(train):,} train / {len(test):,} test rows; {len(feats)} _dev features for Isolation Forest")
    models = fit_groups(train, feats)
    print(f"{len(models)} group baselines fitted (min {MIN_GROUP_N} normal units each)")
    scored = score(test, models, feats)
    validate(test, scored)
    scored.to_csv(out_csv, index=False)
    print(f"\nSaved scored test units to {out_csv}")