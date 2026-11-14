"""Builds wp2_p2p4/docs/WP2_Progress_Report.docx (python-docx): status of WP2 as of 30 Oct 2026, what it does,
how it stands against the agreed drift definition and what is needed next. Numbers come from out/eval_all_s0.csv,
the 3-machine alert run (alerts.py), the walkthrough report and checks on the September .rpt exports.

    uv run --no-project --with python-docx python docs/make_progress_doc.py docs/WP2_Progress_Report.docx
"""
import re
import sys

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = sys.argv[1]
doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
for side in ("left_margin", "right_margin"):
    setattr(sec, side, Cm(2.2))
sec.top_margin = sec.bottom_margin = Cm(2.0)
TEXT_W = 21.0 - 4.4

st = doc.styles["Normal"]
st.font.name, st.font.size = "Calibri", Pt(10.5)
st.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
st.paragraph_format.space_after = Pt(5)
for name, size, color in (("Heading 1", 15, "1F3864"), ("Heading 2", 12.5, "2E5597"), ("Heading 3", 11, "2E5597")):
    h = doc.styles[name]
    h.font.name, h.font.size, h.font.bold = "Calibri", Pt(size), True
    h.font.color.rgb = RGBColor.from_string(color)
    h.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    h.paragraph_format.space_before, h.paragraph_format.space_after = Pt(12 if name == "Heading 1" else 9), Pt(4)


def P(text="", bold=False, italic=False, style=None, size=None):
    p = doc.add_paragraph(style=style)
    _runs(p, text, bold, italic, size)
    return p


def _runs(p, text, bold=False, italic=False, size=None):
    """**bold** and `code` inline markup."""
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not part:
            continue
        if part.startswith("**"):
            r = p.add_run(part[2:-2]); r.bold = True
        elif part.startswith("`"):
            r = p.add_run(part[1:-1]); r.font.name = "Consolas"; r.font.size = Pt(9.5)
        else:
            r = p.add_run(part); r.bold = bold
        r.italic = italic or r.italic
        if size:
            r.font.size = Pt(size)


def B(items, style="List Bullet"):
    for it in items:
        p = doc.add_paragraph(style=style)
        _runs(p, it)
        p.paragraph_format.space_after = Pt(2)


def N(items):
    B(items, "List Number")


def H(text, lvl=1):
    doc.add_heading(text, lvl)


def shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), hexcolor)
    tcPr.append(sh)


def T(rows, widths=None, header=True, size=9):
    n = len(rows[0])
    widths = widths or [TEXT_W / n] * n
    t = doc.add_table(rows=len(rows), cols=n)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            c = t.cell(i, j)
            c.width = Cm(widths[j])
            c.text = ""
            p = c.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            _runs(p, str(val), bold=(header and i == 0), size=size)
            if header and i == 0:
                shade(c, "D9E2F3")
    keep_together(t)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def keep_together(t):
    """Rows never split, and every row stays on the page of the next, so a table moves as a block."""
    rows = t.rows
    for i, row in enumerate(rows):
        trPr = row._tr.get_or_add_trPr()
        trPr.append(OxmlElement("w:cantSplit"))
        if i < len(rows) - 1:
            for c in row.cells:
                for p in c.paragraphs:
                    p.paragraph_format.keep_with_next = True


def KEY(text):
    """Shaded one-cell box for the take-away of a step."""
    t = doc.add_table(rows=1, cols=1)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    c = t.cell(0, 0)
    c.width = Cm(TEXT_W)
    shade(c, "EAF1E4")
    p = c.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    _runs(p, "Take-away: ", bold=True)
    _runs(p, text)
    keep_together(t)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def NEXT(text):
    """Shaded one-cell box for a status summary."""
    t = doc.add_table(rows=1, cols=1)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    c = t.cell(0, 0)
    c.width = Cm(TEXT_W)
    shade(c, "FFF4CE")
    p = c.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    _runs(p, text)
    keep_together(t)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


# ------------------------------------------------------------------ title
t = doc.add_paragraph(); t.alignment = WD_ALIGN_PARAGRAPH.LEFT
r = t.add_run("WP2 progress report — P2 / P4 near-threshold early warning"); r.bold = True; r.font.size = Pt(20)
r.font.color.rgb = RGBColor.from_string("1F3864")
P("Sensata CFT project · Work Package 2 · status as of 30 October 2026", italic=True)
P("Author: Irfan Ramizu · Code: `D:\\SENSATA\\WP2\\Work-Package-2\\wp2_p2p4\\` · Reference design: Trace Sentinel "
  "(`D:\\SENSATA\\sensata2026`)", italic=True, size=9.5)

