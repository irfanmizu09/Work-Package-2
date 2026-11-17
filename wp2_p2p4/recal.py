"""Recalibration input: the store of recalibration events, out/recal_events.csv.

One row per recalibration of a tester fixture:
  time         when the fixture was recalibrated (units tested at or after it see the new state)
  equipmentid  CFT machine
  deviceid     device (product) the alert was on; empty = every device the fixture runs
  fixture      tester fixture
  signal       p2, p4 or both
  finding      drift confirmed / no fault found / other   (what the engineer found when acting)
  note         free text (no serial numbers: the file is plain text on disk)

Events are what features.replay(recals=) and live.Live take. "drift confirmed" rows are the real positives
that retrain.py uses once enough exist.

    python recal.py add --time "2026-07-25 14:10" --machine 9990675 --fixture 3 --signal p2 \
                        --finding "drift confirmed" --note "zero offset readjusted"
    python recal.py list
"""
import argparse
import os
import re
import tempfile

import pandas as pd

import load

PATH = os.path.join(load.OUT, "recal_events.csv")
COLS = ["time", "equipmentid", "deviceid", "fixture", "signal", "finding", "note"]
SIGNALS = ("p2", "p4", "both")
FINDINGS = ("drift confirmed", "no fault found", "other")
SERIAL_LIKE = re.compile(r"\b[0-9A-Z]{10,}\b")      # long ids in a note look like serial numbers


def empty():
    return pd.DataFrame({c: pd.Series(dtype="datetime64[ns]" if c == "time" else "object") for c in COLS})


def validate(ev):
    """Clean types and check every row; raises ValueError naming the bad rows."""
    ev = ev.copy()
    for c in COLS:
        if c not in ev:
            ev[c] = ""
    ev = ev[COLS]
    ev["time"] = pd.to_datetime(ev.time, errors="coerce")
    ev["equipmentid"] = pd.to_numeric(ev.equipmentid, errors="coerce")
    ev["fixture"] = pd.to_numeric(ev.fixture, errors="coerce")
    for c in ("deviceid", "signal", "finding", "note"):
        ev[c] = ev[c].fillna("").astype(str).str.strip()
    ev["signal"] = ev.signal.str.lower()
    ev["finding"] = ev.finding.str.lower()
    bad = []
    for i, r in ev.iterrows():
        why = [w for w, b in (("time", pd.isna(r.time)), ("equipmentid", pd.isna(r.equipmentid)),
                              ("fixture", pd.isna(r.fixture)), (f"signal {r.signal!r}", r.signal not in SIGNALS),
                              (f"finding {r.finding!r}", r.finding not in FINDINGS),
                              ("note looks like it holds a serial number", bool(SERIAL_LIKE.search(r.note))))
               if b]
        if why:
            bad.append(f"row {i}: " + ", ".join(why))
    if bad:
        raise ValueError("bad recal events:\n  " + "\n  ".join(bad))
    ev["equipmentid"] = ev.equipmentid.astype("int64")
    ev["fixture"] = ev.fixture.astype("int64")
    return ev.sort_values("time", kind="stable").reset_index(drop=True)


def read(path=PATH, start=None, end=None):
    """Events in time order, optionally limited to [start, end). Missing file = no events."""
    if not os.path.exists(path):
        return empty()
    ev = validate(pd.read_csv(path, dtype=str, keep_default_na=False))
    if start is not None:
        ev = ev[ev.time >= pd.Timestamp(start)]
    if end is not None:
        ev = ev[ev.time < pd.Timestamp(end)]
    return ev.reset_index(drop=True)


def write(ev, path=PATH):
    """Whole table, atomically (temp file + rename), so a reader never sees half a file."""
    ev = validate(ev)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w", newline="") as f:
        ev.assign(time=ev.time.dt.strftime("%Y-%m-%d %H:%M:%S")).to_csv(f, index=False)
    os.replace(tmp, path)
    return ev


def add(time, equipmentid, fixture, signal, finding, deviceid="", note="", path=PATH):
    """Append one event; returns it as a one-row table."""
    row = validate(pd.DataFrame([dict(time=time, equipmentid=equipmentid, deviceid=deviceid or "",
                                      fixture=fixture, signal=signal, finding=finding, note=note or "")]))
    write(pd.concat([read(path), row], ignore_index=True), path)
    return row


def for_engine(ev):
    """Table for features.replay(recals=) / Live: device "" -> None (every device)."""
    out = ev[["time", "equipmentid", "deviceid", "fixture", "signal"]].copy()
    out["deviceid"] = out.deviceid.where(out.deviceid != "", None)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Recalibration events (out/recal_events.csv)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a_ = sub.add_parser("add")
    a_.add_argument("--time", required=True)
    a_.add_argument("--machine", type=int, required=True)
    a_.add_argument("--device", default="")
    a_.add_argument("--fixture", type=int, required=True)
    a_.add_argument("--signal", required=True, choices=SIGNALS)
    a_.add_argument("--finding", required=True, choices=FINDINGS)
    a_.add_argument("--note", default="")
    sub.add_parser("list")
    ap.add_argument("--path", default=PATH)
    a = ap.parse_args()
    if a.cmd == "add":
        print(add(a.time, a.machine, a.fixture, a.signal, a.finding, a.device, a.note, a.path).to_string(index=False))
    else:
        ev = read(a.path)
        print(ev.to_string(index=False) if len(ev) else "no recalibration events")
