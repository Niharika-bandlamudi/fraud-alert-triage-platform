#!/usr/bin/env python3
"""Export data_final/*.csv to a SQLite database and a plain SQL seed file.
Run:  python src/export_sql.py            (needs data_final/ from run_all.py)
Writes sql/fraud_triage.db and sql/seed.sql
"""
import csv, os, sqlite3, sys

src = sys.argv[1] if len(sys.argv) > 1 else "data_final"
out = "sql"
os.makedirs(out, exist_ok=True)
db_path = os.path.join(out, "fraud_triage.db")
if os.path.exists(db_path):
    os.remove(db_path)

KEEP_TEXT = ("amount", "balance_after", "transfer_amount", "current_balance", "opening_balance", "overdraft_limit")

def col_type(values):
    kind = "INTEGER"
    for v in values:
        if v == "":
            continue
        try:
            int(v)
        except ValueError:
            try:
                float(v)
                kind = "REAL"
            except ValueError:
                return "TEXT"
    return kind

con = sqlite3.connect(db_path)
for fn in sorted(os.listdir(src)):
    if not fn.endswith(".csv"):
        continue
    table = fn[:-4]
    with open(os.path.join(src, fn), newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    head, body = rows[0], rows[1:]
    types = []
    for i, h in enumerate(head):
        t = col_type([r[i] for r in body])
        # IDs, money and timestamps stay TEXT so nothing is rounded or reformatted
        if h.endswith("_id") or h.endswith("_at") or "timestamp" in h or h in KEEP_TEXT:
            t = "TEXT"
        types.append(t)
    cols = ", ".join(f'"{h}" {t}' + (" PRIMARY KEY" if i == 0 else "") for i, (h, t) in enumerate(zip(head, types)))
    con.execute(f'CREATE TABLE "{table}" ({cols})')
    con.executemany(f'INSERT INTO "{table}" VALUES ({",".join("?" * len(head))})',
                    [[(v if v != "" else None) for v in r] for r in body])
    print(f"{table}: {len(body)} rows")
con.commit()

with open(os.path.join(out, "seed.sql"), "w", encoding="utf-8") as f:
    for line in con.iterdump():
        f.write(line + "\n")
con.close()
print("wrote", db_path, "and", os.path.join(out, "seed.sql"))
