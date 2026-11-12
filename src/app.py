#!/usr/bin/env python3
"""Step 6: Streamlit website for fraud alert triage.

Run from the project root:   streamlit run src/app.py

Pages: Overview, Alert queue, Case view (evidence + analyst actions), Rules & evaluation, Data quality.
data_final/ is read-only. Actions logged here go to app_state/new_actions.csv (see app_data.py).
"""
import pandas as pd
import streamlit as st

import app_data as ad

st.set_page_config(page_title="Fraud alert triage", layout="wide")

PAGES = ["Overview", "Alert queue", "Case view", "Rules & evaluation", "Data quality"]
STATUSES = ["open", "in_review", "closed"]


# ---------------------------------------------------------------- data
@st.cache_resource(show_spinner="Loading data_final/ ...")
def get_tables():
    return ad.load_tables()


try:
    T = get_tables()
except FileNotFoundError as err:
    st.error(f"{err}\n\nBuild the data first (from the project root): `python src/run_all.py`")
    st.stop()

REPORT = ad.load_json("validation_report.json")
MANIFEST = ad.load_json("build_manifest.json")
NEW = ad.load_new_actions()
ACTS = ad.all_actions(T, NEW)
CASES = ad.case_table(T, ACTS, NEW)
ALERTS = ad.alert_table(T, CASES)
RULE_NAME = dict(zip(T["risk_rules"]["rule_id"], T["risk_rules"]["rule_name"]))
CASE_ROW = CASES.set_index("case_id")


def inr(x):
    return f"INR {x:,.2f}"


def dt(x):
    return "" if pd.isna(x) else pd.Timestamp(x).strftime("%Y-%m-%d %H:%M")


def queue_order(df):
    return df.sort_values(["priority_score", "opened_at"], ascending=[False, True])


# ---------------------------------------------------------------- navigation
if "page" not in st.session_state:
    st.session_state["page"] = "Overview"


def open_case(case_id):
    st.session_state["case_id"] = case_id
    st.session_state["page"] = "Case view"


with st.sidebar:
    st.title("Fraud alert triage")
    st.caption("Synthetic data, INR. data_final/ is read-only.")
    st.radio("Page", PAGES, key="page")
    st.divider()
    st.caption(f"Actions logged in this app: {len(NEW)}")
    if len(NEW):
        st.download_button("Download app actions (CSV)", ad.NEW_ACTIONS_FILE.read_bytes(),
                           file_name="new_actions.csv", mime="text/csv")
        sure = st.checkbox("Yes, delete the actions logged in this app")
        if st.button("Reset app actions", disabled=not sure):
            ad.reset_new_actions()
            st.rerun()

flash = st.session_state.pop("flash", None)
if flash:
    (st.success if flash[0] == "ok" else st.error)(flash[1])


# ---------------------------------------------------------------- Overview
def page_overview():
    st.header("Overview")
    by = CASES["status"].value_counts()
    cols = st.columns(6)
    cols[0].metric("Cases", len(CASES))
    cols[1].metric("Open", int(by.get("open", 0)))
    cols[2].metric("In review", int(by.get("in_review", 0)))
    cols[3].metric("Closed", int(by.get("closed", 0)))
    cols[4].metric("Alerts", len(ALERTS))
    cols[5].metric("Escalated cases", int(CASES["escalated"].sum()))

    left, right = st.columns(2)
    with left:
        st.subheader("Alerts by rule")
        st.bar_chart(ALERTS.groupby("rule_name").size().rename("alerts"))
    with right:
        st.subheader("Alerts per month")
        monthly = ALERTS.set_index("created_at").resample("MS").size().rename("alerts")
        monthly.index = monthly.index.strftime("%Y-%m")
        st.bar_chart(monthly)

    left, right = st.columns(2)
    with left:
        st.subheader("How closed cases ended")
        closed = CASES[CASES["status"] == "closed"]
        st.bar_chart(closed["final_disposition"].value_counts().rename("cases"))
    with right:
        st.subheader("Work in progress by analyst")
        wip = CASES[CASES["status"] != "closed"]
        if wip.empty:
            st.info("No open or in-review cases.")
        else:
            wip = wip.assign(assigned_to=wip["assigned_to"].replace("", "unassigned"))
            st.dataframe(pd.crosstab(wip["assigned_to"], wip["status"]))

    st.subheader("Highest-priority work waiting")
    wip = CASES[CASES["status"] != "closed"]
    top = queue_order(wip).head(8)[["case_id", "priority_score", "status", "alert_count", "rules", "full_name", "age_days"]]
    st.dataframe(top, hide_index=True)