H("Summary")
B(["**Built:** a complete pipeline from raw tester rows to drift alerts on P2 / P4 output error: cleaning, "
   "features, three detectors, tuning to a false-alarm budget, a saved model, an alert list, and a local live "
   "monitor (Streamlit) that flags bad rows and raises drift alerts with the columns behind them.",
   "**Verified:** the cleaning rules match the real limits file (DPSCFTLimits.rpt) on every device; the reject rule "
   "matches the tester's verdict 99 %+ of the time; the live monitor reproduces the offline alert list exactly.",
   "**Result:** on drifts added to real data (20 machines, test period), the trained model catches 87 % at 0.2 false "
   "alarms per machine per day, 71 % before the first reject. Today's count rule catches 36 %, never before a reject.",
   "**Main gap:** the team's drift definition places drift at the **calibration (CAL) machine**, between "
   "**engineer-marked faults**. WP2 currently monitors the **CFT tester** and learns from **made-up drifts**, because "
   "no data yet links units to a CAL machine, a calibration time, or a fault record. On real reject clusters the "
   "model catches only 11 %; most of them are machine-wide, which points upstream.",
   "**Needed most:** (1) calibration history for the WP1 period (May – Aug 2026), (2) CAL machine ID and calibration "
   "time per unit, (3) the engineers' fault log."])
NEXT("**Status:** pipeline and tooling done and verified · model works on its training assumption · the target "
     "(CAL machine, fault-to-fault labels) is blocked on data · most code carries over once the data arrives.")

# ------------------------------------------------------------------ goal
H("1. Goal and scope")
P("Detect a P2 or P4 output test drifting towards its limit **before** units are rejected, and tell the operator "
  "which machine and fixture to check. P2 and P4 are output tests (sensor output against target at a test "
  "pressure); leak and the P1 / P3 / P5 tests are out of scope. Results feed the WP4 dashboard.")
P("**Drift definition (agreed with the team, 30 Oct):** drift is the behaviour of the **CAL machine**. It is found "
  "in the data between an engineer-marked fault and the previous fault; the model should learn where in that "
  "interval the drift pattern starts. A fault can concern the **whole CAL machine or one fixture** on it.")

# ------------------------------------------------------------------ built
H("2. What has been built")
T([["Step", "File", "What it does"],
   ["a", "`load.py`", "Reads only the needed columns, first passes only. Recovers each device's target and tolerance. "
    "Computes v = 100 × error / tolerance, or records why there is no reading (not tested, not measured, "
    "placeholder, aborted, no limits). Replaces serials with a keyed hash."],
   ["b", "`check_reject_rule.py`", "Checks that |v| > 100 is the tester's real limit; finds two device exceptions"],
   ["c", "`features.py`", "15 streaming features per fixture: departure from its own normal (machine-wide move "
    "removed), trend, CUSUM, headroom, units to the limit, near-limit and reject rates against neighbours"],
   ["d", "`labels.py`", "Training labels: known step / ramp drifts added to healthy real data; real reject clusters "
    "kept for scoring"],
   ["e", "`detectors.py`", "Count rule (today's practice), CUSUM, gradient-boosted trees; alarm tracker (3 readings "
    "to raise, latch, 60 to clear)"],
   ["f", "`evaluate.py`", "Time split (fit / tune / test), thresholds tuned to a false-alarm budget, test scored once"],
   ["g", "`alerts.py`", "Saves the model and thresholds; lists warnings and alarms on real data"],
   ["app", "`live.py`, `app.py`", "Local monitor: replays data live or all at once; flags bad rows with the "
    "columns and values; drift alerts with reasons, the units since the drift began, and machine-wide notes"]],
  [1.0, 4.0, TEXT_W - 5.0], size=8.5)
P("Learning record: `docs/WP2_Walkthrough_Steps_A-G.docx` walks through each step on a sample. Full evaluation: "
  "`docs/WP2_P2P4_Early_Warning.docx`.")

