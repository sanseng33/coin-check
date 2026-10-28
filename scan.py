# scan.py
# optional lead source: fresh Solana tokens that just paid for a DexScreener profile.
# a paid profile is not a quality signal, it just means the dev spent money. the filter decides.
import csv, os, subprocess, sys
import requests
from config import LOG

seen = {r["mint"] for r in csv.DictReader(open(LOG))} if os.path.exists(LOG) else set()
r = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=15)
r.raise_for_status()
fresh = [t["tokenAddress"] for t in r.json()
         if t.get("chainId") == "solana" and t.get("tokenAddress") not in seen]

for mint in fresh[:5]:                   # five per run, so one busy hour can't drain the API budget
    subprocess.run([sys.executable, "check.py", mint])
