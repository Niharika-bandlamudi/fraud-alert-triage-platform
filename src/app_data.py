#!/usr/bin/env python3
"""Step 6 data layer for the Streamlit app (src/app.py).

Everything here is plain pandas, so it can be tested without Streamlit.

Rules of this layer:
  * data_final/ is only READ. generator.py, build_triage.py and validator.py are not touched,
    so `python src/run_all.py` still gives RESULT: PASS after the app has been used.
  * Analyst actions made in the app are appended to app_state/new_actions.csv (same columns as
    analyst_actions.csv). Case and alert status shown in the app = data_final + those new actions.
  * ground_truth.csv is used only for the evaluation page, never for the queue or case view.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data_final"
STATE_DIR = ROOT / "app_state"
NEW_ACTIONS_FILE = STATE_DIR / "new_actions.csv"

FMT = "%Y-%m-%dT%H:%M:%SZ"
AS_OF = pd.Timestamp("2026-11-05")  # analyst work in the synthetic data stops here (assumptions.md, item 15)
NOTE_MAX = 500

ACTION_COLS = ["action_id", "case_id", "alert_id", "analyst_id", "analyst_role",
               "action_type", "disposition", "notes", "action_timestamp"]
ACTION_TYPES = ["assign", "review", "escalate", "request_info", "disposition"]
DISPOSITIONS = ["confirmed_suspicious", "false_positive", "inconclusive"]
SENIOR_ROLES = ("risk_reviewer", "administrator")
CASE_TO_ALERT_STATUS = {"open": "open", "in_review": "under_review", "closed": "closed"}

_TABLES = ["customers", "accounts", "merchants", "devices", "transactions", "transfer_links",
           "risk_rules", "alerts", "cases", "case_alerts", "analyst_actions", "ground_truth"]
_TIME_COLS = {
    "customers": ["onboarded_at", "kyc_verified_at"],
    "accounts": ["opened_at", "closed_at"],
    "transactions": ["txn_timestamp"],
    "transfer_links": ["initiated_at"],
    "alerts": ["created_at"],
    "cases": ["opened_at", "closed_at"],
    "case_alerts": ["linked_at"],
    "analyst_actions": ["action_timestamp"],
}
_NUMERIC = {
    "accounts": ["opening_balance", "current_balance", "overdraft_limit"],
    "transactions": ["amount", "balance_after"],
    "transfer_links": ["transfer_amount"],
    "risk_rules": ["weight"],
    "alerts": ["risk_score"],
    "cases": ["priority_score"],
}


# ---------------------------------------------------------------- loading
def load_tables(data_dir: Path | str = DATA_DIR) -> dict[str, pd.DataFrame]:
    """Read the CSVs of data_final/. IDs stay text, timestamps become datetimes (UTC, no tz)."""
    data_dir = Path(data_dir)
    tables: dict[str, pd.DataFrame] = {}
    for name in _TABLES:
        path = data_dir / f"{name}.csv"
        if not path.exists():
            raise FileNotFoundError(f"{path} not found. Run: python src/run_all.py")
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        for col in _TIME_COLS.get(name, []):
            df[col] = pd.to_datetime(df[col], format=FMT, errors="coerce")
        for col in _NUMERIC.get(name, []):
            df[col] = pd.to_numeric(df[col])
        tables[name] = df
    return tables


def load_json(name: str, data_dir: Path | str = DATA_DIR) -> dict | None:
    path = Path(data_dir) / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_new_actions() -> pd.DataFrame:
    """Actions logged through the app (empty frame if none yet)."""
    if NEW_ACTIONS_FILE.exists():
        df = pd.read_csv(NEW_ACTIONS_FILE, dtype=str, keep_default_na=False)
    else:
        df = pd.DataFrame({c: pd.Series(dtype=str) for c in ACTION_COLS})
    df["action_timestamp"] = pd.to_datetime(df["action_timestamp"], format=FMT, errors="coerce")
    return df[ACTION_COLS]


def reset_new_actions() -> None:
    if NEW_ACTIONS_FILE.exists():
        NEW_ACTIONS_FILE.unlink()


def all_actions(t: dict, new: pd.DataFrame) -> pd.DataFrame:
    base = t["analyst_actions"]
    acts = base.copy() if new.empty else pd.concat([base, new], ignore_index=True)
    return acts.sort_values(["action_timestamp", "action_id"], kind="stable").reset_index(drop=True)


def analysts(t: dict) -> pd.DataFrame:
    """The 12 synthetic analysts and their fixed roles."""
    return (t["analyst_actions"][["analyst_id", "analyst_role"]]
            .drop_duplicates("analyst_id").sort_values("analyst_id").reset_index(drop=True))


# ---------------------------------------------------------------- cases and alerts
def case_table(t: dict, acts: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """One row per case with alert summary, customer facts and the status after new app actions."""
    rules = t["risk_rules"][["rule_id", "rule_name"]]
    ca = (t["case_alerts"][["case_id", "alert_id"]]
          .merge(t["alerts"][["alert_id", "rule_id", "risk_score"]], on="alert_id")
          .merge(rules, on="rule_id"))
    agg = ca.groupby("case_id").agg(
        alert_count=("alert_id", "size"),
        top_alert_score=("risk_score", "max"),
        rule_ids=("rule_id", lambda s: ",".join(sorted(set(s)))),
        rules=("rule_name", lambda s: ", ".join(sorted(set(s)))),
    ).reset_index()
    cust = t["customers"][["customer_id", "full_name", "kyc_status", "kyc_risk_tier"]]
    cases = t["cases"].merge(agg, on="case_id", how="left").merge(cust, on="customer_id", how="left")

    # same status logic as build_triage.py: only assign -> open, any other action -> in_review, disposition -> closed
    status = cases.set_index("case_id")["status"].to_dict()
    disp = cases.set_index("case_id")["final_disposition"].to_dict()
    closed_at = cases.set_index("case_id")["closed_at"].to_dict()
    if not new.empty:
        for cid, g in new.sort_values(["action_timestamp", "action_id"]).groupby("case_id"):
            if cid not in status:
                continue
            d = g[g["action_type"] == "disposition"]
            if len(d):
                last = d.iloc[-1]
                status[cid], disp[cid], closed_at[cid] = "closed", last["disposition"], last["action_timestamp"]
            elif status[cid] == "open" and (g["action_type"] != "assign").any():
                status[cid] = "in_review"
    cases["status"] = cases["case_id"].map(status)
    cases["final_disposition"] = cases["case_id"].map(disp)
    cases["closed_at"] = pd.to_datetime(cases["case_id"].map(closed_at))

    owner = acts[acts["action_type"] == "assign"].drop_duplicates("case_id", keep="last").set_index("case_id")["analyst_id"]
    escalated = set(acts.loc[acts["action_type"] == "escalate", "case_id"])
    last_act = acts.groupby("case_id")["action_timestamp"].max()
    cases["assigned_to"] = cases["case_id"].map(owner).fillna("")
    cases["escalated"] = cases["case_id"].isin(escalated)
    cases["last_activity"] = cases["case_id"].map(last_act)
    age = (AS_OF - cases["opened_at"]).dt.total_seconds() / 86400
    cases["age_days"] = age.where(cases["status"] != "closed").round(1)
    return cases


def alert_table(t: dict, cases: pd.DataFrame) -> pd.DataFrame:
    """Alerts with rule name, case id and status mirrored from the case."""
    a = (t["alerts"].drop(columns="status")
         .merge(t["case_alerts"][["alert_id", "case_id"]], on="alert_id", how="left")
         .merge(t["risk_rules"][["rule_id", "rule_name"]], on="rule_id", how="left"))
    a["status"] = a["case_id"].map(cases.set_index("case_id")["status"]).map(CASE_TO_ALERT_STATUS)
    return a


def parse_breakdown(text: str) -> pd.DataFrame:
    """score_breakdown JSON -> table of factor and points."""
    try:
        d = json.loads(text)
        return pd.DataFrame({"factor": [k.replace("_", " ") for k in d], "points": [int(v) for v in d.values()]})
    except (TypeError, ValueError, AttributeError):
        return pd.DataFrame({"factor": [], "points": []})


def alert_context(t: dict, alert: pd.Series) -> dict:
    """Triggering transaction, account facts, nearby transactions and recent transfers for one alert."""
    out = {"txn": None, "account": None, "nearby": pd.DataFrame(), "transfers": pd.DataFrame()}
    acc = t["accounts"][t["accounts"]["account_id"] == alert["account_id"]]
    if len(acc):
        out["account"] = acc.iloc[0]
    tid = alert["transaction_id"]
    if not tid:
        return out
    tx = t["transactions"]
    row = tx[tx["transaction_id"] == tid]
    if row.empty:
        return out
    ts = row.iloc[0]["txn_timestamp"]
    acct_tx = tx[tx["account_id"] == row.iloc[0]["account_id"]]
    before = acct_tx[acct_tx["txn_timestamp"] <= ts].tail(3)
    window = acct_tx[(acct_tx["txn_timestamp"] >= ts - pd.Timedelta(hours=24))
                     & (acct_tx["txn_timestamp"] <= ts + pd.Timedelta(hours=24))]
    near = (pd.concat([before, window]).drop_duplicates("transaction_id")
            .sort_values("txn_timestamp").tail(80))
    near = (near.merge(t["merchants"][["merchant_id", "merchant_name", "category", "risk_level"]], on="merchant_id", how="left")
            .merge(t["devices"][["device_id", "device_type"]], on="device_id", how="left"))
    near = near.fillna({c: "" for c in ["merchant_name", "category", "risk_level", "device_type"]})
    near["trigger"] = near["transaction_id"].eq(tid).map({True: "<< trigger", False: ""})
    out["txn"] = near[near["transaction_id"] == tid].iloc[0]
    out["nearby"] = near
    tl = t["transfer_links"]
    acc_id = row.iloc[0]["account_id"]
    sel = ((tl["source_account_id"] == acc_id) | (tl["destination_account_id"] == acc_id)) \
        & (tl["initiated_at"] >= ts - pd.Timedelta(hours=72)) & (tl["initiated_at"] <= ts)
    out["transfers"] = tl[sel].sort_values("initiated_at")
    return out


def case_findings(report: dict | None, t: dict, case_id: str, acts: pd.DataFrame) -> list[dict]:
    """Validator findings that touch this case (its alerts, actions, trigger transactions or accounts)."""
    if not report:
        return []
    alert_ids = set(t["case_alerts"].loc[t["case_alerts"]["case_id"] == case_id, "alert_id"])
    al = t["alerts"][t["alerts"]["alert_id"].isin(alert_ids)]
    ids = set(alert_ids) | set(al["transaction_id"]) | set(al["account_id"])
    ids |= set(acts.loc[acts["case_id"] == case_id, "action_id"])
    tl = t["transfer_links"]
    ids |= set(tl.loc[tl["credit_txn_id"].isin(set(al["transaction_id"])), "transfer_id"])
    return [f for f in report.get("findings", []) if f.get("entity_id") in ids]


# ---------------------------------------------------------------- evaluation (uses ground_truth)
def alert_labels(t: dict, alerts: pd.DataFrame) -> pd.DataFrame:
    """Label each alert through the label of its triggering transaction. Evaluation only.

    Same logic as build_triage.py: the label counts as a match when the rule that generated the
    label is the rule that fired; otherwise the rule fired on a transaction of another pattern.
    """
    gt = t["ground_truth"]
    tx = (gt[gt["entity_type"] == "transaction"].drop_duplicates("entity_id")
          [["entity_id", "label_kind", "generating_rule"]])
    m = alerts.merge(tx, left_on="transaction_id", right_on="entity_id", how="left")
    m = m.fillna({"label_kind": "", "generating_rule": ""})
    label = pd.Series("unlabelled", index=m.index)
    label[m["transaction_id"] == ""] = "no trigger (injected)"
    label[m["label_kind"] == "injected_anomaly"] = "injected anomaly"
    match = m["generating_rule"].str[:7] == m["rule_id"]  # label text starts with the rule id, e.g. "RUL-002 fires on ..."
    label[(m["label_kind"] == "false_positive") & match] = "benign look-alike"
    label[(m["label_kind"] == "planted_pattern") & match] = "planted pattern"
    other = m["label_kind"].isin(["false_positive", "planted_pattern"]) & ~match
    label[other] = "overlaps other pattern"
    m["label"] = label
    return m


# ---------------------------------------------------------------- analyst actions
def next_action_id(acts: pd.DataFrame) -> str:
    nums = acts["action_id"].str.extract(r"ACT-2026-(\d+)")[0].dropna().astype(int)
    return f"ACT-2026-{(nums.max() if len(nums) else 0) + 1:06d}"


def validate_action(case: pd.Series, case_alerts: pd.DataFrame, acts: pd.DataFrame, *, action_type: str,
                    alert_id: str, disposition: str, analyst_role: str, notes: str, ts: pd.Timestamp) -> list[str]:
    """Checks from data_dictionary.md (AnalystAction) plus three workflow rules. Returns error messages."""
    if case["status"] == "closed":
        return ["This case is closed, so no further actions can be added."]
    errs: list[str] = []
    cid = case["case_id"]
    mine = acts[acts["case_id"] == cid]
    if action_type not in ACTION_TYPES:
        errs.append("Unknown action type.")
    if action_type == "disposition":
        if disposition not in DISPOSITIONS:
            errs.append("Choose a disposition.")
        if not notes.strip():
            errs.append("A disposition needs a note explaining the decision.")
    elif disposition:
        errs.append("A disposition is only allowed on a disposition action.")
    if len(notes) > NOTE_MAX:
        errs.append(f"Notes are limited to {NOTE_MAX} characters.")
    if action_type in ("review", "disposition"):
        row = case_alerts[case_alerts["alert_id"] == alert_id]
        if row.empty:
            errs.append("The alert must belong to this case.")
        elif ts < row.iloc[0]["created_at"]:
            errs.append("An action cannot be dated before its alert was created.")
    elif alert_id:
        errs.append("Assign, escalate and request_info are case-level and carry no alert.")
    if ts < case["opened_at"]:
        errs.append("An action cannot be dated before the case was opened.")
    if action_type == "escalate" and (mine["action_type"] == "escalate").any():
        errs.append("This case has already been escalated.")
    if action_type == "disposition":
        reviewed = set(mine.loc[mine["action_type"] == "review", "alert_id"])
        missing = [a for a in case_alerts["alert_id"] if a not in reviewed]
        if missing:
            errs.append("Review every alert before closing the case. Not reviewed yet: " + ", ".join(missing))
        if (mine["action_type"] == "escalate").any() and analyst_role not in SENIOR_ROLES:
            errs.append("This case was escalated, so only a risk_reviewer or administrator can close it.")
    return errs


def log_action(t: dict, case_id: str, *, analyst_id: str, action_type: str, alert_id: str = "",
               disposition: str = "", notes: str = "", now: datetime | None = None) -> tuple[bool, str]:
    """Validate and append one analyst action. Returns (ok, message)."""
    new = load_new_actions()
    acts = all_actions(t, new)
    cases = case_table(t, acts, new)
    hit = cases[cases["case_id"] == case_id]
    if hit.empty:
        return False, f"Unknown case {case_id}."
    case = hit.iloc[0]
    ca = (t["case_alerts"][t["case_alerts"]["case_id"] == case_id][["alert_id"]]
          .merge(t["alerts"][["alert_id", "created_at"]], on="alert_id").sort_values("created_at"))
    who = analysts(t)
    who = who[who["analyst_id"] == analyst_id]
    if who.empty:
        return False, f"Unknown analyst {analyst_id}."
    role = who.iloc[0]["analyst_role"]
    if action_type == "disposition":
        alert_id = ca.iloc[-1]["alert_id"]  # same convention as build_triage.py: recorded on the latest alert
    elif action_type != "review":
        alert_id = ""
    now = now or datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    ts = pd.Timestamp(now)
    disposition = disposition if action_type == "disposition" else ""
    errs = validate_action(case, ca, acts, action_type=action_type, alert_id=alert_id, disposition=disposition,
                           analyst_role=role, notes=notes, ts=ts)
    if errs:
        return False, " ".join(errs)
    if not notes.strip():
        notes = {"assign": f"Case assigned to {analyst_id} for triage",
                 "review": "Alert reviewed in triage app",
                 "escalate": "Escalated to risk review in triage app",
                 "request_info": "Requested more information in triage app"}[action_type]
    row = dict(action_id=next_action_id(acts), case_id=case_id, alert_id=alert_id, analyst_id=analyst_id,
               analyst_role=role, action_type=action_type, disposition=disposition, notes=notes.strip(),
               action_timestamp=ts.strftime(FMT))
    STATE_DIR.mkdir(exist_ok=True)
    write_header = not NEW_ACTIONS_FILE.exists()
    with open(NEW_ACTIONS_FILE, "a", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=ACTION_COLS, lineterminator="\n")
        if write_header:
            wr.writeheader()
        wr.writerow(row)
    return True, f"Logged {row['action_id']}: {action_type.replace('_', ' ')} on {case_id}."
