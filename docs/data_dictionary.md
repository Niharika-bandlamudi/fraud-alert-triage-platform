# Data Dictionary

Synthetic data only. All people, accounts, merchants and devices are generated.

## Global conventions

- **Money:** decimal with 2 places, currency INR (one currency to keep reconciliation simple).
- **Timestamps:** ISO 8601, UTC. **Dates:** `YYYY-MM-DD`.
- **IDs:** zero-padded, immutable, identical across every file that references them.
- **Seed:** `20261022` (default). Scale is a parameter so starter and full datasets use the same generator.
- **History:** state changes are appended as new rows (see `AccountStatusHistory`, `AnalystAction`). Nothing is overwritten.
- **Derived** means the value is computed from other records, never generated independently.

## ID formats

| Entity | Format | Example |
|---|---|---|
| Customer | `CUS-NNNNNN` | CUS-000001 |
| Account | `ACC-<customer_id>-NN` | ACC-CUS-000001-01 |
| Merchant | `MER-NNNNNN` | MER-000001 |
| Device | `DEV-NNNNNN` | DEV-000001 |
| Transaction | `TXN-2026-NNNNNNNN` | TXN-2026-00000001 |
| TransferLink | `TRF-2026-NNNNNN` | TRF-2026-000001 |
| RiskRule | `RUL-NNN` | RUL-001 |
| Alert | `ALT-2026-NNNNNN` | ALT-2026-000001 |
| Case | `CASE-2026-NNNNNN` | CASE-2026-000001 |
| AnalystAction | `ACT-2026-NNNNNN` | ACT-2026-000001 |

## 1. Customer (master)

PK: `customer_id`. Relationships: 1:N to Account, 1:N to Case.

| Field | Type | Req | Allowed values / rule | Unique |
|---|---|---|---|---|
| customer_id | string | Y | `CUS-\d{6}` | Y |
| full_name | string | Y | synthetic, 2-80 chars | N |
| date_of_birth | date | Y | age 18-90 at `onboarded_at` | N |
| country | string | Y | ISO 3166 alpha-2 | N |
| kyc_status | enum | Y | pending, verified, rejected, expired | N |
| kyc_risk_tier | enum | Y | low, medium, high | N |
| kyc_verified_at | datetime | O | required iff `kyc_status` = verified; >= `onboarded_at` | N |
| onboarded_at | datetime | Y | not in the future | N |
| status | enum | Y | active, suspended, closed | N |

## 2. Account (master)

PK: `account_id`. FK: `customer_id` -> Customer. 1:N to Transaction, 1:N to AccountStatusHistory.

| Field | Type | Req | Allowed values / rule | Unique |
|---|---|---|---|---|
| account_id | string | Y | `ACC-<customer_id>-\d{2}` | Y |
| customer_id | string | Y | must exist in Customer | N |
| account_type | enum | Y | savings, current | N |
| currency | string | Y | `INR` | N |
| status | enum | Y | active, dormant, frozen, closed (current state, derived from history) | N |
| opened_at | datetime | Y | >= customer `onboarded_at` | N |
| closed_at | datetime | O | required iff status = closed; > `opened_at` | N |
| overdraft_limit | decimal | Y | >= 0; 0 means no overdraft | N |
| opening_balance | decimal | Y | >= 0 | N |
| current_balance | decimal | Y | derived: `balance_after` of the last posted transaction; >= -`overdraft_limit` | N |

## 3. AccountStatusHistory (event, lifecycle)

PK: `history_id`. FK: `account_id` -> Account. Append-only.

| Field | Type | Req | Allowed values / rule | Unique |
|---|---|---|---|---|
| history_id | string | Y | `ASH-\d{7}` | Y |
| account_id | string | Y | must exist in Account | N |
| old_status | enum | O | null for the first row; else active, dormant, frozen, closed | N |
| new_status | enum | Y | active, dormant, frozen, closed | N |
| changed_at | datetime | Y | strictly increasing per account | N |
| reason | string | O | free text, max 200 chars | N |

Allowed transitions: active -> dormant, frozen, closed; dormant -> active, closed; frozen -> active, closed. `closed` is terminal.

## 4. Merchant (master)

