# Prompt: bring the WP2 tester-fixture drift monitor into Trace Sentinel (sensata2026, branch irfan_study)

Paste everything below the line into a new Claude Code session opened in `D:\SENSATA\sensata2026`.

---

Integrate the WP2 P2/P4 drift monitor into Trace Sentinel in this repo, on branch `irfan_study`. It must run
inside the existing Docker setup and show on the existing dashboard. Models must be plug and play: a new model
is a folder that I import, try in shadow, activate and roll back, with no code change and no restart.

## Ground rules

- Work on `irfan_study` only (it tracks `origin/irfan_study`). Changes in this repo are allowed. Commit after
  each step I approve, and don't push unless I say so.
- The WP2 repo `D:\SENSATA\WP2\Work-Package-2` (branch `production-loop`, folder `wp2_p2p4/`) is the
  source. Read it, don't modify it.
- Build one step at a time. For each step: run it on a small sample, show me the output, explain it plainly,
  and wait for my "next".
- Ask before adding any dependency. Both venvs already have Python 3.11.13, scikit-learn 1.9.1, pandas
  3.0.6, numpy 2.4.6 and joblib 1.6.0, so WP2's saved trees load here unchanged.
- Don't change what the existing calibration-group monitor does. Before step 1, record the output of
  `python -m pytest -q` (17 test functions in `tests/`; record the pass count you see) and `python -m sentinel evaluate --days 7 --seed 99`. After every
  step, both must give the same results again.
- Data rules (from WP2): never report accuracy. Always quote the base rate, and use precision/recall,
  PR-AUC, lead time and false alarms per machine per day. Null is not zero: 65535 / 9999 / 999 / -999, and
  Output = Error = 0, are "not measured", not readings. Use first passes only (`TestNo = 1`). Never write or
  commit real serial numbers. No Sensata data goes into git or the Docker image; keep `.dockerignore` as it
  is.

## What is already true (checked)

- **Sentinel watches calibration fixture groups.** The stream key is (cal machine, device, group n/n+4/n+8,
  signal). Units are traced to calibration through `calib_history`.
- **WP2 watches CFT tester fixtures.** The stream key is (tester `EquipmentID`, `DeviceID`, tester
  `Fixture`, signal). It needs no calibration join: `cft_history` already has `EquipmentID` (tester),
  `Fixture` (tester fixture), `TestNo`, `Status`, `P2Error`/`P4Error`, and `cft_limits` has the tolerances.
  So WP2 is a **second monitor beside the existing one, not a replacement**. The two answer different
  questions: "is a calibration fixture drifting" and "is a tester fixture drifting".
- **The feature names are identical.** Both use the same 15 `FEATS` names (`d_s … warm`), but the maths
  differs: WP2 has per-tester noise inflation, peers that are the other tester fixtures, relearn on recal,
  and a gap restart. A name check alone would let a WP2 model load into the calibration engine silently. The
  model contract below must stop that.
- **The model registry exists already.** It has:
  - `models/<version>/model.joblib` plus `metrics.json`;
  - the `models` table;
  - `python -m sentinel models --import <folder> --activate <v>`;
  - per-version threshold overrides in `kv`;
  - an engine that hot-swaps the active model within 5 s (`Engine._check_model`).

  What's missing for plug and play: `train.detector_from` hard-codes the model kinds, there is one active
  model for everything, and nothing declares which feature set a model expects.
- **WP2 code to port** (`wp2_p2p4/`):
  - `features.py`: `FeatureEngine`, `GroupState`, `recal` with mode "relearn" over the next 60 units, and
    `replay(recals=)`.
  - `detectors.py`: `AlarmTracker`, `alarm_events` / `alarm_events_fast` with `resets` and `reset_times`,
    `Cusum` and `Trained`.
  - `load.py`: `prepare`, holding the step-a rules (v = 100 × error / tol, placeholders, aborted units,
    output-reject regex on `Status`, `band_ok` exceptions).
  - `live.py`: `Live`, including `add_recals`, `apply_due` and `recal_log`.
  - `recal.py`: findings are "drift confirmed" / "no fault found" / "other".
  - WP2 saved models are `out/model_<tag>.joblib`, a dict with keys
    `kind, feats, model (sklearn HistGradientBoostingClassifier), thresholds, persist, budget, trained_on`.
    They contain no WP2 classes.
- **WP2 checks to keep:**
  - With no recal events, WP2's own `evaluate.py` reproduces `out/baseline/eval_all_s0.csv` exactly.
  - Live gives the same events as offline replay.
  - `alarm_events_fast` equals `alarm_events`, with and without resets.
