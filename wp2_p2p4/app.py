"""Local app: replay tester data through the WP2 pipeline and watch the flags and drift alerts.

    uv run --with streamlit streamlit run wp2_p2p4/app.py        (from the Work-Package-2 folder)

Two tabs share one pipeline (live.py):
  Live replay      rows arrive in time order, a slice of data time per tick, alerts appear as they are raised
  All at once      the whole window in one go, then tables of every flag and alert
Data: a WP1 parquet split (machines, time window) or an uploaded CSV / parquet with the WP1 column names.
Serial numbers are shown on screen only (toggle in the sidebar); downloads leave them out.
"""
import io
import os

import pandas as pd
import streamlit as st

import live
import load

st.set_page_config(page_title="WP2 drift monitor", layout="wide")
MACHINES = [1870305, 1890932, 1890933, 9990111, 9990163, 9990208, 9990226, 9990227, 9990230, 9990242, 9990512,
            9990675, 9990687, 9990770, 9990771, 9990793, 9990873, 9990874, 20190405, 20190406]


@st.cache_data(show_spinner="Reading parquet ...")
def wp1(split, machines, start, end):
    f = [("equipmentid", "in", list(machines)), ("testtime", ">=", pd.Timestamp(start)),
         ("testtime", "<", pd.Timestamp(end))]
    return load.read(split, live.RAW_COLUMNS, filters=f).sort_values("testtime", kind="stable").reset_index(drop=True)


@st.cache_data(show_spinner="Reading file ...")
def uploaded(name, data):
    b = io.BytesIO(data)
    d = pd.read_parquet(b) if name.lower().endswith(".parquet") else pd.read_csv(b)
    return d


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Data")
    src = st.radio("Source", ["WP1 parquet", "Upload a file"], horizontal=True)
    if src == "WP1 parquet":
        split = st.selectbox("Split", ["test", "train"])
        machines = st.multiselect("Machines (equipmentid)", MACHINES, default=[9990675, 9990771, 20190405])
        c1, c2 = st.columns(2)
        start = c1.date_input("From", pd.Timestamp("2026-07-23") if split == "test" else pd.Timestamp("2026-06-01"))
        end = c2.date_input("To", pd.Timestamp("2026-08-13") if split == "test" else pd.Timestamp("2026-06-15"))
        raw = wp1(split, tuple(machines), start, end) if machines else None
    else:
        up = st.file_uploader("CSV or parquet with the WP1 column names", type=["csv", "parquet"])
        raw = uploaded(up.name, up.getvalue()) if up else None
    st.header("Detector")
    paths = live.models()
    names = [os.path.basename(p) for p in paths] + ["CUSUM (no training)"]
    pick = st.selectbox("Model", names, help="Train one with: python alerts.py --train")
    det_path = paths[names.index(pick)] if pick in names[:-1] else None
    warm_days = st.number_input("Warm-up days (scored, alerts hidden)", 0, 14, 2,
                                help="Each fixture needs ~120 units to learn its normal before it can alert")
    group_min = st.number_input("Machine-wide note when this many fixtures are in alert", 2, 10, 3)
    st.header("Display")
    show_serial = st.toggle("Show real serial numbers (screen only)", True)

st.title("WP2 · P2 / P4 drift monitor")
if raw is None or len(raw) == 0:
    st.info("Pick machines and a window, or upload a file, in the sidebar.")
    st.stop()
miss = live.missing_columns(raw)
if miss:
    st.error("The data is missing columns the pipeline needs: " + ", ".join(miss))
    st.caption("Needed: " + ", ".join(live.RAW_COLUMNS))
    st.stop()
raw = raw.assign(_t=pd.to_datetime(raw.testtime, errors="coerce")).sort_values("_t", kind="stable")
t_first, t_last = raw._t.min(), raw._t.max()
report_from = t_first.normalize() + pd.Timedelta(days=int(warm_days))
det, persist, det_desc = live.detector(det_path)
th = det.thresholds
st.caption(f"{len(raw):,} rows · {t_first:%d %b %Y %H:%M} → {t_last:%d %b %Y %H:%M} · detector: {det_desc} · "
           f"warning ≥ {th['warn']:.3g}, alarm ≥ {th['alarm']:.3g} for {persist} readings in a row · "
           f"alerts shown from {report_from:%d %b %H:%M}")


def new_engine():
    return live.Live(det, persist, report_from=report_from, group_min=int(group_min))