# ---------------------------------------------------------------- Alert queue
def page_queue():
    st.header("Alert queue")
    st.caption("Cases are the unit of work: alerts of one customer within 7 days of each other share a case.")

    c1, c2, c3 = st.columns([2, 2, 1])
    status_sel = c1.multiselect("Status", STATUSES, default=["open", "in_review"])
    rule_sel = c2.multiselect("Rule", list(RULE_NAME), format_func=lambda r: f"{r} {RULE_NAME[r]}")
    min_prio = c3.slider("Min priority", 0, 100, 0)
    c4, c5, c6 = st.columns([3, 2, 1])
    q = c4.text_input("Search case, customer, name, alert or account").strip().lower()
    sort = c5.selectbox("Sort", ["Priority, high to low", "Oldest first", "Newest first", "Most alerts"])
    esc_only = c6.checkbox("Escalated only")

    f = CASES
    if status_sel:
        f = f[f["status"].isin(status_sel)]
    if rule_sel:
        f = f[f["rule_ids"].apply(lambda s: any(r in s.split(",") for r in rule_sel))]
    f = f[f["priority_score"] >= min_prio]
    if esc_only:
        f = f[f["escalated"]]
    if q:
        hit = (f["case_id"].str.lower().str.contains(q, regex=False)
               | f["customer_id"].str.lower().str.contains(q, regex=False)
               | f["full_name"].str.lower().str.contains(q, regex=False))
        ah = ALERTS[ALERTS["alert_id"].str.lower().str.contains(q, regex=False)
                    | ALERTS["account_id"].str.lower().str.contains(q, regex=False)]["case_id"]
        f = f[hit | f["case_id"].isin(ah)]
    if sort == "Oldest first":
        f = f.sort_values("opened_at")
    elif sort == "Newest first":
        f = f.sort_values("opened_at", ascending=False)
    elif sort == "Most alerts":
        f = f.sort_values(["alert_count", "priority_score"], ascending=False)
    else:
        f = queue_order(f)

    st.write(f"**{len(f)}** cases match.")
    if f.empty:
        st.info("No cases match these filters.")
        return
    view = f[["case_id", "priority_score", "status", "escalated", "alert_count", "rules",
              "customer_id", "full_name", "assigned_to", "opened_at", "age_days"]].reset_index(drop=True)
    shown = view.head(500)
    if len(view) > len(shown):
        st.caption(f"Showing the first {len(shown)} cases. Narrow the filters to see the rest.")
    cfg = {"priority_score": st.column_config.ProgressColumn("Priority", min_value=0, max_value=100, format="%d"),
           "age_days": st.column_config.NumberColumn("Age (days)", help="Days since opened, as of 2026-11-05")}
    chosen = None
    try:
        event = st.dataframe(shown, hide_index=True, column_config=cfg, on_select="rerun",
                             selection_mode="single-row", key="queue_table")
        rows = event["selection"]["rows"]
        if rows:
            chosen = shown.iloc[rows[0]]["case_id"]
    except TypeError:  # very old Streamlit without row selection
        st.dataframe(shown, hide_index=True, column_config=cfg)
    if chosen is None:
        chosen = st.selectbox("Or pick a case", shown["case_id"].tolist())
    st.button(f"Open {chosen}", on_click=open_case, args=(chosen,), type="primary")


# ---------------------------------------------------------------- Case view
def render_alert(a):
    ctx = ad.alert_context(T, a)
    left, right = st.columns([3, 2])
    with left:
        st.markdown(f"**Why it fired.** {a['evidence']}")
        bd = ad.parse_breakdown(a["score_breakdown"])
        st.caption(f"Score breakdown, adds up to {a['risk_score']}")
        st.dataframe(bd, hide_index=True)
        if len(bd) and int(bd["points"].sum()) != int(a["risk_score"]):
            st.warning("The breakdown does not add up to the risk score.")
    with right:
        txn, acc = ctx["txn"], ctx["account"]
        if txn is None:
            st.warning("No triggering transaction is recorded for this alert.")
        else:
            st.markdown(f"**Triggering transaction** `{txn['transaction_id']}`")
            st.markdown(f"- {txn['direction']} of {inr(txn['amount'])}, {txn['txn_type']} via {txn['channel']}\n"
                        f"- At {dt(txn['txn_timestamp'])} UTC, balance after {inr(txn['balance_after'])}")
            if txn["merchant_name"]:
                st.markdown(f"- Merchant: {txn['merchant_name']} ({txn['category']}, {txn['risk_level']} risk)")
            if txn["device_type"]:
                st.markdown(f"- Device: {txn['device_id']} ({txn['device_type']})")
        if acc is not None:
            st.markdown(f"**Account** `{acc['account_id']}`: {acc['account_type']}, {acc['status']}, "
                        f"balance {inr(acc['current_balance'])}, overdraft limit {inr(acc['overdraft_limit'])}")
    if ctx["txn"] is not None:
        tab1, tab2 = st.tabs(["Nearby transactions (24h either side)", "Transfers (72h before)"])
        with tab1:
            cols = ["trigger", "txn_timestamp", "direction", "amount", "txn_type", "channel",
                    "merchant_name", "category", "device_type", "balance_after", "status"]
            st.dataframe(ctx["nearby"][cols], hide_index=True)
        with tab2:
            if ctx["transfers"].empty:
                st.caption("No transfers on this account in the 72 hours before the alert.")
            else:
                st.dataframe(ctx["transfers"][["transfer_id", "initiated_at", "source_account_id",
                                               "destination_account_id", "transfer_amount", "status"]], hide_index=True)


