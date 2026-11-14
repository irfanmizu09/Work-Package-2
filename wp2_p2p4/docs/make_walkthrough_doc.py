"""Builds wp2_p2p4/docs/WP2_Walkthrough_Steps_A-G.docx (python-docx): the step-by-step walkthrough of
the WP2 pipeline, steps a to g, with the sample outputs. Numbers come from the demo scripts run on
machines 9990675, 9990771, 20190405, 1-14 June 2026 (train split), from out/check_reject_rule_train.txt,
from out/eval_*_s0.csv (step f) and from out/alerts_test_trained_*_s0.csv (step g).

    uv run --no-project --with python-docx python docs/make_walkthrough_doc.py docs/WP2_Walkthrough_Steps_A-G.docx
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


# ------------------------------------------------------------------ title
t = doc.add_paragraph(); t.alignment = WD_ALIGN_PARAGRAPH.LEFT
r = t.add_run("WP2 walkthrough — from raw tester data to an alarm (steps a–g)"); r.bold = True; r.font.size = Pt(20)
r.font.color.rgb = RGBColor.from_string("1F3864")
P("Sensata CFT project · Work Package 2 · near-threshold detection on P2 / P4 output error", italic=True)
P("Author: Irfan Ramizu · 29 October 2026 · Code: `wp2_p2p4/` · Reference design: Trace Sentinel "
  "(`D:\\SENSATA\\sensata2026`, read-only)", italic=True, size=9.5)

H("Purpose of this document")
P("This is a learning record. It walks through the WP2 pipeline one step at a time, shows what each step "
  "printed on a small real sample, and explains in plain language what the output means and why the step "
  "exists. Steps f and g also quote the full 20-machine evaluation; the main report "
  "`WP2_P2P4_Early_Warning.docx` has its details.")
P("**Sample used for every demo:** 3 CFT machines (9990675, 9990771, 20190405), 1–14 June 2026, WP1 train "
  "split, first passes only: 127,410 tests (steps a–e). Steps f and g use the same 3 machines over the whole "
  "train and test splits. Step b also quotes the saved run on the whole train split "
  "(3.96 million tests, 20 machines, 1 May – 23 July 2026). No serial numbers appear in this document.")

H("The pipeline at a glance", 2)
T([["Step", "File", "Question it answers", "Output"],
   ["a", "`load.py`", "What is each unit's P2 / P4 error, as a share of its tolerance?", "`v_p2`, `v_p4` (or a reason for none)"],
   ["b", "`check_reject_rule.py`", "Does |v| > 100 match the tester's own reject verdict?", "The reject rule, two device exceptions"],
   ["c", "`features.py`", "What state is each fixture in right now?", "15 numbers per reading"],
   ["d", "`labels.py`", "Which rows show a fixture drifting?", "Label y = 0 / 1, drift episodes"],
   ["e", "`detectors.py`", "How do the features become a score, and the score an alarm?", "Score per row; warning / alarm events"],
   ["f", "`evaluate.py`", "How good is it on data it never saw, at a chosen false-alarm rate?", "Thresholds per budget, test results"],
   ["g", "`alerts.py`", "What would the floor see on real data?", "Saved model; list of warnings and alarms (CSV)"]],
  [1.0, 3.4, 7.4, TEXT_W - 11.8], size=8.5)

H("Data columns used", 2)
T([["Column (WP1 parquet)", "Meaning", "Used for"],
   ["`serialno`", "Unit serial", "Replaced by a keyed hash `unit_key` inside `load.py`; never printed"],
   ["`testtime`", "When the unit was tested", "Time order, time split, drift timing"],
   ["`equipmentid`", "CFT tester machine (20 machines)", "Stream key; the unit that is monitored"],
   ["`fixture`", "Tester fixture 1–10", "Stream key"],
   ["`deviceid`", "Product type (90 devices)", "Stream key; tolerance lookup"],
   ["`attempt_no`", "Attempt number for the serial", "Only `attempt_no == 1` (first pass)"],
   ["`status`, `failed`", "Tester verdict text; failed for any reason", "Reject truth (status family); aborted readings"],
   ["`p2output`, `p2error`, `p2press`, `p2_tested`", "P2 reading, tester-computed error, pressure, test enabled", "The signal `v_p2`"],
   ["`p4…` (same)", "Same for P4", "The signal `v_p4`"],
   ["`p2_rel_dev`, `p2_dev_tol` (and P4)", "WP1 deviation columns", "Only to recover target and tolerance per device"]],
  [4.6, 5.6, TEXT_W - 10.2], size=8.5)
P("**Important:** in this dataset `equipmentid` and `fixture` are the **CFT tester's** machine and fixture "
  "(fixtures run 1–10; one machine tests up to 26 devices; rows carry P1–P5, Vcc, Icc). The team states that "
  "P2/P4 faults originate at **calibration**. A calibration machine ID is expected in the next data delivery; "
  "when it arrives, the streams should be keyed by calibration machine and fixture group instead.")

# ------------------------------------------------------------------ a
H("Step a — load.py: clean P2 / P4 values")
P("**Why:** every later step needs one clean number per unit and signal: how far the unit was from target, "
  "as a share of its tolerance. Step a produces that number, or records exactly why there is none.")
H("What it does", 2)
N(["Reads only the needed columns, first passes only (`attempt_no == 1`).",
   "Recovers each device's target and tolerance from WP1's deviation columns: "
   "`target = output / (1 + rel_dev)`, `tol = (output − target) / dev_tol`. The spread over 73,000 rows is "
   "about 10⁻¹³, so the values are exact (83 P2 devices, 44 P4 devices; cached in `out/limits.csv`).",
   "Computes `v = 100 × error / tol` using the tester's own `error`. 0 = on target, ±100 = at the limit.",
   "Sets `v` to NaN, with a reason in `why_*`, whenever there is no real reading.",
   "Sorts the `status` text into families; `fail_p2` / `fail_p4` mark P2 / P4 output rejects only.",
   "Replaces serial numbers with a keyed hash (salt in `out/.salt`, git-ignored)."])
H("Why some units have no value", 2)
T([["why_p2", "Meaning", "Sample count"],
   ["ok", "A real reading", "114,388"],
   ["not_tested", "This device has no P2 test", "10,394"],
   ["aborted", "Failed at an earlier step; value read without test pressure (output ≈ 660 vs ≈ 3250)", "1,575"],
   ["not_measured", "Output and error both exactly 0", "1,047"],
   ["placeholder", "Dummy value: 65535, 999, output = 0 …", "6"],
   ["no_limits", "No tolerance known for the device", "0"]],
  [2.6, 10.8, TEXT_W - 13.4], size=8.5)
P("A worked row: device 62MPP01-04, P2 output 3255, target 3248, tolerance 20, tester error 3.37 → "
  "`v_p2 = 100 × 3.37 / 20 = 16.9 %` of tolerance. Note that the tester's error is **not** output − target "
  "(that would be 7): the tester computes its own error, and that is what it judges.")
H("Status families", 2)
T([["Family", "Examples", "Counts as P2/P4 output reject?", "Sample count"],
   ["p2_output / p4_output", "6: P2 Error Percent, V_Out_HighP2, P4 High Rail", "Yes", "26 / 27"],
   ["p2p4_pressure", "P2/P4 stability, fill timeout, Mensor", "No (pneumatic)", "918"],
   ["other_fail", "Icc, P1/P3 leak, serial code, prior op …", "No", "2,609"],
   ["good", "GOOD", "—", "123,830"]],
  [3.4, 6.6, 3.6, TEXT_W - 13.6], size=8.5)
H("What the sample shows", 2)
T([["Percentile of v (% tol)", "0.1 %", "1 %", "5 %", "25 %", "50 %", "75 %", "95 %", "99 %", "99.9 %"],
   ["P2", "−54", "−39", "−23", "−10", "+3.6", "+13", "+30", "+48", "+65"],
   ["P4", "−41", "−26", "−12", "−1", "+23", "+33", "+45", "+56", "+65"]],
  [3.4] + [(TEXT_W - 3.4) / 9] * 9, size=8.5)
B(["Healthy units sit well inside the limit (99.9 % within ±65 %), so a slow move towards ±80 % stands out.",
   "P4 runs off-centre (median +23 %), so it has less headroom on the high side.",
   "Output rejects are rare: about 0.02 % of rows in the sample (1 in 5,000). This base rate must always be quoted."])
H("The raw flags: what to trust", 2)
B(["`p2error_missing` was False on every row, even where output = 0 and error = −3254. Placeholders must be "
   "detected from the values, not from WP1's missing flags.",
   "`failed = 1` covers all failure types (147 in two days on one machine, mostly Icc, P1 leak, temperature). "
   "Only the `status` text says whether it was P2/P4 output.",
   "`fx_recent_fail` / `mc_recent_fail` count all failure types; the WP2 features compute their own P2/P4-only rates.",
   "Some rows show `attempt_no` of 4,203+ (one serial reused thousands of times, likely a master part). "
   "They are not first passes, so they do not affect WP2; worth reporting to WP1."])
KEY("every unit now has a clean P2/P4 value in % of tolerance, or a recorded reason why it has none. "
    "Null is never treated as zero.")

# ------------------------------------------------------------------ b
H("Step b — check_reject_rule.py: is |v| > 100 the tester's limit?")
P("**Why:** the model learns 'drifting towards the limit'. That only works if our limit is the one the tester "
  "actually applies. This step compares candidate rules with the tester's verdict (`status`).")
T([["Rule", "Formula", "Source"],
   ["R1", "|error| / tol > 1  (|v| > 100)", "Trace Sentinel's rule"],
   ["R2", "|output − target| / tol > 1", "What WP1's `p*_dev_tol` measures"],
   ["R3", "Best cut-off on |v| per device", "Shows devices with a narrower or wider band"]],
  [1.4, 7.0, TEXT_W - 8.4], size=8.5)
H("Result on the whole train split", 2)
T([["Signal", "Rule", "Caught (TP)", "False flags (FP)", "Missed (FN)", "Precision", "Recall"],
   ["P2", "R1", "6,679", "52", "884", "0.992", "0.883"],
   ["P2", "R2", "6,663", "2,062,005", "900", "0.003", "0.881"],
   ["P4", "R1", "1,243", "5", "3", "0.996", "0.998"],
   ["P4", "R2", "1,088", "917,852", "158", "0.001", "0.873"]],
  [1.6, 1.4, 2.4, 3.0, 2.4, 2.6, TEXT_W - 13.4], size=8.5)
P("Base rates: P2 0.197 % and P4 0.059 % of measured units.")
B(["**R1 is the tester's rule.** When |v| exceeds 100 the tester rejects the unit 99.2–99.6 % of the time.",
   "**R2 is not a limit.** It would flag more than half of all healthy P2 units. Any model built on WP1's "
   "`_dev` columns (including the earlier Isolation Forest scripts in `tests_codes/`) measures distance to the "
   "wrong quantity.",
   "**The 884 P2 misses come from two devices.** 31MPP3-2 is rejected from about 64 % of the snapshot tolerance "
   "(recall 0.14), and 85MPP36-01 had a limit of about 80 % until early June (recall 0.41). Every other device "
   "has recall 1.00. Both are listed in `BAND_EXCEPTIONS` (`band_ok = False`): kept in the features, left out of "
   "scoring and drift injection.",
   "**The 52 false flags failed for another reason first** (29 other, 21 P4 output, 2 pressure): the status "
   "names one failure per unit.",
   "**534 P2 rejects have no reading** (output 0 or 65535). They are rejects (`kind = no_reading`) but give "
   "nothing to track, so the features count only rejects with a reading (`out_of_band`)."])
KEY("the 100 % line in our numbers is the tester's real limit (precision above 99 %), except for two "
    "recorded device periods. The tester's status is used as the reject truth.")

# ------------------------------------------------------------------ c
H("Step c — features.py: the state of each fixture")
P("**Why:** one unit is noise. The model needs the state of the fixture: where it sits against its own normal, "
  "whether it is moving, how close it is to the limit, and whether its neighbours look the same.")
P("A **stream** is one (machine, device, tester fixture, signal). A **set** is all fixtures of one machine on "
  "one device and signal (usually 10); they compare themselves with each other. Each reading updates its "
  "stream's state in constant time and returns 15 numbers.")
H("How the state is kept", 2)
B(["**Warm-up:** the first 120 readings of a stream give its centre (median). The set's noise scale σ starts "
   "at MAD × 1.4826 (minimum 3). No features during warm-up.",
   "**Clipping:** each reading is clipped to ±4σ around its expected value, so one wild value cannot wreck the averages.",
   "**Three moving averages:** spans of 30, 100 and 300 units (short, medium, long).",
   "**Machine-wide move:** the median move of the other warm fixtures of the same set away from their own "
   "centres. Subtracting it cancels lot changes and machine wander. The median keeps one drifting neighbour "
   "from dragging the reference.",
   "**Frozen centre:** the centre learns very slowly (span 1,500), and only while the fixture looks normal "
   "(|d_m| < 0.35 and CUSUM < 4). While displaced it is frozen, so a drift is not absorbed; a shift that lasts "
   "more than 600 units is gradually accepted as the new normal.",
   "**CUSUM:** per reading, z = (v − centre − machine move) / (σ × infl), clipped to ±4; "
   "cp = max(0, cp + z − 0.5) and cn likewise downwards, capped at 40. The last time it was 0 is the estimated drift start.",
   "**Idle restart:** a stream idle for 12 h (device changeover) restarts its averages and CUSUM at its centre."])
H("The 15 features", 2)
T([["#", "Feature", "Meaning", "Healthy 1 % / median / 99 %"],
   ["1–3", "d_s, d_m, d_l", "Departure from own centre minus machine move, in σ, at 30 / 100 / 300 units", "±0.43 / 0 / ±0.41 (d_s)"],
   ["4–5", "abs_d_s, abs_d_m", "Size of the departure, either direction", "0 / 0.10 / 0.48"],
   ["6", "trend", "(d_s − d_l) / 135 × 100: still moving? positive = towards the nearer limit", "−0.26 / 0 / 0.29"],
   ["7", "toward", "+1 if the departure points towards the nearer limit, −1 if away", "−1 / +1 / +1"],
   ["8", "cusum", "Accumulated small persistent shift (max of both sides)", "0 / 0 / 7.2"],
   ["9", "headroom", "(100 − |level|) / 100, room left to the limit", "0.53 / 0.88 / 0.99"],
   ["10", "eta_log", "log10 of projected units to the limit (5 = not heading out)", "2.8 / 5.0 / 5.0"],
   ["11", "near_g", "Share of recent units at 80–100 % of tolerance", "0 / 0 / 0.01"],
   ["12–13", "near_diff, rej_diff", "Near-limit and reject rates minus the other fixtures'", "≈ 0"],
   ["14", "rej_w200", "Rejects in the last 200 units (count rule input)", "0 / 0 / 1"],
   ["15", "warm", "min(1, n / 360): how settled the stream is", "0.36 / 1 / 1"]],
  [1.1, 3.0, 8.2, TEXT_W - 12.3], size=8.5)
P("The 135 in `trend` is the lag gap between a span-30 average (lag ≈ 14.5 units) and a span-300 average "
  "(lag ≈ 149.5), so (short − long) / 135 is a slope per unit.")
H("Demo results", 2)
P("212,470 readings → 188,455 feature rows (24,015 used for warm-up) in 23 s (110 µs per reading); "
  "188 streams in 19 sets. Healthy CUSUM is above 10 only 0.6 % of the time. Typical σ is 3–12 % of "
  "tolerance; the machine-wide move ranges up to −16 … +13 % of tolerance.")
T([["Test", "Where", "Mean v", "shift_pct", "machine_move", "d_m", "CUSUM p95"],
   ["+40 % step on fixture 4 only", "fixture 4, before", "8.9", "0.0", "−0.1", "0.00", "0.75"],
   ["", "fixture 4, after", "54.5", "15.1", "4.1", "1.54", "40.0"],
   ["", "other fixtures, after", "14.7", "−0.1", "4.2", "−0.01", "0.06"],
   ["+40 % step on every fixture", "fixture 4, after", "54.5", "−0.2", "40.2", "−0.02", "23.6"],
   ["", "other fixtures, after", "54.7", "−0.2", "40.1", "−0.03", "24.1"]],
  [4.2, 3.6, 1.6, 1.9, 2.3, 1.4, TEXT_W - 15.0], size=8.5)
B(["**One fixture drifting** (machine 9990771, device 62MPP03-04, P2, from 8 June): fixture 4 stands out "
   "(d_m 1.5σ on average, CUSUM at its cap) while the other nine stay at 0. A real machine move of about "
   "+4 % happened at the same time and was removed from every fixture.",
   "shift_pct averages 15, not 40, because the step was never recalibrated: after 600 units the frozen centre "
   "starts to accept it. An alarm comes long before that.",
   "**Every fixture drifting:** the machine-wide move absorbs the whole +40 %, so d_m stays at 0. CUSUM jumps "
   "briefly only because the neighbours' average lags a sudden step; a slow ramp on all fixtures would stay "
   "hidden. **This is a blind spot:** a whole-machine fault (pressure reference, temperature, calibration "
   "standard) is cancelled by design and needs a machine-level detector."])
H("Changes from the reference", 2)
T([["", "Trace Sentinel", "WP2", "Why"],
   ["Stream", "(cal machine, group 1–4, signal)", "(CFT machine, device, fixture 1–10, signal)", "Data has tester machine/fixture; many devices per machine"],
   ["Peers", "3 other groups", "up to 9 fixtures, same device", ""],
   ["Reset", "recalibration records", "12 h idle restart", "No recalibration records"],
   ["Reject flag", "|v| > 100", "tester status, readings only", "Checked in step b"],
   ["CUSUM noise", "units assumed independent", "`infl` ≈ 2 (1.6–4.4)", "Units are correlated; healthy CUSUM sat above 10 a third of the time"],
   ["Trend sign", "trend × toward", "trend × sign(level)", "Fixes a sign error for drifts on the negative side"]],
  [2.4, 4.0, 4.4, TEXT_W - 10.8], size=8.5)
KEY("the features catch a fixture leaving its own normal and ignore whole-machine wander. The price is that "
    "a fault on every fixture at once is hidden.")

# ------------------------------------------------------------------ d
H("Step d — labels.py: what 'drifting' looks like")
P("**Why:** a supervised model needs rows marked 1 (drifting) and 0 (healthy). The plant keeps no record of "
  "when a fixture drifted, so labels must be made.")
H("Way 1: reject-cluster label (real data)", 2)
P("A row is 1 if its stream has at least 3 out-of-band rejects in its next 200 units. On the sample: P2 10 real "
  "rejects → 222 positive rows (0.22 %); P4 16 rejects → 247 rows (0.28 %). Only **one fixture** in two weeks "
  "had a cluster (machine 20190405, device 81MPP18-01, fixture 8), on **P2 and P4 together**, which points to "
  "the fixture itself.")
P("This label is too rare and too crude to train on (all 200 rows before a cluster count as 1). It is used to "
  "score the detectors against real faults.")
H("Way 2: known drifts added to healthy real data (used for training)", 2)
T([["Choice", "Rule", "Why"],
   ["Start point", "≥ 360 readings before; no real reject 24 h before to 14 h after; 24 h since the last episode on the machine; band_ok", "Settled features; no mixing with real rejects; one drift at a time"],
   ["Frequency", "0.5 per machine per day on average", "Enough examples without filling the data"],
   ["Shape", "Step +30–70 % tol, or ramp +6–28 % tol per hour (cap 170); 'small': step 10–30 %, ramp 1–6 %/h", "Large = Trace Sentinel's ranges; small finds the detection limit"],
   ["Direction", "The side the fixture already leans to (sign of its last 300 readings)", "A fixture at +20 is closer to +100"],
   ["End", "After the 5th drift reject (recalibrated) or after 14 h", "How the floor works today"],
   ["Tester behaviour", "A P2 reject makes P4 not measured", "As on the real tester"],
   ["Label", "1 once the drift has moved the unit ≥ 10 % of tolerance", "Smaller shifts are hidden in noise (σ ≈ 3–11 %)"]],
  [2.6, 7.6, TEXT_W - 10.2], size=8.5)
H("Demo results", 2)
P("13 episodes were added to the sample; 8 reached a reject, 6 ended after 5 rejects; 32 rejects added; "
  "1,165 positive rows of 188,443 (base rate 0.62 %). Examples:")
T([["Episode", "Shape", "Units to first reject", "Reading"],
   ["0", "ramp 18 %/h, downwards", "44", "The early-warning window: 44 units to alarm before damage"],
   ["6", "ramp 11 %/h, upwards", "116", "Slower drift: more time, harder to see"],
   ["5", "step +55 % on P4", "none", "Moved to ≈ 78 %: near the limit, never rejected, still labelled 1"],
   ["8", "step +68 %, downwards", "123 (1 reject)", "Ended by the 14 h routine"]],
  [1.8, 4.0, 3.2, TEXT_W - 9.0], size=8.5)
T([["Median per row type", "d_s", "d_m", "abs_d_m", "trend", "cusum", "headroom", "rej_w200"],
   ["drift (label 1)", "−2.59", "−1.26", "2.22", "1.55", "40.0", "0.71", "0"],
   ["episode, < 10 % moved", "−0.06", "−0.01", "0.09", "0.14", "0.0", "0.89", "0"],
   ["healthy", "0.00", "0.00", "0.06", "0.00", "0.0", "0.88", "0"]],
  [4.0] + [(TEXT_W - 4.0) / 7] * 7, size=8.5)
B(["Label-1 rows are clearly different from healthy rows: 2.2σ departure, CUSUM at cap, less headroom.",
   "`trend` is +1.55 although these drifts go down: the sign fix from step c working.",
   "Rows moved by less than 10 % look healthy, which justifies the 10 % cut-off.",
   "The median drift row has **no reject** in its last 200 units: the count rule cannot see it, but trend and "
   "CUSUM can. This is the head start over today's rule."])
P("**Main assumption:** a real drift looks like a step or ramp added to normal readings. A real fault may also "
  "add noise or come and go. Real recalibration records are needed to test this.")
KEY("labels come from known drifts added to real healthy data, so the model learns against real noise, real "
    "machine wander and real correlation between units.")

# ------------------------------------------------------------------ e
H("Step e — detectors.py: from features to a score to an alarm")
P("**Why:** the features describe the fixture; a detector turns them into one score per reading, and the alarm "
  "tracker turns scores into warnings and alarms that an operator can act on.")
H("The three detectors", 2)
T([["Detector", "Score", "Training", "Default thresholds"],
   ["Count rule (today's practice)", "rej_w200 / 3: 1.0 = 3 rejects in the last 200 units", "None", "alarm 1.0, no persistence"],
   ["CUSUM", "cusum × (toward > 0) × warm: only shifts towards the limit count", "None", "warning 6, alarm 10"],
   ["Trained trees (the model)", "Probability of drifting from HistGradientBoostingClassifier on the 15 features; 0 until warm ≥ 0.34", "Yes, on labelled rows", "warning 0.5, alarm 0.8"]],
  [3.6, 7.2, 2.4, TEXT_W - 13.2], size=8.5)
P("Trees: 250 trees, 31 leaves, learning rate 0.06, L2 regularisation 1.0. Positive rows are weighted "
  "min(20, negatives / positives) so that 'never drifting' is not an easy answer.")
H("The alarm tracker", 2)
B(["**Raise:** 3 consecutive scores at or above the warning (or alarm) threshold → warning (or alarm). One noisy reading cannot raise anything.",
   "**Latch:** an alarm stays while the score dips.",
   "**Clear:** 60 consecutive scores below 80 % of the warning threshold.",
   "One tracker state per stream (machine, device, fixture, signal)."])
H("Demo: train on week 1, score week 2", 2)
P("19 episodes were added (1 per machine per day): 9 in week 1 for training, 10 in week 2 for scoring. "
  "Training: 107,059 rows, 761 positives (base rate 0.71 %); 1,314 rows in reject clusters not explained by an "
  "added drift were left out (their truth is unknown). Week 2: 80,381 rows, base rate 1.45 %, 3 machines × 7 days. "
  "Thresholds are the defaults, **not tuned** (tuning is step f).")
T([["Measure", "Count rule", "CUSUM", "Trained trees"],
   ["Row-level PR-AUC (random = 0.0145)", "0.015", "0.948", "0.980"],
   ["Drifts detected (alarm)", "20 %", "90 %", "90 %"],
   ["Alarm before the first reject (3 drifts had rejects)", "0 of 3", "3 of 3", "3 of 3"],
   ["Median units until alarm", "47", "11", "5"],
   ["False alarms per machine per day", "0.05", "0.48", "0.05"],
   ["False warnings per machine per day", "0", "0.76", "0"]],
  [6.8, 3.0, 3.0, TEXT_W - 12.8], size=8.5)
B(["The count rule is no better than random at row level (PR-AUC equals the base rate): it only reacts after rejects.",
   "CUSUM needs no training and already catches most drifts early, but at about ten times the false alarms of the trees.",
   "The trees catch the same drifts sooner (median 5 units) with the count rule's false-alarm level.",
   "Ten episodes is a small sample; the full 20-machine evaluation in step f gives the reliable numbers "
   "(trained trees at 0.5 false alarms per machine per day: 87 % detected, 71 % before the first reject, "
   "85 % of drift rejects avoidable)."])
T([["Feature", "abs_d_s", "cusum", "abs_d_m", "trend", "near_g", "near_diff", "eta_log", "headroom"],
   ["|correlation| with label", "0.84", "0.75", "0.73", "0.67", "0.54", "0.52", "0.21", "0.19"]],
  [3.6] + [(TEXT_W - 3.6) / 8] * 8, size=8.5)
P("A rough view of what the trees use: the size of the departure, CUSUM and trend carry most of the signal; the "
  "reject count (`rej_w200`, 0.09) carries almost none, since it reacts only after damage.")
KEY("the trained trees turn the same features into earlier alarms than CUSUM at a far lower false-alarm rate, "
    "and the alarm tracker keeps single readings from raising alarms.")

# ------------------------------------------------------------------ f
H("Step f — evaluate.py: tuning and the honest test")
P("**Why:** step e used default thresholds and a single week. Step f answers the real question: on data the "
  "model never saw, at a false-alarm rate the floor can live with, how many drifts are caught and how early?")
H("The split by time", 2)
T([["Slice", "Dates", "Used for"],
   ["fit", "train split, before 2 July", "Training the trees"],
   ["tune", "train split, 2–23 July (end of train)", "Choosing thresholds per false-alarm budget"],
   ["test", "WP1 test split, 23 July – 12 August", "Scored once, at the end; never used for any choice"]],
  [2.0, 6.0, TEXT_W - 8.0], size=8.5)
P("The WP1 train/test split is never re-drawn; validation is carved from the end of train, by time. Drifts are "
  "added to every slice (step d), with large and small episodes. Rows in real reject clusters not explained by "
  "an added drift are left out of training, since their truth is unknown.")
H("Tuning to a false-alarm budget", 2)
B(["A **budget** is the number of false alarms per machine per day the floor accepts: 0.1, 0.25, 0.5, 1 or 2.",
   "For each budget, the alarm threshold is found by bisection on the tune slice: the lowest score threshold "
   "whose false alarms (alarms outside any drift episode) stay within the budget. Candidates come from a "
   "grid of score quantiles; up to 3 million healthy rows are used.",
   "The warning threshold uses a looser budget, max(2, 2 × budget), so warnings come earlier and more often.",
   "The count rule has no threshold to tune (3 rejects in 200 units)."])
H("What is measured", 2)
T([["Metric", "Meaning"],
   ["FA / machine / day", "Alarms raised outside any drift episode, per machine per day (the budget check)"],
   ["Detected", "Share of added drifts that raised an alarm before the episode ended"],
   ["Before first reject", "Of drifts that produced a reject, share alarmed before it"],
   ["Delay", "Median units (and hours) from the drift start to the alarm"],
   ["Avoidable", "Share of drift rejects that came after the alarm"],
   ["Real clusters", "Real groups of ≥ 3 rejects in 200 units: detected, and before the first / third reject"]],
  [3.8, TEXT_W - 3.8], size=8.5)
H("Results on the 3-machine sample (test slice)", 2)
P("26 added drifts (15 large, 11 small), 5 real reject clusters; base rate 1.22 % of rows. Row-level PR-AUC: "
  "count rule 0.015, CUSUM 0.878, trained trees 0.973.")
T([["Detector at budget 0.5", "FA / m / day", "Detected", "Before 1st reject", "Delay (units / h)", "Avoidable", "Small drifts detected", "Real clusters detected"],
   ["Count rule", "0.016", "38 %", "0 %", "90 / 7.3", "37 %", "9 %", "5 of 5 (none before 1st reject)"],
   ["CUSUM", "0.145", "81 %", "100 %", "12 / 0.76", "100 %", "55 %", "4 of 5"],
   ["Trained trees", "0.096", "92 %", "100 %", "11.5 / 0.58", "100 %", "82 %", "0 of 5"]],
  [3.2, 1.8, 1.7, 1.9, 2.0, 1.7, 1.9, TEXT_W - 14.2], size=8)
P("Tuned thresholds for the trees at 0.5: warning 0.048, alarm 0.388 (much lower than the defaults of step e).")
H("Results on all 20 machines (test slice)", 2)
P("153 added drifts, 107 real reject clusters; 1.24 million test rows, base rate 1.49 %. PR-AUC: count rule "
  "0.015, CUSUM 0.797, trained trees 0.947.")
T([["Detector", "Budget", "FA / m / day", "Detected", "Before 1st reject", "Delay (units / h)", "Avoidable", "Real: detected / before 1st"],
   ["Count rule", "—", "0.08", "36 %", "0 %", "54 / 4.1", "38 %", "96 % / 15 %"],
   ["CUSUM", "0.5", "0.39", "84 %", "61 %", "13 / 0.81", "82 %", "19 % / 1.9 %"],
   ["Trained trees", "0.1", "0.03", "84 %", "73 %", "12 / 0.76", "84 %", "3.7 % / 2.8 %"],
   ["Trained trees", "0.5", "0.20", "87 %", "71 %", "9 / 0.49", "85 %", "11 % / 3.7 %"],
   ["Trained trees", "2", "1.47", "85 %", "69 %", "8 / 0.42", "81 %", "62 % / 41 %"]],
  [2.6, 1.4, 1.9, 1.7, 2.0, 2.2, 1.8, TEXT_W - 13.6], size=8)
B(["**On added drifts the trees win clearly.** At 0.5 false alarms per machine per day they catch 87 % of "
   "drifts, 71 % before any reject, about half an hour after the drift starts; 85 % of drift rejects would have "
   "been avoidable. The count rule catches 36 % and never before a reject.",
   "**The budget holds.** Measured false alarms (0.20) stay within the budget chosen on the tune slice (0.5).",
   "**On real reject clusters the trees are weak.** They detect only 11 % of the 107 real clusters at budget 0.5. "
   "The count rule detects 96 %, but only after the rejects, by definition. The main report finds that 64 % of real "
   "clusters are **machine-wide**: several fixtures together, which the features cancel by design (step c).",
   "**The sample and the full run agree on direction**, but the sample's 100 % before-first-reject comes from "
   "only a handful of drifts with rejects; quote the 20-machine numbers."])
KEY("on known drifts the trees give a real head start at a false-alarm rate the floor can accept. Real faults are "
    "mostly machine-wide, so the next model must look at the machine as a whole.")

# ------------------------------------------------------------------ g
H("Step g — alerts.py: the saved model and the alert list")
P("**Why:** `evaluate.py` measures the model and throws it away. `alerts.py` is the part one would run: it saves "
  "the model, then scores **real** data (nothing added) and lists the warnings and alarms an operator would see.")
H("Two modes", 2)
T([["Command", "What it does", "Output"],
   ["`python alerts.py --train`", "Fits the trees on the fit slice (same exclusions as step f), tunes thresholds on the tune slice for one budget (`--budget`, default 0.5)", "`out/model_<tag>.joblib`: trees, feature names, thresholds, persistence, budget, rows and end date of the fit"],
   ["`python alerts.py`", "Loads one split and window (default: test, 23 July – 12 August), replays the features, scores with the saved trees (or `--detector cusum`, no training), runs the alarm tracker", "`out/alerts_<split>_<detector>_<tag>.csv`: one row per warning or alarm"]],
  [3.8, 7.4, TEXT_W - 11.2], size=8.5)
P("On the sample: trees fitted on 954,054 rows; thresholds at 0.5 false alarms per machine per day: warning "
  "0.048, alarm 0.388. Each stream needs about 120 units to warm up, so for a short window start a day early "
  "with `--start` and hide early alerts with `--report-from`.")
H("The alert list", 2)
T([["Column", "Meaning"],
   ["`raised`, `level`", "When the alert was raised; warning or alarm"],
   ["`equipmentid`, `deviceid`, `fixture`, `signal`", "Where to look"],
   ["`drift_start`", "CUSUM's estimate of when the shift began: the start of a rework list"],
   ["`shift_pct`", "How far the fixture moved from its own centre, machine-wide move removed (% tol)"],
   ["`level_pct`", "Where the fixture sits now (% tol)"],
   ["`units_to_limit`", "At the current trend, units until the limit (empty if not heading out)"],
   ["`score`", "The trees' probability when raised"],
   ["`band_ok`", "False for the two devices with a different limit (step b)"],
   ["`cleared`", "When it went back to ok (empty = still open)"]],
  [5.2, TEXT_W - 5.2], size=8.5)
H("What it found on real data (3 machines, test split)", 2)
P("143,741 first passes; **14 alarms, 71 warnings** (P2 51, P4 34); 2 still open at the end. By machine: "
  "9990675 49, 9990771 26, 20190405 10. The median alarm is raised 0.3 h after its estimated drift start.")
T([["Raised", "Machine", "Device", "Fixture", "Signal", "shift_pct", "level_pct", "units_to_limit"],
   ["26 Jul 09:50", "9990675", "85MPP37-01", "6", "P2", "−3.5", "−28.2", "928"],
   ["9 Aug 10:32", "9990771", "62MPP04-04", "3", "P2", "+1.8", "+43.1", "619"],
   ["9 Aug 10:37", "9990771", "62MPP04-04", "5", "P2", "+0.8", "+42.8", "648"],
   ["10 Aug 00:48", "9990771", "62MPP04-04", "6", "P2", "+2.0", "+38.4", "705"],
   ["11 Aug 09:50", "9990771", "62MPP04-04", "4", "P2", "+1.4", "+30.9", "646"],
   ["11 Aug 23:24", "9990771", "62MPP04-04", "7", "P2", "+1.4", "+30.8", "722"]],
  [2.4, 1.8, 2.4, 1.4, 1.4, 1.9, 1.9, TEXT_W - 13.2], size=8.5)
B(["**Alerts bunch together.** On 9990771 / 62MPP04-04, alarms came on fixtures 3–7 within three days, all at "
   "+30 to +43 % of tolerance and rising. On 9990675 / 85MPP37-01 the warnings cover fixtures 2–4, 6–8 and 10, all at "
   "−25 to −31 %. Each fixture alone looks only slightly off (`shift_pct` 1–3 %); together they show the "
   "**whole set moving**, the machine-wide pattern from step f.",
   "For the dashboard, alerts should be **grouped by machine and device**, not shown as separate fixture rows.",
   "Warnings are tuned to a looser budget (2 per machine per day), so they are early and noisy by design: "
   "about 1.2 per machine per day here."])
H("Did real rejects follow? (a check outside alerts.py)", 2)
T([["", "Count", "Reject on the same fixture within 24 h", "Reject on any fixture of the same machine, device and signal within 24 h"],
   ["Alarms", "14", "1", "6"],
   ["Warnings", "71", "1", "15"]],
  [2.4, 1.6, 5.0, TEXT_W - 9.0], size=8.5)
B(["Almost nothing follows on the same fixture, but 6 of 14 alarms come before a reject somewhere on the same "
   "set: real trouble is machine-wide again.",
   "**No reject afterwards does not mean a false alarm.** A set at +40 % with about 650 units to go may not reach "
   "the limit within the window. Without recalibration records, right and wrong alarms cannot be told apart.",
   "Device 41MPP2-15 on 20190405 had 39 real P2 rejects and **no alerts**. Unconfirmed guess: its rejects are "
   "spread across fixtures (the machine-wide blind spot) or fall in warm-up. Worth checking before the list is trusted."])
P("The saved joblib file plus the CSV is the interface to WP4: the Streamlit tab can read `alerts_*.csv`, or "
  "load the model and score new data itself.")
KEY("the model can be saved and run on real data, and its alerts point to sets of fixtures moving together. "
    "Grouping by machine and device, and real recalibration records, are the next steps.")

# ------------------------------------------------------------------ open points
H("Open points")
T([["Topic", "Status", "Effect on WP2"],
   ["Calibration machine ID", "Expected in the next data delivery", "Key streams by calibration machine and fixture group (the source of P2/P4 faults)"],
   ["Timestamps on calibration", "Being obtained", "Label drifts by calibration time, as the reference does"],
   ["Recalibration records", "Being obtained", "Real training labels and resets, replacing added drifts"],
   ["Whole-machine blind spot", "Confirmed in steps c, f and g", "Needs a machine-level detector: group alerts by machine and device, alarm when several fixtures move together"],
   ["Alert list truth", "Unknown (step g)", "Shadow mode with a 'mark recalibrated' button would tell right alarms from false ones"],
   ["41MPP2-15 on 20190405", "39 real P2 rejects, no alerts (step g)", "Check whether its rejects are spread across fixtures or fall in warm-up"],
   ["DPSCFTLimits file", "Not on disk", "Recovered tolerances are exact; the two band exceptions could be checked against it"]],
  [3.8, 4.8, TEXT_W - 8.6], size=8.5)

H("Glossary", 2)
T([["Term", "Meaning"],
   ["% of tolerance (v)", "100 × tester error / device tolerance; ±100 is the reject limit"],
   ["Stream", "One (machine, device, tester fixture, signal) sequence of readings"],
   ["σ (sigma)", "Normal unit-to-unit spread of a set, in % of tolerance"],
   ["Machine-wide move", "Median move of the other fixtures of the same machine and device; subtracted to cancel lot changes"],
   ["CUSUM", "Cumulative sum that grows with a small persistent shift and resets to 0 when there is none"],
   ["Base rate", "Share of rows that are positive; a random score has PR-AUC equal to it"],
   ["PR-AUC", "Area under the precision–recall curve; 1 = perfect ranking of drifting rows"],
   ["False-alarm budget", "Allowed false alarms per machine per day; thresholds are tuned to it in step f"],
   ["Avoidable rejects", "Share of drift rejects that come after the alarm, so a recalibration at the alarm would have saved them"]],
  [3.8, TEXT_W - 3.8], size=8.5)

zoom = doc.settings.element.find(qn("w:zoom"))      # python-docx template omits the required percent
if zoom is not None:
    zoom.set(qn("w:percent"), "100")
doc.save(OUT)
print("saved", OUT)
