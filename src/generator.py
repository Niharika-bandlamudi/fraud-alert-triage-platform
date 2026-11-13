#!/usr/bin/env python3
"""Synthetic baseline data generator for the fraud alert triage project.

Creates master data, status history, transactions (balances reconcile), transfers
and planted patterns, plus ground_truth.csv for the planted patterns.
Alerts, cases, analyst actions and injected anomalies are produced by later steps.

Run:  python src/generator.py --seed 20261022 --out data
      python src/generator.py --starter --out data_starter
"""
import argparse, csv, hashlib, json, os
from datetime import datetime, timedelta
import numpy as np

VERSION = "0.2.0"
START = datetime(2026, 1, 1)
END = datetime(2026, 10, 31, 23, 59, 59)
DAY = timedelta(days=1)
HOUR_P = np.array([1, 1, 1, 1, 1, 2, 3, 5, 7, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 7, 5, 3, 2], float)
HOUR_P /= HOUR_P.sum()
CATS = ["grocery", "fuel", "travel", "electronics", "dining", "utilities", "gambling", "crypto", "other"]
CAT_P = [.22, .08, .10, .08, .18, .12, .03, .02, .17]
RISKY = ("electronics", "gambling", "crypto")
# planted pattern instances per 1,000 alerts (scaled by --alerts). Each instance raises one alert, so the
# default (--alerts 1000) gives about 1,000 alerts: 590 true patterns and 392 benign look-alikes (false
# positives), plus a few overlaps and the injected anomaly added later by build_triage.py.
BASE_PATTERNS = dict(velocity=150, new_device=230, circular=100, dormant=110,
                     bill_burst=150, upgrade=149, large_known=93)
FIRST = ["Aarav", "Vivaan", "Aditya", "Ananya", "Diya", "Isha", "Kavya", "Rohan", "Saanvi", "Arjun",
         "Meera", "Nikhil", "Priya", "Rahul", "Sneha", "Tanvi", "Varun", "Neha", "Karthik", "Lakshmi"]
LAST = ["Sharma", "Reddy", "Patel", "Iyer", "Khan", "Nair", "Gupta", "Das", "Rao", "Mehta",
        "Singh", "Verma", "Joshi", "Kulkarni", "Menon"]