def submit_action(case_id):
    ss = st.session_state
    atype = ss[f"atype_{case_id}"]
    ok, msg = ad.log_action(
        T, case_id, analyst_id=ss["analyst_id"].split(" ")[0], action_type=atype,
        alert_id=ss.get(f"aalert_{case_id}", "") if atype == "review" else "",
        disposition=ss.get(f"adisp_{case_id}", "") if atype == "disposition" else "",
        notes=ss.get(f"anotes_{case_id}", ""))
    ss["flash"] = ("ok" if ok else "err", msg)
    if ok:
        ss[f"anotes_{case_id}"] = ""


def render_action_panel(case, case_alerts):
    if case["status"] == "closed":
        st.info(f"This case is closed ({case['final_disposition']}). No further actions can be added.")
        return
    who = ad.analysts(T)
    labels = [f"{r.analyst_id} ({r.analyst_role})" for r in who.itertuples()]
    cid = case["case_id"]
    st.selectbox("Acting as", labels, key="analyst_id")
    atype = st.selectbox("Action", ad.ACTION_TYPES, index=1, key=f"atype_{cid}")
    if atype == "review":
        st.selectbox("Alert reviewed", case_alerts["alert_id"].tolist(), key=f"aalert_{cid}")
    elif atype == "disposition":
        st.selectbox("Disposition", ad.DISPOSITIONS, key=f"adisp_{cid}")
        st.caption(f"Recorded on the latest alert of the case, {case_alerts['alert_id'].iloc[-1]}.")
    st.text_area("Notes", max_chars=ad.NOTE_MAX, key=f"anotes_{cid}",
                 help="Required for a disposition, optional otherwise.")
    st.button("Log action", on_click=submit_action, args=(cid,), type="primary")
    st.caption("Rules: review every alert before closing; a case can only be escalated once; "
               "an escalated case is closed by a risk_reviewer or administrator; a closed case takes no more actions. "
               "Actions are saved to app_state/new_actions.csv and never change data_final/.")


