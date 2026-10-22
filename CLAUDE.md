# WP2 — Sensata CFT early warning (P2 / P4 output drift)

P2 and P4 are OUTPUT tests (sensor output vs. expected at a test pressure), not leak tests.
New work goes in `wp2_p2p4/`. Do not modify `tests_codes/`, `src/`, `wp1_data/` or the
reference repo `D:\SENSATA\sensata2026` (read-only).

Python: `.venv/Scripts/python.exe` (populate with `uv sync --frozen`).
Data: `wp1_data/wp1_data/explain/{train,test}/part-0000.parquet` (fallback
`C:\cft_project\students\wp2\wp1_data\explain`). Read only the columns you need; never load all
94 columns of all rows at once.

## Data rules (from the WP1 dataset notes)
- Never re-split train/test. Validation data is carved from the END of train, by time, with
  serials disjoint from the earlier part.
- Never report accuracy. Always quote the base rate; use precision/recall, PR-AUC, lead time and
  false alarms per machine per day.
- Null is not zero. 65535 / 9999 / 999 / -999 and p2output = 0 / p4output = 0 are placeholders,
  not readings. Output and error both 0 = "not measured".
- Use first attempts only (`attempt_no == 1`) for baselines.
- Do not commit or print real serial numbers in reports or outputs.

## Workflow
- Build one step at a time: run on a small sample, show the output, explain it plainly, and wait
  for the user's "next" before continuing.