PK: `merchant_id`.

| Field | Type | Req | Allowed values / rule | Unique |
|---|---|---|---|---|
| merchant_id | string | Y | `MER-\d{6}` | Y |
| merchant_name | string | Y | synthetic | N |
| category | enum | Y | grocery, fuel, travel, electronics, dining, utilities, gambling, crypto, other | N |
| country | string | Y | ISO 3166 alpha-2 | N |
| risk_level | enum | Y | low, medium, high | N |

## 5. Device (master)

PK: `device_id`. M:N with Account through DeviceAccountLink.

| Field | Type | Req | Allowed values / rule | Unique |
|---|---|---|---|---|
| device_id | string | Y | `DEV-\d{6}` | Y |
| device_type | enum | Y | mobile, web, atm, pos | N |
| os_family | string | O | android, ios, windows, other | N |
| first_seen_at | datetime | Y | <= first linked transaction | N |

## 6. DeviceAccountLink (bridge)

PK: `link_id`. FKs: `device_id` -> Device, `account_id` -> Account. Unique pair (`device_id`, `account_id`).

| Field | Type | Req | Allowed values / rule | Unique |
|---|---|---|---|---|
| link_id | string | Y | `DAL-\d{7}` | Y |
| device_id | string | Y | must exist in Device | N |
| account_id | string | Y | must exist in Account | N |
| first_seen_at | datetime | Y | derived: earliest transaction on this pair | N |
| last_seen_at | datetime | Y | derived; >= `first_seen_at` | N |

## 7. Transaction (event)

PK: `transaction_id`. FKs: `account_id` -> Account (required), `merchant_id` -> Merchant (optional), `device_id` -> Device (optional).

| Field | Type | Req | Allowed values / rule | Unique |
|---|---|---|---|---|
| transaction_id | string | Y | `TXN-2026-\d{8}` | Y |
| account_id | string | Y | must exist; account not closed at `txn_timestamp` (except labelled anomaly) | N |
| merchant_id | string | O | only for card/online purchases | N |
| device_id | string | O | must exist if present | N |
| txn_timestamp | datetime | Y | >= account `opened_at` | N |
| direction | enum | Y | debit, credit | N |
| amount | decimal | Y | > 0 | N |
| txn_type | enum | Y | purchase, transfer_out, transfer_in, deposit, withdrawal, fee | N |
| channel | enum | Y | card, upi, online, branch, atm | N |
| status | enum | Y | posted, reversed | N |
| balance_after | decimal | Y | derived: previous `balance_after` -/+ `amount`; >= -`overdraft_limit` (except labelled anomaly) | N |

Reconciliation rule: for each account ordered by timestamp, `balance_after[n] = balance_after[n-1] + (credit ? amount : -amount)`, starting from `opening_balance`.

## 8. TransferLink (relationship)

PK: `transfer_id`. FKs: `debit_txn_id`, `credit_txn_id` -> Transaction; `source_account_id`, `destination_account_id` -> Account.

| Field | Type | Req | Allowed values / rule | Unique |
|---|---|---|---|---|
| transfer_id | string | Y | `TRF-2026-\d{6}` | Y |
| debit_txn_id | string | Y | transaction with direction = debit | Y |
| credit_txn_id | string | Y | transaction with direction = credit | Y |
| source_account_id | string | Y | equals account of the debit leg | N |
| destination_account_id | string | Y | equals account of the credit leg; != source | N |
| transfer_amount | decimal | Y | equals both leg amounts (except labelled anomaly) | N |
| initiated_at | datetime | Y | equals debit leg timestamp | N |
| status | enum | Y | completed, reversed | N |

## 9. RiskRule (reference)

PK: `rule_id`. 1:N to Alert.

| Field | Type | Req | Allowed values / rule | Unique |
|---|---|---|---|---|
| rule_id | string | Y | `RUL-\d{3}` | Y |
| rule_name | string | Y | short name | Y |
| rule_type | enum | Y | velocity_spike, new_device, circular_transfer, dormant_reactivation, high_amount | N |
| description | string | Y | plain-language logic | N |
| parameters | json | Y | thresholds, e.g. `{"window_minutes": 60, "min_count": 8}` | N |
| weight | integer | Y | 1-100, contribution to alert score | N |
| effective_from | date | Y | | N |
| effective_to | date | O | > `effective_from` if present | N |
| is_active | boolean | Y | | N |