def page_case():
    st.header("Case view")
    ids = CASES["case_id"].tolist()
    current = st.session_state.get("case_id")
    if current not in ids:
        current = queue_order(CASES[CASES["status"] != "closed"]).iloc[0]["case_id"]

    def label(cid):
        r = CASE_ROW.loc[cid]
        return f"{cid} | {r['full_name']} | {r['status']} | priority {r['priority_score']}"

    cid = st.selectbox("Case", ids, index=ids.index(current), format_func=label)
    st.session_state["case_id"] = cid  # plain key, so the chosen case survives page switches
    case = CASE_ROW.loc[cid].copy()
    case["case_id"] = cid
    cols = st.columns(5)
    cols[0].metric("Status", case["status"])
    cols[1].metric("Priority", int(case["priority_score"]))
    cols[2].metric("Alerts", int(case["alert_count"]))
    cols[3].metric("Assigned to", case["assigned_to"] or "unassigned")
    cols[4].metric("Escalated", "yes" if case["escalated"] else "no")
    if case["status"] == "closed":
        st.write(f"Closed {dt(case['closed_at'])} as **{case['final_disposition']}**.")
    st.write(f"Customer **{case['full_name']}** (`{case['customer_id']}`), KYC {case['kyc_status']}, "
             f"risk tier {case['kyc_risk_tier']}. Opened {dt(case['opened_at'])} UTC.")

    for f in ad.case_findings(REPORT, T, cid, ACTS):
        st.warning(f"Validator finding ({f['issue_type']}) on {f['entity_id']}: {f['detail']}")

    case_alerts = (ALERTS[ALERTS["case_id"] == cid].sort_values("created_at"))
    tab_alerts, tab_time, tab_cust, tab_act = st.tabs(["Alerts and evidence", "Timeline", "Customer history", "Log action"])

    with tab_alerts:
        for i, (_, a) in enumerate(case_alerts.iterrows()):
            title = f"{a['alert_id']} | {a['rule_name']} | score {a['risk_score']} | {dt(a['created_at'])}"
            with st.expander(title, expanded=(i == 0)):
                render_alert(a)

    with tab_time:
        tl = ACTS[ACTS["case_id"] == cid][["action_timestamp", "analyst_id", "analyst_role", "action_type",
                                           "alert_id", "disposition", "notes", "action_id"]].copy()
        tl["logged in app"] = tl["action_id"].isin(NEW["action_id"])
        st.dataframe(tl.drop(columns="action_id"), hide_index=True)

    with tab_cust:
        cust = T["customers"][T["customers"]["customer_id"] == case["customer_id"]].iloc[0]
        st.markdown(f"**{cust['full_name']}**, {cust['country']}, born {cust['date_of_birth']}, onboarded {dt(cust['onboarded_at'])}. "
                    f"Customer status {cust['status']}, KYC {cust['kyc_status']}, risk tier {cust['kyc_risk_tier']}.")
        st.subheader("Accounts")
        accts = T["accounts"][T["accounts"]["customer_id"] == cust["customer_id"]]
        st.dataframe(accts[["account_id", "account_type", "status", "opened_at", "closed_at",
                            "overdraft_limit", "current_balance"]], hide_index=True)
        st.subheader("Other cases of this customer")
        other = CASES[(CASES["customer_id"] == cust["customer_id"]) & (CASES["case_id"] != cid)]
        if other.empty:
            st.caption("No other cases.")
        else:
            st.dataframe(other[["case_id", "status", "final_disposition", "priority_score", "rules", "opened_at"]],
                         hide_index=True)

    with tab_act:
        render_action_panel(case, case_alerts)


# ---------------------------------------------------------------- Rules & evaluation
def page_rules():
    st.header("Rules and evaluation")
    rules = T["risk_rules"][["rule_id", "rule_name", "rule_type", "description", "weight", "parameters", "is_active"]]
    st.dataframe(rules, hide_index=True)
    st.caption("Fixed thresholds, not learned. The rules read only transactions, transfers and account history.")

    st.subheader("Evaluation against ground truth")
    st.caption("For measuring the rules only. ground_truth.csv is never used in the queue or case view.")
    lab = ad.alert_labels(T, ALERTS)
    lab["rule"] = lab["rule_id"] + " " + lab["rule_id"].map(RULE_NAME)
    st.dataframe(pd.crosstab(lab["rule"], lab["label"], margins=True, margins_name="total"))
    st.subheader("Average risk score by label")
    avg = lab.groupby("label")["risk_score"].agg(["count", "mean", "min", "max"]).round(1)
    st.dataframe(avg)
    st.caption("Benign look-alikes score lower on average but the ranges overlap, so the score alone cannot separate them.")


# ---------------------------------------------------------------- Data quality
def page_quality():
    st.header("Data quality")
    if not REPORT:
        st.warning("validation_report.json not found. Run `python src/run_all.py`.")
        return
    findings = pd.DataFrame(REPORT.get("findings", []))
    missed, unexpected = REPORT.get("missed", []), REPORT.get("unexpected", [])
    cols = st.columns(4)
    cols[0].metric("Validator result", "PASS" if REPORT.get("passed") else "FAIL")
    cols[1].metric("Findings", len(findings))
    cols[2].metric("Missed anomalies", len(missed))
    cols[3].metric("Unexpected findings", len(unexpected))
    st.write("The five injected anomalies (INJ-01 to INJ-05) are reported as six findings, because one anomaly "
             "touches two records. PASS means the validator caught every labelled anomaly and nothing else.")
    if len(findings):
        st.dataframe(findings, hide_index=True)
    if MANIFEST:
        st.subheader("Build")
        st.write(f"Seed {MANIFEST.get('seed')}, builder {MANIFEST.get('builder_version')}, "
                 f"baseline generator {MANIFEST.get('baseline_generator_version')}.")
    st.subheader("Rows per table in data_final/")
    st.dataframe(pd.DataFrame({"table": list(T), "rows": [len(v) for v in T.values()]}), hide_index=True)


{"Overview": page_overview, "Alert queue": page_queue, "Case view": page_case,
 "Rules & evaluation": page_rules, "Data quality": page_quality}[st.session_state["page"]]()
