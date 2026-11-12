#!/usr/bin/env python3
"""One command for Steps 3-5: build alerts/cases/actions/anomalies, validate, check reproducibility.

Run:  python src/run_all.py            (needs data/ from generator.py)
      python src/run_all.py --quick    (skip the slow two-rebuild reproducibility check)
"""
import os, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
quick = "--quick" in sys.argv
steps = [[os.path.join(here, "build_triage.py"), "--in", "data", "--out", "data_final"],
         [os.path.join(here, "validator.py"), "--data", "data_final"] + ([] if quick else ["--repro"])]
for s in steps:
    print(f"\n=== {os.path.basename(s[0])} ===")
    r = subprocess.run([sys.executable] + s)
    if r.returncode:
        sys.exit(r.returncode)
