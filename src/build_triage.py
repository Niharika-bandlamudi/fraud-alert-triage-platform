#!/usr/bin/env python3
"""Steps 3 and 4: risk rules, alerts, cases, analyst actions and injected anomalies.

Reads the clean baseline written by generator.py (default: data/) and writes the full
dataset to a separate folder (default: data_final/). The baseline folder is never modified,
so the script can be re-run safely and always gives the same output for the same input.

Uses only the Python standard library (random.Random is stable across Python versions).

Run:  python src/build_triage.py --in data --out data_final
"""
import argparse, csv, hashlib, json, os, random
from collections import defaultdict
from datetime import datetime, timedelta

VERSION = "0.2.0"
FMT = "%Y-%m-%dT%H:%M:%SZ"
END = datetime(2026, 10, 31, 23, 59, 59)
SNAPSHOT = datetime(2026, 11, 5)  # analyst work after this moment has not happened yet
RISKY = ("gambling", "crypto")
CASE_GAP = timedelta(days=7)      # alerts of one customer closer than this share a case
EXTRA_ALERT_BONUS = 5             # case priority bonus per extra alert

RULES = [
    dict(rule_id="RUL-001", rule_name="Velocity spike", rule_type="velocity_spike",
         description="8 or more debits on one account within 60 minutes",
         parameters={"window_minutes": 60, "min_count": 8}, weight=40),
    dict(rule_id="RUL-002", rule_name="New device with high spend", rule_type="new_device",
         description="First use of a device on an account (after 5 or more earlier transactions) followed by debits of 25,000 or more within 24 hours",
         parameters={"min_prior_txns": 5, "window_hours": 24, "min_debit_total": 25000}, weight=45),
    dict(rule_id="RUL-003", rule_name="Circular transfer", rule_type="circular_transfer",
         description="Funds return to the origin account through 3 or more hops within 72 hours",
         parameters={"min_hops": 3, "max_hops": 4, "window_hours": 72}, weight=60),
    dict(rule_id="RUL-004", rule_name="Dormant account reactivation", rule_type="dormant_reactivation",
         description="First transaction after 90 or more days of dormancy is a debit of 25,000 or more",
         parameters={"dormant_days": 90, "min_amount": 25000}, weight=50),
    dict(rule_id="RUL-005", rule_name="High-value purchase", rule_type="high_amount",
         description="Single purchase of 100,000 or more (suppressed when RUL-004 already alerts the same transaction)",
         parameters={"min_amount": 100000, "txn_type": "purchase"}, weight=25),
]
RULE = {r["rule_id"]: r for r in RULES}

COLS = {
    "customers": ["customer_id", "full_name", "date_of_birth", "country", "kyc_status", "kyc_risk_tier", "kyc_verified_at", "onboarded_at", "status"],
    "accounts": ["account_id", "customer_id", "account_type", "currency", "status", "opened_at", "closed_at", "overdraft_limit", "opening_balance", "current_balance"],
    "account_status_history": ["history_id", "account_id", "old_status", "new_status", "changed_at", "reason"],
    "merchants": ["merchant_id", "merchant_name", "category", "country", "risk_level"],
    "devices": ["device_id", "device_type", "os_family", "first_seen_at"],
    "device_account_links": ["link_id", "device_id", "account_id", "first_seen_at", "last_seen_at"],
    "transactions": ["transaction_id", "account_id", "merchant_id", "device_id", "txn_timestamp", "direction", "amount", "txn_type", "channel", "status", "balance_after"],
    "transfer_links": ["transfer_id", "debit_txn_id", "credit_txn_id", "source_account_id", "destination_account_id", "transfer_amount", "initiated_at", "status"],
    "risk_rules": ["rule_id", "rule_name", "rule_type", "description", "parameters", "weight", "effective_from", "effective_to", "is_active"],
    "alerts": ["alert_id", "rule_id", "transaction_id", "account_id", "created_at", "risk_score", "score_breakdown", "evidence", "status"],
    "cases": ["case_id", "customer_id", "opened_at", "status", "priority_score", "final_disposition", "closed_at"],
    "case_alerts": ["case_alert_id", "case_id", "alert_id", "linked_at"],
    "analyst_actions": ["action_id", "case_id", "alert_id", "analyst_id", "analyst_role", "action_type", "disposition", "notes", "action_timestamp"],
    "ground_truth": ["truth_id", "entity_type", "entity_id", "label_kind", "issue_type", "expected_decision", "generating_rule", "pattern_instance_id"],
}
COPIED = ["customers", "account_status_history", "merchants", "devices", "device_account_links"]


