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

## Known limitations (update as the project grows)

- To be filled in after the generator and validator are built.