# ------------------------------------------------------------------ data facts
H("3. What the data confirmed")
T([["Check", "Finding", "Consequence"],
   ["Limits", "Recovered target and tolerance match DPSCFTLimits.rpt on all 83 P2 and 44 P4 devices", "Cleaning is exact; the limits file can replace the recovery"],
   ["Reject rule", "|v| > 100 agrees with the tester: precision 0.992 (P2), 0.996 (P4)", "The 100 % line is the real limit"],
   ["Two devices", "31MPP3-2 and 85MPP36-01 are rejected at ~64 % / ~80 % of the file's tolerance (85MPP36-01 until early June)", "Ask why the tester used another limit; both are excluded from scoring"],
   ["P4 after a P2 fail", "None of 4,086 P2 rejects has a real P4 reading (88 % read 0 / 0); every passing unit has one", "P4 = 0 means not tested, never 0 % error"],
   ["80 % near-limit line", "Healthy units reach it 0.46 % (P2) and 0.44 % (P4) of the time", "Use it as a count against neighbours, not one unit"],
   ["Fixture groups", "360,540 of 360,549 calibrated units with three fixtures sit at Fn, Fn+4, Fn+8", "One nest position = three calibration steps; six-fixture units may be recalibrations"],
   ["P4 calibration", "Of 50 P2+P4 devices tested, 1 has calibration records; of 5 P4-only devices, 3 (P2-only: 15 of 63)", "P4 calibration is mostly not in this export"],
   ["Raw flags", "WP1 `p2error_missing` is always False, even for placeholders; `failed` covers all causes", "Bad values are detected from the values; the status text is the reject truth"]],
  [2.6, 7.6, TEXT_W - 10.2], size=8.5)

# ------------------------------------------------------------------ results
H("4. Results")
H("Added drifts, all 20 machines, test period (23 Jul – 12 Aug)", 2)
P("153 added drifts; 1.24 M test rows; base rate 1.49 %. Row-level PR-AUC: count rule 0.015, CUSUM 0.797, "
  "trained trees 0.947.")
T([["Detector", "False alarms / machine / day", "Detected", "Before first reject", "Median delay", "Rejects avoidable", "Real clusters: detected / before 1st"],
   ["Count rule (today)", "0.08", "36 %", "0 %", "54 units / 4.1 h", "38 %", "96 % / 15 %"],
   ["CUSUM, budget 0.5", "0.39", "84 %", "61 %", "13 units / 0.8 h", "82 %", "19 % / 1.9 %"],
   ["Trained trees, budget 0.5", "0.20", "87 %", "71 %", "9 units / 0.5 h", "85 %", "11 % / 3.7 %"]],
  [3.4, 2.4, 1.6, 2.0, 2.4, 1.9, TEXT_W - 13.7], size=8)
B(["On the drift shape it was trained for, the model gives a real head start at a false-alarm rate the floor can accept.",
   "On the 107 real reject clusters it is weak: 64 % of them are **machine-wide** (several fixtures at once), which "
   "the per-fixture features remove by design."])
H("Real data, 3 machines, test period (no drifts added)", 2)
B(["14 alarms and 71 warnings over 3 weeks; alarms bunch on whole fixture sets (e.g. one machine and device: "
   "fixtures 3–7 at +30 to +43 % of tolerance within three days).",
   "6 of 14 alarms were followed within 24 h by a reject on the same machine, device and signal; 1 on the same fixture.",
   "One device had 39 real P2 rejects and no alerts at all.",
   "Without fault or recalibration records, right and wrong alarms cannot be told apart."])

# ------------------------------------------------------------------ app
H("5. The local live monitor")
P("Run from the `Work-Package-2` folder: `uv run --with streamlit streamlit run wp2_p2p4/app.py`, then open "
  "localhost:8501. It reads a WP1 parquet window or an uploaded CSV / parquet with the same column names.")
B(["**Row flags:** one line per problem with one unit, naming the columns and values: unreadable value, missing "
   "key, duplicate, repeat test, placeholder, not measured, failed before this step, no tolerance known, P2 / P4 "
   "reject, near the limit.",
   "**Drift alerts:** per machine, device, fixture and signal, e.g. “ALARM: machine 9990675 · device 85MPP37-01 · "
   "fixture 6 · P2 is drifting: at −28 % of tolerance, ≈ 928 units to the limit, began ≈ 09:18”. Each alert lists "
   "the features outside their healthy range, the raw columns behind it and the units tested since the drift began.",
   "**Machine-wide notes** when three or more fixtures of one machine and device are in alert together.",
   "Same results as the offline alert list (85 of 85 alerts identical). Serials are shown on screen only and left "
   "out of downloads."])

