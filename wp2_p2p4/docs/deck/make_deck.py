"""Builds wp2_p2p4/docs/deck/WP2_Drift_Monitor.pptx (python-pptx): what WP2 does, what it found, the local
monitor app, and what is needed next. Every element is native (text, shapes, table, chart) and editable in
PowerPoint; screenshots are in img/ (serial numbers covered in row_flags.png). Numbers come from
out/eval_all_s0.csv, the 3-machine alert run and the checks in the progress report.

    uv run --no-project --with python-pptx python docs/deck/make_deck.py docs/deck/WP2_Drift_Monitor.pptx
"""
import os
import sys

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_LABEL_POSITION
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt, Emu

OUT = sys.argv[1]
IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "img")

INK, MUTED, PAPER, PANEL = "1B2430", "5B6573", "FFFFFF", "F1F4F7"
RED, AMBER, TEAL, GREY = "D64545", "E9A23B", "1F8A70", "9AA5B1"
FONT = "Calibri"

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
TITLE_ONLY = prs.slide_layouts[5]


def rgb(h):
    return RGBColor.from_string(h)


def text(slide, x, y, w, h, runs, size=16, color=INK, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
         name=None, space_after=6):
    """runs: a string, or a list of paragraphs; a paragraph is a string or a list of (text, {bold, color, size})."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    paras = [runs] if isinstance(runs, str) else runs
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space_after)
        for t, o in ([(para, {})] if isinstance(para, str) else para):
            r = p.add_run()
            r.text = t
            f = r.font
            f.name, f.size = FONT, Pt(o.get("size", size))
            f.bold = o.get("bold", bold)
            f.italic = o.get("italic", False)
            f.color.rgb = rgb(o.get("color", color))
    return tb


def box(slide, x, y, w, h, fill, shape=MSO_SHAPE.ROUNDED_RECTANGLE, line=None, name=None):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = rgb(fill)
    if line:
        s.line.color.rgb = rgb(line)
        s.line.width = Pt(1)
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = 0.08
    if name:
        s.name = name
    return s


def chip(slide, x, y, d, label, fill, size=16):
    """The deck's motif: a step letter or number in a coloured circle."""
    c = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(d), Inches(d))
    c.fill.solid(); c.fill.fore_color.rgb = rgb(fill); c.line.fill.background(); c.shadow.inherit = False
    tf = c.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = label
    r.font.name, r.font.size, r.font.bold = FONT, Pt(size), True
    r.font.color.rgb = rgb(PAPER)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    return c


def slide(title, dark=False, notes=""):
    s = prs.slides.add_slide(TITLE_ONLY)
    bg = s.background.fill
    bg.solid(); bg.fore_color.rgb = rgb(INK if dark else PAPER)
    t = s.shapes.title
    t.left, t.top, t.width, t.height = Inches(0.6), Inches(0.4), Inches(12.1), Inches(0.9)
    tf = t.text_frame
    tf.margin_left = tf.margin_right = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.text = title
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.LEFT
    for r in p.runs:
        r.font.name, r.font.size, r.font.bold = FONT, Pt(34), True
        r.font.color.rgb = rgb(PAPER if dark else INK)
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    return s


def picture(s, name, x, y, w=None, h=None, alt=""):
    pic = s.shapes.add_picture(os.path.join(IMG, name), Inches(x), Inches(y),
                               Inches(w) if w else None, Inches(h) if h else None)
    pic.line.color.rgb = rgb("D0D6DD"); pic.line.width = Pt(0.75)
    pic.name = name.split(".")[0]
    pic._element.nvPicPr.cNvPr.set("descr", alt)
    return pic


# =============================================================== 1. title
s = prs.slides.add_slide(prs.slide_layouts[6])
s.background.fill.solid(); s.background.fill.fore_color.rgb = rgb(INK)
chip(s, 0.8, 1.55, 0.7, "P2", RED, 16); chip(s, 1.6, 1.55, 0.7, "P4", AMBER, 16)
text(s, 0.8, 2.55, 11.5, 1.6, [[("Catching P2 / P4 drift before the rejects", {"size": 44, "bold": True, "color": PAPER})]])
text(s, 0.8, 4.15, 11.0, 0.9, [[("WP2 · near-threshold early warning: what the pipeline does, what it found, and what it "
                                 "needs next", {"size": 20, "color": "C9D1DA"})]])
