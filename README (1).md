# Fraud alert triage platform

Synthetic data generator, rule engine, validator and analyst web app for prioritising transactions and linked accounts for review, using transparent rules and synthetic risk indicators. **All data is synthetic. No external or personal data is used.**

## Quick start (Windows PowerShell, Python 3.11)

```powershell
git clone https://github.com/Niharika-bandlamudi/fraud-alert-triage-platform.git
cd fraud-alert-triage-platform
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

python src/generator.py --seed 20261022 --out data    # 1. clean baseline data (about 3 seconds)
python src/run_all.py                                 # 2. alerts, cases, anomalies, validation, reproducibility, SQL/JSON export
streamlit run src/app.py                              # 3. analyst web app on http://localhost:8501
python -m unittest discover -s tests -v               # 4. automated tests (about 3 seconds)
```

`python src/run_all.py` ends with `RESULT: PASS` when the validator catches exactly the labelled anomalies and two full rebuilds give identical files. Add `--quick` to skip the reproducibility rebuilds. The committed `data/`, `data_final/` and `exports/` folders are the output of these commands, so you can inspect or run the app without regenerating anything.

## What is in the repository

| Path | What it is |
|---|---|
| `src/generator.py` | Steps 1-2 of the brief: master data, transactions, transfers, planted patterns and ground truth. Writes the clean baseline to `data/` |
| `src/build_triage.py` | Rules, alerts, cases, analyst actions and the five injected anomalies. Reads `data/`, writes `data_final/` |
| `src/validator.py` | All validation checks, comparison with `ground_truth.csv`, and the reproducibility check (`--repro`) |
| `src/export_seed.py` | SQL seed data (`exports/seed.sql`, loads into SQLite with foreign keys on) and per-table JSON |
| `src/app.py`, `src/app_data.py`, `src/ui.py` | Streamlit analyst web app, its data layer, and its look and feel (badges, charts, styling). Theme in `.streamlit/config.toml` |
| `src/run_all.py` | One command for build, validate, reproduce, export |
| `tests/test_pipeline.py` | 15 automated tests |
| `docs/data_dictionary.md` | Every entity: field, type, required, allowed values, uniqueness, validation rule, keys, cardinality |
| `docs/assumptions.md` | Assumptions, rule definitions, scoring, known limitations |
| `data/` | Clean baseline CSV files, `generation_manifest.json` with SHA-256 hashes |
| `data_final/` | Full dataset CSV files, `build_manifest.json`, `validation_report.json` |
| `exports/` | `seed.sql`, `json/`, `load_check.txt` |
| `prompts/prompts.md` | LLM prompt history |

## Data produced (seed 20261022)

| Table | Rows | Table | Rows |
|---|---|---|---|
| customers | 5,000 | risk_rules | 5 |
| accounts | 7,000 | alerts | 1,000 |
| transactions | 100,004 | cases | 985 |
| transfer_links | 1,852 | case_alerts | 1,000 |
| devices | 7,731 | analyst_actions | 3,333 |
| merchants | 500 | ground_truth | 5,508 |

The 100,004 transactions are the 100,000 baseline plus the 4 added by the injected anomalies. Entities, keys and relationships are in `docs/data_dictionary.md`.

## How it works

1. **Master data first.** Customers (KYC profiles), accounts (ownership, lifecycle history), merchants, devices and a device-account bridge table are created before any transaction. IDs follow the brief (`CUS-000001`, `ACC-CUS-000001-01`, `TXN-2026-00000001`, `ALT-2026-000001`, `CASE-2026-000001`).
2. **Transactions.** Timestamped debits and credits per account. `balance_after` is computed from the previous balance, so balances reconcile. Transfers create two linked transactions plus a `TransferLink` row.
3. **Planted patterns** (documented in `ground_truth.csv`): velocity spikes, new-device activity, circular transfers, dormant-account reactivation, and three kinds of benign look-alike (bill-payment burst, new phone paying a known payee, large payment to a known payee).
4. **Five rules** (`RUL-001` to `RUL-005`, parameters stored in `risk_rules.csv`). The rules read only transactions, transfers and account history, never the ground truth (a test checks this).
5. **Explainable scores.** Each alert stores a `score_breakdown` (rule weight plus context points, minus mitigating points) that adds up exactly to `risk_score`, and plain-language `evidence`.
6. **Cases.** Alerts of one customer within 7 days share a case. Priority = highest alert score plus 5 per extra alert.
7. **Analyst actions.** Assign, review, escalate, request info, disposition, appended as events. Nothing is overwritten. Case and alert status are derived from the actions.
8. **Injected anomalies** (added after the clean baseline, each with a `ground_truth` row and no change to unrelated rows): transaction on a closed account, negative balance without overdraft, transfer legs that do not reconcile, alert without a triggering transaction, case disposition before the alert.
9. **Ground truth** lives in its own file and is only used to evaluate the rules and the validator.