# ------------------------------------------------------------------ gap
H("6. Where WP2 stands against the drift definition")
T([["Definition", "WP2 today", "Status"],
   ["Drift comes from the CAL machine", "Streams follow the CFT tester's machine and fixture", "Not met: no CAL machine ID in any data"],
   ["Window: previous fault → marked fault", "Rolling windows; restart after 12 h idle", "Not met: no fault log"],
   ["Learn where the pattern starts", "CUSUM change point gives a drift start on every alert", "Met in method"],
   ["Labels from engineer-marked faults", "Labels from drifts added to healthy data", "Not met: no fault log"],
   ["Machine-level and fixture-level faults", "Fixture level only; machine-wide notes as a first step", "Partly met"]],
  [4.6, 6.4, TEXT_W - 11.0], size=8.5)
P("Why: WP1 has test time and the CFT tester but no calibration data; the September exports have calibration "
  "fixtures but no time, machine or status. Only 3 serials appear in both WP1 and the calibration export, so "
  "nothing can be keyed to the CAL machine yet.")

# ------------------------------------------------------------------ needs
H("7. What is needed to improve it")
H("Data (in order of value)", 2)
T([["#", "Request", "What it unlocks"],
   ["1", "Calibration history (serial, device, fixture) for **May – Aug 2026**, the WP1 period", "Join to WP1 by serial: every unit gets its calibration fixture group and a real test time. The pipeline can then run keyed by calibration fixture group, before machine IDs exist"],
   ["2", "**CAL machine ID and calibration timestamp** per unit", "Streams per CAL machine and nest position, in calibration order"],
   ["3", "**Fault log:** CAL machine, time marked, whole machine or which fixture, action taken", "Real labels (fault-to-fault), resets at each fault, lead-time scoring"],
   ["4", "CFT history with `testtime`, `equipmentid`, `fixture`, `attempt_no`, `status`", "Live data in the same shape as WP1, so the app runs on it directly"],
   ["5", "Where P4 calibration is recorded (RPS entries?)", "P4 trace-back"],
   ["6", "Why 31MPP3-2 and 85MPP36-01 reject below the file's tolerance", "Correct limits for those devices"]],
  [0.8, 7.0, TEXT_W - 7.8], size=8.5)
H("Planned changes once the data arrives", 2)
T([["Change", "Effort", "Depends on"],
   ["Stream key: (CAL machine, nest position Fn/Fn+4/Fn+8, device, signal)", "Small: the feature engine takes the key as arguments", "Data 1, 2"],
   ["Reset each stream at every marked fault (`restart()` exists)", "Small", "Data 3"],
   ["Labels: from the detected drift start up to each marked fault, replacing added drifts", "Medium: new labels step", "Data 3"],
   ["Machine-level detector next to the fixture level", "Medium: new features on the shared move", "Data 2 (can start on the CFT tester now)"],
   ["Score by lead time before the engineers' mark, at a fixed false-alarm budget", "Small: change in evaluate.py", "Data 3"],
   ["Read DPSCFTLimits.rpt in `load.limits()`", "Small", "Available now"],
   ["Column mapping for the live export in the app", "Small", "A sample of the live export"]],
  [7.4, 4.6, TEXT_W - 12.0], size=8.5)

# ------------------------------------------------------------------ coordination
H("8. Coordination with the dashboard team")
P("The Trace Sentinel dashboard (14 Oct build) traces P2 / P4 rejects back to calibration fixture groups with a "
  "statistical rule; its CAL machine, CFT tester and times are assigned for demonstration. WP2 has the real time "
  "order and a trained early-warning model on the tester side. The two halves fit: WP2 should become the model "
  "behind the dashboard once units can be linked to a CAL machine and time. Data answers to their questions are "
  "in section 3 (fixture groups, P4 calibration, 80 % line, P4 = 0 after a P2 fail).")

# ------------------------------------------------------------------ open
H("9. Open questions")
B(["Is a six-fixture unit (two nest positions) a recalibration? If so it is a fault signal already in the data.",
   "Does a marked fault record whole machine versus fixture, or must it be inferred?",
   "Who owns the model: WP2 or the dashboard team?",
   "Physical light or buzzer at the PC (plant decision)."])

zoom = doc.settings.element.find(qn("w:zoom"))      # python-docx template omits the required percent
if zoom is not None:
    zoom.set(qn("w:percent"), "100")
doc.save(OUT)
print("saved", OUT)