text(s, 0.8, 6.3, 11.0, 0.5, [[("Irfan Ramizu · Sensata CFT project · Work Package 2 · November 2026",
                                 {"size": 14, "color": GREY})]])
s.notes_slide.notes_text_frame.text = (
    "WP2 looks at the P2 and P4 output tests only. The aim is to see a fixture drifting towards its limit before "
    "units are rejected, and to tell the operator which machine and fixture to check.")

# =============================================================== 2. the idea
s = slide("WP2 alarms while the error is still moving",
          notes="Left: today's practice is a count rule, 3 rejects in the last 200 units. By definition it only fires "
                "after damage. Right: WP2 follows each fixture's error as a percentage of its tolerance and raises an "
                "alarm when it starts moving away from its own normal, typically about 9 units after the drift starts.")
text(s, 0.6, 1.6, 5.9, 4.8, [
    [("Every unit gets one number per signal", {"bold": True, "size": 18})],
    [("v = 100 × tester error ÷ device tolerance. 0 is on target, ±100 is the reject limit.", {})],
    [("Today: the count rule", {"bold": True, "size": 18})],
    [("Alarm when a fixture has 3 rejects in its last 200 units. It always fires after the damage is done.", {})],
    [("WP2: watch the movement", {"bold": True, "size": 18})],
    [("Each fixture is compared with its own normal and with its neighbours on the same machine. A steady move "
      "towards the limit raises a warning, then an alarm, before units fail.", {})]], size=16, space_after=10)
# diagram: one fixture's error over time
px, py, pw, ph = 7.0, 1.6, 5.75, 4.9
box(s, px, py, pw, ph, PANEL, name="diagram panel")
x0, x1 = px + 0.45, px + pw - 0.35
y_lim, y80, y0 = py + 0.75, py + 1.35, py + 3.75
band = box(s, x0, y_lim, x1 - x0, y80 - y_lim, "FBE7C6", shape=MSO_SHAPE.RECTANGLE, name="near-limit band")
lim = s.shapes.add_connector(1, Inches(x0), Inches(y_lim), Inches(x1), Inches(y_lim))
lim.line.color.rgb = rgb(RED); lim.line.width = Pt(2)
for yy in (y0,):
    c = s.shapes.add_connector(1, Inches(x0), Inches(yy), Inches(x1), Inches(yy))
    c.line.color.rgb = rgb(GREY); c.line.width = Pt(1); c.line.dash_style = MSO_LINE_DASH_STYLE.DASH
text(s, x0, y_lim - 0.38, 3.5, 0.3, [[("+100 % reject limit", {"size": 12, "bold": True, "color": RED})]])
text(s, x0 + 0.05, y80 - 0.32, 3.0, 0.3, [[("80–100 % near the limit", {"size": 12, "color": "9A6A12"})]])
text(s, x0, y0 + 0.08, 2.5, 0.3, [[("0 % on target", {"size": 12, "color": MUTED})]])
pts, n = [], 60
for i in range(n + 1):
    f = i / n
    xx = x0 + 0.05 + f * (x1 - x0 - 0.15)
    wob = 0.12 * (1 if i % 2 else -1) * (0.6 if i % 3 else 1.0)
    yy = y0 + wob if f < 0.42 else y0 + wob * 0.6 - (f - 0.42) / 0.58 * (y0 - y_lim + 0.3)
    pts.append((Inches(xx), Inches(yy)))