# ------------------------------------------------------------------ shared rendering
def unit_table(a):
    u = pd.DataFrame(a["units"], columns=["testtime", "serialno", "v_pct_tol", "output", "error", "status"])
    u["testtime"] = pd.to_datetime(u.testtime)
    u["v_pct_tol"] = u.v_pct_tol.round(1)
    return u if show_serial else u.drop(columns="serialno")


def alert_card(ev, expanded=False):
    if ev["type"] == "machine-wide":
        m, dv, s = ev["key"]
        lv = ", ".join(f"{x:+.0f}" for x in ev["levels"])
        st.info(f"**Machine-wide: machine {m} · device {dv} · {s.upper()}**: fixtures "
                f"{', '.join(map(str, ev['fixtures']))} are in alert together ({ev['time']:%d %b %H:%M}). "
                f"Levels {lv} % tol. A whole set moving points to the machine (or calibration), not one fixture.")
        return
    if ev["type"] == "recal":
        m, dv, fx_, s = ev["key"]
        st.info(f"**Recalibrated: machine {m} · fixture {fx_} · {s.upper()}"
                f"{' · device ' + dv if dv else ''}** ({ev['time']:%d %b %H:%M}; {ev['finding'] or 'no finding'})"
                f"{': ' + ev['note'] if ev['note'] else ''}. {len(ev['streams'])} stream(s) re-learn their centre "
                f"from the next 60 units; {len(ev['closed'])} open alert(s) closed.")
        return
    a = ev["alert"]
    if ev["type"] == "cleared" and ev.get("reason") == "recalibrated":
        st.success(f"Closed, recalibrated: machine {a['equipmentid']} · device {a['deviceid']} · fixture "
                   f"{a['fixture']} · {a['signal'].upper()} ({ev['time']:%d %b %H:%M}; {a['level']} raised "
                   f"{a['raised']:%d %b %H:%M})")
        return
    if ev["type"] == "cleared":
        st.success(f"Back to normal: machine {a['equipmentid']} · device {a['deviceid']} · fixture {a['fixture']} · "
                   f"{a['signal'].upper()} ({ev['time']:%d %b %H:%M}; {a['level']} raised {a['raised']:%d %b %H:%M})")
        return
    title, lines = live.message(a)
    box = st.error if a["level"] == "alarm" else st.warning
    box(f"**{title}**  \n{a['raised']:%d %b %Y %H:%M}" + (" (was a warning)" if ev.get("escalated") else ""))
    with st.expander("Why, and which units", expanded=expanded):
        st.markdown("\n".join(f"- {x}" for x in lines))
        st.markdown("**Features outside the healthy range:**  \n" +
                    ("\n".join(f"- {w[1]}" for w in a["why"]) or "- none past the healthy 99 %; the model "
                     "combines several moderate signs"))
        st.markdown(f"**Columns behind this alert:** {live.SIGNAL_COLUMNS[a['signal']]}")
        st.caption("All 15 features at the raise: " +
                   " · ".join(f"{k} {v:.2f}" for k, v in a["features"].items()))
        st.dataframe(unit_table(a), hide_index=True, height=220)


def flag_view(flags, key):
    if flags is None or len(flags) == 0:
        st.caption("No flags yet.")
        return
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("**Flags by type**")
        n = flags.groupby(["kind", "flag", "signal"]).size().rename("rows").reset_index()
        st.dataframe(n, hide_index=True)
    with c2:
        kinds = st.multiselect("Show", sorted(flags.flag.unique()),
                               default=[f for f in flags.flag.unique() if f != "repeat test"], key=key)
        f = flags[flags.flag.isin(kinds)].sort_values("testtime", ascending=False)
        if not show_serial:
            f = f.drop(columns="serialno")
        st.dataframe(f.head(2000), hide_index=True, height=360)
        st.caption(f"{len(f):,} rows (latest 2,000 shown). `columns` = the raw columns that raised the flag.")


def metrics(eng):
    a = eng.alert_table()
    c = st.columns(6)
    c[0].metric("Rows read", f"{eng.n['rows']:,}")
    c[1].metric("First passes", f"{eng.n['first_pass']:,}")
    c[2].metric("Readings scored", f"{eng.n['scored']:,}")
    c[3].metric("Alarms", int((a.level == "alarm").sum()))
    c[4].metric("Warnings", int((a.level == "warning").sum()))
    c[5].metric("Open now", len(eng.open_alerts()))


tab_live, tab_all = st.tabs(["Live replay", "All at once"])

