#!/usr/bin/env python3
"""Step 5: data validator and reproducibility check (standard library only).

Checks every rule in docs/data_dictionary.md, then compares the findings with ground_truth.csv:
every row labelled should_fail_validation must be found, and nothing else may be reported.

Run:  python src/validator.py --data data_final
      python src/validator.py --data data_final --repro     (also rebuilds everything twice and compares hashes)
Exit code 0 means the data passed (clean apart from the labelled anomalies and all of those caught).
"""
import argparse, csv, hashlib, json, os, re, subprocess, sys, tempfile
from collections import defaultdict
from datetime import datetime

FMT = "%Y-%m-%dT%H:%M:%SZ"
TABLES = ["customers", "accounts", "account_status_history", "merchants", "devices", "device_account_links", "transactions",
          "transfer_links", "risk_rules", "alerts", "cases", "case_alerts", "analyst_actions", "ground_truth"]
PK = dict(customers="customer_id", accounts="account_id", account_status_history="history_id", merchants="merchant_id",
          devices="device_id", device_account_links="link_id", transactions="transaction_id", transfer_links="transfer_id",
          risk_rules="rule_id", alerts="alert_id", cases="case_id", case_alerts="case_alert_id", analyst_actions="action_id",
          ground_truth="truth_id")
ID_RE = dict(customer_id=r"CUS-\d{6}", account_id=r"ACC-CUS-\d{6}-\d{2}", history_id=r"ASH-\d{7}", merchant_id=r"MER-\d{6}",
             device_id=r"DEV-\d{6}", link_id=r"DAL-\d{7}", transaction_id=r"TXN-2026-\d{8}", transfer_id=r"TRF-2026-\d{6}",
             rule_id=r"RUL-\d{3}", alert_id=r"ALT-2026-\d{6}", case_id=r"CASE-2026-\d{6}", case_alert_id=r"CAL-\d{6}",
             action_id=r"ACT-2026-\d{6}", truth_id=r"GT-\d{6}")
ENUMS = {
    ("customers", "kyc_status"): "pending verified rejected expired", ("customers", "kyc_risk_tier"): "low medium high",
    ("customers", "status"): "active suspended closed", ("accounts", "account_type"): "savings current",
    ("accounts", "currency"): "INR", ("accounts", "status"): "active dormant frozen closed",
    ("account_status_history", "new_status"): "active dormant frozen closed",
    ("merchants", "category"): "grocery fuel travel electronics dining utilities gambling crypto other",
    ("merchants", "risk_level"): "low medium high", ("devices", "device_type"): "mobile web atm pos",
    ("transactions", "direction"): "debit credit", ("transactions", "txn_type"): "purchase transfer_out transfer_in deposit withdrawal fee",
    ("transactions", "channel"): "card upi online branch atm", ("transactions", "status"): "posted reversed",
    ("transfer_links", "status"): "completed reversed",
    ("risk_rules", "rule_type"): "velocity_spike new_device circular_transfer dormant_reactivation high_amount",
    ("alerts", "status"): "open under_review closed", ("cases", "status"): "open in_review closed",
    ("cases", "final_disposition"): "|confirmed_suspicious false_positive inconclusive",
    ("analyst_actions", "analyst_role"): "operations_analyst risk_reviewer administrator",
    ("analyst_actions", "action_type"): "assign review escalate request_info disposition",
    ("analyst_actions", "disposition"): "|confirmed_suspicious false_positive inconclusive",
    ("ground_truth", "entity_type"): "transaction account transfer alert case analyst_action",
    ("ground_truth", "label_kind"): "planted_pattern injected_anomaly false_positive",
    ("ground_truth", "expected_decision"): "should_alert should_not_alert should_fail_validation should_alert_then_dismiss",
}
ALLOWED = {"active": {"dormant", "frozen", "closed"}, "dormant": {"active", "closed"}, "frozen": {"active", "closed"}, "closed": set()}
ALERT_STATUS = {"closed": "closed", "in_review": "under_review", "open": "open"}
EXTRA_ALERT_BONUS = 5


def pts(s):
    return datetime.strptime(s, FMT)


