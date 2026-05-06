#!/usr/bin/env python3
"""Grant anon SELECT on backtest_runs and wf_results for the share page.
Usage: sops exec-env secrets.env 'python scripts/grant_anon_access.py'
"""
import os, sys
import psycopg2

DB_URL = os.environ.get("TIMESCALE_URL")
if not DB_URL:
    sys.exit("TIMESCALE_URL not set")

conn = psycopg2.connect(DB_URL)
conn.autocommit = True
cur = conn.cursor()

statements = [
    "GRANT SELECT ON quant.backtest_runs TO anon, authenticated",
    "GRANT SELECT ON quant.wf_results TO anon, authenticated",
    "GRANT SELECT ON quant.backtest_trades TO anon, authenticated",
]

for sql in statements:
    try:
        cur.execute(sql)
        print(f"OK: {sql}")
    except Exception as e:
        print(f"SKIP: {sql} -- {e}")

cur.close()
conn.close()
print("done")