- **Plant data gap.** The README's "still needed from the plant" list includes the tester fixture in the CFT
  report. The WP1 data has it; the September extract did not. The tester-fixture monitor needs it, so show
  that clearly when it is missing (the monitor idles) rather than guessing.

## The plug-and-play contract (design this first, step 1)

**1. A monitor** is one kind of stream: its key, the rows it reads, its feature engine and its feature-set id.
- Register two: `cal_group` (the existing code, unchanged) and `tester_fixture` (WP2).
- Proposed layout:
  - `sentinel/monitors/__init__.py`: the registry and a `Monitor` protocol with `name`, `feature_set`,
    `FEATS`, `key_of(row)`, `rows(conn, since_id, limit)`, `new_feature_engine()`, `recal(engine, event)`
    and `label(meta, ...)`.
  - `sentinel/monitors/cal_group.py` and `sentinel/monitors/tester_fixture/`.

**2. A model package** is a folder, `models/<version>/`, containing:
- `model.json`, the manifest:
  `{"format": 1, "version", "monitor", "feature_set": {"id": "tester_fixture/v1", "feats": [...]},
  "detector": {"kind": "trained" | "cusum" | "count-rule" | <registered plugin kind>}, "thresholds",
  "persist", "clear_n", "operating_points": [...], "trained_on": {"from", "to", "data": "<description, no serials>"},
  "metrics": {... base rate, PR-AUC, precision/recall, detected %, before 1st reject %, FA/m/day ...},
  "requires": {"python", "scikit-learn"}, "sha256": {"model.joblib": "..."}}`
- `model.joblib`: the fitted estimator or parameters only.
- `metrics.json`.

**3. A detector kind** is a class in `sentinel/detectors.py`, or in a plugin module inside the image,
registered by name with a decorator.
- The interface is `from_package(manifest, payload) -> obj` with `obj.scores(F: ndarray[n, len(feats)]) ->
  ndarray[n]` and `obj.thresholds`.
- Never import or run code that ships inside a model folder. A `.joblib` file is a pickle, so it runs code
  when loaded. Import only folders you trust, and check the sha256 before `joblib.load`.

**4. The loader refuses**, with a clear message, and keeps the current model live, when any of these hold:
- the manifest's monitor is unknown;
- `feature_set.id` or `feats` differ from that monitor's;
- the scikit-learn version doesn't match;
- the checksum is wrong;
- the kind is unknown.

**5. The registry is per monitor.**
- Add `monitor` and `status` (`inactive` | `shadow` | `active`) to `models`, with exactly one active per
  monitor.
- Folders that predate this have no `model.json`. Read them as `cal_group/v1` so nothing existing breaks.

**6. Swapping.**
- CLI: `python -m sentinel models --import <folder>`, `--shadow <v>`, `--activate <v>`, `--rollback <monitor>`
  (to the previously active version), and `--list [--monitor m]`.
- API: the same under `/api/models` (add `?monitor=`).
- The engine hot-swaps per monitor as today.
- A **shadow** model is scored on the same feature rows as the active one. It writes to a `shadow_alerts`
  table and never raises the light or sound. The Backend tab shows active vs shadow side by side
  (raises, false alarms per machine per day, agreement), so a new model is proven before it goes live.

## Steps (one at a time, wait for my "next" after each)

0. **Baseline.** Run pytest and `evaluate --days 7 --seed 99`, and record both in `docs/benchmarks/` (no
   serials). List anything already failing.
1. **Contract and registry.**
   - Build what's described above for the existing `cal_group` monitor only: the monitor registry, the
     manifest, the detector-kind registry, the per-monitor registry with shadow, and the CLI and API.
   - `train.save` writes `model.json`.
   - Tests:
     - an old folder still loads;
     - a wrong feature set is refused and the old model stays live;
     - shadow never opens a real alert;
     - activate and rollback hot-swap without a restart.
   - Baseline numbers unchanged.
2. **Port the WP2 maths** to `sentinel/monitors/tester_fixture/`: features, the tracker with
   resets/reset_times, fast events, and the step-a cleaning rules mapped from `cft_history` + `cft_limits`
   columns. Keep the time unit consistent with sentinel (ms) without changing results.
   - **Parity test:** run a fixed set of fictitious rows through WP2's original `features.replay` and
     `detectors.alarm_events` (import from the WP2 path at test-generation time), save them as a golden
     file of features and events under `tests/data/` (fictitious values only), and check that the port
     reproduces them exactly, with and without recal events.