def paise(s):
    neg = s.startswith("-")
    a, _, b = s.lstrip("-").partition(".")
    v = int(a) * 100 + int((b + "00")[:2])
    return -v if neg else v


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class V:
    def __init__(self, folder):
        self.t = {}
        for n in TABLES:
            with open(os.path.join(folder, n + ".csv"), newline="", encoding="utf-8") as f:
                self.t[n] = list(csv.DictReader(f))
        self.f = []  # findings

    def add(self, check, issue, etype, eid, detail):
        self.f.append(dict(check=check, issue_type=issue, entity_type=etype, entity_id=eid, detail=detail))

    # ------------------------------------------------------------ generic structure
    def structure(self):
        for n, rows in self.t.items():
            pk = PK[n]
            seen = set()
            for r in rows:
                if not re.fullmatch(ID_RE[pk], r[pk]):
                    self.add("id_format", "format_violation", n, r[pk], f"{pk} does not match {ID_RE[pk]}")
                if r[pk] in seen:
                    self.add("pk_unique", "duplicate_key", n, r[pk], "duplicate primary key")
                seen.add(r[pk])
        for (n, col), vals in ENUMS.items():
            allowed = set(vals.lstrip("|").split())
            if vals.startswith("|"):
                allowed.add("")
            for r in self.t[n]:
                if r[col] not in allowed:
                    self.add("enum", "enum_violation", n, r[PK[n]], f"{col}={r[col]!r}")

    def fk(self, n, col, target, optional=False):
        ids = {r[PK[target]] for r in self.t[target]}
        for r in self.t[n]:
            v = r[col]
            if (v == "" and optional) or v in ids:
                continue
            self.add("fk", "referential_integrity", n, r[PK[n]], f"{col}={v!r} not found in {target}")

    def references(self):
        self.fk("accounts", "customer_id", "customers")
        self.fk("account_status_history", "account_id", "accounts")
        self.fk("device_account_links", "device_id", "devices")
        self.fk("device_account_links", "account_id", "accounts")
        self.fk("transactions", "account_id", "accounts")
        self.fk("transactions", "merchant_id", "merchants", True)
        self.fk("transactions", "device_id", "devices", True)
        for c in ("debit_txn_id", "credit_txn_id"):
            self.fk("transfer_links", c, "transactions")
        for c in ("source_account_id", "destination_account_id"):
            self.fk("transfer_links", c, "accounts")
        self.fk("alerts", "rule_id", "risk_rules")
        self.fk("alerts", "transaction_id", "transactions", True)  # an empty value is reported by alert_trigger below
        self.fk("alerts", "account_id", "accounts")
        self.fk("cases", "customer_id", "customers")
        self.fk("case_alerts", "case_id", "cases")
        self.fk("case_alerts", "alert_id", "alerts")
        self.fk("analyst_actions", "case_id", "cases")
        self.fk("analyst_actions", "alert_id", "alerts", True)

    # ------------------------------------------------------------ master data
    def master(self):
        cust = {r["customer_id"]: r for r in self.t["customers"]}
        for r in self.t["customers"]:
            onb = pts(r["onboarded_at"])
            dob = datetime.strptime(r["date_of_birth"], "%Y-%m-%d")
            age = (onb - dob).days / 365.25
            if not 18 <= age <= 90:
                self.add("age_range", "master_data_rule", "customers", r["customer_id"], f"age {age:.1f} at onboarding")
            if (r["kyc_status"] == "verified") != (r["kyc_verified_at"] != ""):
                self.add("kyc_verified_at", "master_data_rule", "customers", r["customer_id"], "kyc_verified_at present iff verified")
            elif r["kyc_verified_at"] and pts(r["kyc_verified_at"]) < onb:
                self.add("kyc_verified_at", "master_data_rule", "customers", r["customer_id"], "verified before onboarding")
            if onb > datetime(2026, 11, 12):
                self.add("onboarded_future", "master_data_rule", "customers", r["customer_id"], "onboarded in the future")
        hist = defaultdict(list)
        for r in self.t["account_status_history"]:
            hist[r["account_id"]].append(r)
        for r in self.t["accounts"]:
            a = r["account_id"]
            if r["customer_id"] in cust and pts(r["opened_at"]) < pts(cust[r["customer_id"]]["onboarded_at"]):
                self.add("account_opened", "master_data_rule", "accounts", a, "opened before customer onboarded")
            if not a.startswith(f"ACC-{r['customer_id']}-"):
                self.add("id_format", "format_violation", "accounts", a, "account_id does not embed customer_id")
            if (r["status"] == "closed") != (r["closed_at"] != ""):
                self.add("closed_at", "master_data_rule", "accounts", a, "closed_at present iff status closed")
            elif r["closed_at"] and pts(r["closed_at"]) <= pts(r["opened_at"]):
                self.add("closed_at", "master_data_rule", "accounts", a, "closed_at not after opened_at")
            if paise(r["overdraft_limit"]) < 0 or paise(r["opening_balance"]) < 0:
                self.add("account_amounts", "master_data_rule", "accounts", a, "negative overdraft_limit or opening_balance")
            h = sorted(hist[a], key=lambda x: x["history_id"])
            prev, prev_t = "", None
            for x in h:
                t = pts(x["changed_at"])
                if x["old_status"] != prev:
                    self.add("history_chain", "master_data_rule", "account_status_history", x["history_id"], "old_status does not follow previous row")
                elif prev and x["new_status"] not in ALLOWED[prev]:
                    self.add("history_transition", "master_data_rule", "account_status_history", x["history_id"], f"{prev} -> {x['new_status']} not allowed")
                if prev_t and t <= prev_t:
                    self.add("history_order", "master_data_rule", "account_status_history", x["history_id"], "changed_at not increasing")
                prev, prev_t = x["new_status"], t
            if not h or prev != r["status"]:
                self.add("history_status", "master_data_rule", "accounts", a, "status differs from last history row")
            if r["closed_at"] and h and h[-1]["new_status"] == "closed" and pts(h[-1]["changed_at"]) != pts(r["closed_at"]):
                self.add("closed_at", "master_data_rule", "accounts", a, "closed_at differs from history")
        mer = {r["merchant_id"]: r for r in self.t["merchants"]}
        for r in self.t["merchants"]:
            if r["category"] in ("gambling", "crypto") and r["risk_level"] != "high":
                self.add("merchant_risk", "master_data_rule", "merchants", r["merchant_id"], "gambling/crypto must be high risk")

    # ------------------------------------------------------------ transactions
    def transactions(self):
        acc = {r["account_id"]: r for r in self.t["accounts"]}
        by = defaultdict(list)
        for r in self.t["transactions"]:
            by[r["account_id"]].append(r)
        pair = {}
        for acc_id, lst in by.items():
            lst.sort(key=lambda r: (r["txn_timestamp"], r["transaction_id"]))
            a = acc.get(acc_id)
            if not a:
                continue
            od = paise(a["overdraft_limit"])
            bal = paise(a["opening_balance"])
            closed = pts(a["closed_at"]) if a["closed_at"] else None
            for r in lst:
                t = pts(r["txn_timestamp"])
                amt = paise(r["amount"])
                tid = r["transaction_id"]
                if amt <= 0:
                    self.add("txn_amount", "txn_rule", "transactions", tid, "amount must be positive")
                if t < pts(a["opened_at"]):
                    self.add("txn_before_open", "txn_rule", "transactions", tid, "transaction before account opened")
                if closed and t > closed:
                    self.add("txn_on_closed", "txn_on_closed_account", "transactions", tid, f"posted {r['txn_timestamp']} after closed_at {a['closed_at']}")
                if r["merchant_id"] and r["txn_type"] != "purchase":
                    self.add("txn_merchant", "txn_rule", "transactions", tid, "merchant only allowed on purchases")
                bal += amt if r["direction"] == "credit" else -amt
                if bal != paise(r["balance_after"]):
                    self.add("balance_recon", "balance_reconciliation_error", "transactions", tid, f"expected {bal / 100:.2f}, found {r['balance_after']}")
                    bal = paise(r["balance_after"])  # resync so one error is reported once
                if paise(r["balance_after"]) < -od:
                    self.add("balance_floor", "negative_balance_no_overdraft", "transactions", tid,
                             f"balance_after {r['balance_after']} below overdraft floor -{od / 100:.2f}")
                if r["device_id"]:
                    k = (r["device_id"], acc_id)
                    lo, hi = pair.get(k, (r["txn_timestamp"], r["txn_timestamp"]))
                    pair[k] = (min(lo, r["txn_timestamp"]), max(hi, r["txn_timestamp"]))
            if lst and paise(a["current_balance"]) != paise(lst[-1]["balance_after"]):
                self.add("current_balance", "balance_reconciliation_error", "accounts", acc_id, "current_balance differs from last balance_after")
            if lst and paise(a["current_balance"]) < -od:
                self.add("balance_floor", "negative_balance_no_overdraft", "accounts", acc_id,
                         f"current_balance {a['current_balance']} below overdraft floor -{od / 100:.2f}")
        for r in self.t["accounts"]:
            if r["account_id"] not in by and paise(r["current_balance"]) != paise(r["opening_balance"]):
                self.add("current_balance", "balance_reconciliation_error", "accounts", r["account_id"], "no transactions but balance changed")
        dev = {r["device_id"]: r for r in self.t["devices"]}
        seen = set()
        for r in self.t["device_account_links"]:
            k = (r["device_id"], r["account_id"])
            if k in seen:
                self.add("link_unique", "duplicate_key", "device_account_links", r["link_id"], "duplicate device/account pair")
            seen.add(k)
            if k not in pair:
                self.add("link_derived", "master_data_rule", "device_account_links", r["link_id"], "no transactions for this pair")
            elif (r["first_seen_at"], r["last_seen_at"]) != pair[k]:
                self.add("link_derived", "master_data_rule", "device_account_links", r["link_id"], "first/last seen differ from transactions")
        for k in pair:
            if k not in seen:
                self.add("link_missing", "master_data_rule", "device_account_links", f"{k[0]}|{k[1]}", "transactions use a pair with no link row")
        first = {}
        for (dv, _), (lo, _hi) in pair.items():
            first[dv] = min(first.get(dv, lo), lo)
        for dv, lo in first.items():
            if dv in dev and dev[dv]["first_seen_at"] > lo:
                self.add("device_first_seen", "master_data_rule", "devices", dv, "first_seen_at later than first linked transaction")

    def transfers(self):
        tx = {r["transaction_id"]: r for r in self.t["transactions"]}
        for r in self.t["transfer_links"]:
            d, c = tx.get(r["debit_txn_id"]), tx.get(r["credit_txn_id"])
            if not d or not c:
                continue
            tid = r["transfer_id"]
            if d["direction"] != "debit" or c["direction"] != "credit":
                self.add("transfer_legs", "transfer_link_inconsistency", "transfer_links", tid, "leg directions wrong")
            if d["account_id"] != r["source_account_id"] or c["account_id"] != r["destination_account_id"]:
                self.add("transfer_legs", "transfer_link_inconsistency", "transfer_links", tid, "leg accounts do not match link")
            if r["source_account_id"] == r["destination_account_id"]:
                self.add("transfer_legs", "transfer_link_inconsistency", "transfer_links", tid, "source equals destination")
            if r["initiated_at"] != d["txn_timestamp"]:
                self.add("transfer_legs", "transfer_link_inconsistency", "transfer_links", tid, "initiated_at differs from debit leg")
            if not (paise(r["transfer_amount"]) == paise(d["amount"]) == paise(c["amount"])):
                self.add("transfer_amount", "transfer_legs_mismatch", "transfer_links", tid,
                         f"transfer {r['transfer_amount']}, debit leg {d['amount']}, credit leg {c['amount']}")
        used = defaultdict(int)
        for r in self.t["transfer_links"]:
            used[r["debit_txn_id"]] += 1
            used[r["credit_txn_id"]] += 1
        for k, n in used.items():
            if n > 1:
                self.add("transfer_unique", "duplicate_key", "transfer_links", k, "transaction used in more than one transfer")

    # ------------------------------------------------------------ alerts, cases, actions
    def alerts(self):
        tx = {r["transaction_id"]: r for r in self.t["transactions"]}
        for r in self.t["alerts"]:
            a = r["alert_id"]
            try:
                parts = json.loads(r["score_breakdown"])
                if sum(parts.values()) != int(r["risk_score"]):
                    self.add("score_sum", "score_breakdown_mismatch", "alerts", a, "breakdown does not add up to risk_score")
            except (ValueError, TypeError):
                self.add("score_sum", "score_breakdown_mismatch", "alerts", a, "score_breakdown is not valid JSON of numbers")
            if not 0 <= int(r["risk_score"]) <= 100:
                self.add("score_range", "score_breakdown_mismatch", "alerts", a, "risk_score outside 0-100")
            if r["transaction_id"] == "":
                self.add("alert_trigger", "alert_without_trigger", "alerts", a, "no triggering transaction")
                continue
            t = tx.get(r["transaction_id"])
            if t:
                if t["account_id"] != r["account_id"]:
                    self.add("alert_account", "alert_inconsistency", "alerts", a, "account differs from triggering transaction")
                if pts(r["created_at"]) < pts(t["txn_timestamp"]):
                    self.add("alert_time", "alert_inconsistency", "alerts", a, "created before triggering transaction")

    def cases(self):
        alerts = {r["alert_id"]: r for r in self.t["alerts"]}
        acc = {r["account_id"]: r for r in self.t["accounts"]}
        cases = {r["case_id"]: r for r in self.t["cases"]}
        in_case = defaultdict(list)
        seen = defaultdict(int)
        for l in self.t["case_alerts"]:
            seen[l["alert_id"]] += 1
            if l["alert_id"] in alerts:
                in_case[l["case_id"]].append(l)
                if pts(l["linked_at"]) < pts(alerts[l["alert_id"]]["created_at"]):
                    self.add("link_time", "case_inconsistency", "case_alerts", l["case_alert_id"], "linked before alert was created")
        for k, n in seen.items():
            if n > 1:
                self.add("alert_one_case", "case_inconsistency", "alerts", k, "alert belongs to more than one case")
        acts = defaultdict(list)
        for r in self.t["analyst_actions"]:
            acts[r["case_id"]].append(r)
        for cid, c in cases.items():
            ls = in_case.get(cid, [])
            als = [alerts[l["alert_id"]] for l in ls]
            if not als:
                self.add("case_alerts", "case_inconsistency", "cases", cid, "case has no alerts")
                continue
            for a in als:
                if acc[a["account_id"]]["customer_id"] != c["customer_id"]:
                    self.add("case_customer", "case_inconsistency", "cases", cid, f"alert {a['alert_id']} belongs to another customer")
                if a["status"] != ALERT_STATUS[c["status"]]:
                    self.add("alert_status", "case_inconsistency", "alerts", a["alert_id"], "alert status does not match case status")
            if pts(c["opened_at"]) < min(pts(a["created_at"]) for a in als):
                self.add("case_opened", "case_inconsistency", "cases", cid, "opened before its earliest alert")
            want = min(100, max(int(a["risk_score"]) for a in als) + EXTRA_ALERT_BONUS * (len(als) - 1))
            if int(c["priority_score"]) != want:
                self.add("case_priority", "case_inconsistency", "cases", cid, f"priority {c['priority_score']}, expected {want}")
            disp = sorted([x for x in acts[cid] if x["action_type"] == "disposition"], key=lambda x: x["action_timestamp"])
            closed = c["status"] == "closed"
            if closed != (c["final_disposition"] != "") or closed != (c["closed_at"] != ""):
                self.add("case_closed", "case_inconsistency", "cases", cid, "final_disposition/closed_at present iff status closed")
            elif closed:
                if not disp or disp[-1]["disposition"] != c["final_disposition"] or pts(disp[-1]["action_timestamp"]) != pts(c["closed_at"]):
                    self.add("case_closed", "case_inconsistency", "cases", cid, "final_disposition/closed_at differ from last disposition action")
                if pts(c["closed_at"]) <= pts(c["opened_at"]):
                    self.add("case_closed", "case_inconsistency", "cases", cid, "closed_at not after opened_at")
            elif disp:
                self.add("case_closed", "case_inconsistency", "cases", cid, "disposition action on a case that is not closed")
        for r in self.t["analyst_actions"]:
            aid, t = r["action_id"], pts(r["action_timestamp"])
            if (r["action_type"] == "disposition") != (r["disposition"] != ""):
                self.add("action_disposition", "action_inconsistency", "analyst_actions", aid, "disposition present iff action_type disposition")
            if not re.fullmatch(r"ANL-\d{2}", r["analyst_id"]):
                self.add("id_format", "format_violation", "analyst_actions", aid, "analyst_id format")
            c = cases.get(r["case_id"])
            if r["alert_id"]:
                a = alerts.get(r["alert_id"])
                if a and r["alert_id"] not in {l["alert_id"] for l in in_case.get(r["case_id"], [])}:
                    self.add("action_alert", "action_inconsistency", "analyst_actions", aid, "alert does not belong to the case")
                if a and t < pts(a["created_at"]):
                    issue = "disposition_before_alert" if r["action_type"] == "disposition" else "action_inconsistency"
                    self.add("action_time", issue, "analyst_actions", aid, f"{r['action_type']} at {r['action_timestamp']} before alert created {a['created_at']}")
            elif c and t < pts(c["opened_at"]):
                self.add("action_time", "action_inconsistency", "analyst_actions", aid, "action before the case was opened")

    def run(self):
        self.structure()
        self.references()
        self.master()
        self.transactions()
        self.transfers()
        self.alerts()
        self.cases()
        return self.f


