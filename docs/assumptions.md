# Assumptions

1. **Account ID format.** `ACC-<customer-id>-01` is read literally, so the ID is `ACC-CUS-000001-01`. A second account for the same customer uses `-02`. 7,000 accounts over 5,000 customers means some customers hold two.
2. **Currency.** Single currency (INR) so balance reconciliation stays simple.
3. **Extra ID formats.** The brief fixes IDs for customer, account, transaction, alert and case only. Merchant, device, transfer, rule and action IDs follow the same zero-padded style.
4. **Extra tables.** `DeviceAccountLink`, `CaseAlert`, `AccountStatusHistory` and `ground_truth` are added to model many-to-many links, lifecycle history and labels.
5. **Overdraft.** Accounts have `overdraft_limit` >= 0. A balance below `-overdraft_limit` is an error unless it is a labelled anomaly.
6. **Alert to case.** An alert belongs to at most one case. Cases group alerts by customer.
7. **Labels come from rules.** Pattern labels are produced by the same documented logic that plants the pattern, not by random assignment.
8. **Anomalies.** The five injected anomalies are added after the clean baseline and each has a `ground_truth` row. They do not alter unrelated rows.
9. **Reproducibility.** Default seed 20261022. Data sizes are parameters.

10. **Two folders.** `data/` is the clean baseline from `generator.py`. `build_triage.py` reads it and writes `data_final/` (baseline plus rules, alerts, cases, actions, anomalies). It refuses to run if a baseline file no longer matches its manifest hash, so anomalies can never be injected twice.
11. **Rules read only transactions, transfers and account history.** They never read `ground_truth.csv`. Labels are used afterwards to measure detection.
12. **Rule definitions.** RUL-001: 8 debits in 60 minutes (alert on the 8th, 60-minute cool-down). RUL-002: first use of a mobile or web device on an account after 5 earlier transactions, then 25,000 of debits through it within 24 hours (alert on the transaction that crosses 25,000). RUL-003: transfers A to B to C (to D) back to A within 72 hours, alert on the closing credit. RUL-004: a debit of 25,000 or more is the first transaction after a dormant period of 90 or more days (counted from the account opening if it never transacted). RUL-005: a single purchase of 100,000 or more; skipped when RUL-004 already alerts that transaction.
13. **Scoring.** `risk_score` is the weight of the rule plus context points (burst size, amount, customer risk tier, unverified KYC, high-risk merchant) minus mitigating points (utilities-only payees, known payees). The breakdown always adds up exactly; a `cap_adjustment` or `floor_adjustment` row keeps it inside 0-100.
14. **Cases.** Alerts of one customer join the same case while each is within 7 days of the previous one. Every alert is in exactly one case. Case priority adds 5 per extra alert.
15. **Analyst work is simulated.** Timelines are generated per case (assign, review each alert, escalate when priority is 70 or more or by chance, optional request_info, disposition). Anything after 2026-11-05 has not happened yet, so recent cases stay open or in_review, and about 4% of cases stall part-way.
16. **Dispositions.** Derived from the labels with noise: cases containing a planted pattern are confirmed_suspicious 92% of the time, cases with only benign look-alikes are false_positive 90% of the time, the rest are inconclusive.
17. **Injected anomalies (INJ-01 to INJ-05).** Each is appended after the baseline with higher IDs, on accounts whose later history it cannot disturb: a purchase after account closure, a debit that drives a no-overdraft account negative, a transfer whose credit leg is smaller than the debit leg, an alert with no triggering transaction (in its own new case), and a disposition action dated before its alert. Account `current_balance` is updated where an injected transaction changes the last balance.

## Known limitations (update as the project grows)

- Rules are fixed thresholds, not learned. Overlaps happen: 6 of the 236 RUL-002 alerts fire on transactions that belong to circular-transfer or large-payment patterns (a new device legitimately used for a large debit). They are reported as `overlaps_other_pattern`.
- About 600 alerts are produced from the 100,000 transactions (the generator's `--alerts` target of 1,000 only scales the planted patterns); every alert comes from a planted pattern or a labelled benign look-alike, so there is no unlabelled noise.
- Benign look-alikes score lower on average but the ranges overlap, so score alone cannot separate them.
- Analyst names, notes and timings are synthetic templates.
- Pattern labels exist for transactions and transfers only; alerts and cases are judged through their triggering transaction.
