"""Tests for the whole pipeline, run on the small starter dataset so they finish in about a minute.

Run from the project root:   python -m unittest discover -s tests -v
(pytest also works:           python -m pytest tests)
"""
import csv, hashlib, inspect, json, os, shutil, sqlite3, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

import build_triage  # noqa: E402
import export_seed  # noqa: E402
import validator  # noqa: E402


def run(script, *args):
    return subprocess.run([sys.executable, os.path.join(SRC, script), *args], capture_output=True, text=True)


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def rows(folder, name):
    with open(os.path.join(folder, name + ".csv"), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.base = os.path.join(cls.tmp, "base")
        cls.final = os.path.join(cls.tmp, "final")
        r = run("generator.py", "--starter", "--out", cls.base)
        assert r.returncode == 0, r.stderr
        r = run("build_triage.py", "--in", cls.base, "--out", cls.final)
        assert r.returncode == 0, r.stderr
        with open(os.path.join(cls.final, "build_manifest.json")) as f:
            cls.manifest = json.load(f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- data volume and identifiers
    def test_ids_are_unique_and_formatted(self):
        v = validator.V(self.final)
        v.structure()
        self.assertEqual([f for f in v.f if f["check"] in ("id_format", "pk_unique", "enum")], [])

    def test_account_id_embeds_customer_id(self):
        for a in rows(self.final, "accounts"):
            self.assertTrue(a["account_id"].startswith(f"ACC-{a['customer_id']}-"))

    # ---- validator
    def test_validator_passes_and_catches_exactly_the_five_injected_anomalies(self):
        r = run("validator.py", "--data", self.final, "--report", os.path.join(self.tmp, "report.json"))
        self.assertEqual(r.returncode, 0, r.stdout)
        with open(os.path.join(self.tmp, "report.json")) as f:
            rep = json.load(f)
        self.assertEqual(rep["missed"], [])
        self.assertEqual(rep["unexpected"], [])
        issues = {f["issue_type"] for f in rep["findings"]}
        self.assertEqual(issues, {"txn_on_closed_account", "negative_balance_no_overdraft", "transfer_legs_mismatch",
                                  "alert_without_trigger", "disposition_before_alert"})

    def test_validator_detects_corruption(self):
        bad = os.path.join(self.tmp, "bad")
        shutil.copytree(self.final, bad)
        path = os.path.join(bad, "transactions.csv")
        data = rows(bad, "transactions")
        data[10]["balance_after"] = "1.00"            # breaks reconciliation
        data[20]["account_id"] = "ACC-CUS-999999-01"  # breaks a foreign key
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(data)
        found = {f["issue_type"] for f in validator.V(bad).run()}
        self.assertIn("balance_reconciliation_error", found)
        self.assertIn("referential_integrity", found)

    # ---- business rules
    def test_balances_reconcile_before_injection(self):
        accs = {a["account_id"]: a for a in rows(self.base, "accounts")}
        bal = {k: build_triage.paise(a["opening_balance"]) for k, a in accs.items()}
        for t in sorted(rows(self.base, "transactions"), key=lambda r: (r["txn_timestamp"], r["transaction_id"])):
            amt = build_triage.paise(t["amount"])
            bal[t["account_id"]] += amt if t["direction"] == "credit" else -amt
            self.assertEqual(bal[t["account_id"]], build_triage.paise(t["balance_after"]))

    def test_all_planted_patterns_are_detected(self):
        for issue, v in self.manifest["pattern_detection"].items():
            self.assertEqual(v["detected"], v["placed"], issue)

    def test_false_positives_are_represented(self):
        self.assertGreater(self.manifest["pattern_detection"]["benign_lookalike"]["placed"], 0)
        self.assertGreater(sum(c.get("false_positive", 0) for c in self.manifest["alerts_by_rule_and_label"].values()), 0)

    def test_every_alert_has_rule_and_explainable_score(self):
        rules = {r["rule_id"] for r in rows(self.final, "risk_rules")}
        n = 0
        for a in rows(self.final, "alerts"):
            n += 1
            self.assertIn(a["rule_id"], rules)
            self.assertTrue(a["evidence"])
            self.assertEqual(sum(json.loads(a["score_breakdown"]).values()), int(a["risk_score"]))
            self.assertTrue(0 <= int(a["risk_score"]) <= 100)
        self.assertGreater(n, 0)

    def test_alert_belongs_to_at_most_one_case(self):
        ids = [r["alert_id"] for r in rows(self.final, "case_alerts")]
        self.assertEqual(len(ids), len(set(ids)))

    def test_rules_never_read_ground_truth(self):
        for fn in (build_triage.rule_velocity, build_triage.rule_new_device, build_triage.rule_circular,
                   build_triage.rule_dormant, build_triage.rule_high_amount, build_triage.common_factors):
            src = inspect.getsource(fn)
            self.assertNotIn("label", src)
            self.assertNotIn("ground_truth", src)

    def test_ground_truth_is_a_separate_file(self):
        self.assertTrue(os.path.exists(os.path.join(self.final, "ground_truth.csv")))
        for name in ("transactions", "alerts", "cases", "accounts"):
            self.assertNotIn("issue_type", rows(self.final, name)[0])

    # ---- reproducibility
    def test_same_seed_gives_identical_files(self):
        other = os.path.join(self.tmp, "again")
        b2, f2 = os.path.join(other, "b"), os.path.join(other, "f")
        self.assertEqual(run("generator.py", "--starter", "--out", b2).returncode, 0)
        self.assertEqual(run("build_triage.py", "--in", b2, "--out", f2).returncode, 0)
        for name in sorted(os.listdir(self.final)):
            if name.endswith(".csv"):
                self.assertEqual(sha(os.path.join(self.final, name)), sha(os.path.join(f2, name)), name)

    def test_different_seed_gives_different_data(self):
        b2 = os.path.join(self.tmp, "seed2")
        self.assertEqual(run("generator.py", "--starter", "--seed", "7", "--out", b2).returncode, 0)
        self.assertNotEqual(sha(os.path.join(self.base, "transactions.csv")), sha(os.path.join(b2, "transactions.csv")))

    def test_builder_refuses_a_modified_baseline(self):
        mod = os.path.join(self.tmp, "mod")
        shutil.copytree(self.base, mod)
        with open(os.path.join(mod, "merchants.csv"), "a") as f:
            f.write("x\n")
        r = run("build_triage.py", "--in", mod, "--out", os.path.join(self.tmp, "modout"))
        self.assertNotEqual(r.returncode, 0)

    # ---- exports
    def test_sql_seed_loads_with_foreign_keys(self):
        sql, counts = export_seed.sql_for(self.final)
        report, ok = export_seed.load_check(sql, counts)
        self.assertTrue(ok, report)
        con = sqlite3.connect(":memory:")
        con.executescript(sql)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM alerts WHERE transaction_id IS NULL").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