## 10. Alert (event)

PK: `alert_id`. FKs: `rule_id` -> RiskRule, `transaction_id` -> Transaction, `account_id` -> Account. Bridge to Case via CaseAlert.

| Field | Type | Req | Allowed values / rule | Unique |
|---|---|---|---|---|
| alert_id | string | Y | `ALT-2026-\d{6}` | Y |
| rule_id | string | Y | must exist in RiskRule | N |
| transaction_id | string | Y | triggering transaction (null only in the labelled anomaly) | N |
| account_id | string | Y | equals account of the transaction | N |
| created_at | datetime | Y | >= transaction `txn_timestamp` | N |
| risk_score | integer | Y | 0-100, derived from `score_breakdown` | N |
| score_breakdown | json | Y | per-factor points that add up to `risk_score` | N |
| evidence | string | Y | plain-language reason the rule fired | N |
| status | enum | Y | open, under_review, closed | N |

## 11. Case (event)

PK: `case_id`. FK: `customer_id` -> Customer. Bridge to Alert via CaseAlert.

| Field | Type | Req | Allowed values / rule | Unique |
|---|---|---|---|---|
| case_id | string | Y | `CASE-2026-\d{6}` | Y |
| customer_id | string | Y | must exist in Customer | N |
| opened_at | datetime | Y | >= earliest linked alert `created_at` | N |
| status | enum | Y | open, in_review, closed | N |
| priority_score | integer | Y | derived: max alert score plus a bonus per extra alert, capped at 100 | N |
| final_disposition | enum | O | required iff status = closed; confirmed_suspicious, false_positive, inconclusive | N |
| closed_at | datetime | O | required iff status = closed; > `opened_at` | N |

## 12. CaseAlert (bridge)

PK: `case_alert_id`. FKs: `case_id` -> Case, `alert_id` -> Alert. An alert belongs to at most one case.

| Field | Type | Req | Allowed values / rule | Unique |
|---|---|---|---|---|
| case_alert_id | string | Y | `CAL-\d{6}` | Y |
| case_id | string | Y | must exist in Case | N |
| alert_id | string | Y | must exist in Alert | Y |
| linked_at | datetime | Y | >= alert `created_at` | N |

## 13. AnalystAction (event)

PK: `action_id`. FKs: `case_id` -> Case, `alert_id` -> Alert (optional). Append-only.

| Field | Type | Req | Allowed values / rule | Unique |
|---|---|---|---|---|
| action_id | string | Y | `ACT-2026-\d{6}` | Y |
| case_id | string | Y | must exist in Case | N |
| alert_id | string | O | must belong to the case | N |
| analyst_id | string | Y | synthetic, `ANL-\d{2}` | N |
| analyst_role | enum | Y | operations_analyst, risk_reviewer, administrator | N |
| action_type | enum | Y | assign, review, escalate, request_info, disposition | N |
| disposition | enum | O | required iff action_type = disposition; confirmed_suspicious, false_positive, inconclusive | N |
| notes | string | O | max 500 chars | N |
| action_timestamp | datetime | Y | >= linked alert `created_at` (except labelled anomaly) | N |

## 14. ground_truth (separate file, never an input feature)

PK: `truth_id`.

| Field | Type | Req | Allowed values / rule | Unique |
|---|---|---|---|---|
| truth_id | string | Y | `GT-\d{6}` | Y |
| entity_type | enum | Y | transaction, account, transfer, alert, case | N |
| entity_id | string | Y | ID of the affected record | N |
| label_kind | enum | Y | planted_pattern, injected_anomaly, false_positive | N |
| issue_type | enum | Y | velocity_spike, new_device_activity, circular_transfer, dormant_reactivation, txn_on_closed_account, negative_balance_no_overdraft, transfer_legs_mismatch, alert_without_trigger, disposition_before_alert, benign_lookalike | N |
| expected_decision | enum | Y | should_alert, should_not_alert, should_fail_validation | N |
| generating_rule | string | O | documented rule that produced the label | N |