3. **Run the second monitor in the engine.**
   - The tester-fixture monitor polls first passes from `cft_history`, warms up silently, and hot-swaps its
     own model (CUSUM default until one is imported).
   - Recalibrations:
     - add `monitor`, `fixture`, `device` (empty = all devices on the fixture), `signal` (P2 / P4 / both),
       and `finding` to `recal_events`;
     - a tester-fixture recal relearns the centre from the next 60 units and closes the open alert with
       reason "recalibrated", as WP2 does.
   - Add a `monitor` column to `alerts`. Both monitors write there, and `/api/alerts` and `/api/state` can
     filter by it.
   - Add checkpoint and resume of the monitor state (atomic write) so a restart doesn't need a long
     warm-up. Test: a checkpointed and resumed run gives the same alerts as an uninterrupted one.
   - Check:
     - the calibration monitor's numbers are unchanged;
     - on a simulated database, Live == offline for the tester monitor.
4. **WP2 model import.** Write `tools/import_wp2_model.py <wp2 model.joblib> <out folder>`. It turns a WP2
   saved model into a `tester_fixture/v1` package: manifest, sha256, and metrics copied from WP2's
   `eval_*.json` / `eval_*_pr.csv`, keeping the base rate. It copies no data.
   - Demo: import it, shadow it against CUSUM, activate it, roll back.
   - Models stay out of git (`models/` is ignored already; check).
5. **Simulator.** Add tester-fixture drift episodes, with a `scope` column in `sim_drifts`, and a Demo-menu
   control (tester, fixture, signal, step/ramp). This lets the demo show tester alerts, gives ground truth
   for `sentinel evaluate` on the new monitor, and makes the "Mark recalibrated" flow testable. Random
   episodes end the way WP2 assumes: after 5 drift rejects or 14 h, with a recal.
6. **Dashboard** (`trace-sentinel-realdata.html`, live mode only; replay mode and the offline demo stay as
   they are, and say so in the page):
   - **CFT Stream tab:** a "Tester fixtures" grid (tester × fixture, coloured by level per signal) and
     tester-fixture alerts in the banner, labelled "tester fixture" so nobody confuses them with
     calibration alerts.
   - **Report tab:** tester-fixture alerts with level, shift, units to limit, the "why" features, and
     "Mark recalibrated" with finding and note.
   - **Backend tab:** models grouped by monitor, with Import status / Shadow / Activate / Rollback,
     operating point, the manifest's metrics (with base rate), and the shadow-vs-active comparison.
   - In shadow mode, show a banner on the tester section: "Shadow mode: do not act on these alerts".
7. **Docker.**
   - The image still copies only `sentinel/` and the dashboard, so the new code is included. No data or
     models go in the image.
   - Add `SENTINEL_MONITORS` (default `cal_group,tester_fixture`).
   - Entry point: the demo still bootstraps and trains the calibration model; the tester monitor starts on
     CUSUM.
   - Document plugging a model into a running container:
     `docker compose cp <folder> demo:/data/models/incoming/<v>`, then
     `docker compose exec demo python -m sentinel models --import /data/models/incoming/<v> --shadow <v>`,
     and later `--activate <v>`.
   - Verify `docker compose --profile demo up -d --build`, the healthcheck, and a swap with no restart.
8. **Docs.**
   - `docs/ARCHITECTURE.md`: the two monitors, the contract, the new tables and columns, API changes.
   - `docs/MODEL-PLUGINS.md`: how to build a new model package for either monitor, the checklist the loader
     enforces, and how to shadow, activate and roll back.
   - README: a short summary.
   - Rerun all tests and both baseline checks, and report them.

## Done means

- Pytest passes, including the new contract, parity, checkpoint-resume, fast-vs-slow and swap tests.
- The calibration monitor's evaluate numbers are identical to step 0.
- In Docker, the dashboard shows both monitors. A WP2 model package can be imported, shadowed, activated
  and rolled back without a restart. A package for the wrong monitor or feature set is refused.
- No serial numbers or Sensata data in git or the image.

## Questions to ask me when you reach them

- Should a tester-fixture recal reset all devices on that fixture, or only the device named? WP2 currently
  resets all, which costs detection on rarely tested devices.
- Should the floor see tester-fixture alerts with sound and light, or as a quieter separate alert class?
- How should real recal rows reach `recal_events` on the plant: dashboard only, or also from a plant
  maintenance table?
