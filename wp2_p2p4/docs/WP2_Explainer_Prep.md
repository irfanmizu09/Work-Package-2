# WP2: how to explain it (speaker prep)

Numbers come from `out/eval_all_s0.csv`: the full run on all 20 machines, seed 0, with the test slice scored once.

---

## 1. The 30-second version

> WP2 is an early warning for the CFT tester's **P2 and P4 output tests**. Today the floor reacts
> when a fixture has 3 rejects in its last 200 units, so the alarm always comes *after* the damage.
> WP2 follows every fixture's output error over time. It raises a warning, then an alarm, when the
> error starts moving towards the reject limit, *before* units fail. On drifts we added to real data,
> the trained model catches 87 % of them, 71 % before the first reject, typically within 9 units. It
> raises about 0.2 false alarms per machine per day.

---

## 2. What was done: seven steps, one file each

| Step | File | What it does | One line to say |
|---|---|---|---|
| a. Clean | `load.py` | One row per first-attempt test. Each unit gets `v = 100 × error ÷ tolerance`, so 0 = on target and ±100 = reject limit | "Every unit becomes one comparable number per signal, or a reason why there is none." |
| b. Check | `check_reject_rule.py` | Does \|v\| > 100 reproduce the tester's own reject decision? | "99.2–99.6 % agreement, so our number is the tester's real limit." |
| c. Describe | `features.py` | 15 streaming features per machine × device × fixture × signal | "Each fixture is compared with its own normal and with its neighbours." |
| d. Label | `labels.py` | Adds known drifts (steps and ramps) to real, healthy data | "We created ground truth, because none exists." |
| e. Score | `detectors.py` | Count rule (today), CUSUM (statistics), trained trees (ML), plus the alarm tracker | "Three detectors, the same features, a fair comparison." |
| f. Measure | `evaluate.py` | Split by time; thresholds set by a false-alarm budget; test scored once | "Measured the way the floor would feel it." |
| g. Alert | `alerts.py` | Saves the model and lists warnings and alarms on real data | "The output is a list: which fixture, since when, how far off." |
| App | `live.py`, `app.py` | Streamlit app: replays data and shows row flags and drift alerts as they are raised | "A working local monitor, the WP4 Tab 1 candidate." |

**Cleaning rules worth mentioning (step a):**
- Placeholder values (65535, 9999, output = 0) are treated as **missing, not zero**.
- After a P2 reject, P4 is not measured: the tester stops.
- Pneumatic fails (stability, fill timeout, Mensor) are **not** output rejects.
- Device limits were first worked out from WP1's columns. They match the real limits file on 127 of 127 devices.
- Serial numbers are replaced by a keyed hash and never written to outputs.

**The 15 features (step c), in plain words:**
- **Departure** from the fixture's own normal, at three speeds (≈30, 100 and 300 units): `d_s`, `d_m`, `d_l` and their sizes.
- **Machine-wide move removed.** If every fixture on a machine moves together, that is subtracted, so one bad fixture stands out.
- **Trend** and **toward**: is it still moving, and is it moving towards the limit?
- **CUSUM**: adds up small shifts that keep going.
- **Headroom / eta**: how far to the limit, and how many units until it gets there at the current trend.
- **Near-limit share** and **recent rejects**: the share of recent units at 80–100 % of tolerance, and rejects in the last 200 units.
- **Warm**: the fixture has enough history (~120 units) to be trusted.
- **Noise correction**: units are not independent (lag-1 autocorrelation ≈ 0.3), so the CUSUM noise is scaled per machine × device × signal. Without this, the CUSUM sat high for a third of healthy time.

---

## 3. The training method (the part you'll be asked about)

### What kind of learning
**Supervised binary classification** with **gradient-boosted decision trees**
(scikit-learn `HistGradientBoostingClassifier`).

- **Input:** the 15 features for one fixture at one moment (one row per unit tested).
- **Output:** the probability that this fixture is drifting right now.
- **Settings:** 250 trees, learning rate 0.06, up to 31 leaves per tree, L2 regularisation 1.0, fixed random seed.

### Where the labels come from: injected drift (the key idea)
The data has **no record of when a fixture actually drifted**. So we made known drifts:

1. Take **real, healthy** production data.
2. At random times, add a drift to one fixture:
   - **Step**: a jump of 30–70 % of tolerance ("large") or 10–30 % ("small").
   - **Ramp**: 6–28 % of tolerance per hour ("large") or 1–6 % per hour ("small").
   - The drift goes towards the side the fixture already leans to.
3. Units pushed past ±100 become rejects. A P2 reject also removes that unit's P4 reading, as on the real tester.
4. The episode ends the way the floor ends it today: after 5 drift rejects ("recalibrated") or after 14 hours.
5. **Label = 1** while the drift has moved the unit by at least 10 % of tolerance. Otherwise 0.

771 episodes were injected across 20 machines (about 0.5 per machine per day).

**Why this is reasonable:** the noise, autocorrelation, changeovers and machine-wide moves are all
real. Only the drift is synthetic, and we know exactly when it started.

### Handling the imbalance
- Only **≈1.2–1.5 %** of rows are positive (that is the base rate).
- Positive rows get up to **20× weight** in training.
- Negatives are subsampled to 3 M rows. All positives are kept.
- Rows inside a **real** reject cluster that no injected drift explains are **left out of training**. They might be real drifts, so they are neither positive nor negative.