## Results

- **Detection:** all 590 planted true patterns and all 392 benign look-alikes raise an alert (100% recall, `data_final/build_manifest.json`). Alerts by rule: RUL-001 300, RUL-002 396, RUL-003 100, RUL-004 110, RUL-005 93.
- **False positives are represented:** 392 alerts (about 39%) come from benign look-alikes. Average score is lower for them than for true patterns, but the ranges overlap.
- **Validation:** 157,036 rows checked. The validator reports exactly the 5 injected anomalies (6 findings, because the negative balance is reported on both the transaction and the account), 0 missed, 0 unexpected. It checks primary keys, ID formats, enums, foreign keys, date ordering, balance reconciliation, lifecycle transitions, duplicates, and the alert, case and action rules in the data dictionary.
- **Reproducibility:** `python src/validator.py --data data_final --repro` regenerates everything twice from the seed and compares SHA-256 of every CSV file (run 1 equals run 2, and both equal the committed `data_final/`). The SHA-256 of `data/customers.csv` starts with `4b88f823`; all hashes are in the manifests. `.gitattributes` forces LF line endings so hashes also match after cloning on Windows.
- **SQL seed:** `exports/load_check.txt` shows `seed.sql` loading into SQLite with foreign keys on and 0 foreign key violations.

## Analyst web app

`streamlit run src/app.py` has five pages: **Overview**, **Alert queue** (filter, sort by risk score, open an alert to see evidence, score breakdown, triggering transaction and account history), **Case view** (alerts, timeline, record analyst actions with role checks), **Rules & evaluation**, **Data quality** (validator result and ground-truth evaluation). Actions made in the app are written to `app_state/new_actions.csv`; `data_final/` is never modified, so `run_all.py` still passes after using the app.

## Key decisions and trade-offs

- **Baseline and final data are separate folders.** The builder checks the baseline against its manifest hashes and refuses to run if it was changed, so anomalies can never be injected twice.
- **Standard library for the pipeline, pandas only for the app.** This keeps output byte-for-byte identical across Python and library versions (the generator was checked with two NumPy versions).
- **Labels come from rules.** Pattern labels are written by the same code that plants each pattern. Analyst dispositions are derived from those labels with noise (92% and 90% agreement), documented in `docs/assumptions.md`.
- **Rules are simple thresholds on purpose**, so every alert can be explained to an analyst. The cost is some overlap between rules (16 RUL-002 alerts also match other patterns).

## Limitations

See `docs/assumptions.md`. In short: fixed thresholds, simulated analyst behaviour and timings, labels only on transactions and transfers, single currency (INR), alert volume is exactly 1,000 only for the default seed and scale.

## How AI was used

Tool: Claude (claude.ai). The full prompt history is in `prompts/prompts.md`.

- **Where AI accelerated the work:** drafting the data dictionary, writing the generator, rule engine, validator, exporter, tests and the Streamlit app, and debugging.
- **Where I relied on it heavily:** the generator and builder code, the scoring design, and the first version of the app.
- **What I reviewed, ran and validated myself:** ran every step on my own machine and compared the output with the AI's run (the `customers.csv` SHA-256 matched), ran the validator and reproducibility check, removed a duplicate `generator.py` that had ended up in `docs/`, fixed line endings with `.gitattributes`, checked the dictionary against the generated files (the AI found and fixed a mismatch in `ground_truth` values), checked the app pages against the data, and pushed each step as a separate commit.