ff = s.shapes.build_freeform(pts[0][0], pts[0][1], scale=1.0)
ff.add_line_segments(pts[1:], close=False)
path = ff.convert_to_shape(); path.name = "fixture error"
path.fill.background(); path.line.color.rgb = rgb(INK); path.line.width = Pt(2.25)
for xx, yy in pts:
    if yy < Inches(y_lim):
        d = Inches(0.13)
        dot = s.shapes.add_shape(MSO_SHAPE.OVAL, xx - d // 2, yy - d // 2, d, d)
        dot.fill.solid(); dot.fill.fore_color.rgb = rgb(RED); dot.line.fill.background()


def marker(xa, label, color, top, shift=0.0):
    m = s.shapes.add_connector(1, Inches(xa), Inches(py + 0.35), Inches(xa), Inches(py + ph - 0.75))
    m.line.color.rgb = rgb(color); m.line.width = Pt(1.75); m.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    text(s, xa - 1.25 + shift, top, 2.5, 0.6, [[(label, {"size": 12, "bold": True, "color": color})]], align=PP_ALIGN.CENTER,
         space_after=0)


marker(x0 + 0.48 * (x1 - x0), "WP2 alarm\n~9 units after the start", TEAL, py + ph - 0.68)
marker(x1 - 0.1, "Count rule\nafter 3 rejects", MUTED, py + ph - 0.68, shift=-0.35)

# =============================================================== 3. pipeline
s = slide("Seven steps turn raw tester rows into an alert",
          notes="Each step is one Python file in wp2_p2p4. a and b make the value trustworthy, c describes each "
                "fixture, d makes training labels, e scores and raises alarms, f measures it fairly, g saves the "
                "model and lists alerts. The app runs a, c, e and g live.")
steps = [("a", "Clean", "load.py", "v in % of tolerance, or the reason there is none"),
         ("b", "Check", "check_reject_rule.py", "|v| > 100 is the tester's real limit"),
         ("c", "Describe", "features.py", "15 numbers per fixture: departure, trend, CUSUM, headroom"),
         ("d", "Label", "labels.py", "known drifts added to healthy real data"),
         ("e", "Score", "detectors.py", "count rule, CUSUM, trained trees; alarm tracker"),
         ("f", "Measure", "evaluate.py", "split by time; thresholds set by a false-alarm budget"),
         ("g", "Alert", "alerts.py", "saved model; warning / alarm list")]
cw, gap, top = 1.62, 0.13, 1.85
for i, (k, head, f, body) in enumerate(steps):
    x = 0.6 + i * (cw + gap)
    box(s, x, top, cw, 3.55, PANEL, name=f"step {k}")
    chip(s, x + 0.2, top + 0.22, 0.6, k, TEAL if k in "ceg" else INK, 18)
    text(s, x + 0.2, top + 1.0, cw - 0.35, 0.45, [[(head, {"bold": True, "size": 18})]])
    text(s, x + 0.2, top + 1.45, cw - 0.3, 0.35, [[(f, {"size": 11, "color": MUTED})]])
    text(s, x + 0.2, top + 1.85, cw - 0.32, 1.6, [[(body, {"size": 14})]])
box(s, 0.6, 5.75, 12.1, 0.95, "E6F2EE", name="app note")
text(s, 0.85, 5.75, 11.6, 0.95, [[("The live monitor (", {}), ("live.py", {"bold": True}), (" + ", {}),
                                    ("app.py", {"bold": True}),
                                    (") runs steps a, c, e and g row by row and gives exactly the same alerts as "
                                     "alerts.py (85 of 85).", {})]], size=16, anchor=MSO_ANCHOR.MIDDLE)

# =============================================================== 4. data facts
s = slide("The data confirmed the cleaning rules",
          notes="Four checks that make the value v trustworthy. The limits we worked out from WP1's columns match "
                "the real DPSCFTLimits file on every device. Our 100 % line matches the tester's own verdict. A P4 "
                "value of 0 after a P2 reject means the test stopped, not a perfect reading. And 80 % of tolerance "
                "is reached by healthy units only about 1 in 220 times.")
facts = [("127 / 127", "device limits match the real limits file (DPSCFTLimits.rpt)", TEAL),
         ("99.2–99.6 %", "of units past |v| > 100 are rejected by the tester", TEAL),
         ("0 of 4,086", "P2 rejects have a real P4 reading: P4 = 0 means not tested", AMBER),
         ("0.46 %", "of healthy units reach 80 % of tolerance, so count them, not one unit", AMBER)]
for i, (big, small, col) in enumerate(facts):
    x = 0.6 + (i % 2) * 6.15
    y = 1.65 + (i // 2) * 2.55
    box(s, x, y, 5.95, 2.3, PANEL, name=f"fact {i + 1}")
    text(s, x + 0.35, y + 0.3, 5.3, 0.95, [[(big, {"size": 44, "bold": True, "color": col})]])
    text(s, x + 0.35, y + 1.3, 5.3, 0.9, [[(small, {"size": 16})]])
text(s, 0.6, 6.85, 12.1, 0.35, [[("WP1 train split, 1 May – 23 Jul 2026 (3.96 M first-pass tests); limits file "
                                  "and September exports from the plant.", {"size": 11, "color": MUTED})]])

# =============================================================== 5. results
s = slide("On known drifts the model gives a real head start",
          notes="Drifts were added to real data on all 20 machines; the test period 23 Jul – 12 Aug was scored once. "
                "At a budget of 0.5 false alarms per machine per day the trees catch 87 % of drifts, 71 % before the "
                "first reject, and 85 % of the drift rejects would have been avoidable. The count rule catches 36 % "
                "and never before a reject. Caveat: these are drifts we added, see the next slides for real data.")
cd = CategoryChartData()
cd.categories = ["Drifts detected", "Alarm before first reject", "Rejects avoidable"]
cd.add_series("Count rule (today)", (0.36, 0.0, 0.38))
cd.add_series("CUSUM", (0.84, 0.61, 0.82))
cd.add_series("Trained trees (WP2)", (0.87, 0.71, 0.85))
gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(1.5), Inches(8.2), Inches(5.3), cd)
gf.name = "results chart"
ch = gf.chart
ch.has_legend = True; ch.legend.position = XL_LEGEND_POSITION.BOTTOM; ch.legend.include_in_layout = False
ch.legend.font.size = Pt(13); ch.legend.font.name = FONT; ch.legend.font.color.rgb = rgb(INK)
ch.font.name = FONT
va = ch.value_axis
va.maximum_scale, va.minimum_scale = 1.0, 0.0
va.tick_labels.number_format, va.tick_labels.number_format_is_linked = "0%", False
va.tick_labels.font.size = Pt(12); va.tick_labels.font.color.rgb = rgb(MUTED)
va.major_gridlines.format.line.color.rgb = rgb("E3E7EC"); va.format.line.fill.background()
ca = ch.category_axis
ca.tick_labels.font.size = Pt(13); ca.tick_labels.font.color.rgb = rgb(INK)
ca.format.line.color.rgb = rgb("C9D1DA")
plot = ch.plots[0]
plot.gap_width, plot.overlap = 60, -10
plot.has_data_labels = True
dl = plot.data_labels
dl.number_format, dl.number_format_is_linked = "0%", False
dl.position = XL_LABEL_POSITION.OUTSIDE_END
dl.font.size = Pt(12); dl.font.color.rgb = rgb(INK)
for ser, col in zip(plot.series, (GREY, AMBER, TEAL)):
    ser.format.fill.solid(); ser.format.fill.fore_color.rgb = rgb(col)
text(s, 9.2, 1.6, 3.5, 0.4, [[("False alarms per machine per day", {"bold": True, "size": 16})]])
for i, (lab, val, col) in enumerate((("Count rule", "0.08", GREY), ("CUSUM", "0.39", AMBER),
                                     ("Trained trees", "0.20", TEAL))):
    y = 2.15 + i * 0.95
    text(s, 9.2, y, 1.6, 0.8, [[(val, {"size": 36, "bold": True, "color": col})]])
    text(s, 10.85, y + 0.22, 1.9, 0.5, [[(lab, {"size": 15})]])
box(s, 9.2, 5.05, 3.5, 1.75, "FDECEC", name="caveat")
text(s, 9.4, 5.15, 3.15, 1.55, [[("But: ", {"bold": True, "color": RED}),
                                   ("on 107 real reject clusters the trees catch only 11 %. 64 % of them hit several "
                                    "fixtures at once.", {})]], size=14, anchor=MSO_ANCHOR.MIDDLE)
text(s, 0.6, 6.9, 8.2, 0.35, [[("153 drifts added to real data, 20 machines, test period 23 Jul – 12 Aug 2026; budget "
                                "0.5 false alarms per machine per day.", {"size": 11, "color": MUTED})]])

# =============================================================== 6. app overview
s = slide("A local monitor replays the data and raises alerts",
          notes="The app runs on the PC at localhost:8501. Pick a data source (a WP1 parquet window or an uploaded "
                "file with the same columns), pick the saved model, and either replay the data live or process the "
                "whole window at once. In VS Code: Run and Debug, 'WP2 drift monitor (Streamlit)', F5.")
picture(s, "app_home.png", 0.6, 1.5, h=5.3, alt="WP2 drift monitor start page: data source, machines, window and model in the sidebar")
xr = 0.6 + 5.3 * 1412 / 900 + 0.45
items = [("1", "Pick the data", "WP1 parquet (split, machines, dates) or an uploaded CSV / parquet"),
         ("2", "Pick the model", "saved trees from alerts.py --train, or CUSUM with no training"),
         ("3", "Replay or run all", "live: 1 h of data per second; or the whole window in one go"),
         ("4", "Read the output", "row flags for bad units, drift alerts for fixtures")]
for i, (k, head, body) in enumerate(items):
    y = 1.6 + i * 1.32
    chip(s, xr, y, 0.5, k, TEAL, 16)
    text(s, xr + 0.7, y - 0.02, 12.7 - xr - 0.7, 1.2, [[(head, {"bold": True, "size": 17})],
                                                      [(body, {"size": 14, "color": MUTED})]], space_after=2)

# =============================================================== 7. live replay
s = slide("Live replay shows alerts as they are raised",
          notes="After pressing Start, the first two days are processed at once so every fixture can learn its "
                "normal; their alerts are hidden. Then rows arrive in time order. The counters show rows read, first "
                "passes kept, readings scored, alarms, warnings and fixtures still in alert. The table on the right "
                "lists every fixture in alert right now.")
picture(s, "live_replay.png", 0.6, 1.5, w=7.6, alt="Live replay: data clock, counters, alert feed and fixtures in alert")
yb = 1.5 + 7.6 * 702 / 1322 + 0.3
text(s, 0.6, yb, 7.6, 6.9 - yb, [[("Example: ", {"bold": True}),
                                   ("by 26 Jul, 134,653 first passes were scored on all 20 machines: 2 alarms, 18 "
                                    "warnings, 11 fixtures in alert.", {})]], size=14)
counters = [("Rows read", "everything in the file, repeats included"),
            ("First passes", "attempt 1 only: the baseline"),
            ("Readings scored", "P2 and P4 values with a real reading, on a warmed-up fixture"),
            ("Alarms / Warnings", "alerts raised so far"),
            ("Open now", "fixtures still in alert")]
text(s, 8.65, 1.55, 4.1, 0.4, [[("What the counters mean", {"bold": True, "size": 18})]])
for i, (k, v) in enumerate(counters):
    y = 2.15 + i * 0.92
    text(s, 8.65, y, 4.1, 0.85, [[(k, {"bold": True, "size": 15})], [(v, {"size": 14, "color": MUTED})]],
         space_after=1)

# =============================================================== 8. row flags
s = slide("Row flags name the columns behind each problem",
          notes="Row flags are about single units. Each line says what was wrong, which raw columns raised it and "
                "the values found. Unusable readings are kept out of the drift features instead of being treated as "
                "zero. Serial numbers are shown on screen in the app but are covered in this deck.")
picture(s, "row_flags.png", 0.6, 1.45, w=10.6, alt="Row flags table: time, machine, fixture, signal, flag and values (serial numbers covered)")
yb = 1.45 + 10.6 * 747 / 1828 + 0.3
trig = [("failed before this step", "failed = 1, earlier step in the status"),
        ("not measured / placeholder", "0 / 0, 65535, 999, -999 or empty"),
        ("near the limit", "80 % ≤ |v| ≤ 100 %: passed, but close"),
        ("P2 / P4 output reject", "status names a P2 / P4 output failure")]
for i, (k, v) in enumerate(trig):
    x = 0.6 + (i % 2) * 6.15
    y = yb + (i // 2) * 0.48
    text(s, x, y, 6.0, 0.45, [[(k + ": ", {"bold": True}), (v, {"color": MUTED})]], size=14)

# =============================================================== 9. drift alerts
s = slide("Drift alerts name the machine, device, fixture and signal",
          notes="A drift alert is about a fixture, not one unit. The model scores every reading; three readings in a "
                "row over the warning threshold raise a warning, over the alarm threshold an alarm. Opening 'Why, "
                "and which units' shows the level, how far it moved, units to the limit, the drift start, the "
                "features outside their healthy range and the units tested since. When three or more fixtures of one "
                "machine and device are in alert together, a machine-wide note appears: that points to the machine "
                "or calibration, not one fixture.")
picture(s, "alert_feed.png", 0.6, 1.45, h=5.45, alt="Alert feed: an alarm, a machine-wide note and warnings on machine 9990675")
xr = 0.6 + 5.45 * 783 / 697 + 0.5
text(s, xr, 1.5, 12.7 - xr, 0.4, [[("When an alert is raised", {"bold": True, "size": 18})]])
yb = 2.2
rules = [(RED, "Alarm", "score ≥ 0.388 for 3 readings in a row"),
         (AMBER, "Warning", "score ≥ 0.048 for 3 readings in a row; early and noisy by design"),
         ("2F6FB0", "Machine-wide", "3 or more fixtures of one machine and device in alert together"),
         (TEAL, "Back to normal", "60 readings below 80 % of the warning level")]
for i, (col, k, v) in enumerate(rules):
    y = yb + i * 0.95
    dot = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(xr), Inches(y + 0.07), Inches(0.24), Inches(0.24))
    dot.fill.solid(); dot.fill.fore_color.rgb = rgb(col); dot.line.fill.background()
    text(s, xr + 0.4, y, 12.7 - xr - 0.4, 0.9, [[(k + ": ", {"bold": True}), (v, {"color": MUTED})]], size=15)
text(s, xr, 6.0, 12.7 - xr, 0.9, [[("Inside 'Why, and which units': ", {"bold": True}),
                                    ("level, move from its own normal, units to the limit, drift start, the features "
                                     "outside their healthy range, and the units tested since.", {"color": MUTED})]],
     size=14)

# =============================================================== 9b. fixtures in alert
s = slide("Fixtures in alert now: where each sits, where it is heading",
          notes="This table lists every fixture currently in warning or alarm. 'since' is when the alert was raised. "
                "level_pct is where the fixture sits now in % of tolerance, shift_pct how far it moved from its own "
                "normal after removing the machine-wide move, units_to_limit the units left at the current trend "
                "(None when it is not heading out), and score the model's latest score. A score near 0 means the "
                "fixture is settling; it clears after 60 low readings.")
picture(s, "open_alerts.png", 0.6, 1.45, w=11.4, alt="Fixtures in alert now: level, shift, units to the limit and score")
yb = 1.45 + 11.4 * 575 / 1841 + 0.3
cols = [("level_pct", "where the fixture sits now, % of tolerance (limit ±100)"),
        ("shift_pct", "how far it moved from its own normal, machine-wide move removed"),
        ("units_to_limit", "units left at the current trend; None = not heading out"),
        ("score", "the model's latest score; near 0 = settling, clears after 60 low readings")]
for i, (k, v) in enumerate(cols):
    x = 0.6 + i * 3.08
    box(s, x, yb, 2.85, 1.6, PANEL, name=f"column {k}")
    text(s, x + 0.25, yb + 0.2, 2.4, 0.4, [[(k, {"bold": True, "size": 17})]])
    text(s, x + 0.25, yb + 0.6, 2.4, 0.95, [[(v, {"size": 14, "color": MUTED})]])

# =============================================================== 10. gap
s = slide("Against the agreed drift definition, the data is the blocker",
          notes="The team defines drift as behaviour of the CAL machine, found between engineer-marked faults. WP2 "
                "follows the CFT tester and learns from added drifts because no data yet links units to a CAL "
                "machine, a calibration time or a fault. The method for finding where a drift starts is already in "
                "place.")
rows = [("Definition", "WP2 today", "Status"),
        ("Drift comes from the CAL machine", "Follows the CFT tester's machine and fixture", "Not met: no CAL machine ID"),
        ("Window: previous fault → marked fault", "Rolling windows, restart after 12 h idle", "Not met: no fault log"),
        ("Learn where the pattern starts", "CUSUM change point gives a drift start", "Met"),
        ("Labels from engineer-marked faults", "Drifts added to healthy data", "Not met: no fault log"),
        ("Whole machine and single fixture", "Fixture level; machine-wide notes", "Partly met")]
tbl = s.shapes.add_table(len(rows), 3, Inches(0.6), Inches(1.6), Inches(12.1), Inches(4.6))
tbl.name = "definition table"
t = tbl.table
for j, wdt in enumerate((4.2, 4.7, 3.2)):
    t.columns[j].width = Inches(wdt)
for i, row in enumerate(rows):
    t.rows[i].height = Inches(0.72)
    for j, val in enumerate(row):
        c = t.cell(i, j)
        c.fill.solid()
        c.fill.fore_color.rgb = rgb(INK if i == 0 else (PANEL if i % 2 else PAPER))
        c.vertical_anchor = MSO_ANCHOR.MIDDLE
        c.margin_left = c.margin_right = Inches(0.15)
        tf = c.text_frame; tf.word_wrap = True
        tf.text = val
        r = tf.paragraphs[0].runs[0]
        col = PAPER if i == 0 else INK
        if i and j == 2:
            col = TEAL if val == "Met" else (AMBER if val.startswith("Partly") else RED)
        r.font.name, r.font.size, r.font.bold = FONT, Pt(15), (i == 0 or j == 2)
        r.font.color.rgb = rgb(col)
text(s, 0.6, 6.45, 12.1, 0.6, [[("Why: ", {"bold": True}),
                                 ("WP1 has test time and tester but no calibration data; the September exports have "
                                  "calibration fixtures but no time, machine or status. Only 3 serials appear in both.",
                                  {"color": MUTED})]], size=14)

# =============================================================== 11. next
s = slide("Three data requests unlock the CAL-machine model", dark=True,
          notes="Most of the code carries over. With the calibration history for May to August, every WP1 unit "
                "gets its calibration fixture group and a real time, so the pipeline can be rerun keyed by "
                "calibration group. Machine IDs and the fault log then give the real streams, resets and labels.")
asks = [("1", "Calibration history, May – Aug 2026", "Join to WP1 by serial: each unit gets its calibration fixture group "
                                                     "and a real test time. The pipeline can rerun keyed by calibration "
                                                     "group."),
        ("2", "CAL machine ID and calibration time", "Streams per CAL machine and nest position (Fn, Fn+4, Fn+8), "
                                                    "in calibration order."),
        ("3", "Engineers' fault log", "Machine, time marked, whole machine or which fixture. Real labels, resets at "
                                      "each fault, lead-time scoring.")]
for i, (k, head, body) in enumerate(asks):
    x = 0.6 + i * 4.1
    box(s, x, 1.75, 3.85, 3.6, "26324A", name=f"ask {k}")
    chip(s, x + 0.3, 2.05, 0.65, k, RED if i == 0 else AMBER, 20)
    text(s, x + 0.3, 2.9, 3.3, 0.9, [[(head, {"bold": True, "size": 19, "color": PAPER})]])
    text(s, x + 0.3, 3.8, 3.3, 1.5, [[(body, {"size": 14, "color": "C9D1DA"})]])
text(s, 0.6, 5.75, 12.1, 1.2, [[("Then: ", {"bold": True, "color": PAPER}),
                                  ("re-key the streams, reset at each marked fault, label from the drift start to the "
                                   "fault, add a machine-level detector, and score by how long before the engineers' "
                                   "mark the alarm comes.", {"color": "C9D1DA"})]], size=16)

prs.save(OUT)
print("saved", OUT)