### Splitting the data (no leakage)
| Slice | Dates (2026) | Rows | Episodes | Used for |
|---|---|---|---|---|
| fit | 1 May – 1 Jul | 4.13 M | 443 | training the trees |
| tune | 2 Jul – 23 Jul (end of WP1 train) | 1.61 M | 175 | choosing the alarm thresholds |
| test | 23 Jul – 12 Aug (WP1 test) | 1.24 M | 153 | **scored once**, reported |

- Split **by time**, never randomly. WP1's train/test split was never re-split.
- The code checks that **no serial number appears in more than one slice**.
- The features stream through all three slices in time order, as they would live.

### From score to alarm
- **Thresholds are chosen by false-alarm budget, not by accuracy.** For each budget (0.1, 0.25, 0.5, 1, 2 false alarms per machine per day), we pick the lowest threshold on the *tune* slice that stays within it.
- **Alarm tracker:** a warning or alarm needs **3 scores in a row** above the threshold, so one noisy unit can't trigger it. It clears only after **60 units in a row** comfortably below, so it doesn't flap.

### The two comparison detectors (no training)
- **Count rule:** today's floor practice, 3 rejects in the last 200 units. This is the baseline to beat.
- **CUSUM:** a classical statistical change detector on the departure from the fixture's normal. It counts only moves towards the limit. Its thresholds are tuned to the same budgets.

---

## 4. Results to quote (test slice, budget 0.5 false alarms per machine per day)

Base rate on test = **1.49 %** of rows. Always say this before any PR-AUC.

| | Count rule (today) | CUSUM | **Trained trees** |
|---|---|---|---|
| Row-level PR-AUC (base 0.015) | 0.015 | 0.797 | **0.947** |
| False alarms / machine / day | 0.08 | 0.39 | **0.20** |
| Drifts detected | 35.9 % | 84.3 % | **86.9 %** |
| Alarm before the 1st reject | 0 % | 61.3 % | **71.0 %** |
| Median delay | 54 units / 4.1 h | 13 units / 0.8 h | **9 units / 0.5 h** |
| Drift rejects avoidable | 38 % | 82 % | **85 %** |
| Small drifts detected | 12.5 % | 73.6 % | **79.2 %** |

**The trade-off dial:** at 0.1 false alarms per machine per day, the trees still catch 84 % of drifts (73 % before the first reject).
At 1.0, they catch 89 % with an 8-unit delay. Sensata picks the budget. We don't.

---

## 5. Be upfront about this (it's the first hard question)

**On real reject clusters (107 in test), the trees are weak.** At budget 0.5 they alarm on only 11 %, and
3.7 % come before the first reject. The count rule "catches" 96 %, but only because a reject cluster is, by
definition, what the count rule fires on. At budget 2.0 the trees reach 62 % (41 % before the first reject).

How to say it:
> "The model is very good at the drift *we defined*: a gradual or step shift of one fixture. Many real
> reject clusters look different (sudden faults, single bad batches, pneumatic issues). Without a fault
> log we can't tell which real clusters were drifts. That is the main limitation, and it's why we're
> asking for data."

**What's blocking a "real-label" model:**
1. **Calibration history (May–Aug):** to link each unit to its CAL machine and calibration fixture group.
2. **CAL machine ID and calibration time:** to build streams in calibration order.
3. **The engineers' fault log:** real labels, resets at each fault, and lead time against the engineers' mark.

Most of the pipeline carries over: re-key the streams, swap injected labels for logged faults, and retrain.

---

## 6. Likely questions and short answers

**"The WP2 brief says Isolation Forest on leak rate. Why not that?"**
P2/P4 are *output* tests, not leak tests, and the problem is a fixture **drifting over time**.
An Isolation Forest scores units one at a time against a static population. It can't see that a
fixture has been creeping up for 50 units. Single units are also noisy: 0.46 % of healthy units reach 80 %
of tolerance by chance, so a per-unit flag mostly flags noise. We follow the trend per fixture instead.
(The leak-channel Isolation Forest version exists in `tests_codes/near_threshold_v2/v3.py`.)

**"What's your accuracy?"**
We don't report accuracy. With a 1.5 % base rate, "never alarm" scores 98.5 %. We report detection rate,
lead time and false alarms per machine per day, plus PR-AUC against the base rate.

**"Isn't training on fake drift circular?"**
Partly. That's why the test slice is scored once, why small drifts below the simulator's range are
included, and why we also report real reject clusters honestly. The background is real data, so the
false-alarm rate is a real-data number.

**"Why trees and not deep learning?"**
15 hand-built features already describe the physics (departure, trend, CUSUM). Trees train in minutes,
are robust, need no scaling, and the features behind each alarm can be shown (the app lists the "why").

**"Why does CUSUM matter if the trees win?"**
It needs no training data, so it's the fallback for a new machine or device, and it's easy to explain.

**"What happens if a whole machine shifts?"**
The machine-wide move is removed so that one fixture stands out. The app also adds a machine-level note
when several fixtures of the same machine and device are in alert together. A dedicated
machine-level detector is planned for when fault data arrives.

**"Can it run live?"**
Yes. `live.py` keeps the feature state between chunks, and `app.py` (Streamlit) replays data and raises
alerts in time order. The saved model is `out/model_*.joblib`.

---

## 7. Where things are

- Slides: `docs/deck/WP2_Drift_Monitor.pptx`
- Written report: `docs/WP2_Progress_Report.docx`, walkthrough `docs/WP2_Walkthrough_Steps_A-G.docx`
- Full results: `out/eval_all_s0.csv` / `.log`
- Run the app: `uv run --with streamlit streamlit run wp2_p2p4/app.py` (from `Work-Package-2/`)