# ---------------------------------------------------------------- helpers
def pts(s):
    return datetime.strptime(s, FMT)


def fts(d):
    return d.strftime(FMT)


def paise(s):
    neg = s.startswith("-")
    a, _, b = s.lstrip("-").partition(".")
    v = int(a) * 100 + int((b + "00")[:2])
    return -v if neg else v


def money(p):
    s = "-" if p < 0 else ""
    p = abs(int(p))
    return f"{s}{p // 100}.{p % 100:02d}"


def inr(p):
    return f"{p / 100:,.2f}"


def read(path, name):
    with open(os.path.join(path, name + ".csv"), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def jdump(d):
    return json.dumps(d, separators=(",", ":"))


# ---------------------------------------------------------------- load
class Data:
    def __init__(self, folder):
        self.folder = folder
        self.customers = {r["customer_id"]: r for r in read(folder, "customers")}
        self.accounts = read(folder, "accounts")
        self.acc = {r["account_id"]: r for r in self.accounts}
        self.merchants = {r["merchant_id"]: r for r in read(folder, "merchants")}
        self.devices = {r["device_id"]: r for r in read(folder, "devices")}
        self.history = read(folder, "account_status_history")
        self.transfers = read(folder, "transfer_links")
        self.gt = read(folder, "ground_truth")
        self.txn_rows = read(folder, "transactions")
        self.txns = []
        for r in self.txn_rows:
            self.txns.append(dict(tid=r["transaction_id"], acc=r["account_id"], mer=r["merchant_id"], dev=r["device_id"],
                                  ts=pts(r["txn_timestamp"]), dir=r["direction"], amt=paise(r["amount"]), typ=r["txn_type"],
                                  ch=r["channel"], bal=paise(r["balance_after"])))
        self.tx = {t["tid"]: t for t in self.txns}
        self.by_acc = defaultdict(list)
        for t in sorted(self.txns, key=lambda x: (x["ts"], x["tid"])):
            self.by_acc[t["acc"]].append(t)
        self.label = {}  # transaction_id -> (label_kind, issue_type, instance)
        for g in self.gt:
            if g["entity_type"] == "transaction":
                self.label[g["entity_id"]] = (g["label_kind"], g["issue_type"], g["pattern_instance_id"], g["generating_rule"][:7])


# ---------------------------------------------------------------- scoring
def common_factors(d, acc_id, txns):
    f = {}
    cust = d.customers[d.acc[acc_id]["customer_id"]]
    f["customer_risk_tier"] = {"high": 10, "medium": 4}.get(cust["kyc_risk_tier"], 0)
    if cust["kyc_status"] != "verified":
        f["kyc_not_verified"] = 8
    if any(t["mer"] and d.merchants[t["mer"]]["risk_level"] == "high" for t in txns):
        f["high_risk_merchant"] = 10
    return {k: v for k, v in f.items() if v}


def finish(factors):
    """Make the breakdown add up to a score in 0..100 (adjustment rows keep it exact)."""
    s = sum(factors.values())
    if s > 100:
        factors["cap_adjustment"] = 100 - s
    elif s < 0:
        factors["floor_adjustment"] = -s
    return factors, sum(factors.values())


def known_payee(d, acc_id, mer, before, need):
    n = sum(1 for t in d.by_acc[acc_id] if t["ts"] < before and t["typ"] == "purchase" and t["mer"] == mer)
    return n >= need


# ---------------------------------------------------------------- rules
def rule_velocity(d):
    hits = []
    r = RULE["RUL-001"]["parameters"]
    win = timedelta(minutes=r["window_minutes"])
    for acc, lst in d.by_acc.items():
        deb = [t for t in lst if t["dir"] == "debit"]
        left, cool = 0, None
        for i, t in enumerate(deb):
            while t["ts"] - deb[left]["ts"] > win:
                left += 1
            if i - left + 1 >= r["min_count"] and (cool is None or t["ts"] >= cool):
                start = deb[left]["ts"]
                burst = [x for x in deb[left:] if x["ts"] - start <= win]
                total = sum(x["amt"] for x in burst)
                f = {"rule_weight": RULE["RUL-001"]["weight"], "burst_size": min(12, 2 * (len(burst) - r["min_count"]))}
                f["burst_amount"] = 10 if total >= 10000000 else 5 if total >= 5000000 else 0
                if all(x["mer"] and d.merchants[x["mer"]]["category"] == "utilities" for x in burst):
                    f["utilities_payees_only"] = -15
                f.update(common_factors(d, acc, burst))
                ev = (f"{len(burst)} debits within 60 minutes starting {fts(start)} (threshold {r['min_count']}), "
                      f"total INR {inr(total)}")
                hits.append(dict(rule="RUL-001", txn=t, factors=f, evidence=ev))
                cool = t["ts"] + win
    return hits


def rule_new_device(d):
    hits = []
    r = RULE["RUL-002"]["parameters"]
    need = r["min_debit_total"] * 100
    for acc, lst in d.by_acc.items():
        first = {}
        for i, t in enumerate(lst):
            if t["dev"] and t["dev"] not in first:
                first[t["dev"]] = i
        for dev, i in first.items():
            if d.devices[dev]["device_type"] not in ("mobile", "web") or i < r["min_prior_txns"]:
                continue
            t0 = lst[i]["ts"]
            run, used = 0, []
            for t in lst[i:]:
                if t["ts"] - t0 > timedelta(hours=r["window_hours"]):
                    break
                if t["dev"] == dev and t["dir"] == "debit":
                    run += t["amt"]
                    used.append(t)
                    if run >= need:
                        f = {"rule_weight": RULE["RUL-002"]["weight"]}
                        f["debit_amount"] = 10 if run >= 5000000 else 5 if run >= 3500000 else 0
                        mers = {x["mer"] for x in used if x["mer"]}
                        if mers and all(known_payee(d, acc, m, t0, 2) for m in mers):
                            f["known_payees_only"] = -15
                        f.update(common_factors(d, acc, used))
                        ev = (f"Device {dev} first used on this account at {fts(t0)}; debits of INR {inr(run)} "
                              f"via it within 24 hours (threshold {r['min_debit_total']:,})")
                        hits.append(dict(rule="RUL-002", txn=t, factors=f, evidence=ev))
                        break
    return hits


def rule_circular(d):
    hits = []
    r = RULE["RUL-003"]["parameters"]
    win = timedelta(hours=r["window_hours"])
    tl = []
    for t in d.transfers:
        deb, cred = d.tx[t["debit_txn_id"]], d.tx[t["credit_txn_id"]]
        tl.append(dict(id=t["transfer_id"], src=t["source_account_id"], dst=t["destination_account_id"], t0=deb["ts"],
                       t1=cred["ts"], amt=paise(t["transfer_amount"]), cred=cred))
    out = defaultdict(list)
    for t in tl:
        out[t["src"]].append(t)
    seen = set()
    for first in sorted(tl, key=lambda x: (x["t0"], x["id"])):
        stack = [[first]]
        while stack:
            path = stack.pop()
            last = path[-1]
            if last["dst"] == first["src"]:
                if len(path) >= r["min_hops"]:
                    key = frozenset(p["id"] for p in path)
                    if key not in seen:
                        seen.add(key)
                        acc = first["src"]
                        total = sum(p["amt"] for p in path)
                        f = {"rule_weight": RULE["RUL-003"]["weight"], "extra_hops": 5 * (len(path) - r["min_hops"])}
                        f["transfer_amount"] = 10 if first["amt"] >= 30000000 else 5 if first["amt"] >= 10000000 else 0
                        if last["t1"] - first["t0"] <= timedelta(hours=24):
                            f["fast_return"] = 5
                        f.update(common_factors(d, acc, []))
                        route = " -> ".join([p["src"] for p in path] + [acc])
                        ev = (f"Funds left {acc} at {fts(first['t0'])} and returned after {len(path)} hops "
                              f"({route}) within {(last['t1'] - first['t0']).total_seconds() / 3600:.1f} hours; "
                              f"first leg INR {inr(first['amt'])}")
                        hits.append(dict(rule="RUL-003", txn=last["cred"], factors=f, evidence=ev))
                continue
            if len(path) >= r["max_hops"]:
                continue
            visited = {p["src"] for p in path}
            for nxt in out.get(last["dst"], []):
                if nxt["t0"] >= last["t1"] and nxt["t0"] - first["t0"] <= win and (nxt["dst"] == first["src"] or nxt["dst"] not in visited):
                    stack.append(path + [nxt])
    return hits


def rule_dormant(d):
    hits = []
    r = RULE["RUL-004"]["parameters"]
    dormant_at = defaultdict(list)
    for h in d.history:
        if h["new_status"] == "dormant":
            dormant_at[h["account_id"]].append(pts(h["changed_at"]))
    for acc, times in dormant_at.items():
        lst = d.by_acc.get(acc, [])
        for dt in times:
            idx = next((i for i, t in enumerate(lst) if t["ts"] > dt), None)
            if idx is None:
                continue
            t = lst[idx]
            quiet_since = lst[idx - 1]["ts"] if idx > 0 else pts(d.acc[acc]["opened_at"])  # no earlier txn: dormant since opening
            gap = (t["ts"] - quiet_since).days
            if gap >= r["dormant_days"] and t["dir"] == "debit" and t["amt"] >= r["min_amount"] * 100:
                f = {"rule_weight": RULE["RUL-004"]["weight"]}
                f["debit_amount"] = 10 if t["amt"] >= 10000000 else 5 if t["amt"] >= 5000000 else 0
                if gap >= 120:
                    f["long_dormancy"] = 5
                f.update(common_factors(d, acc, [t]))
                ev = (f"First transaction after {gap} days of inactivity (account dormant since {fts(dt)}) "
                      f"is a debit of INR {inr(t['amt'])}")
                hits.append(dict(rule="RUL-004", txn=t, factors=f, evidence=ev))
    return hits


def rule_high_amount(d, skip):
    hits = []
    r = RULE["RUL-005"]["parameters"]
    for t in d.txns:
        if t["dir"] == "debit" and t["typ"] == r["txn_type"] and t["amt"] >= r["min_amount"] * 100 and t["tid"] not in skip:
            f = {"rule_weight": RULE["RUL-005"]["weight"], "debit_amount": 10 if t["amt"] >= 15000000 else 5}
            if t["mer"] and known_payee(d, t["acc"], t["mer"], t["ts"], 3):
                f["known_payee"] = -10
            f.update(common_factors(d, t["acc"], [t]))
            ev = f"Single purchase of INR {inr(t['amt'])} (threshold {r['min_amount']:,})"
            hits.append(dict(rule="RUL-005", txn=t, factors=f, evidence=ev))
    return hits


# ---------------------------------------------------------------- step 3
def build_alerts(d, rng):
    hits = rule_velocity(d) + rule_new_device(d) + rule_circular(d)
    dor = rule_dormant(d)
    hits += dor
    hits += rule_high_amount(d, {h["txn"]["tid"] for h in dor})
    hits.sort(key=lambda h: (h["txn"]["ts"], h["rule"], h["txn"]["tid"]))
    alerts = []
    for h in hits:
        factors, score = finish(dict(h["factors"]))
        created = h["txn"]["ts"] + timedelta(minutes=rng.randint(1, 20), seconds=rng.randint(0, 59))
        alerts.append(dict(rule_id=h["rule"], transaction_id=h["txn"]["tid"], account_id=h["txn"]["acc"], created=created,
                           risk_score=score, breakdown=factors, evidence=h["evidence"], status="open"))
    alerts.sort(key=lambda a: (a["created"], a["rule_id"], a["transaction_id"]))
    for n, a in enumerate(alerts, 1):
        a["alert_id"] = f"ALT-2026-{n:06d}"
    return alerts


def build_cases(d, alerts, rng):
    by_cust = defaultdict(list)
    for a in alerts:
        by_cust[d.acc[a["account_id"]]["customer_id"]].append(a)
    groups = []
    for cust, lst in by_cust.items():
        lst.sort(key=lambda a: a["created"])
        cur = [lst[0]]
        for a in lst[1:]:
            if a["created"] - cur[-1]["created"] > CASE_GAP:
                groups.append((cust, cur))
                cur = []
            cur.append(a)
        groups.append((cust, cur))
    cases = []
    for cust, lst in groups:
        opened = lst[0]["created"] + timedelta(minutes=rng.randint(2, 45), seconds=rng.randint(0, 59))
        cases.append(dict(customer_id=cust, alerts=lst, opened=opened))
    cases.sort(key=lambda c: (c["opened"], c["customer_id"]))
    for n, c in enumerate(cases, 1):
        c["case_id"] = f"CASE-2026-{n:06d}"
    return cases


OPS = [f"ANL-{i:02d}" for i in range(1, 9)]
REV = ["ANL-09", "ANL-10", "ANL-11"]
ADM = ["ANL-12"]


def pick_disposition(d, c, rng):
    labels = [d.label.get(a["transaction_id"]) for a in c["alerts"]]
    if any(l and l[0] == "planted_pattern" for l in labels):
        return "confirmed_suspicious" if rng.random() < 0.92 else "inconclusive"
    if any(l and l[0] == "false_positive" for l in labels):
        return "false_positive" if rng.random() < 0.90 else "inconclusive"
    x = rng.random()
    return "false_positive" if x < 0.6 else "inconclusive" if x < 0.9 else "confirmed_suspicious"


def build_actions(d, cases, rng):
    """Plan each case timeline, cut it at the snapshot date, then derive case and alert status."""
    actions = []
    for c in cases:
        als = sorted(c["alerts"], key=lambda a: a["created"])
        c["priority"] = min(100, max(a["risk_score"] for a in als) + EXTRA_ALERT_BONUS * (len(als) - 1))
        t = c["opened"] + timedelta(minutes=rng.randint(5, 90))
        seq = []
        role = "administrator" if rng.random() < 0.08 else "operations_analyst"
        who = rng.choice(ADM if role == "administrator" else OPS)
        seq.append((t, who, role, "assign", None, "", f"Case assigned to {who} for triage"))
        owner = who if role == "operations_analyst" else rng.choice(OPS)
        for a in als:
            t = max(t, a["created"]) + timedelta(minutes=rng.randint(15, 600), seconds=rng.randint(0, 59))
            seq.append((t, owner, "operations_analyst", "review", a["alert_id"], "",
                        f"Reviewed {RULE[a['rule_id']]['rule_name'].lower()} alert, risk score {a['risk_score']}"))
        escalated = c["priority"] >= 70 or rng.random() < 0.12
        closer, closer_role = owner, "operations_analyst"
        if escalated:
            t += timedelta(minutes=rng.randint(10, 240), seconds=rng.randint(0, 59))
            closer = rng.choice(REV)
            closer_role = "risk_reviewer"
            seq.append((t, owner, "operations_analyst", "escalate", None, "", f"Escalated to risk review (priority {c['priority']})"))
        if rng.random() < 0.18:
            t += timedelta(minutes=rng.randint(20, 480), seconds=rng.randint(0, 59))
            seq.append((t, closer, closer_role, "request_info", None, "", "Requested transaction confirmation from the customer"))
        disp = pick_disposition(d, c, rng)
        t += timedelta(minutes=rng.randint(30, 2880), seconds=rng.randint(0, 59))
        note = {"confirmed_suspicious": "Pattern confirmed, funds movement not explained by customer history",
                "false_positive": "Activity consistent with customer history, no further action",
                "inconclusive": "Evidence insufficient to confirm or dismiss"}[disp]
        seq.append((t, closer, closer_role, "disposition", als[-1]["alert_id"], disp, note))
        if rng.random() < 0.04:  # stuck case: work stops part-way and never reaches a disposition
            seq = seq[:rng.randint(1, len(seq) - 1)]
        seq = [s for s in seq if s[0] <= SNAPSHOT]
        c["seq"] = seq
        disp_row = next((s for s in seq if s[3] == "disposition"), None)
        if disp_row:
            c["status"], c["final_disposition"], c["closed_at"] = "closed", disp_row[5], disp_row[0]
        elif any(s[3] != "assign" for s in seq):
            c["status"], c["final_disposition"], c["closed_at"] = "in_review", "", None
        else:
            c["status"], c["final_disposition"], c["closed_at"] = "open", "", None
        for a in als:
            a["status"] = {"closed": "closed", "in_review": "under_review", "open": "open"}[c["status"]]
        for s in seq:
            actions.append(dict(case_id=c["case_id"], ts=s[0], analyst_id=s[1], role=s[2], type=s[3], alert_id=s[4] or "",
                                disposition=s[5], notes=s[6]))
    actions.sort(key=lambda a: (a["ts"], a["case_id"], a["type"]))
    for n, a in enumerate(actions, 1):
        a["action_id"] = f"ACT-2026-{n:06d}"
    return actions


def link_rows(cases, rng):
    rows = []
    for c in cases:
        for a in sorted(c["alerts"], key=lambda a: a["created"]):
            linked = max(c["opened"], a["created"] + timedelta(minutes=rng.randint(1, 30)))
            rows.append(dict(case_id=c["case_id"], alert_id=a["alert_id"], linked=linked))
    for n, r in enumerate(rows, 1):
        r["case_alert_id"] = f"CAL-{n:06d}"
    return rows


# ---------------------------------------------------------------- step 4
def inject(d, alerts, cases, links, actions, rng):
    """Add the five labelled anomalies after the clean baseline. Returns (new txn rows, new transfer rows, gt rows)."""
    new_txn, new_trf, gt = [], [], []
    last = {}
    for acc, lst in d.by_acc.items():
        last[acc] = (lst[-1]["ts"], lst[-1]["bal"])
    nxt = {"txn": len(d.txns), "trf": len(d.transfers)}
    touched = {}

    def add_txn(acc, ts, direction, amt, typ, ch, mer=""):
        nxt["txn"] += 1
        bal = last[acc][1] + (amt if direction == "credit" else -amt)
        row = dict(transaction_id=f"TXN-2026-{nxt['txn']:08d}", account_id=acc, merchant_id=mer, device_id="",
                   txn_timestamp=fts(ts), direction=direction, amount=money(amt), txn_type=typ, channel=ch, status="posted",
                   balance_after=money(bal))
        new_txn.append(row)
        last[acc] = (ts, bal)
        touched[acc] = bal
        return row

    def gt_row(etype, eid, issue, rule, inst):
        gt.append(dict(entity_type=etype, entity_id=eid, label_kind="injected_anomaly", issue_type=issue,
                       expected_decision="should_fail_validation", generating_rule=rule, pattern_instance_id=inst))

    mers = sorted(d.merchants)
    accs = sorted(d.acc)

    # 1. transaction on a closed account
    cand = [a for a in accs if d.acc[a]["status"] == "closed" and d.acc[a]["closed_at"] and a in last
            and pts(d.acc[a]["closed_at"]) <= END - timedelta(days=10) and last[a][1] + paise_od(d, a) >= 400000]
    a = rng.choice(cand)
    ts = pts(d.acc[a]["closed_at"]) + timedelta(days=rng.randint(1, 20), seconds=rng.randint(0, 86399))
    row = add_txn(a, ts, "debit", rng.randint(1500, 3500) * 100, "purchase", "card", rng.choice(mers))
    gt_row("transaction", row["transaction_id"], "txn_on_closed_account",
           "INJ-01: purchase posted after the account closed_at timestamp", "INJ-01")

    # 2. negative balance on an account with no overdraft
    cand = [a for a in accs if d.acc[a]["status"] == "active" and paise_od(d, a) == 0 and a in last
            and 0 <= last[a][1] <= 3000000 and last[a][0] <= END - timedelta(days=5)]
    a = rng.choice(cand)
    ts = last[a][0] + timedelta(days=rng.randint(1, 3), seconds=rng.randint(0, 3600))
    amt = last[a][1] + rng.randint(2000, 9000) * 100
    row = add_txn(a, ts, "debit", amt, "purchase", "card", rng.choice(mers))
    gt_row("transaction", row["transaction_id"], "negative_balance_no_overdraft",
           "INJ-02: debit larger than the balance on an account with overdraft_limit 0", "INJ-02")
    gt_row("account", a, "negative_balance_no_overdraft",
           "INJ-02: derived current_balance is below the allowed overdraft floor", "INJ-02")

    # 3. transfer whose two legs have different amounts
    cand = [a for a in accs if d.acc[a]["status"] == "active" and a in last and a not in touched
            and last[a][0] <= END - timedelta(days=5)]
    while True:
        s, t = rng.choice(cand), rng.choice(cand)
        amt = rng.randint(20000, 40000) * 100
        if d.acc[s]["customer_id"] != d.acc[t]["customer_id"] and last[s][1] - amt >= -paise_od(d, s):
            break
    ts = max(last[s][0], last[t][0]) + timedelta(days=rng.randint(1, 3), seconds=rng.randint(0, 3600))
    deb = add_txn(s, ts, "debit", amt, "transfer_out", "upi")
    cred = add_txn(t, ts + timedelta(seconds=5), "credit", amt - rng.randint(500, 1500) * 100, "transfer_in", "upi")
    nxt["trf"] += 1
    tid = f"TRF-2026-{nxt['trf']:06d}"
    new_trf.append(dict(transfer_id=tid, debit_txn_id=deb["transaction_id"], credit_txn_id=cred["transaction_id"],
                        source_account_id=s, destination_account_id=t, transfer_amount=deb["amount"],
                        initiated_at=deb["txn_timestamp"], status="completed"))
    gt_row("transfer", tid, "transfer_legs_mismatch",
           "INJ-03: credit leg amount differs from debit leg amount and transfer_amount", "INJ-03")

    # 4. alert without a triggering transaction (placed in its own case)
    a = rng.choice([x for x in accs if d.acc[x]["status"] == "active"])
    created = datetime(2026, 10, 15) + timedelta(seconds=rng.randint(0, 10 * 86400))
    alert = dict(alert_id=f"ALT-2026-{len(alerts) + 1:06d}", rule_id="RUL-005", transaction_id="", account_id=a, created=created,
                 risk_score=55, breakdown={"rule_weight": 25, "manual_flag": 30},
                 evidence="Alert raised with no triggering transaction attached", status="open")
    alerts.append(alert)
    case = dict(case_id=f"CASE-2026-{len(cases) + 1:06d}", customer_id=d.acc[a]["customer_id"], alerts=[alert],
                opened=created + timedelta(minutes=10), status="open", priority=55, final_disposition="", closed_at=None)
    cases.append(case)
    links.append(dict(case_alert_id=f"CAL-{len(links) + 1:06d}", case_id=case["case_id"], alert_id=alert["alert_id"],
                      linked=created + timedelta(minutes=10)))
    actions.append(dict(action_id=f"ACT-2026-{len(actions) + 1:06d}", case_id=case["case_id"], alert_id="", analyst_id="ANL-01",
                        role="operations_analyst", type="assign", disposition="", notes="Case assigned to ANL-01 for triage",
                        ts=created + timedelta(minutes=30)))
    gt_row("alert", alert["alert_id"], "alert_without_trigger",
           "INJ-04: alert has no transaction_id", "INJ-04")

    # 5. disposition recorded before the alert existed
    closed = [c for c in cases if c["status"] == "closed" and c["case_id"] != case["case_id"]]
    c = rng.choice(closed)
    al = sorted(c["alerts"], key=lambda x: x["created"])[0]
    act = dict(action_id=f"ACT-2026-{len(actions) + 1:06d}", case_id=c["case_id"], alert_id=al["alert_id"], analyst_id="ANL-09",
               role="risk_reviewer", type="disposition", disposition=c["final_disposition"],
               notes="Disposition entered from earlier review",
               ts=al["created"] - timedelta(days=rng.randint(1, 3), seconds=rng.randint(0, 3600)))
    actions.append(act)
    gt_row("analyst_action", act["action_id"], "disposition_before_alert",
           "INJ-05: disposition action timestamp is earlier than the alert created_at", "INJ-05")
    return new_txn, new_trf, gt, touched


def paise_od(d, acc):
    return paise(d.acc[acc]["overdraft_limit"])


# ---------------------------------------------------------------- output
def evaluate(d, alerts):
    """Compare alerts with the planted-pattern labels (kept out of the rules themselves)."""
    inst_total, inst_hit = defaultdict(set), defaultdict(set)
    for lab in d.label.values():
        inst_total[lab[1]].add(lab[2])
    per_rule = defaultdict(lambda: defaultdict(int))
    for a in alerts:
        lab = d.label.get(a["transaction_id"]) if a["transaction_id"] else None
        if lab is None:
            kind = "unlabelled"
        elif lab[3] == a["rule_id"]:
            kind = lab[0]
            inst_hit[lab[1]].add(lab[2])
        else:
            kind = "overlaps_other_pattern"  # rule fired legitimately on a txn that belongs to another planted pattern
        per_rule[a["rule_id"]][kind] += 1
    recall = {k: dict(placed=len(v), detected=len(inst_hit.get(k, set()) & v)) for k, v in sorted(inst_total.items())}
    return {k: dict(v) for k, v in sorted(per_rule.items())}, recall


def write(out, name, rows):
    path = os.path.join(out, name + ".csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=COLS[name], lineterminator="\n")
        wr.writeheader()
        wr.writerows(rows)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", default="data")
    ap.add_argument("--out", default="data_final")
    a = ap.parse_args()

    with open(os.path.join(a.src, "generation_manifest.json")) as f:
        base = json.load(f)
    for name, meta in base["files"].items():
        if sha(os.path.join(a.src, name)) != meta["sha256"]:
            raise SystemExit(f"{name} in {a.src}/ does not match its manifest hash. Regenerate it with generator.py first.")
    seed = base["seed"]
    d = Data(a.src)

    alerts = build_alerts(d, random.Random(seed * 7 + 3))
    cases = build_cases(d, alerts, random.Random(seed * 7 + 4))
    actions = build_actions(d, cases, random.Random(seed * 7 + 5))
    links = link_rows(cases, random.Random(seed * 7 + 6))
    per_rule, recall = evaluate(d, alerts)

    new_txn, new_trf, new_gt, touched = inject(d, alerts, cases, links, actions, random.Random(seed * 7 + 7))

    T = {}
    for n in COPIED + ["merchants"]:
        T[n] = read(a.src, n)
    T["accounts"] = []
    for r in d.accounts:
        r = dict(r)
        if r["account_id"] in touched:
            r["current_balance"] = money(touched[r["account_id"]])
        T["accounts"].append(r)
    T["transactions"] = d.txn_rows + new_txn
    T["transfer_links"] = d.transfers + new_trf
    T["risk_rules"] = [dict(rule_id=r["rule_id"], rule_name=r["rule_name"], rule_type=r["rule_type"], description=r["description"],
                            parameters=jdump(r["parameters"]), weight=r["weight"], effective_from="2026-01-01", effective_to="",
                            is_active="true") for r in RULES]
    T["alerts"] = [dict(alert_id=x["alert_id"], rule_id=x["rule_id"], transaction_id=x["transaction_id"], account_id=x["account_id"],
                        created_at=fts(x["created"]), risk_score=x["risk_score"], score_breakdown=jdump(x["breakdown"]),
                        evidence=x["evidence"], status=x["status"]) for x in sorted(alerts, key=lambda z: z["alert_id"])]
    T["cases"] = [dict(case_id=c["case_id"], customer_id=c["customer_id"], opened_at=fts(c["opened"]), status=c["status"],
                       priority_score=c["priority"], final_disposition=c["final_disposition"],
                       closed_at=fts(c["closed_at"]) if c["closed_at"] else "") for c in cases]
    T["case_alerts"] = [dict(case_alert_id=l["case_alert_id"], case_id=l["case_id"], alert_id=l["alert_id"], linked_at=fts(l["linked"]))
                        for l in links]
    T["analyst_actions"] = [dict(action_id=x["action_id"], case_id=x["case_id"], alert_id=x["alert_id"], analyst_id=x["analyst_id"],
                                 analyst_role=x["role"], action_type=x["type"], disposition=x["disposition"], notes=x["notes"],
                                 action_timestamp=fts(x["ts"])) for x in actions]
    gt = [dict(r) for r in d.gt]
    for g in new_gt:
        g = dict(g)
        g["truth_id"] = f"GT-{len(gt) + 1:06d}"
        gt.append(g)
    T["ground_truth"] = gt

    os.makedirs(a.out, exist_ok=True)
    files = {}
    for name in COLS:
        files[name + ".csv"] = dict(rows=len(T[name]), sha256=sha(write(a.out, name, T[name])))
    manifest = dict(builder_version=VERSION, seed=seed, baseline_dir=a.src, baseline_generator_version=base["generator_version"],
                    baseline_files={k: v["sha256"] for k, v in base["files"].items()},
                    alerts_by_rule_and_label=per_rule, pattern_detection=recall, snapshot=fts(SNAPSHOT), files=files)
    with open(os.path.join(a.out, "build_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"seed={seed} baseline={a.src}/ -> {a.out}/")
    for k, v in files.items():
        print(f"  {k:28s} {v['rows']:>8,} rows")
    print("\nAlerts by rule (labelled against ground truth):")
    for k, v in per_rule.items():
        print(f"  {k}  {sum(v.values()):>4} alerts  {v}")
    print("Planted pattern instances detected:")
    for k, v in recall.items():
        print(f"  {k:24s} {v['detected']:>4} / {v['placed']}")
    print("Case status:", {s: sum(1 for c in cases if c["status"] == s) for s in ("open", "in_review", "closed")})


if __name__ == "__main__":
    main()