# ------------------------------------------------------------------ live
with tab_live:
    S = st.session_state
    sig = (len(raw), t_first, t_last, det_desc, report_from, int(group_min))
    if S.get("sig") != sig:                       # data or settings changed: start over
        S.sig, S.eng, S.cursor, S.running, S.flags = sig, None, None, False, []
    def start():
        # callbacks run before the page is drawn, so the buttons show the new state at once
        if S.eng is None:
            S.eng = new_engine()
            warm = raw[raw._t < report_from]
            f, _ = S.eng.feed(warm.drop(columns="_t"))
            S.flags = [f]
            S.cursor = report_from
        S.running = True

    def pause():
        S.running = False

    def reset():
        S.eng, S.cursor, S.running, S.flags = None, None, False, []

    c = st.columns([1, 1, 1, 3])
    c[0].button("Start" if S.eng is None else "Resume", type="primary", disabled=S.running, on_click=start,
                help="The warm-up days are processed at once (a few seconds)")
    c[1].button("Pause", disabled=not S.running, on_click=pause)
    c[2].button("Reset", on_click=reset)
    speed = c[3].select_slider("Data time per second", ["10 min", "30 min", "1 h", "3 h", "6 h", "12 h"], "1 h")

    @st.fragment(run_every=1.0)
    def tick():
        S = st.session_state
        if S.eng is None:
            st.caption("Press Start: the warm-up days are processed at once, then rows arrive in time order.")
            return
        if S.running:
            nxt = S.cursor + pd.Timedelta(speed.replace(" ", ""))
            ch = raw[(raw._t >= S.cursor) & (raw._t < nxt)]
            f, _ = S.eng.feed(ch.drop(columns="_t"))
            S.flags.append(f)
            S.cursor = nxt
            if S.cursor > t_last:
                S.running = False
        done = 1.0 if S.cursor > t_last else (S.cursor - t_first) / (t_last - t_first)
        st.progress(min(1.0, max(0.0, done)),
                    text=f"Data clock {min(S.cursor, t_last):%a %d %b %Y %H:%M}" + ("" if S.running else " (paused)"))
        metrics(S.eng)
        left, right = st.columns([3, 2])
        with left:
            st.subheader("Alert feed (newest first)")
            evs = [e for e in S.eng.events if e["time"] >= report_from][-25:][::-1]
            if not evs:
                st.caption("No alerts yet.")
            for i, e in enumerate(evs):
                alert_card(e, expanded=False)
        with right:
            st.subheader("Fixtures in alert now")
            o = S.eng.open_alerts()
            if len(o):
                st.dataframe(o, hide_index=True)
            else:
                st.caption("None.")
            st.subheader("Latest row flags")
            fl = pd.concat(S.flags[-50:], ignore_index=True) if S.flags else None
            if fl is not None and len(fl):
                fl = fl[fl.flag != "repeat test"].tail(15).iloc[::-1]
                st.dataframe(fl[["testtime", "serialno", "equipmentid", "fixture", "signal", "flag", "values"]]
                             if show_serial else fl[["testtime", "equipmentid", "fixture", "signal", "flag", "values"]],
                             hide_index=True)

    tick()

# ------------------------------------------------------------------ all at once
with tab_all:
    if st.button("Run the whole window", type="primary"):
        eng, flags = new_engine(), []
        days = list(raw.groupby(raw._t.dt.floor("D")))
        bar = st.progress(0.0, text="Running ...")
        for i, (day, ch) in enumerate(days):
            f, _ = eng.feed(ch.drop(columns="_t"))
            flags.append(f)
            bar.progress((i + 1) / len(days), text=f"{day:%d %b}: {eng.n['first_pass']:,} first passes")
        st.session_state.batch = (eng, pd.concat(flags, ignore_index=True))
    if "batch" in st.session_state:
        eng, flags = st.session_state.batch
        metrics(eng)
        a = eng.alert_table()
        st.subheader("Drift alerts")
        st.dataframe(a, hide_index=True)
        st.download_button("Download alerts (CSV, no serials)", a.to_csv(index=False), "alerts.csv")
        mw = [e for e in eng.events if e["type"] == "machine-wide"]
        if mw:
            st.subheader("Machine-wide notes")
            for e in mw:
                alert_card(e)
        st.subheader("Explain one alert")
        shown = [x for x in eng.alerts if not x.get("hidden")]
        if shown:
            i = st.selectbox("Alert", range(len(shown)), format_func=lambda i: live.message(shown[i])[0] +
                             f"  ({shown[i]['raised']:%d %b %H:%M})")
            alert_card({"type": "alert", "alert": shown[i], "time": shown[i]["raised"]}, expanded=True)
        st.subheader("Row flags")
        flag_view(flags, "batch_flags")
        st.download_button("Download flags (CSV, no serials)", flags.drop(columns="serialno").to_csv(index=False),
                           "flags.csv")