def compare(findings, gt):
    expected = {(g["issue_type"], g["entity_id"]) for g in gt if g["expected_decision"] == "should_fail_validation"}
    found = {(f["issue_type"], f["entity_id"]) for f in findings}
    return sorted(expected - found), sorted(found - expected), expected


def repro(data_dir):
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(data_dir, "build_manifest.json")) as f:
        manifest = json.load(f)
    seed = manifest["seed"]
    runs = []
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("run1", "run2"):
            base, fin = os.path.join(tmp, name + "_base"), os.path.join(tmp, name + "_final")
            subprocess.run([sys.executable, os.path.join(here, "generator.py"), "--seed", str(seed), "--out", base],
                           check=True, stdout=subprocess.DEVNULL)
            subprocess.run([sys.executable, os.path.join(here, "build_triage.py"), "--in", base, "--out", fin],
                           check=True, stdout=subprocess.DEVNULL)
            runs.append({f: sha(os.path.join(fin, f)) for f in sorted(os.listdir(fin)) if f.endswith(".csv")})
    committed = {f: sha(os.path.join(data_dir, f)) for f in sorted(os.listdir(data_dir)) if f.endswith(".csv")}
    ok1, ok2 = runs[0] == runs[1], runs[0] == committed
    print(f"\nReproducibility (seed {seed}, two full rebuilds):")
    print(f"  run 1 == run 2 .............. {'PASS' if ok1 else 'FAIL'}")
    print(f"  rebuild == {data_dir}/ ........ {'PASS' if ok2 else 'FAIL'}")
    for f in committed:
        if runs[0].get(f) != committed[f]:
            print(f"  differs: {f}")
    return ok1 and ok2


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data_final")
    ap.add_argument("--repro", action="store_true", help="rebuild twice from the seed and compare file hashes")
    ap.add_argument("--report", default=None, help="where to write the JSON report (default <data>/validation_report.json)")
    a = ap.parse_args()
    v = V(a.data)
    findings = v.run()
    missing, unexpected, expected = compare(findings, v.t["ground_truth"])
    by = defaultdict(int)
    for f in findings:
        by[(f["check"], f["issue_type"])] += 1
    print(f"Validated {a.data}/: {sum(len(r) for r in v.t.values()):,} rows in {len(v.t)} tables")
    print(f"Findings: {len(findings)}   labelled anomalies expected: {len(expected)}")
    for (chk, issue), n in sorted(by.items()):
        print(f"  {chk:18s} {issue:32s} {n}")
    print(f"Caught {len(expected) - len(missing)} / {len(expected)} labelled anomalies; unexpected findings: {len(unexpected)}")
    for m in missing:
        print("  MISSED    ", m)
    for u in unexpected[:20]:
        print("  UNEXPECTED", u)
    ok = not missing and not unexpected
    report = dict(data=a.data, passed=ok, findings=findings, missed=missing, unexpected=unexpected)
    path = a.report or os.path.join(a.data, "validation_report.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    if a.repro:
        ok = repro(a.data) and ok
    print("\nRESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
