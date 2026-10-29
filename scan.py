# scan.py
# optional lead source: fresh Solana tokens that just paid for a DexScreener profile.
# a paid profile is not a quality signal, it just means the dev spent money. the filter decides.
import csv, os, subprocess, sys, time
import requests
from config import LOG, RECHECK

rows = list(csv.DictReader(open(LOG))) if os.path.exists(LOG) else []
seen = {r["mint"] for r in rows}
r = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=15)
r.raise_for_status()
fresh = [t["tokenAddress"] for t in r.json()
         if t.get("chainId") == "solana" and t.get("tokenAddress") not in seen]

for mint in fresh[:5]:                   # five per run, so one busy hour can't drain the API budget
    subprocess.run([sys.executable, "check.py", mint])

# [desk fix] 2026-10-29: pool-stage rejects (too thin / too fresh / still on the bonding curve / tier B rules)
# used to be final. Re-check the ones first seen in the last RECHECK window_hours, at most once per every_min,
# newest first, per_run per scan. Free (Rugcheck + DexScreener) unless the token now passes all 13 checks.
now = time.time()
ts = lambda s: time.mktime(time.strptime(s, "%Y-%m-%d %H:%M"))
first, last = {}, {}
for row in rows:
    first.setdefault(row["mint"], row)
    last[row["mint"]] = row
due = [m for m, row in last.items()
       if row["stage"] == "pool" and row["verdict"] == "SKIP"
       and any((row["reason"] or "").startswith(x) for x in RECHECK["reasons"])
       and now - ts(first[m]["time"]) <= RECHECK["window_hours"] * 3600
       and now - ts(row["time"]) >= RECHECK["every_min"] * 60]
due.sort(key=lambda m: first[m]["time"], reverse=True)
for mint in due[:RECHECK["per_run"]]:
    subprocess.run([sys.executable, "check.py", mint])