def fts(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def money(p):  # integer paise -> "123.45"
    s = "-" if p < 0 else ""
    p = abs(int(p))
    return f"{s}{p // 100}.{p % 100:02d}"


def generate(n_cust, n_acc, n_txn, n_alerts, seed):
    rng = np.random.default_rng(seed)
    if not (n_cust <= n_acc <= 2 * n_cust):
        raise ValueError("accounts must be between customers and 2 x customers")

    def rand_dt(lo, hi):
        return lo + timedelta(seconds=int(rng.integers(0, max(1, int((hi - lo).total_seconds())))))

    # ---------------- merchants
    n_mer = max(60, n_cust // 10)
    mer_cat = [str(c) for c in rng.choice(CATS, n_mer, p=CAT_P)]
    for i in range(len(CATS)):
        mer_cat[i] = CATS[i]  # guarantee every category exists
    merchants = []
    for i, c in enumerate(mer_cat):
        if c in ("gambling", "crypto"):
            risk = "high"
        else:
            risk = str(rng.choice(["low", "medium"], p=[.7, .3] if c in ("electronics", "travel") else [.9, .1]))
        country = "IN" if rng.random() < .9 else str(rng.choice(["US", "SG", "AE", "GB"]))
        merchants.append(dict(merchant_id=f"MER-{i + 1:06d}", merchant_name=f"{c.title()} Point {i + 1}",
                              category=c, country=country, risk_level=risk))
    risky_idx = [i for i, c in enumerate(mer_cat) if c in RISKY]
    util_idx = [i for i, c in enumerate(mer_cat) if c == "utilities"]

    # ---------------- customers and devices
    devices = []

    def new_device(dtype, owner):
        os_ = str(rng.choice(["android", "ios"], p=[.7, .3])) if dtype == "mobile" else str(rng.choice(["windows", "other"]))
        if dtype == "atm":
            os_ = "other"
        devices.append(dict(device_type=dtype, os_family=os_, owner=owner))
        return len(devices) - 1

    customers = []
    base = datetime(2021, 1, 1)
    span = (datetime(2026, 8, 31) - base).days
    for i in range(n_cust):
        onb = base + timedelta(days=int(rng.integers(0, span)), seconds=int(rng.integers(0, 86400)))
        age = int(rng.integers(18, 76))
        dob = (onb - timedelta(days=age * 366 + int(rng.integers(0, 365)))).date()
        kyc = str(rng.choice(["verified", "pending", "expired", "rejected"], p=[.88, .06, .04, .02]))
        c = dict(customer_id=f"CUS-{i + 1:06d}", full_name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                 date_of_birth=str(dob), country="IN" if rng.random() < .94 else str(rng.choice(["US", "GB", "AE", "SG", "DE"])),
                 kyc_status=kyc, kyc_risk_tier=str(rng.choice(["low", "medium", "high"], p=[.7, .24, .06])),
                 kyc_verified_at=fts(onb + timedelta(days=int(rng.integers(0, 15)))) if kyc == "verified" else "",
                 onboarded_at=fts(onb), onb=onb, devs=[new_device("mobile", i)])
        if rng.random() < .45:
            c["devs"].append(new_device("web" if rng.random() < .7 else "mobile", i))
        customers.append(c)
    atm_idx = [new_device("atm", -1) for _ in range(max(20, n_cust // 50))]

    # ---------------- accounts
    extra = set(int(x) for x in rng.choice(n_cust, n_acc - n_cust, replace=False)) if n_acc > n_cust else set()
    accts = []
    for ci, c in enumerate(customers):
        for sfx in ((1, 2) if ci in extra else (1,)):
            if sfx == 1:
                opened = min(c["onb"] + timedelta(days=int(rng.integers(0, 31)), seconds=int(rng.integers(0, 86400))), datetime(2026, 9, 30))
            else:
                opened = max(accts[-1]["opened"] + DAY, min(c["onb"] + timedelta(days=int(rng.integers(30, 401))), datetime(2026, 10, 1)))
            a = dict(ci=ci, account_id=f"ACC-{c['customer_id']}-{sfx:02d}",
                     account_type="savings" if rng.random() < .65 else "current", opened=opened,
                     od=0 if rng.random() < .8 else int(rng.choice([10000, 25000, 50000])) * 100,
                     base_open=int(np.clip(rng.lognormal(np.log(20000), 1.0), 1000, 500000)) * 100,
                     fav=[int(x) for x in rng.choice(n_mer, 5, replace=False)],
                     events=[(opened, "active", "account opened")], closed_at="")
            a["a0"] = max(opened + timedelta(hours=1), START)
            a["a1"] = END  # normal activity window is [a0, a1)
            accts.append(a)

    # ---------------- account lifecycle (closed / frozen / dormant)
    for a in accts:
        if customers[a["ci"]]["kyc_status"] == "rejected":
            f = min(a["opened"] + timedelta(days=int(rng.integers(20, 91))), END - timedelta(hours=1))
            a["events"].append((f, "frozen", "KYC rejected"))
            a["a1"] = f
        elif a["opened"] <= datetime(2026, 6, 1):
            r = rng.random()
            lo, hi = max(a["opened"] + timedelta(days=60), START + timedelta(days=30)), END - timedelta(days=15)
            if r < .07 and lo < hi:
                c = rand_dt(lo, hi)
                a["events"].append((c, "closed", "customer request"))
                a["a1"], a["closed_at"] = c, fts(c)
            elif r < .10:
                lo, hi = max(a["a0"], START) + timedelta(days=30), END - timedelta(days=95)
                if lo < hi:
                    t = rand_dt(lo, hi)
                    a["events"].append((t + timedelta(days=90), "dormant", "no activity for 90 days"))
                    a["a1"] = t

    scale = n_alerts / 1000.0
    cnt = {k: max(1, round(v * scale)) for k, v in BASE_PATTERNS.items()}
    used = set()

    def take(pool, k):
        out = []
        for _ in range(min(k, len(pool))):
            ai = pool.pop(int(rng.integers(len(pool))))
            used.add(ai)
            out.append(ai)
        return out

    def take_if(pool, ok):
        while pool:
            ai = pool.pop(int(rng.integers(len(pool))))
            used.add(ai)
            r = ok(ai)
            if r is not None:
                return ai, r
        return None, None

    # planted dormant reactivation: lifecycle changes must be set before normal activity
    dorm_plan = []
    dpool = [ai for ai, a in enumerate(accts) if len(a["events"]) == 1 and a["opened"] <= datetime(2026, 4, 1)]
    for ai in take(dpool, cnt["dormant"]):
        a = accts[ai]
        lo, hi = max(a["a0"], START) + timedelta(days=30), END - timedelta(days=136)
        if lo >= hi:
            continue
        t0 = rand_dt(lo, hi)
        dormant_at = t0 + timedelta(days=90)
        react = dormant_at + timedelta(days=int(rng.integers(15, 46)), seconds=int(rng.integers(0, 86400)))
        a["events"] += [(dormant_at, "dormant", "no activity for 90 days"), (react, "active", "activity after dormancy")]
        a["a1"] = t0
        dorm_plan.append((ai, react, int(rng.integers(1, 4))))

    # ---------------- shapes of planted patterns (known before normal volume is set)
    sh = dict(vel=[int(rng.integers(8, 15)) for _ in range(cnt["velocity"])],
              bill=[int(rng.integers(8, 11)) for _ in range(cnt["bill_burst"])],
              nd=[int(rng.integers(2, 5)) for _ in range(cnt["new_device"])],
              circ=[int(rng.integers(3, 5)) for _ in range(cnt["circular"])])
    n_tr = int(0.015 * n_txn)
    planned = (sum(sh["vel"]) + sum(sh["bill"]) + sum(sh["nd"]) + 2 * cnt["upgrade"] + cnt["large_known"]
               + sum(1 + 2 * k for k in sh["circ"]) + sum(d[2] for d in dorm_plan) + 2 * n_tr)
    budget = n_txn - planned
    if budget < n_cust:
        raise ValueError("transactions too few for this scale; raise --transactions")

    intents, hist, transfers = [], {i: [] for i in range(len(accts))}, []

    def add(ai, t, direction, amt, typ, ch, mer=None, dev=None, tag=None):
        d = dict(ai=ai, ts=t, dir=direction, amt=int(amt), typ=typ, ch=ch, mer=mer, dev=dev, tag=tag, seq=len(intents))
        intents.append(d)
        return d

    def dev_for(ai):
        pool = customers[accts[ai]["ci"]]["devs"]
        return pool[0] if (len(pool) == 1 or rng.random() < .8) else pool[1]

    def pick_channel(ai):
        ch = str(rng.choice(["card", "online", "upi"], p=[.4, .3, .3]))
        return ch, (None if ch == "card" else dev_for(ai))

    def gen_normal(ai, n):
        a = accts[ai]
        a0, a1 = a["a0"], a["a1"]
        if n <= 0 or (a1 - a0).days < 2:
            return
        n_c = int(rng.binomial(n, .28))
        n_d = n - n_c
        b0 = datetime(a0.year, a0.month, a0.day)
        ds, hs = rng.integers(0, max(1, (a1 - b0).days), n), rng.choice(24, size=n, p=HOUR_P)
        ms, ss = rng.integers(0, 60, n), rng.integers(0, 60, n)
        times = [max(a0, min(b0 + timedelta(days=int(ds[i]), hours=int(hs[i]), minutes=int(ms[i]), seconds=int(ss[i])),
                             a1 - timedelta(seconds=1))) for i in range(n)]
        d_amts = np.clip(rng.lognormal(np.log(900), 1.0, n_d), 20, 20000)
        for i in range(n_d):
            r = rng.random()
            if r < .87:
                ch, dev = pick_channel(ai)
                mer = a["fav"][int(rng.integers(5))] if rng.random() < .6 else int(rng.integers(n_mer))
                d = add(ai, times[i], "debit", int(d_amts[i] * 100), "purchase", ch, mer, dev)
            elif r < .97:
                amt = max(500, int(round(d_amts[i] / 500)) * 500) * 100
                d = add(ai, times[i], "debit", amt, "withdrawal", "atm", None, atm_idx[int(rng.integers(len(atm_idx)))])
            else:
                d = add(ai, times[i], "debit", int(rng.integers(5, 60)) * 100, "fee", "online")
            hist[ai].append(d)
        if n_c:
            total = max(float(d_amts.sum()) * 100, 500000) * rng.uniform(.8, 1.5)
            shares = rng.dirichlet(np.ones(n_c))
            for j in range(n_c):
                ch = str(rng.choice(["branch", "online", "upi"], p=[.2, .4, .4]))
                d = add(ai, times[n_d + j], "credit", max(10000, int(total * shares[j])), "deposit", ch, None,
                        None if ch == "branch" else dev_for(ai))
                hist[ai].append(d)

    def spread(total, weights):
        w = np.array(weights, float)
        return rng.multinomial(total, w / w.sum())

    w = [((a["a1"] - a["a0"]).days / 300.0) * rng.lognormal(0, 1.0) if (a["a1"] - a["a0"]).days >= 2 else 0.0 for a in accts]
    for ai, k in enumerate(spread(budget, w)):
        gen_normal(ai, int(k))
    for h in hist.values():
        h.sort(key=lambda x: x["ts"])

    elig = [ai for ai, a in enumerate(accts) if len(a["events"]) == 1]
    P = [ai for ai in elig if len(hist[ai]) >= 8 and ai not in used]
    inst = {}

    def iid(code):
        inst[code] = inst.get(code, 0) + 1
        return f"PI-{code}-{inst[code]:04d}"

    def add_transfer(src, dst, t, amt, tag=None):
        ch = str(rng.choice(["upi", "online"]))
        d = add(src, t, "debit", amt, "transfer_out", ch, dev=dev_for(src), tag=tag)
        c = add(dst, t + timedelta(seconds=int(rng.integers(1, 20))), "credit", amt, "transfer_in", ch, tag=tag)
        transfers.append(dict(deb=d, cred=c, src=src, dst=dst, amt=int(amt), tag=tag))

    # ---- normal transfers between different customers
    made = tries = 0
    while elig and made < n_tr and tries < n_tr * 20:
        tries += 1
        s, d_ = elig[int(rng.integers(len(elig)))], elig[int(rng.integers(len(elig)))]
        if accts[s]["ci"] == accts[d_]["ci"]:
            continue
        lo, hi = max(accts[s]["a0"], accts[d_]["a0"]) + DAY, END - DAY
        if lo >= hi:
            continue
        add_transfer(s, d_, rand_dt(lo, hi), int(np.clip(rng.lognormal(np.log(6000), .9), 200, 50000)) * 100)
        made += 1

    # ---- velocity spikes (true) and bill-payment bursts (benign look-alike)
    def burst(ai, k, mers, tag, amt_med, hi_amt):
        a = accts[ai]
        t = rand_dt(a["a0"] + timedelta(days=10), END - timedelta(days=2))
        offs = sorted(int(x) for x in rng.integers(0, int(rng.integers(25, 56)) * 60, k))
        for o in offs:
            ch, dev = ("upi", dev_for(ai)) if mers is not None else pick_channel(ai)
            mer = mers[int(rng.integers(len(mers)))] if mers is not None else int(rng.integers(n_mer))
            add(ai, t + timedelta(seconds=o), "debit", int(np.clip(rng.lognormal(np.log(amt_med), .6), 100, hi_amt)) * 100,
                "purchase", ch, mer, dev, tag)

    for k in sh["vel"]:
        got = take(P, 1)
        if got:
            burst(got[0], k, None, ("planted_pattern", "velocity_spike", iid("VEL"),
                                    "RUL-001: 8 or more debits on one account within 60 minutes", "should_alert"), 1500, 15000)
    for k in sh["bill"]:
        got = take(P, 1)
        if got:
            burst(got[0], k, util_idx, ("false_positive", "benign_lookalike", iid("FPB"),
                                        "RUL-001 fires on a monthly bill-payment burst to utilities; benign", "should_alert_then_dismiss"), 1200, 6000)

    # ---- new-device activity (true) and new-phone upgrade (benign look-alike)
    def nd_ok(ai):
        c = [x for x in hist[ai][5:] if x["ts"] <= accts[ai]["a1"] - timedelta(days=2)]
        return c or None

    for n in sh["nd"]:
        ai, cand = take_if(P, nd_ok)
        if ai is None:
            break
        t = cand[int(rng.integers(len(cand)))]["ts"] + timedelta(minutes=int(rng.integers(30, 600)))
        dv = new_device("mobile", accts[ai]["ci"])
        tag = ("planted_pattern", "new_device_activity", iid("NDV"),
               "RUL-002: first use of a device on the account followed by debits of 25,000 or more within 24h", "should_alert")
        for j in range(n):
            amt = (rng.integers(15000, 45000) if j == 0 else rng.integers(10000, 30000) if j == 1 else rng.integers(5000, 25000)) * 100
            add(ai, t, "debit", amt, "purchase", "online", risky_idx[int(rng.integers(len(risky_idx)))], dv, tag)
            t += timedelta(minutes=int(rng.integers(5, 90)))

    def known_ok(need):
        def ok(ai):
            h = hist[ai]
            cut = int(len(h) * .7)
            c = {}
            for x in h[:cut]:
                if x["typ"] == "purchase":
                    c[x["mer"]] = c.get(x["mer"], 0) + 1
            known = sorted(m for m, v in c.items() if v >= need)
            if known and h[cut]["ts"] <= accts[ai]["a1"] - timedelta(days=2):
                return known[int(rng.integers(len(known)))], h[cut]["ts"]
            return None
        return ok

    for _ in range(cnt["upgrade"]):
        ai, r = take_if(P, known_ok(2))
        if ai is None:
            break
        m, t = r
        t += timedelta(minutes=int(rng.integers(30, 600)))
        dv = new_device("mobile", accts[ai]["ci"])
        devices[dv]["os_family"] = devices[customers[accts[ai]["ci"]]["devs"][0]]["os_family"]
        tag = ("false_positive", "benign_lookalike", iid("FPU"),
               "RUL-002 fires on a new phone paying a known payee; benign", "should_alert_then_dismiss")
        add(ai, t, "debit", int(rng.integers(200, 2000)) * 100, "purchase", "online", m, dv, tag)
        add(ai, t + timedelta(minutes=int(rng.integers(10, 180))), "debit", int(rng.integers(25000, 60000)) * 100,
            "purchase", "online", m, dv, tag)

    for _ in range(cnt["large_known"]):
        ai, r = take_if(P, known_ok(3))
        if ai is None:
            break
        m, t = r
        add(ai, t + timedelta(hours=int(rng.integers(6, 48))), "debit", int(rng.integers(100000, 180000)) * 100, "purchase",
            "online", m, dev_for(ai), ("false_positive", "benign_lookalike", iid("FPL"),
                                       "RUL-005 fires on a large payment to a known payee; benign", "should_alert_then_dismiss"))

    # ---- dormant reactivation (true)
    for ai, react, n in dorm_plan:
        tag = ("planted_pattern", "dormant_reactivation", iid("DOR"),
               "RUL-004: first transaction after 90+ days of dormancy is a debit of 25,000 or more", "should_alert")
        t = react
        for j in range(n):
            amt = (rng.integers(25000, 120000) if j == 0 else rng.integers(5000, 40000)) * 100
            add(ai, t, "debit", amt, "purchase", "online", risky_idx[int(rng.integers(len(risky_idx)))], dev_for(ai), tag)
            t += timedelta(hours=int(rng.integers(1, 6)))

    # ---- circular transfers (true): deposit, then A -> B -> C (-> D) -> A
    Q = [ai for ai in elig if ai not in used]
    for k in sh["circ"]:
        cyc, cs, tries = [], set(), 0
        while len(cyc) < k and Q and tries < 300:
            tries += 1
            ai = Q[int(rng.integers(len(Q)))]
            if accts[ai]["ci"] not in cs and ai not in cyc:
                cyc.append(ai)
                cs.add(accts[ai]["ci"])
        if len(cyc) < k:
            break
        for ai in cyc:
            Q.remove(ai)
            used.add(ai)
        lo, hi = max(accts[i]["a0"] for i in cyc) + timedelta(days=2), END - timedelta(days=3)
        if lo >= hi:
            continue
        t = rand_dt(lo, hi)
        amt0 = int(rng.integers(60000, 400000)) * 100
        tag = ("planted_pattern", "circular_transfer", iid("CIR"),
               "RUL-003: funds return to the origin account through 3 or more hops within 72 hours", "should_alert")
        add(cyc[0], t - timedelta(hours=int(rng.integers(1, 6))), "credit", amt0, "deposit", "branch", tag=tag)
        for j in range(k):
            add_transfer(cyc[j], cyc[(j + 1) % k], t, int(amt0 * (1 - 0.012 * j)), tag)
            t += timedelta(hours=int(rng.integers(1, 10)))

    short = n_txn - len(intents)  # top up if some pattern could not be placed
    if short > 0:
        for ai, k in enumerate(spread(short, w)):
            gen_normal(ai, int(k))

    # ---------------- order, ids, balances
    intents.sort(key=lambda x: (x["ts"], x["seq"]))
    cum, minc = {}, {}
    for x in intents:
        s = cum.get(x["ai"], 0) + (x["amt"] if x["dir"] == "credit" else -x["amt"])
        cum[x["ai"]], x["cum"] = s, s
        minc[x["ai"]] = min(minc.get(x["ai"], 0), s)
    opening = {ai: max(a["base_open"], -minc.get(ai, 0) - a["od"]) for ai, a in enumerate(accts)}
    for n, x in enumerate(intents, 1):
        x["tid"] = f"TXN-2026-{n:08d}"
        x["bal"] = opening[x["ai"]] + x["cum"]
    last_bal = {}
    for x in intents:
        last_bal[x["ai"]] = x["bal"]

    # ---------------- build output tables
    T = {}
    T["merchants"] = merchants
    links = {}
    for x in intents:
        if x["dev"] is not None:
            k = (x["dev"], x["ai"])
            links[k] = [min(links[k][0], x["ts"]), max(links[k][1], x["ts"])] if k in links else [x["ts"], x["ts"]]
    first_seen = {}
    for (dv, _), (f, _l) in links.items():
        first_seen[dv] = min(first_seen.get(dv, f), f)
    T["devices"] = [dict(device_id=f"DEV-{i + 1:06d}", device_type=d["device_type"], os_family=d["os_family"],
                         first_seen_at=fts(first_seen.get(i, customers[d["owner"]]["onb"] if d["owner"] >= 0 else START)))
                    for i, d in enumerate(devices)]
    T["device_account_links"] = [dict(link_id=f"DAL-{n:07d}", device_id=f"DEV-{dv + 1:06d}", account_id=accts[ai]["account_id"],
                                      first_seen_at=fts(v[0]), last_seen_at=fts(v[1]))
                                 for n, ((dv, ai), v) in enumerate(sorted(links.items()), 1)]
    hist_rows, acc_rows = [], []
    for ai, a in enumerate(accts):
        prev = ""
        for t, st, why in a["events"]:
            hist_rows.append(dict(history_id=f"ASH-{len(hist_rows) + 1:07d}", account_id=a["account_id"], old_status=prev,
                                  new_status=st, changed_at=fts(t), reason=why))
            prev = st
        acc_rows.append(dict(account_id=a["account_id"], customer_id=customers[a["ci"]]["customer_id"], account_type=a["account_type"],
                             currency="INR", status=prev, opened_at=fts(a["opened"]), closed_at=a["closed_at"],
                             overdraft_limit=money(a["od"]), opening_balance=money(opening[ai]),
                             current_balance=money(last_bal.get(ai, opening[ai]))))
    T["account_status_history"], T["accounts"] = hist_rows, acc_rows
    by_c = {}
    for r in acc_rows:
        by_c.setdefault(r["customer_id"], []).append(r["status"])
    T["customers"] = [{k: v for k, v in c.items() if k not in ("onb", "devs")} |
                      dict(status="suspended" if c["kyc_status"] == "rejected" else
                           "closed" if all(s == "closed" for s in by_c[c["customer_id"]]) else "active") for c in customers]
    T["transactions"] = [dict(transaction_id=x["tid"], account_id=accts[x["ai"]]["account_id"],
                              merchant_id=f"MER-{x['mer'] + 1:06d}" if x["mer"] is not None else "",
                              device_id=f"DEV-{x['dev'] + 1:06d}" if x["dev"] is not None else "",
                              txn_timestamp=fts(x["ts"]), direction=x["dir"], amount=money(x["amt"]), txn_type=x["typ"],
                              channel=x["ch"], status="posted", balance_after=money(x["bal"])) for x in intents]
    transfers.sort(key=lambda t: t["deb"]["tid"])
    for n, t in enumerate(transfers, 1):
        t["id"] = f"TRF-2026-{n:06d}"
    T["transfer_links"] = [dict(transfer_id=t["id"], debit_txn_id=t["deb"]["tid"], credit_txn_id=t["cred"]["tid"],
                                source_account_id=accts[t["src"]]["account_id"], destination_account_id=accts[t["dst"]]["account_id"],
                                transfer_amount=money(t["amt"]), initiated_at=fts(t["deb"]["ts"]), status="completed") for t in transfers]
    gt = []

    def gt_row(etype, eid, tag):
        gt.append(dict(truth_id=f"GT-{len(gt) + 1:06d}", entity_type=etype, entity_id=eid, label_kind=tag[0], issue_type=tag[1],
                       expected_decision=tag[4], generating_rule=tag[3], pattern_instance_id=tag[2]))

    for x in intents:
        if x["tag"]:
            gt_row("transaction", x["tid"], x["tag"])
    for t in transfers:
        if t["tag"]:
            gt_row("transfer", t["id"], t["tag"])
    T["ground_truth"] = gt
    meta = dict(pattern_instances_requested=cnt, pattern_instances_placed={k: v for k, v in sorted(inst.items())},
                normal_transfers=made)
    return T, meta


COLS = {
    "customers": ["customer_id", "full_name", "date_of_birth", "country", "kyc_status", "kyc_risk_tier", "kyc_verified_at", "onboarded_at", "status"],
    "accounts": ["account_id", "customer_id", "account_type", "currency", "status", "opened_at", "closed_at", "overdraft_limit", "opening_balance", "current_balance"],
    "account_status_history": ["history_id", "account_id", "old_status", "new_status", "changed_at", "reason"],
    "merchants": ["merchant_id", "merchant_name", "category", "country", "risk_level"],
    "devices": ["device_id", "device_type", "os_family", "first_seen_at"],
    "device_account_links": ["link_id", "device_id", "account_id", "first_seen_at", "last_seen_at"],
    "transactions": ["transaction_id", "account_id", "merchant_id", "device_id", "txn_timestamp", "direction", "amount", "txn_type", "channel", "status", "balance_after"],
    "transfer_links": ["transfer_id", "debit_txn_id", "credit_txn_id", "source_account_id", "destination_account_id", "transfer_amount", "initiated_at", "status"],
    "ground_truth": ["truth_id", "entity_type", "entity_id", "label_kind", "issue_type", "expected_decision", "generating_rule", "pattern_instance_id"],
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=20261022)
    ap.add_argument("--customers", type=int, default=5000)
    ap.add_argument("--accounts", type=int, default=7000)
    ap.add_argument("--transactions", type=int, default=100000)
    ap.add_argument("--alerts", type=int, default=1000, help="target alert volume; scales planted pattern counts")
    ap.add_argument("--starter", action="store_true", help="small dataset: 500 / 700 / 10,000 / 100")
    ap.add_argument("--out", default="data")
    a = ap.parse_args()
    if a.starter:
        a.customers, a.accounts, a.transactions, a.alerts = 500, 700, 10000, 100
    T, meta = generate(a.customers, a.accounts, a.transactions, a.alerts, a.seed)
    os.makedirs(a.out, exist_ok=True)
    manifest = dict(generator_version=VERSION, seed=a.seed, customers=a.customers, accounts=a.accounts,
                    transactions=a.transactions, alerts_target=a.alerts, **meta, files={})
    for name, cols in COLS.items():
        path = os.path.join(a.out, f"{name}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
            wr.writeheader()
            wr.writerows(T[name])
        with open(path, "rb") as f:
            manifest["files"][f"{name}.csv"] = dict(rows=len(T[name]), sha256=hashlib.sha256(f.read()).hexdigest())
    with open(os.path.join(a.out, "generation_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"seed={a.seed} wrote {a.out}/")
    for k, v in manifest["files"].items():
        print(f"  {k:28s} {v['rows']:>8,} rows")


if __name__ == "__main__":
    main()
